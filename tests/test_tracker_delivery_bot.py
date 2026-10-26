"""«Сводка сейчас» and the delivery-rules check in the bot: owner only, through a real Dispatcher.

Telegram itself is replaced by capturing what the bot would say; the tracker core is real. The owner's clock is
Asia/Jerusalem: the tests start on Sunday 1 Nov 2026 at 10:00 (a working morning, UTC+2).
"""

import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from app.bot.access import AccessMiddleware
from app.bot.tracker_handlers import (
    SUMMARY_BUTTON,
    RULES_CHECK_BUTTON,
    RULES_CHECK_CALLBACK,
    TEST_EVENT_BUTTON,
    TelegramSender,
    register_tracker_handlers,
)
from app.tracker import delivery, test_samples
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory

OWNER, STRANGER = 42, 7
JERUSALEM = ZoneInfo("Asia/Jerusalem")


def run(coro):
    return asyncio.run(coro)


class FakeBot:
    def __init__(self):
        self.sent = []
        self.failing = False

    async def send_message(self, chat_id, text, reply_markup=None):
        if self.failing:
            raise ConnectionError("telegram is down")
        self.sent.append(text)


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 1, 10, 0, tzinfo=JERUSALEM).astimezone(timezone.utc)

    def __call__(self):
        return self.now


@pytest.fixture
def telegram():
    return FakeBot()


@pytest.fixture
def tracker(telegram):
    tracker = Tracker(
        create_session_factory("sqlite://"), clock=Clock(), sender=TelegramSender(telegram, OWNER), sources={}
    )
    asyncio.run(
        tracker.set_delivery_rules(
            tz_name="Asia/Jerusalem", workdays=[6, 0, 1, 2, 3], summary_at="15:00", quiet_from="21:00", quiet_until="07:30"
        )
    )
    return tracker


@pytest.fixture
def replies(monkeypatch):
    said = []

    async def message_answer(self, text=None, **kwargs):
        markup = kwargs.get("reply_markup")
        rows = getattr(markup, "inline_keyboard", []) if markup else []
        said.append(("message", text, [b for row in rows for b in row]))

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


def say(dp, uid, text):
    user = User(id=uid, is_bot=False, first_name="x")
    message = Message(message_id=1, date=0, chat=Chat(id=uid, type="private"), from_user=user, text=text)
    asyncio.run(dp.feed_update(Bot(token="123456:TEST"), Update(update_id=1, message=message)))


def press(dp, uid, data):
    user = User(id=uid, is_bot=False, first_name="x")
    message = Message(message_id=1, date=0, chat=Chat(id=uid, type="private"), from_user=user, text="m")
    callback = CallbackQuery(id="1", from_user=user, chat_instance="c", data=data, message=message)
    asyncio.run(dp.feed_update(Bot(token="123456:TEST"), Update(update_id=2, callback_query=callback)))


def waiting_events(tracker):
    run(tracker.record_event("test", {"text": "первое"}, dedup_key="1"))
    run(tracker.record_event("test", {"text": "второе"}, dedup_key="2"))


# --- «Сводка сейчас» -------------------------------------------------------------------------------


@pytest.mark.parametrize("how", [SUMMARY_BUTTON, "/summary"])
def test_summary_now_sends_what_waits_in_one_message(tracker, telegram, replies, how):
    waiting_events(tracker)  # a working morning: the rules keep them back

    say(make_dispatcher(tracker), OWNER, how)

    [summary] = telegram.sent
    assert summary.startswith("📋 Сводка · вс, 1 ноя")
    assert "первое" in summary and "второе" in summary
    assert replies == []


def test_summary_now_with_nothing_waiting_says_so(tracker, telegram, replies):
    say(make_dispatcher(tracker), OWNER, SUMMARY_BUTTON)

    assert telegram.sent == []
    assert replies[0][0] == "message" and "нет" in replies[0][1]


def test_summary_now_tells_when_the_send_failed_and_keeps_the_events(tracker, telegram, replies):
    waiting_events(tracker)
    telegram.failing = True
    dp = make_dispatcher(tracker)

    say(dp, OWNER, SUMMARY_BUTTON)

    assert "не удалось" in replies[0][1].lower()
    telegram.failing = False
    say(dp, OWNER, SUMMARY_BUTTON)
    assert len(telegram.sent) == 1


def test_removed_summary_and_test_event_commands_are_gone(tracker, telegram, replies):
    waiting_events(tracker)
    dp = make_dispatcher(tracker)

    say(dp, OWNER, "/digest")
    say(dp, OWNER, "/test_event")

    assert replies == []
    assert telegram.sent == []


# --- the delivery-rules check, inside «Тестовое событие» -------------------------------------------


def test_the_test_event_list_ends_with_the_rules_check(tracker, replies):
    say(make_dispatcher(tracker), OWNER, TEST_EVENT_BUTTON)

    [(_, _, markup)] = replies
    last = markup[-1]
    assert last.text == RULES_CHECK_BUTTON == "🕒 Проверить правила доставки"
    assert not last.callback_data.startswith("tev:")


def test_the_rules_check_lists_every_moment_of_the_week(tracker, replies):
    say(make_dispatcher(tracker), OWNER, TEST_EVENT_BUTTON)
    [(_, _, markup)] = replies
    replies.clear()

    press(make_dispatcher(tracker), OWNER, markup[-1].callback_data)

    [_, (kind, text, buttons)] = replies
    assert kind == "message" and "окн" not in text.lower()
    assert [b.text for b in buttons] == [s.label for s in test_samples.DELIVERY_CHECKS]
    assert all(b.callback_data.startswith("twin:") for b in buttons)


def test_a_working_morning_is_held_and_the_owner_is_told_when_the_summary_comes(tracker, telegram, replies):
    press(make_dispatcher(tracker), OWNER, "twin:work-morning")

    [summary] = telegram.sent
    assert summary.startswith("📋 Сводка") and "вышли серии 5–6" in summary
    [_, (kind, text, _)] = replies
    assert kind == "message"
    # the clock stands at Sunday 10:00 itself, so the substituted Sunday 10:00 is the next one
    assert "вс, 8 ноя в 10:00" in text and "ничего не пришло" in text and "вс, 8 ноя в 15:00" in text


def test_a_day_off_is_delivered_at_once_and_the_owner_is_told(tracker, telegram, replies):
    press(make_dispatcher(tracker), OWNER, "twin:friday")

    assert len(telegram.sent) == 2
    assert not any(m.startswith("📋") for m in telegram.sent)
    [_, (kind, text, _)] = replies
    assert "пт, 6 ноя в 12:00" in text and "сразу" in text


def test_a_failed_send_is_reported_not_called_a_success(tracker, telegram, replies):
    telegram.failing = True

    press(make_dispatcher(tracker), OWNER, "twin:friday")

    assert "Не удалось" in replies[-1][1]


def test_an_unknown_delivery_check_is_answered_not_crashed(tracker, telegram, replies):
    press(make_dispatcher(tracker), OWNER, "twin:gone")

    assert telegram.sent == []
    assert replies[0][0] == "callback" and replies[0][1]


def test_the_values_of_buttons_already_sent_are_unchanged(tracker, replies):
    say(make_dispatcher(tracker), OWNER, TEST_EVENT_BUTTON)
    [(_, _, markup)] = replies
    assert markup[0].callback_data == "tev:ping"  # the sample buttons of an old message keep working
    assert RULES_CHECK_CALLBACK == "tchk:open"
    assert [c.id for c in test_samples.DELIVERY_CHECKS][0] == "work-morning"


@pytest.mark.parametrize("with_middleware", [True, False])
def test_stranger_gets_nothing(tracker, telegram, replies, with_middleware):
    waiting_events(tracker)
    dp = make_dispatcher(tracker, with_middleware)

    say(dp, STRANGER, SUMMARY_BUTTON)
    say(dp, STRANGER, "/summary")
    say(dp, STRANGER, TEST_EVENT_BUTTON)
    press(dp, STRANGER, RULES_CHECK_CALLBACK)
    press(dp, STRANGER, "twin:friday")

    assert replies == []
    assert telegram.sent == []
