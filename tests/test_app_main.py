"""The process entry point `app.main` (ADR 0007): what it hands the runtime, failures before the start and their
report, a malformed token, the old entry point and the launch script."""

import asyncio
import logging
import subprocess
import sys
from datetime import datetime as dt, timezone
from pathlib import Path

import pytest
from aiogram import Bot, Dispatcher
from sqlalchemy import select

import app.main as app_main
from app.bot.tracker_handlers import MALFORMED_TOKEN, TelegramSender
from app.startup_report import read_record
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import DeliveryItem
from app.utils import logging_config

ROOT = Path(__file__).resolve().parent.parent
BOT_TOKEN = "123456789:AAH-secretTokenValue_abcdefghijklmnopqrstuv"


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr("app.config.load_dotenv", lambda *a, **k: False)  # the real .env must not leak into the tests
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    monkeypatch.setenv("TMDB_API_KEY", "tmdb-test-key")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "42")
    monkeypatch.setenv("BOT_TIMEZONE", "UTC")
    monkeypatch.delenv("OWNER_CHAT_ID", raising=False)
    monkeypatch.delenv(app_main.WEB_BIND_HOST, raising=False)
    monkeypatch.delenv("WEB_PASSWORD", raising=False)
    monkeypatch.setattr(app_main, "WEB_SECRET_FILE", tmp_path / "web_secret")  # not the real data folder
    monkeypatch.setattr(app_main, "STARTUP_FAILURE_FILE", tmp_path / "startup_failure.json")
    monkeypatch.setattr(app_main, "setup_logging", lambda level: None)
    return monkeypatch


@pytest.fixture
def assembled(env):
    """`main` up to the runtime: an in-memory database, and the runtime and the web server recorded, not run."""
    seen = {}

    def fake_web_server(app, *, host, port, stop_grace):
        seen.update(host=host, port=port, stop_grace=stop_grace)
        return "server"

    class FakeRuntime:
        def __init__(self, **parts):
            seen["parts"] = parts

        async def run(self):
            return 0

    env.setattr(app_main, "create_session_factory", lambda: create_session_factory("sqlite://"))
    env.setattr(app_main, "web_server", fake_web_server)
    env.setattr(app_main, "Runtime", FakeRuntime)
    return seen


def test_main_hands_the_runtime_the_web_server_the_scheduler_and_the_bot(assembled):
    assert asyncio.run(app_main.main()) == 0

    parts = assembled["parts"]
    assert parts["web"] == "server" and isinstance(parts["bot"], app_main.TelegramPart)
    assert len(parts["scheduler"].get_jobs()) == 3  # polling, delivery and the backup (`add_jobs`)
    assert (assembled["port"], assembled["stop_grace"]) == (8080, 5)


def test_the_web_listens_on_this_pc_only_unless_the_image_says_otherwise(assembled):
    asyncio.run(app_main.main())
    assert assembled["host"] == "127.0.0.1"


def test_web_bind_host_from_the_environment_is_used(assembled, env):
    env.setenv(app_main.WEB_BIND_HOST, "0.0.0.0")

    asyncio.run(app_main.main())

    assert assembled["host"] == "0.0.0.0"


# ---- failures before the start and their report ---------------------------

@pytest.fixture
def reports(env):
    """The reports `run` sends to Telegram (no network): (chat, the failure, the heading); Telegram takes them."""
    sent = []

    def fake_send(token, chat, exc, heading):
        sent.append((chat, str(exc), heading))
        return True

    env.setattr(app_main, "send_startup_error_sync", fake_send)
    return sent


async def failing_main():
    raise RuntimeError("the database is locked")


def test_a_failure_before_the_start_is_reported_to_the_owner_and_exits_with_1(env, reports):
    env.setattr(app_main, "main", failing_main)

    assert app_main.run() == 1
    assert [(chat, text) for chat, text, _ in reports] == [(42, "the database is locked")]
    assert "Бот не запустился" in reports[0][2]


def test_the_same_failure_on_the_next_start_is_not_reported_again(env, reports):
    env.setattr(app_main, "main", failing_main)

    assert app_main.run() == 1
    assert app_main.run() == 1

    assert len(reports) == 1


def test_a_successful_start_forgets_the_failure_and_the_same_one_is_reported_at_once(env, reports, assembled, caplog):
    real_main = app_main.main
    env.setattr(app_main, "main", failing_main)
    app_main.run()

    with caplog.at_level(logging.INFO):
        assert asyncio.run(real_main()) == 0
    assert read_record(app_main.STARTUP_FAILURE_FILE) is None
    assert "больше не повторяется" in caplog.text
    app_main.run()

    assert len(reports) == 2


def test_an_empty_allowlist_is_a_failure_before_the_start_reported_to_the_owner_chat(env, reports):
    env.setenv("ALLOWED_TELEGRAM_USER_IDS", "")
    env.setenv("OWNER_CHAT_ID", "777")

    assert app_main.run() == 1

    assert [(chat, text) for chat, text, _ in reports] == [(777, app_main.EMPTY_ALLOWLIST)]
    assert "ALLOWED_TELEGRAM_USER_IDS пуст: бот не запускается открытым для всех" in app_main.EMPTY_ALLOWLIST


def test_an_empty_allowlist_without_an_owner_chat_is_only_logged(env, reports, caplog):
    env.setenv("ALLOWED_TELEGRAM_USER_IDS", "")

    with caplog.at_level(logging.CRITICAL):
        assert app_main.run() == 1

    assert reports == []
    assert "запуск не удался" in caplog.text and "ALLOWED_TELEGRAM_USER_IDS пуст" in caplog.text
    assert not app_main.STARTUP_FAILURE_FILE.exists()  # nowhere to report: the record is not touched


def test_settings_that_do_not_read_give_no_report(env, reports):
    env.delenv("TELEGRAM_BOT_TOKEN")

    assert app_main.run() == 1

    assert reports == [] and not app_main.STARTUP_FAILURE_FILE.exists()


def test_ctrl_c_before_the_parts_started_leaves_quietly(env):
    async def interrupted_main():
        raise KeyboardInterrupt

    env.setattr(app_main, "main", interrupted_main)

    assert app_main.run() == 0


def test_stopping_the_bot_part_before_it_receives_is_quiet():
    async def scenario():
        part = app_main.TelegramPart(Bot(token=BOT_TOKEN), Dispatcher())
        await part.stop()
        await part.close()

    asyncio.run(scenario())


class StartingDispatcher(Dispatcher):
    """aiogram's dispatcher whose polling only sends its `startup` event, the way `start_polling` does after its
    preparation, and asks Telegram for nothing."""

    async def start_polling(self, *bots, **kwargs):
        await self.emit_startup(bot=bots[-1], dispatcher=self, bots=bots)


def test_the_bot_part_says_receiving_has_begun_on_the_dispatchers_startup():
    began = []

    async def scenario():
        part = app_main.TelegramPart(Bot(token=BOT_TOKEN), StartingDispatcher())
        await part.receive(lambda: began.append("first"))
        await part.receive(lambda: began.append("second"))  # each attempt signals once, to its own runtime call
        await part.close()

    asyncio.run(scenario())

    assert began == ["first", "second"]


# ---- a malformed token ----------------------------------------------------

@pytest.mark.parametrize("token", ["", "your_telegram_bot_token_here", "123456:abc def"])
def test_a_malformed_token_does_not_stop_the_start_and_the_bot_part_cannot_connect(assembled, env, caplog, token):
    env.setenv("TELEGRAM_BOT_TOKEN", token)

    with caplog.at_level(logging.INFO):
        assert asyncio.run(app_main.main()) == 0

    parts = assembled["parts"]
    assert parts["web"] == "server"  # the web app was built and handed over
    bot = parts["bot"]

    async def connect_and_close():
        with pytest.raises(RuntimeError, match="токен бота неверного вида"):
            await bot.connect()
        await bot.stop()
        await bot.close()

    asyncio.run(connect_and_close())
    assert caplog.text.count(MALFORMED_TOKEN) == 1
    assert token == "" or token not in caplog.text


def test_without_a_bot_the_queue_keeps_the_event_and_counts_the_attempt():
    session_factory = create_session_factory("sqlite://")
    tracker = Tracker(session_factory, clock=lambda: dt.now(tz=timezone.utc), sender=TelegramSender(None, 42),
                      sources={})

    with pytest.raises(RuntimeError, match="токен бота неверного вида"):
        asyncio.run(TelegramSender(None, 42).send("text"))
    result = asyncio.run(tracker.send_test_event(tracker.test_samples()[0].id))

    assert result.delivered is False
    with session_factory() as session:
        [item] = session.scalars(select(DeliveryItem))
    assert (item.status, item.attempts) == ("pending", 1)
    assert "токен бота неверного вида" in item.last_error


# ---- the log --------------------------------------------------------------

def test_the_log_is_in_data_logs():
    assert logging_config.LOG_DIR == ROOT / "data" / "logs"


# ---- the old entry point and the launch script ----------------------------

def test_the_old_entry_point_says_how_to_start_and_exits_with_1():
    result = subprocess.run([sys.executable, "-m", "app.bot.main"], cwd=ROOT, capture_output=True, timeout=60,
                            env={"PYTHONIOENCODING": "utf-8", "PATH": ""})

    assert result.returncode == 1
    assert "Бот запускается через Docker: .\\start-bot.ps1" in result.stdout.decode("utf-8")
