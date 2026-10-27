"""Launch, environment settings and logs: nothing of the owner in the template, one owner chat, one place that masks."""

import ast
import asyncio
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.bot import error_handler
from app.config import Settings, time_zone_of
from app.providers.anilist import AniListProvider
from app.providers.igdb import IGDBProvider
from app.providers.tmdb import TMDbProvider
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.utils.logging_config import MaskingFormatter

ROOT = Path(__file__).resolve().parent.parent
BOT_TOKEN = "123456789:AAH-secretTokenValue_abcdefghijklmnopqrstuv"
REMOVED_SETTINGS = [
    "kinopub_client_id", "kinopub_client_secret", "kinopub_access_token", "rawg_api_key",
    "poll_scan_interval_seconds", "ps_store_region", "steam_country_code",
]


@pytest.fixture
def env(monkeypatch):
    """The required keys set to test values, everything optional cleared, so a real .env never leaks in."""
    monkeypatch.setattr("app.config.load_dotenv", lambda *a, **k: False)  # the real .env must not leak into the tests
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    monkeypatch.setenv("TMDB_API_KEY", "tmdb-test-key")
    for name in (
        "ALLOWED_TELEGRAM_USER_IDS", "ALLOWED_TELEGRAM_USER_IDS_RAW", "OWNER_CHAT_ID", "BOT_TIMEZONE",
        "TMDB_MIN_CALL_INTERVAL", "TMDB_MAX_CALLS_PER_MINUTE", "TMDB_429_BACKOFF_BASE_SECONDS", "TMDB_429_MAX_RETRIES",
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


# ---- time zone ------------------------------------------------------------

def test_without_bot_timezone_the_core_works_in_utc_and_the_log_warns(env, caplog):
    with caplog.at_level(logging.WARNING):
        tz = time_zone_of(Settings())

    assert tz == ZoneInfo("UTC")
    assert "часовой пояс не задан, используется UTC" in caplog.text
    tracker = Tracker(
        create_session_factory("sqlite://"),
        clock=lambda: datetime(2026, 11, 1, 12, tzinfo=timezone.utc),
        sender=None, sources={}, default_tz=tz,
    )
    assert asyncio.run(tracker.delivery_rules()).tz == ZoneInfo("UTC")


def test_a_blank_bot_timezone_counts_as_not_set(env, caplog):
    env.setenv("BOT_TIMEZONE", "")

    with caplog.at_level(logging.WARNING):
        tz = time_zone_of(Settings())

    assert tz == ZoneInfo("UTC") and "часовой пояс не задан" in caplog.text


def test_with_bot_timezone_there_is_no_warning(env, caplog):
    env.setenv("BOT_TIMEZONE", "Europe/Moscow")

    with caplog.at_level(logging.WARNING):
        tz = time_zone_of(Settings())

    assert tz == ZoneInfo("Europe/Moscow")
    assert "часовой пояс не задан" not in caplog.text


# ---- settings -------------------------------------------------------------

def test_settings_of_removed_code_are_gone():
    assert not set(REMOVED_SETTINGS) & set(Settings.model_fields)


def test_anilist_and_igdb_keep_their_own_rate_limits_and_ignore_the_tmdb_ones(env):
    env.setenv("TMDB_MIN_CALL_INTERVAL", "77")
    env.setenv("TMDB_MAX_CALLS_PER_MINUTE", "88")
    env.setenv("TMDB_429_BACKOFF_BASE_SECONDS", "99")
    env.setenv("TMDB_429_MAX_RETRIES", "11")

    tmdb, anilist, igdb = TMDbProvider(), AniListProvider(), IGDBProvider()

    assert (tmdb.min_call_interval, tmdb.max_calls_per_minute) == (77, 88)
    assert (tmdb.backoff_base_seconds, tmdb.backoff_max_retries) == (99, 11)
    for client in (anilist, igdb):
        assert client.min_call_interval < 77 and client.max_calls_per_minute < 88
        assert client.backoff_base_seconds < 99 and client.backoff_max_retries < 11


def test_env_example_has_only_used_keys_each_with_a_russian_comment():
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    keys = []
    for number, line in enumerate(lines):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key = line.split("=", 1)[0].strip()
        keys.append(key)
        previous = lines[number - 1] if number else ""
        assert previous.startswith("#") and re.search("[А-Яа-я]", previous), f"{key}: no Russian comment above it"

    used = {name.upper() for name in Settings.model_fields} | {"ALLOWED_TELEGRAM_USER_IDS"}
    assert set(keys) <= used
    assert "BOT_TIMEZONE" in keys and any("Europe/Moscow" in line for line in lines)
    assert not {name.upper() for name in REMOVED_SETTINGS} & set(keys)


# ---- the owner chat -------------------------------------------------------

@pytest.mark.parametrize("configured, expected", [("555", 555), ("-100123", -100123), ("", 42), ("your_chat_id_here", 42)])
def test_owner_chat_is_the_number_or_else_the_first_allowed_user(env, configured, expected):
    env.setenv("ALLOWED_TELEGRAM_USER_IDS", "42, 43")
    env.setenv("OWNER_CHAT_ID", configured)

    assert Settings().owner_chat == expected


def test_owner_chat_is_none_when_there_is_nobody_to_ask(env):
    assert Settings().owner_chat is None


@pytest.mark.parametrize("configured", ["", "your_chat_id_here"])
def test_error_report_goes_to_the_first_allowed_user_when_owner_chat_id_is_not_a_number(env, configured):
    env.setenv("ALLOWED_TELEGRAM_USER_IDS", "42, 43")
    env.setenv("OWNER_CHAT_ID", configured)
    reports = []

    async def fake_send(token, chat_id, exc):
        reports.append((token, chat_id, exc))

    env.setattr(error_handler, "send_runtime_error", fake_send)

    async def failing(event, data):
        raise ValueError("boom")

    with pytest.raises(ValueError):
        asyncio.run(error_handler.ErrorMiddleware()(failing, "event", {}))

    assert [(token, chat_id) for token, chat_id, _ in reports] == [(BOT_TOKEN, 42)]


# ---- logs -----------------------------------------------------------------

def test_a_token_in_a_log_record_leaves_the_formatter_masked_without_manual_masking():
    exc = RuntimeError(f"POST https://api.telegram.org/bot{BOT_TOKEN}/sendMessage failed")
    record = logging.LogRecord("t", logging.WARNING, __file__, 1, "sending failed: %r", (exc,), None)

    line = MaskingFormatter("%(message)s").format(record)

    assert BOT_TOKEN not in line and "sending failed" in line


LOG_METHODS = {"debug", "info", "warning", "error", "critical", "exception"}


def _log_calls(tree):
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in LOG_METHODS
            and isinstance(node.func.value, ast.Name) and node.func.value.id in {"logging", "logger", "log"}
        ):
            yield node


def test_code_writes_to_the_log_with_percent_arguments_and_without_mask_secrets():
    offenders = []
    for path in sorted((ROOT / "app").rglob("*.py")):
        for call in _log_calls(ast.parse(path.read_text(encoding="utf-8"))):
            message_is_f_string = bool(call.args) and isinstance(call.args[0], ast.JoinedStr)
            masks = any(
                isinstance(n, ast.Call) and getattr(n.func, "id", None) == "mask_secrets"
                for arg in call.args for n in ast.walk(arg)
            )
            if message_is_f_string or masks:
                offenders.append(f"{path.relative_to(ROOT)}:{call.lineno}")

    assert offenders == []
