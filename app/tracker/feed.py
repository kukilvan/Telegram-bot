"""The feed (`Tracker.feed()`): one read of the database for «Скоро», «Позже» and «Недавно». How the rows read and
which buttons they have is decided by the pure `feed_rows`; this module only gathers what it needs.

The number of reads does not grow with the number of titles: the seasons, episodes, parts, dates and events of all
titles come in one read each. Today is the date on the owner's clock (`SettingsStore.time_zone`, read here).
"""

import asyncio
from collections.abc import Iterable, Mapping
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.tracker import failures, feed_rows, sequel_events, storage
from app.tracker.cards import local_moment
from app.tracker.context import PRIMARY_ROLE, CoreContext
from app.tracker.delivery_service import format_event
from app.tracker.feed_rows import Feed, FeedEvent, FeedTitle, Piece
from app.tracker.kinds import KINDS, is_seasonal
from app.tracker.models import (
    ARCHIVE_STATUSES, Event, ExternalId, MovieRecord, SourceSnapshot, Title, TitleKind,
)
from app.tracker.movie_events import MovieDates
from app.tracker.settings_store import SettingsStore

if TYPE_CHECKING:
    from app.tracker.polling import Pollers


def _utc(day: date, tz: tzinfo) -> datetime:
    """The start of a day on the owner's clock as a naive UTC moment, like everything stored."""
    return datetime.combine(day, time(0)).replace(tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)


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
            gap = self.settings.part_gap(session)
            today = local_moment(self.ctx.now(), tz).date()
            titles = {t.id: t for t in session.scalars(select(Title))}
            shown = {t.id: FeedTitle(t.id, t.kind, t.name, t.poster_path) for t in titles.values()}
            soon, later = feed_rows.upcoming(self._pieces(session, titles, shown, tz, gap, today), today)
            events = self._events(session, titles, shown, tz, today)
            listed = self._listed(session, events)
        return Feed(soon, later, feed_rows.recent(events, today, listed), has_titles=bool(titles))

    @staticmethod
    def _pieces(
        session, titles: Mapping[int, Title], shown: Mapping[int, FeedTitle], tz: tzinfo, gap: timedelta, today: date
    ) -> list[Piece]:
        """What comes out from today on, of the titles that are not in the archive."""
        active = select(Title.id).where(Title.status.not_in(ARCHIVE_STATUSES))
        pieces: list[Piece] = []
        for title_id, seasons in storage.load_seasons_of(session, active).items():
            title = titles[title_id]
            if is_seasonal(title.kind):
                local = tz if KINDS[title.kind].local_times else None  # the source gives the moment, not only the day
                pieces += feed_rows.season_pieces(shown[title_id], seasons, gap, local, today)
        own_states = session.execute(
            select(SourceSnapshot.title_id, SourceSnapshot.state)
            .join(ExternalId, ExternalId.title_id == SourceSnapshot.title_id)
            .where(
                ExternalId.role == PRIMARY_ROLE,
                SourceSnapshot.source == ExternalId.source,
                SourceSnapshot.title_id.in_(active),
            )
        )
        for title_id, state in own_states:
            if not is_seasonal(titles[title_id].kind):
                dates = MovieDates.from_state(state)
                pieces += feed_rows.movie_pieces(shown[title_id], dates.theatrical, dates.digital, today)
        coming_movies = session.execute(
            select(MovieRecord.title_id, MovieRecord.name, MovieRecord.aired_on).where(
                MovieRecord.title_id.in_(active), MovieRecord.released.is_(False), MovieRecord.aired_on >= today
            )
        )
        for title_id, name, aired_on in coming_movies:
            pieces += feed_rows.franchise_pieces(shown[title_id], [(name, aired_on)], today)
        return pieces

    @staticmethod
    def _events(
        session, titles: Mapping[int, Title], shown: Mapping[int, FeedTitle], tz: tzinfo, today: date
    ) -> list[FeedEvent]:
        """The events of the last days that belong to a title in the list (a test event has none), «could not check»
        left out, whatever the title's status and whether the event went out yet."""
        since = _utc(today - timedelta(days=feed_rows.RECENT_DAYS - 1), tz)
        events = session.scalars(
            select(Event).where(
                Event.title_id.is_not(None),  # a test event belongs to no title
                Event.detected_at >= since,
                Event.type != failures.SOURCE_FAILED,
            )
        )
        return [
            FeedEvent(
                e.id, e.type, shown[e.title_id], titles[e.title_id].status, format_event(e), e.payload,
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
