"""Allowlist: env name matches, parsing is strict, strangers and empty lists are rejected."""

import asyncio
from types import SimpleNamespace

import pytest

from app.bot.access import AccessMiddleware
from app.config import Settings, parse_user_ids


def test_parse_user_ids_skips_blanks_and_spaces():
    assert parse_user_ids("1, 2,,3 ,") == [1, 2, 3]
    assert parse_user_ids("") == []


def test_parse_user_ids_rejects_junk():
    with pytest.raises(ValueError):
        parse_user_ids("123,abc")


def test_settings_reads_env_name_used_in_dotenv(monkeypatch):
    # Regression: the field was read from ..._RAW, so ALLOWED_TELEGRAM_USER_IDS was ignored
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TMDB_API_KEY", "k")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "42, 43")
    assert Settings().allowed_telegram_user_ids == [42, 43]


def _run(allowed, user):
    calls = []

    async def handler(event, data):
        calls.append(event)
        return "handled"

    data = {"event_from_user": user}
    result = asyncio.run(AccessMiddleware(allowed)(handler, "evt", data))
    return result, calls


def test_owner_passes():
    result, calls = _run([42], SimpleNamespace(id=42))
    assert result == "handled" and calls == ["evt"]


def test_stranger_is_dropped():
    result, calls = _run([42], SimpleNamespace(id=7))
    assert result is None and calls == []


def test_update_without_user_is_dropped():
    result, calls = _run([42], None)
    assert result is None and calls == []


def test_empty_allowlist_lets_nobody_in():
    result, calls = _run([], SimpleNamespace(id=42))
    assert result is None and calls == []


def test_real_dispatcher_gates_message_inline_and_callback():
    # event_from_user must be populated at update level, otherwise the gate silently drops the owner too
    from aiogram import Bot, Dispatcher
    from aiogram.types import CallbackQuery, Chat, InlineQuery, Message, Update, User

    seen = []
    dp = Dispatcher()
    dp.update.outer_middleware(AccessMiddleware([42]))

    @dp.message()
    async def on_message(m):
        seen.append("message")

    @dp.inline_query()
    async def on_inline(q):
        seen.append("inline")

    @dp.callback_query()
    async def on_callback(c):
        seen.append("callback")

    bot = Bot(token="123456:TEST")

    def updates(uid):
        u = User(id=uid, is_bot=False, first_name="x")
        chat = Chat(id=uid, type="private")
        yield Update(update_id=1, message=Message(message_id=1, date=0, chat=chat, from_user=u, text="hi"))
        yield Update(update_id=2, inline_query=InlineQuery(id="1", from_user=u, query="q", offset=""))
        yield Update(
            update_id=3,
            callback_query=CallbackQuery(id="1", from_user=u, chat_instance="c", data="d"),
        )

    async def feed(uid):
        for upd in updates(uid):
            await dp.feed_update(bot, upd)

    asyncio.run(feed(7))
    assert seen == []
    asyncio.run(feed(42))
    assert seen == ["message", "inline", "callback"]
