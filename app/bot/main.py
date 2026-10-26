"""Bot entry point: the access gate, the tracker core with its handlers and the scheduler."""

import asyncio
import logging
from datetime import datetime as dt, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.bot.access import AccessMiddleware
from app.bot.error_handler import ErrorMiddleware, send_startup_error_sync
from app.bot.tracker_handlers import TelegramSender, owner_chat_id, register_tracker_handlers
from app.config import get_settings
from app.providers.anilist import AniListProvider
from app.providers.shikimori import ShikimoriClient
from app.providers.tmdb import TMDbProvider
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.sources.shikimori_anime import ShikimoriAnimeSource
from app.tracker.sources.tmdb_movies import TmdbMovieSource
from app.tracker.sources.tmdb_sequels import TmdbSequelSource
from app.tracker.sources.tmdb_series import TmdbSeriesSource
from app.utils.backup import backup_database
from app.utils.logging_config import setup_logging

TRACKER_BEAT_SECONDS = 60  # how often the tracker polls due titles and, separately, sends the queue (retrying failed sends)

def build_dispatcher(tracker: Tracker, allowed_ids: list[int]) -> Dispatcher:
    """The whole bot: the allowlist, the error reporter and the tracker menu. Nothing else answers."""
    dp = Dispatcher()
    # Allowlist goes first so strangers never reach the handlers or the error reporter
    dp.update.outer_middleware(AccessMiddleware(allowed_ids))
    # Error reporting middleware (catches all unhandled exceptions)
    dp.update.outer_middleware(ErrorMiddleware())
    register_tracker_handlers(dp, tracker, allowed_ids)
    return dp


async def main() -> None:
    setup_logging(level="INFO")
    settings = get_settings()
    logging.info("Starting bot...")

    allowed_ids = settings.allowed_telegram_user_ids
    if not allowed_ids:
        logging.critical("ALLOWED_TELEGRAM_USER_IDS is empty: refusing to start an open bot")
        raise SystemExit(1)

    tmdb = TMDbProvider()
    anilist = AniListProvider()
    shikimori = ShikimoriClient()

    async with Bot(token=settings.telegram_bot_token) as bot:
        me = await bot.get_me()
        logging.info(f"Bot started as @{me.username}")

        tracker = Tracker(
            create_session_factory(),
            clock=lambda: dt.now(tz=timezone.utc),
            sender=TelegramSender(bot, owner_chat_id(settings.owner_chat_id, allowed_ids)),
            sources={
                "movie": TmdbMovieSource(tmdb),
                "series": TmdbSeriesSource(tmdb),
                "anime": ShikimoriAnimeSource(shikimori, anilist),
            },
            sequel_sources={"movie": TmdbSequelSource(tmdb)},
            default_tz=ZoneInfo(settings.bot_timezone),
        )
        dp = build_dispatcher(tracker, allowed_ids)

        scheduler = AsyncIOScheduler()
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
        # Daily database backup at 3 AM
        scheduler.add_job(
            backup_database, "cron", hour=3, minute=0,
            misfire_grace_time=90,
        )
        scheduler.start()

        # Long polling (for VPS deployment without webhook setup)
        await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        # Startup crash protection: send error via HTTP before anything else
        try:
            settings = get_settings()
            send_startup_error_sync(settings.telegram_bot_token, settings.owner_chat_id, e)
        except Exception:
            pass  # Best effort — don't crash on error reporting
        raise
