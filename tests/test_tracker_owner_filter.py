"""The owner filter on the tracker router: a stranger's update gets no answer from any handler, even on a
dispatcher without `AccessMiddleware` (the second line of defence)."""

import asyncio
from datetime import datetime, timezone

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from app.bot.tracker_handlers import (
    ADD_BUTTON,
    SUMMARY_BUTTON,
    MY_TITLES_BUTTON,
    TEST_EVENT_BUTTON,
    register_tracker_handlers,
)
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory

OWNER, STRANGER = 42, 7

MESSAGES = ["/start", "/summary", ADD_BUTTON, MY_TITLES_BUTTON, SUMMARY_BUTTON, TEST_EVENT_BUTTON]
CALLBACKS = [
    "tev:ping",
    "twin:friday",
    "tchk:open",
    "tadd:movie",
    "tpick:movie:1",
    "tcard:1",
    "tact:card:1",
    "tact:follow:movie:1",
    "tact:watched:1",
    "tact:seasons:1",
    "tact:delete:1",
    "tdel:y:1",
    "tdel:n:1",
    "tdm:open",
    "tdm:abc:go",
    "tsea:1:1",
]


class FakeSender:
    def __init__(self):
        self.sent = []

    async def send(self, message, actions=()):
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
    said = []

    async def message_answer(self, text=None, **kwargs):
        said.append(text)

    async def callback_answer(self, text=None, **kwargs):
        said.append(text)

    monkeypatch.setattr(Message, "answer", message_answer)
    monkeypatch.setattr(CallbackQuery, "answer", callback_answer)
    return said


def bare_dispatcher(tracker):
    """No AccessMiddleware: only the router's own filter stands between the update and the handlers."""
    dp = Dispatcher()
    register_tracker_handlers(dp, tracker, [OWNER])
    return dp


def feed(dp, update):
    asyncio.run(dp.feed_update(Bot(token="123456:TEST"), update))


def message_update(uid, text, user=True):
    sender = User(id=uid, is_bot=False, first_name="x") if user else None
    message = Message(message_id=1, date=0, chat=Chat(id=uid, type="private"), from_user=sender, text=text)
    return Update(update_id=1, message=message)


def callback_update(uid, data):
    user = User(id=uid, is_bot=False, first_name="x")
    message = Message(message_id=1, date=0, chat=Chat(id=uid, type="private"), from_user=user, text="m")
    return Update(update_id=2, callback_query=CallbackQuery(id="1", from_user=user, chat_instance="c", data=data, message=message))


@pytest.mark.parametrize("text", MESSAGES)
def test_a_stranger_message_gets_no_answer(tracker, sender, replies, text):
    feed(bare_dispatcher(tracker), message_update(STRANGER, text))

    assert replies == [] and sender.sent == []


@pytest.mark.parametrize("data", CALLBACKS)
def test_a_stranger_button_press_gets_no_answer(tracker, sender, replies, data):
    feed(bare_dispatcher(tracker), callback_update(STRANGER, data))

    assert replies == [] and sender.sent == []


def test_a_message_without_a_sender_gets_no_answer(tracker, replies):
    feed(bare_dispatcher(tracker), message_update(STRANGER, "/start", user=False))

    assert replies == []


@pytest.mark.parametrize("text", MESSAGES)
def test_the_owner_message_is_answered(tracker, replies, text):
    feed(bare_dispatcher(tracker), message_update(OWNER, text))

    assert len(replies) == 1


@pytest.mark.parametrize("data", ["tev:ping", "tchk:open", "tadd:movie", "tcard:1", "tdm:open"])
def test_the_owner_button_press_is_answered(tracker, replies, data):
    feed(bare_dispatcher(tracker), callback_update(OWNER, data))

    assert replies
