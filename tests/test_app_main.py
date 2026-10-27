"""The process entry point `app.main` (ADR 0007): what it hands the runtime, failures before the start, the old
entry point and the launch script."""

import asyncio
import logging
import subprocess
import sys
from pathlib import Path

import pytest
from aiogram import Bot, Dispatcher

import app.main as app_main
from app.tracker.db import create_session_factory
from app.utils import logging_config

ROOT = Path(__file__).resolve().parent.parent
BOT_TOKEN = "123456789:AAH-secretTokenValue_abcdefghijklmnopqrstuv"


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr("app.config.load_dotenv", lambda *a, **k: False)  # the real .env must not leak into the tests
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    monkeypatch.setenv("TMDB_API_KEY", "tmdb-test-key")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "42")
    monkeypatch.setenv("BOT_TIMEZONE", "UTC")
    monkeypatch.delenv("OWNER_CHAT_ID", raising=False)
    monkeypatch.delenv(app_main.WEB_BIND_HOST, raising=False)
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


def test_an_empty_allowlist_refuses_to_start(env, caplog):
    env.setenv("ALLOWED_TELEGRAM_USER_IDS", "")

    with caplog.at_level(logging.CRITICAL):
        assert asyncio.run(app_main.main()) == 1

    assert "refusing to start an open bot" in caplog.text


def test_a_failure_before_the_start_is_reported_to_the_owner_and_exits_with_1(env):
    reports = []

    async def failing_main():
        raise RuntimeError("the database is locked")

    env.setattr(app_main, "setup_logging", lambda level: None)
    env.setattr(app_main, "main", failing_main)
    env.setattr(app_main, "send_startup_error_sync", lambda token, chat, exc: reports.append((chat, str(exc))))

    assert app_main.run() == 1
    assert reports == [(42, "the database is locked")]


def test_ctrl_c_before_the_parts_started_leaves_quietly(env):
    async def interrupted_main():
        raise KeyboardInterrupt

    env.setattr(app_main, "setup_logging", lambda level: None)
    env.setattr(app_main, "main", interrupted_main)

    assert app_main.run() == 0


def test_stopping_the_bot_part_before_it_receives_is_quiet():
    async def scenario():
        part = app_main.TelegramPart(Bot(token=BOT_TOKEN), Dispatcher())
        await part.stop()
        await part.close()

    asyncio.run(scenario())


# ---- the log --------------------------------------------------------------

def test_the_log_is_in_data_logs():
    assert logging_config.LOG_DIR == ROOT / "data" / "logs"


# ---- the old entry point and the launch script ----------------------------

def test_the_old_entry_point_says_how_to_start_and_exits_with_1():
    result = subprocess.run([sys.executable, "-m", "app.bot.main"], cwd=ROOT, capture_output=True, timeout=60,
                            env={"PYTHONIOENCODING": "utf-8", "PATH": ""})

    assert result.returncode == 1
    assert "Бот запускается через Docker: .\\start-bot.ps1" in result.stdout.decode("utf-8")
