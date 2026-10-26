"""The slimmed-down bot as `app.bot.main` assembles it: the menu and the buttons, nothing of the old commands."""

import asyncio
from datetime import datetime, timezone

import pytest
from aiogram import Bot
from aiogram.types import CallbackQuery, Chat, InlineQuery, Message, ReplyKeyboardMarkup, Update, User

from app.bot.main import build_dispatcher
from app.bot.tracker_handlers import (
    ADD_BUTTON,
    BOT_COMMANDS,
    DIGEST_BUTTON,
    MY_TITLES_BUTTON,
    TEST_EVENT_BUTTON,
)
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory

OWNER, STRANGER = 42, 7


class FakeSender:
    async def send(self, message, actions=()):
        pass


@pytest.fixture
def tracker():
    return Tracker(
        create_session_factory("sqlite://"),
        clock=lambda: datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc),
        sender=FakeSender(),
    )


@pytest.fixture
def replies(monkeypatch):
    said = []

    async def message_answer(self, text=None, **kwargs):
        said.append((text, kwargs.get("reply_markup")))

    async def callback_answer(self, text=None, **kwargs):
        said.append((text, None))

    monkeypatch.setattr(Message, "answer", message_answer)
    monkeypatch.setattr(CallbackQuery, "answer", callback_answer)
    return said


def say(tracker, text, uid=OWNER):
    dp = build_dispatcher(tracker, [OWNER])
    user = User(id=uid, is_bot=False, first_name="x")
    message = Message(message_id=1, date=0, chat=Chat(id=uid, type="private"), from_user=user, text=text)
    asyncio.run(dp.feed_update(Bot(token="123456:TEST"), Update(update_id=1, message=message)))


def test_start_shows_the_menu_with_exactly_the_four_buttons(tracker, replies):
    say(tracker, "/start")

    [(text, keyboard)] = replies
    assert "Бот работает" in text
    assert "окна" not in text.lower()
    assert isinstance(keyboard, ReplyKeyboardMarkup)
    labels = [button.text for row in keyboard.keyboard for button in row]
    assert labels == [ADD_BUTTON, MY_TITLES_BUTTON, DIGEST_BUTTON, TEST_EVENT_BUTTON]


@pytest.mark.parametrize(
    "text",
    [
        "/add 841",
        "/remove 841",
        "/watchlist",
        "/note 841 text",
        "/notes",
        "/events 841",
        "/search Дюна",
        "/searchgame Witcher",
        "/digest",
        "/test_event",
        "🕒 Окна доставки",
        "Дюна",
    ],
)
def test_old_commands_and_free_text_search_get_no_answer(tracker, replies, text):
    say(tracker, text)

    assert replies == []


def test_inline_search_gets_no_answer(tracker, replies):
    dp = build_dispatcher(tracker, [OWNER])
    user = User(id=OWNER, is_bot=False, first_name="x")
    update = Update(update_id=1, inline_query=InlineQuery(id="1", from_user=user, query="дюна", offset=""))

    asyncio.run(dp.feed_update(Bot(token="123456:TEST"), update))

    assert replies == []
    assert "inline_query" not in dp.resolve_used_update_types()


def test_a_stranger_gets_no_menu(tracker, replies):
    say(tracker, "/start", uid=STRANGER)

    assert replies == []


@pytest.mark.parametrize("button", [ADD_BUTTON, MY_TITLES_BUTTON, DIGEST_BUTTON, TEST_EVENT_BUTTON])
def test_every_menu_button_gets_an_answer(tracker, replies, button):
    say(tracker, button)

    assert len(replies) == 1 and replies[0][0]


def test_summary_command_answers(tracker, replies):
    say(tracker, "/summary")

    assert len(replies) == 1 and replies[0][0]


def test_the_commands_registered_in_telegram_are_summary_only():
    assert [(c.command, c.description) for c in BOT_COMMANDS] == [("summary", "Сводка сейчас")]
