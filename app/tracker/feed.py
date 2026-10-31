"""The feed (`Tracker.feed()`): one read of the database for «Скоро», «Позже» and «Недавно». How the rows read and
which buttons they have is decided by the pure `feed_rows`; what comes out of a title is cut by the poller of its kind
(`Poller.feed_pieces`): this module groups the titles by kind and asks each poller once.

The number of reads does not grow with the number of titles: the seasons, episodes, parts, dates and events of all
titles come in one read each. Today is the date on the owner's clock; the time zone, the break between parts and today
are read here once (`SettingsStore`) and handed to the pollers.
"""

import asyncio
from collections.abc import Iterable, Mapping
from datetime import date, datetime, time, timedelta, tzinfo
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.tracker import delivery, failures, feed_rows, sequel_events
from app.tracker.cards import local_moment
from app.tracker.context import CoreContext, naive_utc
from app.tracker.feed_rows import Feed, FeedBasis, FeedEvent, FeedTitle, Piece
from app.tracker.models import ARCHIVE_STATUSES, Event, Title, TitleKind
from app.tracker.settings_store import SettingsStore

if TYPE_CHECKING:
    from app.tracker.polling import Pollers


class FeedReader:
    def __init__(self, ctx: CoreContext, settings: SettingsStore, pollers: "Pollers") -> None:
        self.ctx = ctx
        self.settings = settings
        self.pollers = pollers

    async def feed(self) -> Feed:
        return await asyncio.to_thread(self._feed)

    def _feed(self) -> Feed:
        with self.ctx.session_factory() as session:
            tz = self.settings.time_zone(session)  # read here, where it is needed (coding standard 2)
            basis = FeedBasis(tz, self.settings.part_gap(session), local_moment(self.ctx.now(), tz).date())
            titles = {t.id: t for t in session.scalars(select(Title))}
            shown = {t.id: FeedTitle(t.id, t.kind, t.name, t.poster_path) for t in titles.values()}
            soon, later = feed_rows.upcoming(self._pieces(session, titles, shown, basis), basis.today)
            events = self._events(session, titles, shown, tz, basis.today)
            listed = self._listed(session, events)
        return Feed(soon, later, feed_rows.recent(events, basis.today, listed), has_titles=bool(titles), today=basis.today)

    def _pieces(
        self, session, titles: Mapping[int, Title], shown: Mapping[int, FeedTitle], basis: FeedBasis
    ) -> list[Piece]:
        """What comes out from today on, of the titles that are not in the archive: the poller of each kind cuts the
        pieces of all its titles at once."""
        by_kind: dict[TitleKind, dict[int, FeedTitle]] = {}
        for title in titles.values():
            if title.status not in ARCHIVE_STATUSES:
                by_kind.setdefault(title.kind, {})[title.id] = shown[title.id]
        pieces: list[Piece] = []
        for kind, of_kind in by_kind.items():
            pieces += self.pollers.reader_of(kind).feed_pieces(session, of_kind, basis)
        return pieces

    @staticmethod
    def _events(
        session, titles: Mapping[int, Title], shown: Mapping[int, FeedTitle], tz: tzinfo, today: date
    ) -> list[FeedEvent]:
        """The events of the last days that belong to a title in the list (a test event has none), «could not check»
        left out, whatever the title's status and whether the event went out yet."""
        first_day = today - timedelta(days=feed_rows.RECENT_DAYS - 1)
        since = naive_utc(datetime.combine(first_day, time(0), tzinfo=tz))  # the day starts on the owner's clock
        events = session.scalars(
            select(Event).where(
                Event.title_id.is_not(None),  # a test event belongs to no title
                Event.detected_at >= since,
                Event.type != failures.SOURCE_FAILED,
            )
        )
        return [
            FeedEvent(
                e.id, e.type, shown[e.title_id], titles[e.title_id].status,
                delivery.format_event(e.type, e.payload), e.payload,
                local_moment(e.detected_at, tz),
            )
            for e in events
        ]

    def _listed(self, session, events: Iterable[FeedEvent]) -> dict[tuple[TitleKind, str], int]:
        """The titles of the announced sequels that the list has already, by their ids in the source: one read a kind."""
        wanted: dict[TitleKind, set[str]] = {}
        for event in events:
            if event.type == sequel_events.SEQUEL_ANNOUNCED and (sequel := feed_rows.sequel_of(event.data)) is not None:
                wanted.setdefault(sequel[0], set()).add(sequel[1])
        listed: dict[tuple[TitleKind, str], int] = {}
        for kind, ids in wanted.items():
            try:
                poller = self.pollers.of(kind)
            except KeyError:  # no source of this kind: nothing of it can be in the list
                continue
            listed.update({(kind, external_id): title_id for external_id, title_id in poller.known_ids(session, ids).items()})
        return listed
