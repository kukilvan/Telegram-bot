"""Process entry point, `python -m app.main`: the bot, the scheduler and the web in one process (ADR 0007).

Order: log → settings → database → tracker core → web server → scheduler → bot → watchdog (the last four start in
`app/runtime.py`). A failure before the work begins exits with code 1 and is reported to the owner in Telegram: the
same failure at once and then once a day, while Docker starts the process again every minute (`app/startup_report.py`).
"""

import asyncio
import logging
import os
import sys
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime as dt, timezone
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.utils.token import TokenValidationError, validate_token
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.bot.error_handler import send_startup_error_sync
from app.bot.main import add_jobs, build_dispatcher
from app.bot.tracker_handlers import BOT_COMMANDS, MALFORMED_TOKEN, TelegramSender
from app.config import Settings, get_settings, time_zone_of
from app.providers.anilist import AniListProvider
from app.providers.igdb import IGDBProvider
from app.providers.shikimori import ShikimoriClient
from app.providers.steam import SteamProvider
from app.providers.tmdb import TMDbProvider
from app.runtime import Health, Runtime
from app.startup_report import forget_failure, report_failure
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import TitleKind
from app.tracker.sources.igdb_games import IgdbGameSource
from app.tracker.sources.shikimori_anime import ShikimoriAnimeSource
from app.tracker.sources.tmdb_movies import TmdbMovieSource
from app.tracker.sources.tmdb_sequels import TmdbSequelSource
from app.tracker.sources.tmdb_series import TmdbSeriesSource
from app.utils.logging_config import setup_logging
from app.web import MIN_PASSWORD_LENGTH, create_web_app, web_server
from app.web.posters import image_sources

WEB_PORT = 8080  # inside the process; the port on the PC is docker compose's business
# Not the owner's setting (not in .env.example): run from .venv on Windows the web must not open to the whole home
# network, so the default is this PC only; the Docker image sets 0.0.0.0
WEB_BIND_HOST = "WEB_BIND_HOST"
WEB_STOP_GRACE_SECONDS = 5  # the started requests get this long on stop
WEB_SECRET_FILE = Path("data") / "web_secret"  # the key that signs the session cookie (next to the database)
STARTUP_FAILURE_FILE = Path("data") / "startup_failure.json"  # the last failure before the start and its report
EMPTY_ALLOWLIST = (
    "ALLOWED_TELEGRAM_USER_IDS пуст: бот не запускается открытым для всех. "
    "Впишите в .env свой номер Telegram (узнать — @userinfobot)"
)


class TelegramPart:
    """The bot part of the runtime: aiogram's long polling without its own signal handling. Without a bot (a malformed
    token) every connect fails with the same words, and the runtime tries again by its rules."""

    def __init__(self, bot: Bot | None, dispatcher: Dispatcher) -> None:
        self._bot = bot
        self._dispatcher = dispatcher
        self._receiving_began: Callable[[], None] = lambda: None
        # once, not per attempt: the dispatcher keeps its handlers
        dispatcher.startup.register(self._on_startup)

    async def connect(self) -> None:
        if self._bot is None:
            raise RuntimeError(MALFORMED_TOKEN)
        me = await self._bot.me()
        logging.info("Bot started as @%s", me.username)
        await self._bot.set_my_commands(BOT_COMMANDS)

    async def receive(self, started: Callable[[], None]) -> None:
        # aiogram's `startup` comes after its preparation, right before it asks Telegram for messages
        self._receiving_began = started
        # The session stays open between the attempts: the queue sends events through it (`TelegramSender`)
        await self._dispatcher.start_polling(self._bot, handle_signals=False, close_bot_session=False)

    async def _on_startup(self) -> None:
        self._receiving_began()

    async def stop(self) -> None:
        with suppress(RuntimeError):  # "Polling is not started": the bot is connecting or waiting to connect again
            await self._dispatcher.stop_polling()

    async def close(self) -> None:
        if self._bot is not None:
            await self._bot.session.close()


def telegram_bot(token: str) -> Bot | None:
    """The bot, or None when aiogram refuses the token (empty, no `:`, a space…): the process goes on without it, the
    web and the polling of sources work. The token itself is never logged."""
    try:
        validate_token(token)
    except TokenValidationError:
        logging.error(MALFORMED_TOKEN)
        return None
    return Bot(token=token)


def build_tracker(settings: Settings, bot: Bot | None) -> Tracker:
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
            # without the keys of IGDB the source is «not connected»: it asks nothing and says so
            TitleKind.GAME: IgdbGameSource(
                IGDBProvider(settings.igdb_client_id, settings.igdb_client_secret), SteamProvider()
            ),
        },
        sequel_sources={TitleKind.MOVIE: TmdbSequelSource(tmdb)},
        default_tz=time_zone_of(settings),
    )


async def main() -> int:
    settings = get_settings()
    logging.info("Starting bot...")

    allowed_ids = settings.allowed_telegram_user_ids
    if not allowed_ids:
        raise RuntimeError(EMPTY_ALLOWLIST)  # a failure before the start, reported as any other
    if settings.owner_chat_id.strip() and settings.owner_chat_id_number is None:
        logging.warning("OWNER_CHAT_ID is not a number; messages for the owner go to the first allowed user")

    if len(settings.web_password) < MIN_PASSWORD_LENGTH:
        logging.warning("WEB_PASSWORD не задан или короче %s символов: вход в веб закрыт", MIN_PASSWORD_LENGTH)

    bot = telegram_bot(settings.telegram_bot_token)
    tracker = build_tracker(settings, bot)

    health = Health()
    host = os.environ.get(WEB_BIND_HOST, "").strip() or "127.0.0.1"
    web_app = create_web_app(
        health=health.report, password=settings.web_password, secret_file=WEB_SECRET_FILE, tracker=tracker,
        image_sources=image_sources(settings.shikimori_base_url), telegram_down=lambda: health.telegram_down,
    )
    server = web_server(web_app, host=host, port=WEB_PORT, stop_grace=WEB_STOP_GRACE_SECONDS)
    scheduler = AsyncIOScheduler()
    add_jobs(scheduler, tracker)
    runtime = Runtime(
        web=server, scheduler=scheduler, bot=TelegramPart(bot, build_dispatcher(tracker, allowed_ids)), health=health,
    )
    forget_failure(STARTUP_FAILURE_FILE)  # everything is assembled: the start succeeded
    return await runtime.run()


def report_startup_error(exc: BaseException) -> None:
    """Send the failure to the owner over plain HTTP (the bot may not be up), if it is due; best effort. Nowhere to
    send it (the settings do not read, no owner's chat) — no report, and the record of the failure stays as it is."""
    try:
        settings = get_settings()
    except Exception:
        return  # the failure is the settings themselves: run() has logged it
    chat = settings.owner_chat
    if chat is None:
        return
    try:
        report_failure(
            exc,
            send=lambda heading: send_startup_error_sync(settings.telegram_bot_token, chat, exc, heading),
            file=STARTUP_FAILURE_FILE,
            now=dt.now(tz=timezone.utc),
        )
    except Exception:
        logging.exception("отчёт о сбое запуска не отправлен")  # it must not hide the failure itself


def run() -> int:
    setup_logging(level="INFO")
    try:
        return asyncio.run(main())
    except KeyboardInterrupt:
        # Windows, Ctrl+C before the parts started or a second Ctrl+C during the stop: leave quietly
        logging.info("остановлено")
        return 0
    except Exception as exc:
        logging.critical("запуск не удался", exc_info=True)
        report_startup_error(exc)
        return 1


if __name__ == "__main__":
    sys.exit(run())
