"""The bot in link mode (stage 7.2, ticket 01): with an app address «Карточка» is a link, a card in the chat has the one
button «Открыть в приложении», the menu is «Сводка сейчас» alone, `/start` and the old texts of the menu answer with a
text link; the old callback buttons still work. Chat mode (no address) is covered by the older bot tests, which pass
untouched. Through a real `Dispatcher` and the real core; Telegram is replaced by capturing what the bot would say."""

import asyncio
from datetime import date, datetime, timezone

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, ReplyKeyboardMarkup, Update, User

from app.bot.access import AccessMiddleware
from app.bot.app_links import AppLinks
from app.bot.tracker_handlers import (
    ADD_BUTTON,
    MY_TITLES_BUTTON,
    NO_ADD_BUTTON,
    OPEN_IN_APP_BUTTON,
    START_TEXT,
    SUMMARY_BUTTON,
    TEST_EVENT_BUTTON,
    TelegramSender,
    actions_markup,
    main_keyboard,
    register_tracker_handlers,
)
from app.tracker import follow_ups, price_events
from app.tracker.actions import CARD, DELETE, STEAM_LABEL, Action, event_actions
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.sources.tmdb_movies import MovieSnapshot

OWNER = 42
ADDRESS = "http://192.168.1.124:8080"
LINKS = AppLinks(ADDRESS)
DUNE = "438631"
T0 = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


class FakeMovieSource:
    source_key = "tmdb_movie"

    async def suggest(self, query):
        return []

    async def snapshot(self, external_id):
        return MovieSnapshot(
            external_id=external_id, name="Дюна", original_name="Dune", year=2021, genres=[],
            theatrical_date=date(2021, 9, 15),
        )


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((text, [b for row in getattr(reply_markup, "inline_keyboard", []) for b in row]))


@pytest.fixture
def telegram():
    return FakeBot()


@pytest.fixture
def tracker(telegram):
    return Tracker(
        create_session_factory("sqlite://"), clock=lambda: T0, sender=TelegramSender(telegram, OWNER, LINKS),
        sources={"movie": FakeMovieSource()},
    )


@pytest.fixture
def said(monkeypatch):
    """What the bot said: dicts with the text, the parse mode, the inline buttons and the menu of each message."""
    said = []

    async def message_answer(self, text=None, **kwargs):
        markup = kwargs.get("reply_markup")
        said.append({
            "kind": "message", "text": text, "parse_mode": kwargs.get("parse_mode"),
            "menu": markup if isinstance(markup, ReplyKeyboardMarkup) else None,
            "buttons": [b for row in getattr(markup, "inline_keyboard", []) for b in row],
        })

    async def callback_answer(self, text=None, **kwargs):
        said.append({"kind": "callback", "text": text, "buttons": [], "menu": None, "parse_mode": None})

    async def edit_markup(self, **kwargs):
        pass

    monkeypatch.setattr(Message, "answer", message_answer)
    monkeypatch.setattr(CallbackQuery, "answer", callback_answer)
    monkeypatch.setattr(Message, "edit_reply_markup", edit_markup)
    return said


class Chat_:
    def __init__(self, tracker, links=LINKS):
        self.dp = Dispatcher()
        self.dp.update.outer_middleware(AccessMiddleware([OWNER]))
        register_tracker_handlers(self.dp, tracker, [OWNER], links)
        self._update_id = 0

    def feed(self, **update):
        self._update_id += 1
        asyncio.run(self.dp.feed_update(Bot(token="123456:TEST"), Update(update_id=self._update_id, **update)))

    def say(self, text):
        user = User(id=OWNER, is_bot=False, first_name="x")
        message = Message(message_id=1, date=0, chat=Chat(id=OWNER, type="private"), from_user=user, text=text)
        self.feed(message=message)

    def press(self, data):
        user = User(id=OWNER, is_bot=False, first_name="x")
        message = Message(message_id=1, date=0, chat=Chat(id=OWNER, type="private"), from_user=user, text="m")
        self.feed(callback_query=CallbackQuery(id="1", from_user=user, chat_instance="c", data=data, message=message))


def add_dune(tracker):
    return asyncio.run(tracker.add_title("movie", DUNE)).title_id


def menu_texts(menu):
    return [button.text for row in menu.keyboard for button in row]


# --- the addresses ----------------------------------------------------------------------------------------------------


def test_the_links_append_the_paths_of_the_pages_to_the_address():
    assert LINKS.card(42) == f"{ADDRESS}/titles/42"
    assert (LINKS.home(), LINKS.list(), LINKS.settings()) == (f"{ADDRESS}/", f"{ADDRESS}/list", f"{ADDRESS}/settings")


# --- «Карточка» under messages ----------------------------------------------------------------------------------------


def test_a_card_button_of_an_event_is_a_link_with_its_own_label_and_the_others_stay_what_they_are():
    actions = event_actions("movie_released", 1, 7)  # «Посмотрел» and «Карточка»

    watched, card = (row[0] for row in actions_markup(actions, LINKS).inline_keyboard)

    assert card.text == "📄 Карточка" and card.url == f"{ADDRESS}/titles/7" and card.callback_data is None
    assert watched.callback_data == "tact:watched:7" and watched.url is None


def test_a_steam_message_has_a_card_link_and_the_link_to_steam():
    actions = event_actions(price_events.DISCOUNT, 1, 7, {"steam_id": "1145350"})

    card, steam = (row[0] for row in actions_markup(actions, LINKS).inline_keyboard)

    assert card.url == f"{ADDRESS}/titles/7" and steam.text == STEAM_LABEL and "steampowered" in steam.url


def test_an_announcement_keeps_follow_by_the_bot_and_has_a_card_link():
    actions = event_actions(follow_ups.TYPES[0], 1, 7, {"kind": "game", "sequel_id": "55"})

    follow, card = (row[0] for row in actions_markup(actions, LINKS).inline_keyboard)

    assert follow.callback_data == "tact:follow:game:55" and card.url == f"{ADDRESS}/titles/7"


def test_a_summary_card_button_is_a_link_with_the_name_of_the_title():
    markup = actions_markup([Action("📄 Карточка: Дюна", CARD, 7), Action("🗑 Удалить", DELETE, 7)], LINKS)

    card, delete = (row[0] for row in markup.inline_keyboard)

    assert card.text == "📄 Карточка: Дюна" and card.url == f"{ADDRESS}/titles/7"
    assert delete.callback_data == "tact:delete:7"


def test_without_links_every_button_calls_the_bot_as_before():
    markup = actions_markup(event_actions("movie_released", 1, 7))

    assert all(row[0].url is None and row[0].callback_data for row in markup.inline_keyboard)


def test_the_sender_sends_the_link_buttons_in_link_mode(telegram):
    asyncio.run(TelegramSender(telegram, OWNER, LINKS).send("Дюна вышла", event_actions("movie_released", 1, 7)))

    ((_, buttons),) = telegram.sent
    assert [(b.text, b.url) for b in buttons if b.url] == [("📄 Карточка", f"{ADDRESS}/titles/7")]


# --- a card in the chat -----------------------------------------------------------------------------------------------


def test_a_card_in_the_chat_has_the_one_button_that_opens_it_in_the_app(tracker, said):
    title_id = add_dune(tracker)

    Chat_(tracker).press(f"tcard:{title_id}")

    card = next(m for m in said if m["kind"] == "message")
    assert [(b.text, b.url) for b in card["buttons"]] == [(OPEN_IN_APP_BUTTON, f"{ADDRESS}/titles/{title_id}")]
    assert OPEN_IN_APP_BUTTON == "📄 Открыть в приложении"


def test_an_old_card_button_still_shows_the_card_in_the_chat_with_the_app_button(tracker, said):
    title_id = add_dune(tracker)

    Chat_(tracker).press(f"tact:card:{title_id}")

    card = next(m for m in said if m["kind"] == "message")
    assert "Дюна" in card["text"] and [b.url for b in card["buttons"]] == [f"{ADDRESS}/titles/{title_id}"]


def test_the_old_buttons_of_a_card_still_work(tracker, said):
    title_id = add_dune(tracker)

    Chat_(tracker).press(f"tact:delete:{title_id}")  # the question; its answer buttons are callbacks in both modes

    question = next(m for m in said if m["kind"] == "message")
    assert [b.callback_data for b in question["buttons"]] == [f"tdel:y:{title_id}", f"tdel:n:{title_id}"]


# --- the menu, /start and the old texts -------------------------------------------------------------------------------


def test_the_menu_is_one_button_in_link_mode_and_three_in_chat_mode():
    assert menu_texts(main_keyboard(LINKS)) == [SUMMARY_BUTTON]
    assert menu_texts(main_keyboard()) == [MY_TITLES_BUTTON, SUMMARY_BUTTON, TEST_EVENT_BUTTON]


def test_start_brings_the_new_menu_and_a_text_link_to_the_app(tracker, said):
    Chat_(tracker).say("/start")

    (reply,) = said
    assert menu_texts(reply["menu"]) == [SUMMARY_BUTTON]
    assert reply["parse_mode"] == "HTML" and reply["buttons"] == []
    assert reply["text"].startswith("👋 Бот работает.")
    assert "сохраню во «Входящие» приложения." in reply["text"] and "веб-приложения" not in reply["text"]
    assert reply["text"].endswith(f'в приложении: <a href="{ADDRESS}/">🌐 Открыть приложение</a>')


def test_start_in_chat_mode_is_the_old_text_and_menu(tracker, said):
    Chat_(tracker, links=None).say("/start")

    (reply,) = said
    assert reply["text"] == START_TEXT and reply["parse_mode"] is None
    assert menu_texts(reply["menu"]) == [MY_TITLES_BUTTON, SUMMARY_BUTTON, TEST_EVENT_BUTTON]


@pytest.mark.parametrize(
    ("text", "sentence", "label", "path"),
    [
        (MY_TITLES_BUTTON, "Список теперь в приложении: ", "📚 Открыть список", "/list"),
        (
            TEST_EVENT_BUTTON,
            "Тестовое событие и проверка правил доставки теперь в Настройках приложения: ",
            "⚙️ Открыть Настройки",
            "/settings",
        ),
    ],
)
def test_an_old_menu_text_gets_the_new_menu_and_its_link(tracker, said, text, sentence, label, path):
    Chat_(tracker).say(text)

    (reply,) = said
    assert reply["text"] == f'{sentence}<a href="{ADDRESS}{path}">{label}</a>'
    assert menu_texts(reply["menu"]) == [SUMMARY_BUTTON] and reply["parse_mode"] == "HTML"
    assert asyncio.run(tracker.inbox_item(1)) is None  # not an inbox item


def test_the_old_add_button_gets_its_answer_with_the_new_menu(tracker, said):
    Chat_(tracker).say(ADD_BUTTON)

    (reply,) = said
    assert reply["text"] == NO_ADD_BUTTON and menu_texts(reply["menu"]) == [SUMMARY_BUTTON]
    assert asyncio.run(tracker.inbox_item(1)) is None


def test_the_old_texts_are_not_answered_with_links_in_chat_mode(tracker, said):
    Chat_(tracker, links=None).say(MY_TITLES_BUTTON)

    (reply,) = said
    assert reply["text"] == "Список пуст. Перешлите мне пост о фильме, сериале, аниме или игре или напишите название."


def test_the_summary_button_still_answers_in_link_mode(tracker, said):
    Chat_(tracker).say(SUMMARY_BUTTON)

    assert [m["text"] for m in said] == ["Накопленных событий нет — присылать нечего."]


@pytest.mark.parametrize("data", ["tev:ping", "tchk:open", "twin:friday", "tdm:open", "tdm:abc:go", "tadd:movie"])
def test_the_callback_buttons_of_the_old_menu_work_in_link_mode(tracker, said, data):
    Chat_(tracker).press(data)

    assert said  # every one is answered (a popup or a message), none is lost
