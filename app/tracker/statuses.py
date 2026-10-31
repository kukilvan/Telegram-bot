"""The owner's marks on a title and the status that follows from them: «Посмотрел», «Бросил», «Вернуть в список», the
season marks and «Отметить все вышедшие»; and the owner's scores, which only what is watched gets. What differs by kind
(the sequel check that starts after «Посмотрел») is asked of the title's poller; whether a title has seasons, of the
table of kinds.

A season is known by its record (`SeasonRecord.id`), not by its number: the seasons of an anime are renumbered when the
source changes its chain, and a mark sent from a card opened before that must reach the season the owner saw."""

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING

from app.tracker import scores
from app.tracker import seasons as season_logic
from app.tracker import storage
from app.tracker.context import CoreContext
from app.tracker.errors import CannotScore, UnknownSeason, UnknownTitle
from app.tracker.kinds import is_seasonal
from app.tracker.models import ARCHIVE_STATUSES, SeasonRecord, SourceSnapshot, Title, TitleStatus
from app.tracker.queue import EventQueue
from app.tracker.results import ChangeResult, WatchableSeason

if TYPE_CHECKING:
    from app.tracker.polling import Pollers


def _title(session, title_id: int) -> Title:
    """The title; UnknownTitle when the list has none with this id."""
    title = session.get(Title, title_id)
    if title is None:
        raise UnknownTitle(title_id)
    return title


def _season(session, title_id: int, season_id: int) -> SeasonRecord:
    """The record of a season of this title; UnknownSeason for one that is gone or belongs to another title."""
    record = session.get(SeasonRecord, season_id)
    if record is None or record.title_id != title_id:
        raise UnknownSeason(f"{title_id}:{season_id}")
    return record


def _move(title: Title, status: TitleStatus, now: datetime, *, tracking: bool) -> None:
    """The title gets a status the owner asked for: the status, the moment it changed and whether the title is still
    followed (its own source checked) go together."""
    title.status = status
    title.status_changed_at = now
    title.tracking_enabled = tracking


def _watchable(loaded: list[tuple[SeasonRecord, season_logic.Season]], now: datetime) -> list[WatchableSeason]:
    """The seasons with something released, with the owner's marks: the ones that can be marked."""
    return [
        WatchableSeason(record.id, season.number, record.watched) for record, season in loaded if season.released(now) > 0
    ]


def _markable(
    loaded: list[tuple[SeasonRecord, season_logic.Season]], title_id: int, season_id: int, now: datetime
) -> SeasonRecord:
    """The record of a season that can be marked; UnknownSeason for one that is not there (or not of this title) or
    has nothing released."""
    record = next((r for r, season in loaded if r.id == season_id and season.released(now) > 0), None)
    if record is None:
        raise UnknownSeason(f"{title_id}:{season_id}")
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

    async def toggle_season(self, title_id: int, season_id: int) -> list[WatchableSeason]:
        """The button of a season (by its record): mark it as watched, or take the mark off if it is there. Returns the
        seasons that can be marked, with their marks as they are now. Raises UnknownTitle, and UnknownSeason for a
        season that is not there, not of this title or has nothing released."""
        return await asyncio.to_thread(self._toggle_season, title_id, season_id)

    def _toggle_season(self, title_id: int, season_id: int) -> list[WatchableSeason]:
        now = self.ctx.now()
        with self.ctx.write_session() as session:
            title = _title(session, title_id)
            loaded = storage.load_seasons(session, title_id)
            record = _markable(loaded, title_id, season_id, now)
            record.watched = not record.watched
            storage.refresh_status(session, title, now)
            seasons = _watchable(loaded, now)
            session.commit()
            return seasons

    async def set_season_watched(self, title_id: int, season_id: int, watched: bool) -> None:
        """Mark a season (by its record) as watched, or take the mark off (the state asked for, not a switch: marking
        twice changes nothing). The season's score stays either way; without the mark it is not shown. Raises
        UnknownTitle, and UnknownSeason for a season that is not there, not of this title or has nothing released."""
        await asyncio.to_thread(self._set_season_watched, title_id, season_id, watched)

    def _set_season_watched(self, title_id: int, season_id: int, watched: bool) -> None:
        now = self.ctx.now()
        with self.ctx.write_session() as session:
            title = _title(session, title_id)
            _markable(storage.load_seasons(session, title_id), title_id, season_id, now).watched = watched
            storage.refresh_status(session, title, now)
            session.commit()

    async def mark_all_released(self, title_id: int) -> ChangeResult:
        """«Отметить все вышедшие»: every season with at least one released episode gets the mark. Nothing to mark,
        or a film (it has no seasons): nothing changes. Raises UnknownTitle."""
        return await asyncio.to_thread(self._mark_all_released, title_id)

    def _mark_all_released(self, title_id: int) -> ChangeResult:
        now = self.ctx.now()
        with self.ctx.write_session() as session:
            title = _title(session, title_id)
            unmarked = [
                record for record, season in storage.load_seasons(session, title_id)
                if season.released(now) > 0 and not record.watched
            ]
            for record in unmarked:
                record.watched = True
            if unmarked:
                storage.refresh_status(session, title, now)
            session.commit()
            return ChangeResult(changed=bool(unmarked))

    # --- «Посмотрел» ----------------------------------------------------------------------------

    async def mark_watched(self, title_id: int) -> ChangeResult:
        """«Посмотрел»: the movie gets «Просмотрено» and moves to the archive, where only its sequels are watched."""
        return await asyncio.to_thread(self._set_watched, title_id)

    def _set_watched(self, title_id: int) -> ChangeResult:
        now = self.ctx.now()
        with self.ctx.write_session() as session:
            title = _title(session, title_id)
            if title.status == TitleStatus.WATCHED:
                return ChangeResult(changed=False)
            _move(title, TitleStatus.WATCHED, now, tracking=False)  # its own release is no longer followed
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
            return ChangeResult(changed=True)

    # --- «Бросил» and «Вернуть в список» --------------------------------------------------------

    async def mark_dropped(self, title_id: int) -> ChangeResult:
        """«Бросил», from any status but itself: the title goes to the archive and is no longer checked, not even for
        sequels, and its messages that have not gone out yet are taken out of the queue. Raises UnknownTitle."""
        return await asyncio.to_thread(self._mark_dropped, title_id)

    def _mark_dropped(self, title_id: int) -> ChangeResult:
        now = self.ctx.now()
        with self.ctx.write_session() as session:
            title = _title(session, title_id)
            if title.status == TitleStatus.DROPPED:
                return ChangeResult(changed=False)
            _move(title, TitleStatus.DROPPED, now, tracking=False)
            storage.drop_sequel_check(session, title_id)  # a watched movie dropped in a second tab
            EventQueue.withdraw(session, title_id)
            session.commit()
            return ChangeResult(changed=True)

    async def restore_title(self, title_id: int) -> ChangeResult:
        """«Вернуть в список»: the title leaves the archive. A movie is «Хочу» again; a series or an anime comes back from
        «Бросил» with the status its season marks give. Its own source is checked within a minute, and that first check
        is the baseline: what happened while the title was in the archive is recorded without events. A title out of
        the archive, or a series that is «Просмотрено» (its marks give that status), is left as it is. Raises UnknownTitle."""
        return await asyncio.to_thread(self._restore_title, title_id)

    def _restore_title(self, title_id: int) -> ChangeResult:
        now = self.ctx.now()
        with self.ctx.write_session() as session:
            title = _title(session, title_id)
            seasonal = is_seasonal(title.kind)
            if title.status not in ARCHIVE_STATUSES or (seasonal and title.status == TitleStatus.WATCHED):
                return ChangeResult(changed=False)
            _move(title, TitleStatus.WANT, now, tracking=True)
            title.restored_at = now
            # a movie waits for its own release again; the next «Посмотрел» starts the sequel check anew
            storage.drop_sequel_check(session, title_id)
            storage.refresh_status(session, title, now)  # a series: the status its marks give
            own = storage.own_snapshot(session, title_id)
            if own is not None:
                own.next_check_at = now
            session.commit()
            return ChangeResult(changed=True)

    # --- scores ---------------------------------------------------------------------------------

    async def set_title_score(self, title_id: int, score: int | None) -> ChangeResult:
        """The owner's own score of the title: a value of the scale, or None to take it off (a series or an anime then
        shows the average of its seasons again). A value only while the title can be scored (`scores.scorable`):
        CannotScore otherwise; taking it off always works. Raises UnknownTitle, and ValueError for a value off the
        scale (the caller's mistake)."""
        if score is not None:
            scores.check(score)
        return await asyncio.to_thread(self._set_title_score, title_id, score)

    def _set_title_score(self, title_id: int, score: int | None) -> ChangeResult:
        with self.ctx.write_session() as session:
            title = _title(session, title_id)
            if score is not None and not scores.scorable(title, storage.any_marked(session, title_id)):
                raise CannotScore(title_id)
            changed = title.score != score
            title.score = score
            session.commit()
            return ChangeResult(changed)

    async def set_season_score(self, title_id: int, season_id: int, score: int | None) -> ChangeResult:
        """The score of a season (by its record): a value of the scale, or None to take it off. A value only while
        the season has its «watched» mark: CannotScore otherwise. Raises UnknownTitle, UnknownSeason for a season that
        is not there or not of this title, and ValueError for a value off the scale."""
        if score is not None:
            scores.check(score)
        return await asyncio.to_thread(self._set_season_score, title_id, season_id, score)

    def _set_season_score(self, title_id: int, season_id: int, score: int | None) -> ChangeResult:
        with self.ctx.write_session() as session:
            _title(session, title_id)
            record = _season(session, title_id, season_id)
            if score is not None and not record.watched:
                raise CannotScore(title_id, season_id)
            changed = record.score != score
            record.score = score
            session.commit()
            return ChangeResult(changed)
