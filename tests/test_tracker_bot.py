"""«Тестовое событие» in the bot: owner only, menu built from the tracker's registered samples."""

import asyncio
from datetime import datetime, timezone

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from app.bot.access import AccessMiddleware
from app.bot.tracker_handlers import RULES_CHECK_BUTTON, TEST_EVENT_BUTTON, register_tracker_handlers
from app.tracker.core import TestSample, Tracker
from app.tracker.db import create_session_factory

OWNER, STRANGER = 42, 7


class FakeSender:
    def __init__(self):
        self.sent = []
        self.failing = False

    async def send(self, message, actions=()):
        if self.failing:
            raise ConnectionError("down")
        self.sent.append(message)


@pytest.fixture
def sender():
    return FakeSender()


@pytest.fixture
def tracker(sender):
    return Tracker(
        create_session_factory("sqlite://"),
        clock=lambda: datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc),
        sender=sender,
    )


@pytest.fixture
def replies(monkeypatch):
    """Capture what the bot would say instead of calling Telegram."""
    said = []

    async def message_answer(self, text=None, **kwargs):
        said.append(("message", text, kwargs.get("reply_markup")))

    async def callback_answer(self, text=None, **kwargs):
        said.append(("callback", text, None))

    monkeypatch.setattr(Message, "answer", message_answer)
    monkeypatch.setattr(CallbackQuery, "answer", callback_answer)
    return said


def make_dispatcher(tracker, with_middleware=True):
    dp = Dispatcher()
    if with_middleware:
        dp.update.outer_middleware(AccessMiddleware([OWNER]))
    register_tracker_handlers(dp, tracker, [OWNER])
    return dp


def press_menu_button(dp, uid):
    user = User(id=uid, is_bot=False, first_name="x")
    chat = Chat(id=uid, type="private")
    message = Message(message_id=1, date=0, chat=chat, from_user=user, text=TEST_EVENT_BUTTON)
    asyncio.run(dp.feed_update(Bot(token="123456:TEST"), Update(update_id=1, message=message)))


def press_sample_button(dp, uid, data):
    user = User(id=uid, is_bot=False, first_name="x")
    callback = CallbackQuery(id="1", from_user=user, chat_instance="c", data=data)
    asyncio.run(dp.feed_update(Bot(token="123456:TEST"), Update(update_id=2, callback_query=callback)))


def menu_buttons(replies):
    [(_, _, markup)] = replies
    return [b for row in markup.inline_keyboard for b in row]


def test_owner_gets_a_menu_of_registered_samples(tracker, replies):
    tracker.register_test_sample(TestSample("movie", "Фильм: объявлена дата", lambda: {"text": "x"}))

    press_menu_button(make_dispatcher(tracker), OWNER)

    labels = [b.text for b in menu_buttons(replies)]
    assert labels == [k.label for k in tracker.test_samples()] + [RULES_CHECK_BUTTON]
    assert "Фильм: объявлена дата" in labels


def test_choosing_a_sample_delivers_the_event(tracker, sender, replies):
    press_sample_button(make_dispatcher(tracker), OWNER, "tev:ping")

    assert len(sender.sent) == 1
    assert replies == [("callback", "Отправлено", None)]


def test_failed_send_tells_the_owner_it_will_be_retried(tracker, sender, replies):
    sender.failing = True

    press_sample_button(make_dispatcher(tracker), OWNER, "tev:ping")

    assert sender.sent == []
    assert replies[0][0] == "callback" and "позже" in replies[0][1]


def test_stale_menu_button_is_answered_not_crashed(tracker, sender, replies):
    press_sample_button(make_dispatcher(tracker), OWNER, "tev:gone")

    assert sender.sent == []
    assert replies[0][0] == "callback" and replies[0][1]


@pytest.mark.parametrize("with_middleware", [True, False])
def test_stranger_gets_nothing(tracker, sender, replies, with_middleware):
    dp = make_dispatcher(tracker, with_middleware)

    press_menu_button(dp, STRANGER)
    press_sample_button(dp, STRANGER, "tev:ping")

    assert replies == []
    assert sender.sent == []
