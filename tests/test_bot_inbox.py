"""«Входящие» in the bot (spec 1.1–1.3, 2.1, 2.2 of stage 6.4), through a real aiogram Dispatcher and the real core:
what is taken in, the pause and its restart, the line «Предыдущий…», «Что это?» and its buttons, every press.

The whole conversation runs in one event loop, so the pause (shortened here) really runs out between messages.
"""

import asyncio
from datetime import datetime, timezone

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, MessageOriginChannel, PhotoSize, Sticker, Update, User

from app.bot import inbox_handlers
from app.bot.access import AccessMiddleware
from app.bot.tracker_handlers import ADD_BUTTON, MY_TITLES_BUTTON, SUMMARY_BUTTON, TEST_EVENT_BUTTON, register_tracker_handlers
from app.tracker.core import InboxReason, InboxState, Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import TitleKind

OWNER = 42
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
PAUSE = 0.15  # long enough that a write of the core between two messages never outlasts it
QUESTION_ROWS = [["Фильм", "Сериал"], ["Аниме", "Игра"], ["🗑 Не сохранять"]]


class FakeSender:
    async def send(self, message, actions=()):
        pass


@pytest.fixture(autouse=True)
def short_pause(monkeypatch):
    monkeypatch.setattr(inbox_handlers, "PAUSE_SECONDS", PAUSE)


@pytest.fixture
def tracker():
    return Tracker(create_session_factory("sqlite://"), clock=lambda: NOW, sender=FakeSender())


@pytest.fixture
def telegram(monkeypatch):
    """What the bot did: ("message", text, rows of buttons), ("popup", text) and ("edit", rows)."""
    said = []

    def rows_of(markup):
        return [[(b.text, b.callback_data) for b in row] for row in getattr(markup, "inline_keyboard", [])] if markup else []

    async def message_answer(self, text=None, **kwargs):
        said.append(("message", text, rows_of(kwargs.get("reply_markup"))))

    async def callback_answer(self, text=None, **kwargs):
        said.append(("popup", text))

    async def edit_reply_markup(self, reply_markup=None, **kwargs):
        said.append(("edit", rows_of(reply_markup)))

    monkeypatch.setattr(Message, "answer", message_answer)
    monkeypatch.setattr(CallbackQuery, "answer", callback_answer)
    monkeypatch.setattr(Message, "edit_reply_markup", edit_reply_markup)
    return said


class Conversation:
    """One chat with the bot in one event loop."""

    def __init__(self, tracker):
        self.tracker = tracker
        self.dp = Dispatcher()
        self.dp.update.outer_middleware(AccessMiddleware([OWNER]))
        register_tracker_handlers(self.dp, tracker, [OWNER])
        self.bot = Bot(token="123456:TEST")
        self.number = 0

    async def feed(self, **update):
        self.number += 1
        await self.dp.feed_update(self.bot, Update(update_id=self.number, **update))

    def message(self, text=None, **fields):
        self.number += 1
        return Message(
            message_id=self.number, date=NOW, chat=Chat(id=OWNER, type="private"),
            from_user=User(id=OWNER, is_bot=False, first_name="x"), text=text, **fields,
        )

    async def say(self, text=None, **fields):
        await self.feed(message=self.message(text, **fields))

    async def press(self, data):
        user = User(id=OWNER, is_bot=False, first_name="x")
        await self.feed(callback_query=CallbackQuery(
            id="1", from_user=user, chat_instance="c", data=data, message=self.message("Что это?"),
        ))


async def pause(times=1.0):
    await asyncio.sleep(PAUSE * times)


def talk(tracker, scenario):
    async def go():
        chat = Conversation(tracker)
        result = await scenario(chat)
        await pause(3)  # whatever is still pausing answers now
        return result

    return asyncio.run(go())


def messages(telegram):
    return [entry for entry in telegram if entry[0] == "message"]


def labels(rows):
    return [[text for text, _ in row] for row in rows]


def photo():
    return [PhotoSize(file_id="p", file_unique_id="p", width=1, height=1)]


# --- taking in ---------------------------------------------------------------------------------------


def test_a_text_is_written_before_any_answer_and_asked_about_after_the_pause(tracker, telegram):
    seen = {}

    async def scenario(chat):
        await chat.say("Привет")
        seen["item"] = await tracker.inbox_item(1)
        seen["said"] = list(telegram)

    talk(tracker, scenario)

    assert seen["item"].text == "Привет" and seen["said"] == []
    [(_, text, rows)] = messages(telegram)
    assert text == "Что это?" and labels(rows) == QUESTION_ROWS
    assert [data for row in rows for _, data in row] == [
        "inb:1:k:movie", "inb:1:k:series", "inb:1:k:anime", "inb:1:k:game", "inb:1:x",
    ]


def test_the_callback_data_of_a_large_number_fits_telegram():
    rows = inbox_handlers.question_markup(10**12).inline_keyboard

    assert all(len(b.callback_data.encode()) <= 64 for row in rows for b in row)


@pytest.mark.parametrize(
    "fields",
    [
        {"sticker": Sticker(file_id="s", file_unique_id="s", type="regular", width=1, height=1, is_animated=False, is_video=False)},
        {"photo": photo()},
    ],
    ids=["sticker", "picture"],
)
def test_a_message_without_text_goes_to_the_inbox_at_the_end_of_the_pause(tracker, telegram, fields):
    talk(tracker, lambda chat: chat.say(**fields))

    assert messages(telegram) == [("message", "В сообщении нет текста — сохранил во «Входящие».", [])]
    item = asyncio.run(tracker.inbox_item(1))
    assert (item.state, item.reason) == (InboxState.INBOX, InboxReason.NO_TEXT)


def test_an_album_gets_one_question(tracker, telegram):
    async def scenario(chat):
        await chat.say(caption="Альбом Hades II", photo=photo(), media_group_id="a")
        for _ in range(4):
            await pause(0.2)
            await chat.say(photo=photo(), media_group_id="a")

    talk(tracker, scenario)

    assert [text for _, text, _ in messages(telegram)] == ["Что это?"]
    assert asyncio.run(tracker.inbox_item(1)).text == "Альбом Hades II"
    assert asyncio.run(tracker.inbox_item(2)) is None


def test_a_joined_message_starts_the_pause_again(tracker, telegram, monkeypatch):
    monkeypatch.setattr(inbox_handlers, "PAUSE_SECONDS", PAUSE * 4)
    seen = {}

    async def scenario(chat):
        await chat.say("Посмотри")
        await pause(2.4)
        origin = MessageOriginChannel(
            type="channel", date=NOW, chat=Chat(id=-1, type="channel", username="ch"), message_id=5
        )
        await chat.say("Пост канала", forward_origin=origin)
        await pause(2.4)  # 1.2 pauses after the first message: without the restart the question would be here
        seen["early"] = messages(telegram)
        await pause(4)

    talk(tracker, scenario)

    assert seen["early"] == []
    assert [text for _, text, _ in messages(telegram)] == ["Что это?"]
    item = asyncio.run(tracker.inbox_item(1))
    assert item.text == "Посмотри\n\nПост канала" and item.post_url == "https://t.me/ch/5"


def test_a_new_post_moves_the_waiting_one_and_says_so_once(tracker, telegram):
    async def scenario(chat):
        await chat.say("Тест два")
        await chat.say("Тест три")  # before the first pause is over: the first never gets its question

    talk(tracker, scenario)

    [(_, text, rows)] = messages(telegram)
    assert text == "Предыдущий пост без ответа ушёл во «Входящие».\n\nЧто это?"
    assert rows[-1] == [("🗑 Не сохранять", "inb:2:x")]
    first = asyncio.run(tracker.inbox_item(1))
    assert (first.state, first.reason) == (InboxState.INBOX, InboxReason.NO_ANSWER)


def test_a_new_post_after_an_answered_question_says_the_line_too(tracker, telegram):
    async def scenario(chat):
        await chat.say("Тест два")
        await pause(2)
        await chat.say("Тест три")

    talk(tracker, scenario)

    assert [text for _, text, _ in messages(telegram)] == [
        "Что это?", "Предыдущий пост без ответа ушёл во «Входящие».\n\nЧто это?",
    ]


def test_five_posts_in_a_row_leave_four_in_the_inbox(tracker, telegram):
    async def scenario(chat):
        for n in range(5):
            await chat.say(f"Пост {n}")
            await pause(2)

    talk(tracker, scenario)

    assert asyncio.run(tracker.inbox_count()) == 4
    assert asyncio.run(tracker.inbox_item(5)).state == InboxState.WAITING


@pytest.mark.parametrize("text", ["/start", "/unknown", MY_TITLES_BUTTON, SUMMARY_BUTTON, TEST_EVENT_BUTTON, ADD_BUTTON])
def test_commands_and_menu_buttons_are_never_taken_in(tracker, telegram, text):
    talk(tracker, lambda chat: chat.say(text))

    assert asyncio.run(tracker.inbox_item(1)) is None
    assert not any(entry[1] == "Что это?" for entry in messages(telegram))


def test_an_edited_message_is_not_taken_in(tracker, telegram):
    talk(tracker, lambda chat: chat.feed(edited_message=chat.message("Дюна")))

    assert asyncio.run(tracker.inbox_item(1)) is None and telegram == []


# --- presses -----------------------------------------------------------------------------------------


def asked(tracker, text="Тест один"):
    """An item asked about, as after its pause."""
    async def scenario(chat):
        await chat.say(text)

    talk(tracker, scenario)


def test_a_kind_is_answered_early_takes_the_buttons_off_and_keeps_the_kind(tracker, telegram):
    asked(tracker)
    telegram.clear()

    talk(tracker, lambda chat: chat.press("inb:1:k:game"))

    assert telegram == [("popup", "Ищу…"), ("edit", []), ("message", "Тип запомнил — сохранил во «Входящие».", [])]
    item = asyncio.run(tracker.inbox_item(1))
    assert (item.state, item.reason, item.kind) == (InboxState.INBOX, InboxReason.NOT_FOUND, TitleKind.GAME)


def test_a_kind_of_an_item_already_in_the_inbox_still_works(tracker, telegram):
    async def scenario(chat):
        await chat.say("Первый")
        await pause(2)
        await chat.say("Второй")
        await pause(2)
        await chat.press("inb:1:k:movie")

    talk(tracker, scenario)

    assert ("message", "Тип запомнил — сохранил во «Входящие».", []) in telegram
    assert asyncio.run(tracker.inbox_item(1)).kind == TitleKind.MOVIE
    assert asyncio.run(tracker.inbox_item(2)).state == InboxState.WAITING


def test_not_saving_deletes_and_its_old_buttons_are_spent(tracker, telegram):
    asked(tracker, "Привет")
    telegram.clear()

    async def scenario(chat):
        await chat.press("inb:1:x")
        await chat.press("inb:1:x")
        await chat.press("inb:1:k:movie")

    talk(tracker, scenario)

    assert telegram == [
        ("edit", []), ("popup", "Не сохраняю."),
        ("edit", []), ("popup", "Эта запись уже разобрана."),
        ("popup", "Эта запись уже разобрана."),
    ]
    assert asyncio.run(tracker.inbox_item(1)) is None


@pytest.mark.parametrize("data", ["inb:", "inb:x:x", "inb:1", "inb:1:k:book", "inb:1:q:movie", "inb:1:k:"])
def test_a_button_the_bot_cannot_read_no_longer_works(tracker, telegram, data):
    asked(tracker)
    telegram.clear()

    talk(tracker, lambda chat: chat.press(data))

    assert telegram == [("popup", "Эта кнопка больше не работает.")]
    assert asyncio.run(tracker.inbox_item(1)).state == InboxState.WAITING


def test_after_a_restart_the_buttons_of_an_item_still_work(tracker, telegram):
    asked(tracker)
    telegram.clear()

    talk(tracker, lambda chat: chat.press("inb:1:k:anime"))  # a new dispatcher: the memory of the bot is empty

    assert telegram[-1] == ("message", "Тип запомнил — сохранил во «Входящие».", [])
