"""The bot's assembly: the access gate and the tracker handlers (`build_dispatcher`), the scheduler's jobs
(`add_jobs`). The process itself starts in `app.main`."""

import sys
from datetime import datetime as dt, timezone

from aiogram import Dispatcher
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.bot.access import AccessMiddleware
from app.bot.app_links import AppLinks
from app.bot.error_handler import ErrorMiddleware
from app.bot.runtime_watch import RunningUpdates
from app.bot.tracker_handlers import register_tracker_handlers
from app.tracker.core import Tracker, shikimori_site

TRACKER_BEAT_SECONDS = 60  # how often the tracker polls due titles, sends the queue (retrying failed sends) and moves the inbox items that waited 12 hours
BACKUP_EVERY_HOURS = 1  # how often the bot checks whether a database copy is due (the copy itself: over a day since the last)


def build_dispatcher(
    tracker: Tracker, allowed_ids: list[int], links: AppLinks | None = None, shikimori_base_url: str = "",
    running: RunningUpdates | None = None,
) -> Dispatcher:
    """The whole bot: the allowlist, the error reporter and the tracker menu. Nothing else answers. `links` is link mode
    (the buttons lead to the app), `None` is chat mode; `shikimori_base_url` is SHIKIMORI_BASE_URL, the site the posters
    of Shikimori are shown from in the cards (KI-21); `running` keeps the updates being handled, for the stop to wait
    for them (KI-9; a fresh one when not given)."""
    dp = Dispatcher()
    # Outermost: every update is kept while it runs, the stop waits for it
    dp.update.outer_middleware(running if running is not None else RunningUpdates())
    # Allowlist goes first so strangers never reach the handlers or the error reporter
    dp.update.outer_middleware(AccessMiddleware(allowed_ids))
    # Error reporting middleware (catches all unhandled exceptions)
    dp.update.outer_middleware(ErrorMiddleware())
    register_tracker_handlers(dp, tracker, allowed_ids, links, shikimori_site(shikimori_base_url))
    return dp


def add_jobs(scheduler: AsyncIOScheduler, tracker: Tracker) -> None:
    """The scheduler's jobs: polling, delivery, the 12 hours of the inbox items and the database backup."""
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
    # A job of its own: a bug in it must not stop polling or delivery
    scheduler.add_job(
        tracker.expire_inbox, "interval",
        seconds=TRACKER_BEAT_SECONDS,
        misfire_grace_time=30, coalesce=True, max_instances=1,
    )
    # The owner's PC is not on at night, so there is no fixed hour: every hour, starting now, the job makes a copy if
    # the last one is over a day old (so a start after a day off copies at once)
    scheduler.add_job(
        tracker.backup_database, "interval",
        hours=BACKUP_EVERY_HOURS, next_run_time=dt.now(timezone.utc),
        misfire_grace_time=300, coalesce=True, max_instances=1,
    )


if __name__ == "__main__":
    # The bot is no longer a process of its own: it runs with the scheduler and the web in `app.main` (ADR 0007)
    print("Бот запускается через Docker: .\\start-bot.ps1")
    sys.exit(1)
