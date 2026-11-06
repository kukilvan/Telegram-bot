"""«Мои тайтлы», the card and what is left of «➕ Добавить» in the bot: owner only, through a real aiogram Dispatcher.

Telegram itself is replaced by capturing what the bot would say; the tracker core is real.
"""

import asyncio
from datetime import date, datetime, timezone

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from app.bot.access import AccessMiddleware
from app.bot.tracker_handlers import ADD_BUTTON, MY_TITLES_BUTTON, register_tracker_handlers
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.sources.tmdb_movies import MovieSnapshot, Suggestion

OWNER, STRANGER = 42, 7

DUNE_2 = MovieSnapshot(
    external_id="693134",
    name="Дюна: Часть вторая",
    original_name="Dune: Part Two",
    year=2024,
    genres=["фантастика", "приключения"],
    theatrical_date=date(2024, 2, 27),
    digital_date=date(2024, 4, 15),
)
DUNE_3 = MovieSnapshot(
    external_id="1170608",
    name="Дюна: Часть третья",
    original_name="Dune: Part Three",
    year=2026,
    genres=["фантастика"],
    theatrical_date=date(2026, 12, 16),
)


def run(coro):
    return asyncio.run(coro)


class FakeMovieSource:
    source_key = "tmdb_movie"

    def __init__(self):
        self.by_id = {s.external_id: s for s in (DUNE_2, DUNE_3)}
        self.queries = []
        self.failing = False

    async def suggest(self, query):
        self.queries.append(query)
        if query == "ничего":
            return []
        return [Suggestion("movie", s.external_id, s.name, s.original_name, s.year) for s in self.by_id.values()]

    async def snapshot(self, external_id):
        if self.failing:
            raise ConnectionError("tmdb is down")
        return self.by_id.get(external_id)


class FakeSender:
    async def send(self, message, actions=()):
        pass


@pytest.fixture
def movies():
    return FakeMovieSource()


@pytest.fixture
def tracker(movies):
    return Tracker(
        create_session_factory("sqlite://"),
        clock=lambda: datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc),
        sender=FakeSender(),
        sources={"movie": movies},
    )


@pytest.fixture
def replies(monkeypatch):
    """What the bot said: ("message", text, buttons) or ("callback", text, None)."""
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


class Chat_:
    """One conversation with the bot through a real Dispatcher."""

    def __init__(self, tracker, uid=OWNER, with_middleware=True):
        self.uid = uid
        self.tracker = tracker
        self.dp = Dispatcher()
        if with_middleware:
            self.dp.update.outer_middleware(AccessMiddleware([OWNER]))
        register_tracker_handlers(self.dp, tracker, [OWNER])
        self._update_id = 0

    def _feed(self, **update):
        self._update_id += 1
        asyncio.run(self.dp.feed_update(Bot(token="123456:TEST"), Update(update_id=self._update_id, **update)))

    def _user(self):
        return User(id=self.uid, is_bot=False, first_name="x")

    def _message(self, text=None):
        return Message(
            message_id=1, date=0, chat=Chat(id=self.uid, type="private"), from_user=self._user(), text=text
        )

    def say(self, text):
        self._feed(message=self._message(text))

    def press(self, data):
        self._feed(
            callback_query=CallbackQuery(
                id="1", from_user=self._user(), chat_instance="c", data=data, message=self._message("menu")
            )
        )


def labels(buttons):
    return [b.text for b in buttons]


def callback_of(buttons, label_part):
    return next(b.callback_data for b in buttons if label_part in b.text)


def add_movie(chat, replies, pick="Часть вторая"):
    """Into the list as the core adds it (the bot adds by «Да» on an offer, ticket 04 of stage 6.4)."""
    external_id = {"Часть вторая": DUNE_2.external_id, "Часть третья": DUNE_3.external_id}[pick]
    return run(chat.tracker.add_title("movie", external_id)).title_id


# --- the card ---------------------------------------------------------------------------------


def test_the_card_of_an_added_movie_shows_its_dates_and_status(tracker, replies):
    chat = Chat_(tracker)
    chat.press(f"tcard:{add_movie(chat, replies)}")

    _, text, _ = replies[-1]
    assert "Дюна: Часть вторая" in text and "Dune: Part Two" in text
    assert "27 февраля 2024" in text and "15 апреля 2024" in text
    assert "Хочу" in text
    [entry] = run(tracker.list_titles())
    assert entry.name == "Дюна: Часть вторая" and entry.status == "want"


def test_unannounced_dates_read_not_announced(tracker, replies):
    chat = Chat_(tracker)
    chat.press(f"tcard:{add_movie(chat, replies, pick='Часть третья')}")

    assert "Цифровой релиз: не объявлена" in replies[-1][1]


# --- «➕ Добавить» is gone ---------------------------------------------------------------------


def test_the_add_text_of_an_old_keyboard_says_the_button_is_gone_and_sends_the_new_keyboard(tracker, movies, replies):
    Chat_(tracker).say(ADD_BUTTON)

    [(_, text, _)] = replies
    assert text == "Кнопки «Добавить» больше нет: просто перешлите мне пост или напишите название."
    assert movies.queries == []


@pytest.mark.parametrize("data", ["tadd:movie", "tpick:movie:693134", "tadd:", "tpick:"])
def test_an_old_add_button_no_longer_works(tracker, movies, replies, data):
    Chat_(tracker).press(data)

    assert replies == [("callback", "Эта кнопка больше не работает.", None)]
    assert movies.queries == [] and run(tracker.list_titles()) == []


def test_a_text_is_taken_in_not_searched(tracker, movies, replies):
    Chat_(tracker).say("дюна")

    assert movies.queries == []
    assert run(tracker.inbox_item(1)).text == "дюна"  # the question comes after the pause (test_bot_inbox.py)


# --- the list ---------------------------------------------------------------------------------


def test_empty_list_says_how_to_add(tracker, replies):
    Chat_(tracker).say(MY_TITLES_BUTTON)

    _, text, buttons = replies[-1]
    assert text == "Список пуст. Перешлите мне пост о фильме, сериале, аниме или игре или напишите название."
    assert buttons == []


def test_list_shows_every_title_and_a_tap_opens_the_card(tracker, replies):
    chat = Chat_(tracker)
    add_movie(chat, replies)
    add_movie(chat, replies, pick="Часть третья")

    chat.say(MY_TITLES_BUTTON)
    _, _, buttons = replies[-1]
    assert labels(buttons) == ["🎬 Дюна: Часть вторая (2024)", "🎬 Дюна: Часть третья (2026)", "🗑 Удалить несколько"]

    chat.press(callback_of(buttons, "Часть третья"))
    _, card, _ = replies[-1]
    assert "Дюна: Часть третья" in card and "16 декабря 2026" in card


def test_the_list_keeps_a_dropped_title_as_it_was(tracker, replies):
    chat = Chat_(tracker)
    add_movie(chat, replies)
    run(tracker.mark_dropped(1))

    chat.say(MY_TITLES_BUTTON)

    _, _, buttons = replies[-1]
    assert labels(buttons) == ["🎬 Дюна: Часть вторая (2024)", "🗑 Удалить несколько"]


def test_card_of_a_removed_title_is_answered_not_crashed(tracker, replies):
    Chat_(tracker).press("tcard:999")

    assert replies[-1][0] == "callback" and replies[-1][1]


# --- the owner only ---------------------------------------------------------------------------


@pytest.mark.parametrize("with_middleware", [True, False])
def test_stranger_gets_nothing_anywhere(tracker, movies, replies, with_middleware):
    chat = Chat_(tracker, uid=STRANGER, with_middleware=with_middleware)

    chat.say(ADD_BUTTON)
    chat.say(MY_TITLES_BUTTON)
    chat.press("tadd:movie")
    chat.say("дюна")
    chat.press("tpick:movie:693134")
    chat.press("tcard:1")

    assert replies == []
    assert movies.queries == []
    assert run(tracker.list_titles()) == [] and run(tracker.inbox_item(1)) is None
