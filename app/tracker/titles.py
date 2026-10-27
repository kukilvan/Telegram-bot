"""The owner's list: adding, deleting and opening titles, «Посмотрел», «Следить», the season marks and the status that
follows from them. What differs by kind (the first seasons, the first check) is asked of the title's poller."""

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, func, select

from app.tracker import seasons as season_logic
from app.tracker import sequel_events, storage
from app.tracker.cards import MovieLine, TitleCard
from app.tracker.context import PRIMARY_ROLE, CoreContext
from app.tracker.errors import TitleNotFound, UnknownEvent, UnknownKind, UnknownSeason, UnknownTitle
from app.tracker.kinds import KINDS, is_seasonal
from app.tracker.models import ExternalId, Event, MovieRecord, SeasonRecord, SourceSnapshot, Title, TitleKind, TitleStatus
from app.tracker.results import AddResult, DeleteResult, Overview, TitleSummary, WatchableSeason, WatchedResult
from app.tracker.settings_store import SettingsStore
from app.tracker.sources.dates import parse_date

if TYPE_CHECKING:
    from app.tracker.polling import Pollers


def _watchable(loaded: list[tuple[SeasonRecord, season_logic.Season]], now: datetime) -> list[WatchableSeason]:
    """The seasons with something released, with the owner's marks: the ones that can be marked."""
    return [WatchableSeason(season.number, record.watched) for record, season in loaded if season.released(now) > 0]


class Titles:
    def __init__(self, ctx: CoreContext, settings: SettingsStore, pollers: "Pollers") -> None:
        self.ctx = ctx
        self.settings = settings
        self.pollers = pollers

    # --- adding ---------------------------------------------------------------------------------

    async def search(self, kind: TitleKind, query: str) -> list[Any]:
        """Suggestions for `query` from the source of this kind. Raises KeyError for an unknown kind."""
        return await self.pollers.of(kind).source.suggest(query)

    async def add_title(self, kind: TitleKind, external_id: str) -> AddResult:
        """Put a search result into the list with status «Хочу», or open the title that is already there."""
        source = self.pollers.of(kind).source
        existing = await asyncio.to_thread(self._find_title_id, source.source_key, external_id)
        if existing is not None:
            return AddResult(existing, created=False)
        snapshot = await source.snapshot(external_id)
        if snapshot is None:
            raise TitleNotFound(f"{source.source_key}:{external_id}")
        if snapshot.external_id != external_id:  # the source named the title by another entry (any entry of an anime franchise)
            existing = await asyncio.to_thread(self._find_title_id, source.source_key, snapshot.external_id)
            if existing is not None:
                return AddResult(existing, created=False)
        return await asyncio.to_thread(self._store_title, kind, source.source_key, snapshot)

    def _find_title_id(self, source_key: str, external_id: str) -> int | None:
        with self.ctx.session_factory() as session:
            return self._primary_title_id(session, source_key, external_id)

    @staticmethod
    def _primary_title_id(session, source_key: str, external_id: str) -> int | None:
        return session.scalar(
            select(ExternalId.title_id).where(
                ExternalId.source == source_key,
                ExternalId.external_id == external_id,
                ExternalId.role == PRIMARY_ROLE,
            )
        )

    def _store_title(self, kind: TitleKind, source_key: str, snapshot: Any) -> AddResult:
        now = self.ctx.now()
        poller = self.pollers.of(kind)
        with self.ctx.write_session() as session:
            # the same title may have been added by a second request while this one waited for the source: the
            # write session holds the database, so what is seen here stays true until the commit
            existing = self._primary_title_id(session, source_key, snapshot.external_id)
            if existing is not None:
                return AddResult(existing, created=False)
            title = Title(
                kind=kind,
                name=snapshot.name,
                original_name=snapshot.original_name,
                year=snapshot.year,
                genres=list(snapshot.genres),
                poster_path=snapshot.poster_path,
                overview=snapshot.overview,
                status=TitleStatus.WANT,
                tracking_enabled=True,
                added_at=now,
                status_changed_at=now,
            )
            session.add(title)
            session.flush()
            session.add(
                ExternalId(title_id=title.id, source=source_key, external_id=snapshot.external_id, role=PRIMARY_ROLE)
            )
            state = snapshot.state()
            seasons = poller.first_seasons(snapshot, now)
            session.add(
                SourceSnapshot(
                    title_id=title.id,
                    source=source_key,
                    state=state,
                    observed_at=now,
                    # the snapshot taken now is the baseline; the first poll compares against it
                    next_check_at=poller.first_check(seasons, state, now),
                )
            )
            records = storage.store_seasons(session, title.id, seasons)
            poller.store_extras(session, title.id, records, snapshot)
            storage.refresh_status(session, title, now)
            session.commit()
            return AddResult(title.id, created=True)

    # --- seasons and statuses -------------------------------------------------------------------

    async def watchable_seasons(self, title_id: int) -> list[WatchableSeason]:
        """Seasons that can be marked as watched, with their marks. A season with nothing released cannot."""
        return await asyncio.to_thread(self._watchable_seasons, title_id)

    def _watchable_seasons(self, title_id: int) -> list[WatchableSeason]:
        with self.ctx.session_factory() as session:
            return _watchable(storage.load_seasons(session, title_id), self.ctx.now())

    async def toggle_season(self, title_id: int, number: int) -> list[WatchableSeason]:
        """The button of a season: mark it as watched, or take the mark off if it is there. Returns the seasons
        that can be marked, with their marks as they are now. Raises UnknownTitle, and UnknownSeason for a season
        that is not there or has nothing released."""
        return await asyncio.to_thread(self._toggle_season, title_id, number)

    def _toggle_season(self, title_id: int, number: int) -> list[WatchableSeason]:
        now = self.ctx.now()
        with self.ctx.write_session() as session:
            title = session.get(Title, title_id)
            if title is None:
                raise UnknownTitle(title_id)
            loaded = storage.load_seasons(session, title_id)
            record = next((r for r, season in loaded if season.number == number and season.released(now) > 0), None)
            if record is None:
                raise UnknownSeason(f"{title_id}:{number}")
            record.watched = not record.watched
            storage.refresh_status(session, title, now)
            seasons = _watchable(loaded, now)
            session.commit()
            return seasons

    async def set_season_watched(self, title_id: int, number: int, watched: bool) -> None:
        """Mark a season as watched, or take the mark off. Marking twice changes nothing."""
        await asyncio.to_thread(self._set_season_watched, title_id, number, watched)

    def _set_season_watched(self, title_id: int, number: int, watched: bool) -> None:
        with self.ctx.write_session() as session:
            if session.get(Title, title_id) is None:
                raise UnknownTitle(title_id)
            record = session.scalar(
                select(SeasonRecord).where(SeasonRecord.title_id == title_id, SeasonRecord.number == number)
            )
            if record is None:
                raise UnknownSeason(f"{title_id}:{number}")
            record.watched = watched
            storage.refresh_status(session, session.get(Title, title_id), self.ctx.now())
            session.commit()

    async def mark_watched(self, title_id: int) -> WatchedResult:
        """«Посмотрел»: the movie gets «Просмотрено» and moves to the archive, where only its sequels are watched."""
        return await asyncio.to_thread(self._set_watched, title_id)

    def _set_watched(self, title_id: int) -> WatchedResult:
        now = self.ctx.now()
        with self.ctx.write_session() as session:
            title = session.get(Title, title_id)
            if title is None:
                raise UnknownTitle(title_id)
            if title.status == TitleStatus.WATCHED:
                return WatchedResult(changed=False)
            title.status = TitleStatus.WATCHED
            title.status_changed_at = now
            title.tracking_enabled = False  # its own release is no longer followed
            sequels = self.pollers.sequels_of(title.kind)
            if sequels is not None:
                # an empty state means "not looked at yet": the first check records the collection as it is,
                # so sequels that already exist are not announced as news
                session.add(
                    SourceSnapshot(
                        title_id=title.id, source=sequels.source.source_key, state={}, observed_at=now,
                        next_check_at=sequels.first_check((), {}, now),
                    )
                )
            session.commit()
            return WatchedResult(changed=True)

    # --- deleting -------------------------------------------------------------------------------

    async def delete_title(self, title_id: int) -> DeleteResult:
        """Remove a title and everything that belongs to it, in one transaction: all of it or nothing."""
        return await asyncio.to_thread(self._delete_title, title_id)

    def _delete_title(self, title_id: int) -> DeleteResult:
        with self.ctx.write_session() as session:
            name = session.scalar(select(Title.name).where(Title.id == title_id))
            if name is None:
                raise UnknownTitle(title_id)
            # the database cascades: seasons, ids, snapshots, events, and the queue entries of those events
            removed = session.execute(delete(Title).where(Title.id == title_id)).rowcount
            if not removed:  # deleted by someone else since the name was read
                session.rollback()
                raise UnknownTitle(title_id)
            session.commit()
            return DeleteResult(name)

    # --- sequels --------------------------------------------------------------------------------

    async def follow_sequel_of(self, kind: str, sequel_id: str) -> AddResult:
        """«Следить» under a sequel announcement: the sequel joins the list as «Хочу». Pressing twice opens it.
        The button names the sequel, so it works even when the announcement or its film is gone."""
        try:
            title_kind = TitleKind(kind)  # `kind` is text from a button or a stored event
        except ValueError:
            raise UnknownKind(kind) from None
        if self.pollers.sequels_of(title_kind) is None:
            raise UnknownKind(kind)
        return await self.add_title(title_kind, sequel_id)

    async def follow_sequel(self, event_id: int) -> AddResult:
        """The same for an old button, which holds only the number of the announcement: works while the event exists."""
        kind, sequel_id = await asyncio.to_thread(self._announced_sequel, event_id)
        return await self.follow_sequel_of(kind, sequel_id)

    def _announced_sequel(self, event_id: int) -> tuple[str, str]:
        with self.ctx.session_factory() as session:
            event = session.get(Event, event_id)
            if event is None or event.type != sequel_events.SEQUEL_ANNOUNCED:
                raise UnknownEvent(event_id)
            return event.payload["kind"], event.payload["sequel_id"]

    # --- the list and the card ------------------------------------------------------------------

    async def list_titles(self) -> list[TitleSummary]:
        return await asyncio.to_thread(self._list_titles)

    def _list_titles(self) -> list[TitleSummary]:
        with self.ctx.session_factory() as session:
            rows = session.scalars(select(Title).order_by(Title.id))
            return [TitleSummary(t.id, t.kind, t.name, t.year, t.status) for t in rows]

    async def overview(self) -> Overview:
        return await asyncio.to_thread(self._overview)

    def _overview(self) -> Overview:
        with self.ctx.session_factory() as session:
            count = session.scalar(select(func.count(Title.id))) or 0
            # only a successful check writes `observed_at`, so a failed one does not move it
            last = session.scalar(select(func.max(SourceSnapshot.observed_at)))
            tz = self.settings.time_zone(session)  # read here, where it is needed (coding standard 2)
        local = last.replace(tzinfo=timezone.utc).astimezone(tz) if last is not None else None
        return Overview(count, local)

    async def title_card(self, title_id: int) -> TitleCard | None:
        return await asyncio.to_thread(self._title_card, title_id)

    def _title_card(self, title_id: int) -> TitleCard | None:
        with self.ctx.session_factory() as session:
            title = session.get(Title, title_id)
            if title is None:
                return None
            state = storage.own_state(session, title_id)
            seasons_view = None
            if is_seasonal(title.kind):
                loaded = storage.load_seasons(session, title_id)
                seasons_view = season_logic.summarize(
                    (season for _, season in loaded),
                    {record.number for record, _ in loaded if record.watched},
                    self.ctx.now(),
                    self.settings.part_gap(session),
                )
            movies = session.scalars(
                select(MovieRecord).where(MovieRecord.title_id == title_id).order_by(MovieRecord.id)
            )
            return TitleCard(
                id=title.id,
                kind=title.kind,
                name=title.name,
                original_name=title.original_name,
                year=title.year,
                genres=list(title.genres),
                status=title.status,
                theatrical_date=parse_date(state.get("theatrical_date")),
                digital_date=parse_date(state.get("digital_date")),
                seasons=seasons_view,
                franchise_movies=tuple(MovieLine(m.name, m.aired_on, m.released) for m in movies),
                tz=self.settings.time_zone(session) if KINDS[title.kind].local_times else None,
            )
