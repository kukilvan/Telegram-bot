"""Polling: the pass over the titles whose check time has come, and the one table that says which poller serves a kind.

A failing source postpones only its own title; the others are still polled. Database work runs in a worker thread, so
a slow disk never freezes the bot.
"""

import asyncio
import logging
from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from sqlalchemy import and_, or_, select

from app.tracker import failures, movie_events
from app.tracker import storage
from app.tracker.context import PRIMARY_ROLE, CoreContext
from app.tracker.models import ExternalId, SourceSnapshot, Title, TitleKind, TitleStatus
from app.tracker.pollers.anime import AnimePoller
from app.tracker.pollers.base import DueTitle, Poller
from app.tracker.pollers.game import GamePoller
from app.tracker.pollers.movie import MoviePoller
from app.tracker.pollers.sequels import SequelPoller
from app.tracker.pollers.series import SeriesPoller
from app.tracker.queue import EventQueue
from app.tracker.results import PollReport
from app.tracker.settings_store import SettingsStore

# an own-release check runs for these, while tracking is on
POLLED_STATUSES = (TitleStatus.WANT, TitleStatus.IN_PROGRESS, TitleStatus.WAITING)

# the only place that chooses the poller by the kind of title; a new kind is a new poller here and a row in `kinds`
POLLER_CLASSES: Mapping[TitleKind, type[Poller]] = {
    TitleKind.MOVIE: MoviePoller,
    TitleKind.SERIES: SeriesPoller,
    TitleKind.ANIME: AnimePoller,
    TitleKind.GAME: GamePoller,
}


class Pollers:
    """The pollers of the kinds the core has a source for, and the sequel pollers of the kinds that have a sequel source.
    What the owner reads (the feed, the card) is asked of the poller of any kind, with a source or without: it reads
    only the database."""

    def __init__(
        self,
        ctx: CoreContext,
        settings: SettingsStore,
        queue: EventQueue,
        sources: Mapping[TitleKind, Any],
        sequel_sources: Mapping[TitleKind, Any],
    ) -> None:
        self._every = {
            kind: poller_class(kind, sources.get(kind), ctx, settings, queue) for kind, poller_class in POLLER_CLASSES.items()
        }
        self._release = {kind: self._every[kind] for kind in sources}
        self._sequels = {
            kind: SequelPoller(kind, source, ctx, settings, queue, release_source=sources.get(kind))
            for kind, source in sequel_sources.items()
        }

    def of(self, kind: TitleKind) -> Poller:
        """The poller of the kind's own release. KeyError when the core has no source for the kind."""
        return self._release[kind]

    def reader_of(self, kind: TitleKind) -> Poller:
        """The poller of the kind for what the owner reads; every kind has one, whether the core has its source or not."""
        return self._every[kind]

    def sequels_of(self, kind: TitleKind) -> SequelPoller | None:
        return self._sequels.get(kind)

    def for_due(self, due: DueTitle) -> Poller:
        return self._sequels[due.kind] if due.sequels else self._release[due.kind]


class Polling:
    def __init__(self, ctx: CoreContext, queue: EventQueue, pollers: Pollers) -> None:
        self.ctx = ctx
        self.queue = queue
        self.pollers = pollers

    async def poll_due(self) -> PollReport:
        """Look at every title whose check time has come and queue the events found."""
        report = PollReport()
        broken: list[tuple[DueTitle, Exception]] = []
        async with self.ctx.poll_lock:
            for due in await asyncio.to_thread(self._due_titles):
                await self._poll_one(due, report, broken)
            if broken:
                await self._tell_owner_about(broken, report)
        return report

    def _due_titles(self) -> list[DueTitle]:
        now = self.ctx.now()
        with self.ctx.session_factory() as session:
            # a title's own source is the one of its primary id; any other snapshot is its sequel check
            own = SourceSnapshot.source == ExternalId.source
            # the own source's first check since «Вернуть в список»: the stored look is older than the return
            baseline = and_(own, Title.restored_at.is_not(None), SourceSnapshot.observed_at < Title.restored_at)
            rows = session.execute(
                select(Title.id, Title.kind, Title.name, ExternalId.external_id, SourceSnapshot.source, ~own, baseline)
                .join(SourceSnapshot, SourceSnapshot.title_id == Title.id)
                .join(
                    ExternalId,
                    (ExternalId.title_id == Title.id) & (ExternalId.role == PRIMARY_ROLE),
                )
                .where(
                    or_(
                        and_(
                            own,
                            Title.kind.in_(tuple(POLLER_CLASSES)),
                            Title.status.in_(POLLED_STATUSES),
                            Title.tracking_enabled.is_(True),
                        ),
                        and_(~own, Title.status == TitleStatus.WATCHED),
                    ),
                    (SourceSnapshot.next_check_at.is_(None)) | (SourceSnapshot.next_check_at <= now),
                )
                .order_by(Title.id)
            )
            return [
                DueTitle(title_id, kind, name, external_id, source, bool(sequels), bool(first_after_return))
                for title_id, kind, name, external_id, source, sequels, first_after_return in rows
            ]

    async def _poll_one(self, due: DueTitle, report: PollReport, broken: list[tuple[DueTitle, Exception]]) -> None:
        try:
            poller = self.pollers.for_due(due)
            snapshot = await poller.source.snapshot(due.external_id)
            if snapshot is None:
                raise failures.TitleGone(f"{due.kind}:{due.external_id} is no longer known to the source")
            found = await asyncio.to_thread(poller.apply, due, snapshot)
        except Exception as exc:  # one broken title or source must not stop the pass
            if not await asyncio.to_thread(self._still_checked, due):
                # nothing broke: the title was deleted, or its check stopped («Бросил», «Вернуть в список»)
                logging.info("title %s or its check was removed while it was polled", due.id)
                return
            logging.warning("polling title %s failed: %s", due.id, repr(exc))
            report.failed += 1
            broken.append((due, exc))
            try:
                await asyncio.to_thread(self._postpone, due, movie_events.RETRY_AFTER_FAILURE)
            except Exception as postpone_exc:  # even a failed postponement leaves the other titles to the pass
                logging.warning("postponing title %s failed: %s", due.id, repr(postpone_exc))
            return
        report.polled += 1
        report.events += found

    def _still_checked(self, due: DueTitle) -> bool:
        """Whether the snapshot of this check is still there (it goes with its title, and with the sequel check)."""
        with self.ctx.session_factory() as session:
            return session.scalar(
                select(SourceSnapshot.id).where(
                    SourceSnapshot.title_id == due.id, SourceSnapshot.source == due.snapshot_source
                )
            ) is not None

    async def _tell_owner_about(self, broken: list[tuple[DueTitle, Exception]], report: PollReport) -> None:
        try:
            report.notices = await asyncio.to_thread(self.queue.queue_failure_notices, broken)
        except Exception as exc:  # a notice that cannot be stored must not hide the pass; the next failure tries again
            logging.warning("queueing failure notices failed: %s", repr(exc))

    def _postpone(self, due: DueTitle, delay: timedelta) -> None:
        now = self.ctx.now()
        with self.ctx.write_session() as session:
            storage.stored_snapshot(session, due.id, due.snapshot_source).next_check_at = now + delay
            session.commit()
