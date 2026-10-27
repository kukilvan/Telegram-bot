"""The bot's assembly: the access gate and the tracker handlers (`build_dispatcher`), the scheduler's jobs
(`add_jobs`). The process itself starts in `app.main`."""

import sys
from datetime import datetime as dt, timezone

from aiogram import Dispatcher
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.bot.access import AccessMiddleware
from app.bot.error_handler import ErrorMiddleware
from app.bot.tracker_handlers import register_tracker_handlers
from app.tracker.core import Tracker
from app.utils.backup import backup_database

TRACKER_BEAT_SECONDS = 60  # how often the tracker polls due titles and, separately, sends the queue (retrying failed sends)
BACKUP_EVERY_HOURS = 1  # how often the bot checks whether a database copy is due (the copy itself: over a day since the last)


def build_dispatcher(tracker: Tracker, allowed_ids: list[int]) -> Dispatcher:
    """The whole bot: the allowlist, the error reporter and the tracker menu. Nothing else answers."""
    dp = Dispatcher()
    # Allowlist goes first so strangers never reach the handlers or the error reporter
    dp.update.outer_middleware(AccessMiddleware(allowed_ids))
    # Error reporting middleware (catches all unhandled exceptions)
    dp.update.outer_middleware(ErrorMiddleware())
    register_tracker_handlers(dp, tracker, allowed_ids)
    return dp


def add_jobs(scheduler: AsyncIOScheduler, tracker: Tracker) -> None:
    """The scheduler's jobs: polling, delivery and the database backup."""
    # Two independent jobs: a slow source must never hold back delivery of events already in the queue.
    # The queue send also retries events whose earlier send failed.
    scheduler.add_job(
        tracker.poll_due, "interval",
        seconds=TRACKER_BEAT_SECONDS,
        misfire_grace_time=30, coalesce=True, max_instances=1,
    )
    scheduler.add_job(
        tracker.deliver_pending, "interval",
        seconds=TRACKER_BEAT_SECONDS,
        misfire_grace_time=30, coalesce=True, max_instances=1,
    )
    # The owner's PC is not on at night, so there is no fixed hour: every hour, starting now, the job makes a copy if
    # the last one is over a day old (so a start after a day off copies at once)
    scheduler.add_job(
        backup_database, "interval",
        hours=BACKUP_EVERY_HOURS, next_run_time=dt.now(timezone.utc),
        misfire_grace_time=300, coalesce=True, max_instances=1,
    )


if __name__ == "__main__":
    # The bot is no longer a process of its own: it runs with the scheduler and the web in `app.main` (ADR 0007)
    print("Бот запускается через Docker: .\\start-bot.ps1")
    sys.exit(1)
