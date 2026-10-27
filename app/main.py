"""Process entry point, `python -m app.main`: the bot, the scheduler and the web in one process (ADR 0007).

Order: log → settings → database → tracker core → web server → scheduler → bot → watchdog (the last four start in
`app/runtime.py`). A failure before the work begins is reported to the owner in Telegram and exits with code 1.
"""

import asyncio
import logging
import os
import sys
from contextlib import suppress
from datetime import datetime as dt, timezone

from aiogram import Bot, Dispatcher
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.bot.error_handler import send_startup_error_sync
from app.bot.main import add_jobs, build_dispatcher
from app.bot.tracker_handlers import BOT_COMMANDS, TelegramSender
from app.config import Settings, get_settings, time_zone_of
from app.providers.anilist import AniListProvider
from app.providers.shikimori import ShikimoriClient
from app.providers.tmdb import TMDbProvider
from app.runtime import Health, Runtime
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import TitleKind
from app.tracker.sources.shikimori_anime import ShikimoriAnimeSource
from app.tracker.sources.tmdb_movies import TmdbMovieSource
from app.tracker.sources.tmdb_sequels import TmdbSequelSource
from app.tracker.sources.tmdb_series import TmdbSeriesSource
from app.utils.logging_config import setup_logging
from app.web import create_web_app, web_server

WEB_PORT = 8080  # inside the process; the port on the PC is docker compose's business
# Not the owner's setting (not in .env.example): run from .venv on Windows the web must not open to the whole home
# network, so the default is this PC only; the Docker image sets 0.0.0.0
WEB_BIND_HOST = "WEB_BIND_HOST"
WEB_STOP_GRACE_SECONDS = 5  # the started requests get this long on stop


class TelegramPart:
    """The bot part of the runtime: aiogram's long polling without its own signal handling."""

    def __init__(self, bot: Bot, dispatcher: Dispatcher) -> None:
        self._bot = bot
        self._dispatcher = dispatcher

    async def connect(self) -> None:
        me = await self._bot.me()
        logging.info("Bot started as @%s", me.username)
        await self._bot.set_my_commands(BOT_COMMANDS)

    async def receive(self) -> None:
        # The session stays open between the attempts: the queue sends events through it (`TelegramSender`)
        await self._dispatcher.start_polling(self._bot, handle_signals=False, close_bot_session=False)

    async def stop(self) -> None:
        with suppress(RuntimeError):  # "Polling is not started": the bot is connecting or waiting to connect again
            await self._dispatcher.stop_polling()

    async def close(self) -> None:
        await self._bot.session.close()


def build_tracker(settings: Settings, bot: Bot) -> Tracker:
    """The tracker core with its sources; the database is migrated (and copied first) here."""
    tmdb = TMDbProvider()
    return Tracker(
        create_session_factory(),
        clock=lambda: dt.now(tz=timezone.utc),
        sender=TelegramSender(bot, settings.owner_chat),
        sources={
            TitleKind.MOVIE: TmdbMovieSource(tmdb),
            TitleKind.SERIES: TmdbSeriesSource(tmdb),
            TitleKind.ANIME: ShikimoriAnimeSource(ShikimoriClient(), AniListProvider()),
        },
        sequel_sources={TitleKind.MOVIE: TmdbSequelSource(tmdb)},
        default_tz=time_zone_of(settings),
    )


async def main() -> int:
    settings = get_settings()
    logging.info("Starting bot...")

    allowed_ids = settings.allowed_telegram_user_ids
    if not allowed_ids:
        logging.critical("ALLOWED_TELEGRAM_USER_IDS is empty: refusing to start an open bot")
        return 1
    if settings.owner_chat_id.strip() and settings.owner_chat_id_number is None:
        logging.warning("OWNER_CHAT_ID is not a number; messages for the owner go to the first allowed user")

    bot = Bot(token=settings.telegram_bot_token)
    tracker = build_tracker(settings, bot)

    health = Health()
    host = os.environ.get(WEB_BIND_HOST, "").strip() or "127.0.0.1"
    server = web_server(create_web_app(health=health.report), host=host, port=WEB_PORT,
                        stop_grace=WEB_STOP_GRACE_SECONDS)
    scheduler = AsyncIOScheduler()
    add_jobs(scheduler, tracker)
    runtime = Runtime(
        web=server, scheduler=scheduler, bot=TelegramPart(bot, build_dispatcher(tracker, allowed_ids)), health=health,
    )
    return await runtime.run()


def report_startup_error(exc: BaseException) -> None:
    """Send the failure to the owner over plain HTTP (the bot may not be up); best effort."""
    try:
        settings = get_settings()
        if settings.owner_chat is not None:
            send_startup_error_sync(settings.telegram_bot_token, settings.owner_chat, exc)
    except Exception:
        pass  # a report that fails must not hide the failure itself


def run() -> int:
    setup_logging(level="INFO")
    try:
        return asyncio.run(main())
    except KeyboardInterrupt:
        # Windows, Ctrl+C before the parts started or a second Ctrl+C during the stop: leave quietly
        logging.info("остановлено")
        return 0
    except Exception as exc:
        logging.exception("запуск не удался")
        report_startup_error(exc)
        return 1


if __name__ == "__main__":
    sys.exit(run())
