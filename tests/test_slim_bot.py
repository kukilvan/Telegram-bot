"""The slimmed-down bot as `app.bot.main` assembles it: the menu and the buttons, nothing of the old commands; any other
text is an inbox item."""

import asyncio
from datetime import datetime, timezone

import pytest
from aiogram import Bot
from aiogram.types import CallbackQuery, Chat, InlineQuery, Message, ReplyKeyboardMarkup, Update, User

from app.bot.main import build_dispatcher
from app.bot.tracker_handlers import (
    ADD_BUTTON,
    BOT_COMMANDS,
    SUMMARY_BUTTON,
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


START = (
    "👋 Бот работает. Чтобы добавить фильм, сериал, аниме или игру, перешлите мне пост о нём или напишите название: я "
    "найду и предложу добавить, а что не найду — сохраню во «Входящие» веб-приложения.\n\n"
    "Кнопки меню внизу: «Мои тайтлы» — ваш список, «Сводка сейчас» присылает накопленные события, «Тестовое событие» "
    "показывает, как выглядят сообщения, и проверяет правила доставки."
)


def rows_of(keyboard):
    return [[button.text for button in row] for row in keyboard.keyboard]


def test_start_shows_the_menu_with_exactly_the_three_buttons(tracker, replies):
    say(tracker, "/start")

    [(text, keyboard)] = replies
    assert text == START
    assert isinstance(keyboard, ReplyKeyboardMarkup)
    assert rows_of(keyboard) == [[MY_TITLES_BUTTON], [SUMMARY_BUTTON], [TEST_EVENT_BUTTON]]


def test_the_add_text_of_an_old_keyboard_brings_the_new_keyboard(tracker, replies):
    say(tracker, ADD_BUTTON)

    [(text, keyboard)] = replies
    assert text == "Кнопки «Добавить» больше нет: просто перешлите мне пост или напишите название."
    assert rows_of(keyboard) == [[MY_TITLES_BUTTON], [SUMMARY_BUTTON], [TEST_EVENT_BUTTON]]


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
    ],
)
def test_old_commands_get_no_answer_and_are_not_taken_in(tracker, replies, text):
    say(tracker, text)

    assert replies == []
    assert asyncio.run(tracker.inbox_item(1)) is None


@pytest.mark.parametrize("text", ["Дюна", "🕒 Окна доставки"])  # a free text and the button of an old version
def test_a_free_text_is_taken_in(tracker, replies, text):
    say(tracker, text)

    assert asyncio.run(tracker.inbox_item(1)).text == text


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


@pytest.mark.parametrize("button", [ADD_BUTTON, MY_TITLES_BUTTON, SUMMARY_BUTTON, TEST_EVENT_BUTTON])
def test_every_menu_button_gets_an_answer(tracker, replies, button):
    say(tracker, button)

    assert len(replies) == 1 and replies[0][0]


def test_summary_command_answers(tracker, replies):
    say(tracker, "/summary")

    assert len(replies) == 1 and replies[0][0]


def test_the_commands_registered_in_telegram_are_summary_only():
    assert [(c.command, c.description) for c in BOT_COMMANDS] == [("summary", "Сводка сейчас")]
