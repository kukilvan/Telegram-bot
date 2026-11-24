"""«Что это?» after a restart (spec 9 of stage 9.1d, KI-57): the answer to the pause of an item is marked
(`answered_at`, by the question and by the first offer card), `Tracker.inbox_unanswered` gives the waiting items of the
last 12 hours without it, and the bot asks about them in the owner's chat once polling starts — once."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from aiogram import Bot, Dispatcher

from app.bot import inbox_handlers
from app.bot.tracker_handlers import register_tracker_handlers
from app.tracker.core import IncomingMessage, InboxOutcome
from app.tracker.models import InboxRecord
from inbox_fakes import Clients, tracker_on

OWNER = 42
START = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
STEAM_ELDEN_RING = "https://store.steampowered.com/app/1245620/ELDEN_RING/"


def run(coro):
    return asyncio.run(coro)


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def tracker(clock, tmp_path):
    return tracker_on(Clients(), url=f"sqlite:///{tmp_path / 'tracker.db'}", clock=clock)


def take(tracker, text, links=()):
    return run(tracker.take_in(IncomingMessage(text=text, forwarded=True, links=links))).item_id


def answered_at(tracker, item_id):
    with tracker.session_factory() as session:
        return session.get(InboxRecord, item_id).answered_at


# --- answered_at ---------------------------------------------------------------------------------------------


def test_the_question_marks_the_item_answered(tracker):
    item = take(tracker, "Что-то без ссылок")
    assert answered_at(tracker, item) is None

    assert run(tracker.inbox_pause_over(item)).outcome == InboxOutcome.ASK

    assert answered_at(tracker, item) == START.replace(tzinfo=None)


def test_the_offer_card_marks_the_item_answered(tracker):
    item = take(tracker, f"Смотрите {STEAM_ELDEN_RING}", links=(STEAM_ELDEN_RING,))

    assert run(tracker.inbox_pause_over(item)).outcome == InboxOutcome.OFFER

    assert answered_at(tracker, item) == START.replace(tzinfo=None)


def test_a_question_for_an_item_removed_meanwhile_says_nothing(tracker):
    item = take(tracker, "Что-то")
    run(tracker.forget_inbox_item(item))

    assert run(tracker.inbox_pause_over(item)).outcome == InboxOutcome.NOTHING


def test_no_question_for_an_item_a_newer_message_moved_after_its_pause_was_read(tracker):
    """Review 9.1d, F2: the question is decided after the links were looked up (seconds); a message that comes meanwhile
    moves the item to «Входящие», and the question then says nothing and marks nothing."""
    item = take(tracker, "Первый пост")
    take(tracker, "Второй пост")  # the first one goes to «Входящие» «без ответа»

    assert tracker._answers._ask(item).outcome == InboxOutcome.NOTHING
    assert answered_at(tracker, item) is None


# --- inbox_unanswered ----------------------------------------------------------------------------------------


def test_only_a_waiting_unanswered_item_younger_than_twelve_hours_is_unanswered(tracker, clock):
    old = take(tracker, "Старый пост")
    clock.now = START + timedelta(hours=13)
    young = take(tracker, "Новый пост")  # the old one went to «Входящие» «без ответа»

    assert run(tracker.inbox_unanswered()) == [young]

    run(tracker.inbox_pause_over(young))
    assert run(tracker.inbox_unanswered()) == []
    assert old != young


def test_an_item_waiting_thirteen_hours_is_not_unanswered(tracker, clock):
    take(tracker, "Пост")
    clock.now = START + timedelta(hours=11, minutes=59)
    assert len(run(tracker.inbox_unanswered())) == 1

    clock.now = START + timedelta(hours=13)
    assert run(tracker.inbox_unanswered()) == []


# --- the start of the bot ------------------------------------------------------------------------------------


@pytest.fixture
def sent(monkeypatch):
    said = []

    async def send_message(self, chat_id, text, **kwargs):
        markup = kwargs.get("reply_markup")
        rows = [[b.callback_data for b in row] for row in markup.inline_keyboard] if markup else []
        said.append((chat_id, text, rows, kwargs.get("link_preview_options")))

    monkeypatch.setattr(Bot, "send_message", send_message)
    return said


async def start_bot(tracker, owner_chat=OWNER):
    """A process of the bot starts: the dispatcher's start, as aiogram gives it before the first update."""
    dp = Dispatcher()
    register_tracker_handlers(dp, tracker, [OWNER], owner_chat=owner_chat)
    bot = Bot(token="123456:TEST")
    await dp.emit_startup(bot=bot)
    await asyncio.sleep(0.2)  # the answers go in a task of their own
    return dp, bot


def test_the_start_asks_about_an_unanswered_item_in_the_owners_chat_once(tracker, sent):
    item = take(tracker, "Пост перед остановкой")  # the bot stopped in the middle of its pause

    async def go():
        dp, bot = await start_bot(tracker)
        await dp.emit_startup(bot=bot)  # polling that starts again in the same process
        await asyncio.sleep(0.2)

    run(go())

    assert [(chat, text) for chat, text, _, _ in sent] == [(OWNER, inbox_handlers.QUESTION)]
    assert sent[0][2][0] == [f"inb:{item}:k:movie", f"inb:{item}:k:series"]
    assert inbox_handlers.PREVIOUS_MOVED not in sent[0][1]
    assert answered_at(tracker, item) is not None


def test_a_restart_after_the_question_sends_nothing_for_the_same_item(tracker, sent):
    take(tracker, "Пост")
    run(start_bot(tracker))
    sent.clear()

    run(start_bot(tracker))

    assert sent == []


def test_the_start_sends_the_card_of_an_item_with_a_link_with_its_poster(tracker, sent):
    item = take(tracker, f"Смотрите {STEAM_ELDEN_RING}", links=(STEAM_ELDEN_RING,))

    run(start_bot(tracker))

    [(chat, text, rows, preview)] = sent
    assert chat == OWNER and text.startswith("Это оно?") and "Elden Ring" in text
    assert rows == [[f"inb:{item}:y:0", f"inb:{item}:n:0"]]
    assert preview.url.startswith("https://images.igdb.com/")


def test_no_owners_chat_and_nothing_unanswered_send_nothing(tracker, sent):
    run(start_bot(tracker))
    take(tracker, "Пост")
    run(start_bot(tracker, owner_chat=None))

    assert sent == []


def test_a_failing_send_goes_to_the_log(tracker, monkeypatch, caplog):
    async def send_message(self, chat_id, text, **kwargs):
        raise ConnectionError("Telegram is down")

    monkeypatch.setattr(Bot, "send_message", send_message)
    take(tracker, "Пост")

    run(start_bot(tracker))

    assert "answering an inbox item after the start failed" in caplog.text
