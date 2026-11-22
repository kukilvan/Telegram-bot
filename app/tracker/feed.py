"""The feed (`Tracker.feed()`): one read of the database for «Скоро», «Позже» and «Недавно». How the rows read and
which buttons they have is decided by the pure `feed_rows`; what comes out of a title is cut by the poller of its kind
(`Poller.feed_pieces`): this module groups the titles by kind and asks each poller once.

«Недавно» also holds what came out before a title's baseline (adding, or the return from the archive) and is not in the
log: each poller hands over what its schedule says came out in the window (`Poller.feed_released`), and the pure
`feed_released` keeps it against the baselines of the titles read here and the events of the window read once more.

The number of reads does not grow with the number of titles: the seasons, episodes, parts, dates and events of all
titles come in one read each. Today is the date on the owner's clock; the time zone, the break between parts and today
are read here once (`SettingsStore`) and handed to the pollers.
"""

import asyncio
from collections.abc import Iterable, Mapping
from datetime import date, datetime, time, timedelta, tzinfo
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.tracker import delivery, failures, feed_released, feed_rows
from app.tracker.actions import FOLLOW_TYPES
from app.tracker.cards import local_moment
from app.tracker.context import CoreContext, naive_utc
from app.tracker.feed_released import Baseline, Out
from app.tracker.feed_rows import Feed, FeedBasis, FeedEvent, Followable, FeedTitle, Piece, RecentRow
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
            now = self.ctx.now()
            basis = FeedBasis(tz, self.settings.part_gap(session), local_moment(now, tz).date())
            titles = {t.id: t for t in session.scalars(select(Title))}
            shown = {t.id: FeedTitle(t.id, t.kind, t.name, t.poster_path) for t in titles.values()}
            by_kind = self._active_by_kind(titles, shown)
            soon, later = feed_rows.upcoming(self._pieces(session, by_kind, basis), basis.today)
            events = self._events(session, titles, shown, tz, basis.today)
            listed = self._listed(session, events)
            released = self._released(session, titles, by_kind, basis, now)
        recent = feed_rows.recent(events, basis.today, listed, released)
        return Feed(soon, later, recent, has_titles=bool(titles), today=basis.today)

    @staticmethod
    def _active_by_kind(
        titles: Mapping[int, Title], shown: Mapping[int, FeedTitle]
    ) -> dict[TitleKind, dict[int, FeedTitle]]:
        """The titles that are not in the archive, by kind: whose dates the Feed shows."""
        by_kind: dict[TitleKind, dict[int, FeedTitle]] = {}
        for title in titles.values():
            if title.status not in ARCHIVE_STATUSES:
                by_kind.setdefault(title.kind, {})[title.id] = shown[title.id]
        return by_kind

    def _pieces(self, session, by_kind: Mapping[TitleKind, Mapping[int, FeedTitle]], basis: FeedBasis) -> list[Piece]:
        """What comes out from today on: the poller of each kind cuts the pieces of all its titles at once."""
        pieces: list[Piece] = []
        for kind, of_kind in by_kind.items():
            pieces += self.pollers.reader_of(kind).feed_pieces(session, of_kind, basis)
        return pieces

    def _released(
        self, session, titles: Mapping[int, Title], by_kind: Mapping[TitleKind, Mapping[int, FeedTitle]],
        basis: FeedBasis, now: datetime,
    ) -> list[tuple[date, RecentRow]]:
        """The rows of «Недавно» from the schedule: what the poller of each kind says came out in the window, kept when
        it came out before the title's baseline and the log of the window does not name it. `now`: naive UTC."""
        outs: list[Out] = []
        for kind, of_kind in by_kind.items():
            outs += self.pollers.reader_of(kind).feed_released(session, of_kind, basis, now)
        if not outs:
            return []
        baselines = {t.id: Baseline(t.added_at, t.restored_at) for t in titles.values()}
        return feed_released.released_rows(outs, baselines, self._logged(session, basis))

    @staticmethod
    def _logged(session, basis: FeedBasis) -> set[tuple]:
        """What the log of the window names (`feed_released.logged`): the events of an episode or a film date found since
        today − 7 on the owner's clock — one day more than the window, for the zones west of UTC."""
        first_day = basis.today - timedelta(days=feed_rows.RECENT_DAYS)
        since = naive_utc(datetime.combine(first_day, time(0), tzinfo=basis.tz))
        rows = session.execute(
            select(Event.title_id, Event.type, Event.payload).where(
                Event.title_id.is_not(None), Event.type.in_(feed_released.LOGGED_TYPES), Event.detected_at >= since
            )
        )
        return feed_released.logged(rows)

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

    def _listed(self, session, events: Iterable[FeedEvent]) -> dict[Followable, int]:
        """The titles of the announced sequels, expansions and games that the list has already, by their ids in the
        source: one read a kind."""
        wanted: dict[TitleKind, set[str]] = {}
        for event in events:
            if event.type in FOLLOW_TYPES and (target := feed_rows.followable_of(event.data)) is not None:
                wanted.setdefault(target.kind, set()).add(target.external_id)
        listed: dict[Followable, int] = {}
        for kind, ids in wanted.items():
            try:
                poller = self.pollers.of(kind)
            except KeyError:  # no source of this kind: nothing of it can be in the list
                continue
            listed.update({Followable(kind, external_id): title_id for external_id, title_id in poller.known_ids(session, ids).items()})
        return listed
