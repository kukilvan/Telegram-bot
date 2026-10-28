"""The owner's marks on a title and the status that follows from them: «Посмотрел», the season marks and
«Отметить все вышедшие». What differs by kind (the sequel check that starts after «Посмотрел») is asked of the
title's poller."""

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING

from app.tracker import seasons as season_logic
from app.tracker import storage
from app.tracker.context import CoreContext
from app.tracker.errors import UnknownSeason, UnknownTitle
from app.tracker.models import SeasonRecord, SourceSnapshot, Title, TitleStatus
from app.tracker.results import WatchableSeason, WatchedResult

if TYPE_CHECKING:
    from app.tracker.polling import Pollers


def _watchable(loaded: list[tuple[SeasonRecord, season_logic.Season]], now: datetime) -> list[WatchableSeason]:
    """The seasons with something released, with the owner's marks: the ones that can be marked."""
    return [WatchableSeason(season.number, record.watched) for record, season in loaded if season.released(now) > 0]


def _markable(loaded: list[tuple[SeasonRecord, season_logic.Season]], title_id: int, number: int, now: datetime) -> SeasonRecord:
    """The record of a season that can be marked; UnknownSeason for one that is not there or has nothing released."""
    record = next((r for r, season in loaded if season.number == number and season.released(now) > 0), None)
    if record is None:
        raise UnknownSeason(f"{title_id}:{number}")
    return record


class Statuses:
    def __init__(self, ctx: CoreContext, pollers: "Pollers") -> None:
        self.ctx = ctx
        self.pollers = pollers

    # --- the season marks -----------------------------------------------------------------------

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
            record = _markable(loaded, title_id, number, now)
            record.watched = not record.watched
            storage.refresh_status(session, title, now)
            seasons = _watchable(loaded, now)
            session.commit()
            return seasons

    async def set_season_watched(self, title_id: int, number: int, watched: bool) -> None:
        """Mark a season as watched, or take the mark off (the state asked for, not a switch: marking twice changes
        nothing). Raises UnknownTitle, and UnknownSeason for a season that is not there or has nothing released."""
        await asyncio.to_thread(self._set_season_watched, title_id, number, watched)

    def _set_season_watched(self, title_id: int, number: int, watched: bool) -> None:
        now = self.ctx.now()
        with self.ctx.write_session() as session:
            title = session.get(Title, title_id)
            if title is None:
                raise UnknownTitle(title_id)
            _markable(storage.load_seasons(session, title_id), title_id, number, now).watched = watched
            storage.refresh_status(session, title, now)
            session.commit()

    async def mark_all_released(self, title_id: int) -> WatchedResult:
        """«Отметить все вышедшие»: every season with at least one released episode gets the mark. Nothing to mark,
        or a film (it has no seasons): nothing changes. Raises UnknownTitle."""
        return await asyncio.to_thread(self._mark_all_released, title_id)

    def _mark_all_released(self, title_id: int) -> WatchedResult:
        now = self.ctx.now()
        with self.ctx.write_session() as session:
            title = session.get(Title, title_id)
            if title is None:
                raise UnknownTitle(title_id)
            unmarked = [
                record for record, season in storage.load_seasons(session, title_id)
                if season.released(now) > 0 and not record.watched
            ]
            for record in unmarked:
                record.watched = True
            if unmarked:
                storage.refresh_status(session, title, now)
            session.commit()
            return WatchedResult(changed=bool(unmarked))

    # --- «Посмотрел» ----------------------------------------------------------------------------

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
