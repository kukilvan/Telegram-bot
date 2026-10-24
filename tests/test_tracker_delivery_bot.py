"""«Сводка сейчас» and the delivery-window test in the bot: owner only, through a real Dispatcher.

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
from app.bot.tracker_handlers import DIGEST_BUTTON, WINDOWS_BUTTON, TelegramSender, main_keyboard, register_tracker_handlers
from app.tracker import delivery
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory

OWNER, STRANGER = 42, 7
JERUSALEM = ZoneInfo("Asia/Jerusalem")


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
            tz_name="Asia/Jerusalem", workdays=[6, 0, 1, 2, 3], digest_at="15:00", quiet_from="21:00", quiet_until="07:30"
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
    tracker.record_event("test", {"text": "первое"}, dedup_key="1")
    tracker.record_event("test", {"text": "второе"}, dedup_key="2")


# --- «Сводка сейчас» -------------------------------------------------------------------------------


@pytest.mark.parametrize("how", [DIGEST_BUTTON, "/digest"])
def test_summary_now_sends_what_waits_in_one_message(tracker, telegram, replies, how):
    waiting_events(tracker)  # a working morning: the rules keep them back

    say(make_dispatcher(tracker), OWNER, how)

    [summary] = telegram.sent
    assert summary.startswith("📋 Сводка · вс, 1 ноя")
    assert "первое" in summary and "второе" in summary
    assert replies == []


def test_summary_now_with_nothing_waiting_says_so(tracker, telegram, replies):
    say(make_dispatcher(tracker), OWNER, DIGEST_BUTTON)

    assert telegram.sent == []
    assert replies[0][0] == "message" and "нет" in replies[0][1]


def test_summary_now_tells_when_the_send_failed_and_keeps_the_events(tracker, telegram, replies):
    waiting_events(tracker)
    telegram.failing = True
    dp = make_dispatcher(tracker)

    say(dp, OWNER, DIGEST_BUTTON)

    assert "не удалось" in replies[0][1].lower()
    telegram.failing = False
    say(dp, OWNER, DIGEST_BUTTON)
    assert len(telegram.sent) == 1


def test_the_main_keyboard_has_the_new_buttons():
    texts = [b.text for row in main_keyboard().keyboard for b in row]

    assert DIGEST_BUTTON in texts and WINDOWS_BUTTON in texts


# --- the delivery-window test ---------------------------------------------------------------------


def test_the_windows_menu_lists_every_scenario(tracker, replies):
    say(make_dispatcher(tracker), OWNER, WINDOWS_BUTTON)

    [(_, _, buttons)] = replies
    assert [b.text for b in buttons] == [s.label for s in delivery.WINDOW_SCENARIOS]
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


def test_an_unknown_scenario_is_answered_not_crashed(tracker, telegram, replies):
    press(make_dispatcher(tracker), OWNER, "twin:gone")

    assert telegram.sent == []
    assert replies[0][0] == "callback" and replies[0][1]


@pytest.mark.parametrize("with_middleware", [True, False])
def test_stranger_gets_nothing(tracker, telegram, replies, with_middleware):
    waiting_events(tracker)
    dp = make_dispatcher(tracker, with_middleware)

    say(dp, STRANGER, DIGEST_BUTTON)
    say(dp, STRANGER, "/digest")
    say(dp, STRANGER, WINDOWS_BUTTON)
    press(dp, STRANGER, "twin:friday")

    assert replies == []
    assert telegram.sent == []
