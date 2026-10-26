"""«Добавить» and «Мои тайтлы» in the bot: owner only, through a real aiogram Dispatcher.

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


def add_movie(chat, replies, query="дюна", pick="Часть вторая"):
    """«Добавить» → «Фильм» → name → pick; returns the replies of the whole walk."""
    chat.say(ADD_BUTTON)
    chat.press(callback_of(replies[-1][2], "Фильм"))
    chat.say(query)
    chat.press(callback_of(replies[-1][2], pick))


# --- walking the add flow ---------------------------------------------------------------------


def test_add_button_offers_the_movie_type(tracker, replies):
    Chat_(tracker).say(ADD_BUTTON)

    [(_, text, buttons)] = replies
    assert labels(buttons) == ["Фильм"]


def test_choosing_the_type_asks_for_the_name(tracker, replies):
    chat = Chat_(tracker)
    chat.say(ADD_BUTTON)
    chat.press(callback_of(replies[-1][2], "Фильм"))

    assert "название" in replies[-1][1].lower()


def test_typed_name_is_searched_and_results_are_buttons(tracker, movies, replies):
    chat = Chat_(tracker)
    chat.say(ADD_BUTTON)
    chat.press(callback_of(replies[-1][2], "Фильм"))
    chat.say("дюна")

    assert movies.queries == ["дюна"]
    assert labels(replies[-1][2]) == ["Дюна: Часть вторая (2024)", "Дюна: Часть третья (2026)"]


def test_nothing_found_says_so_and_how_to_retry(tracker, replies):
    chat = Chat_(tracker)
    chat.say(ADD_BUTTON)
    chat.press(callback_of(replies[-1][2], "Фильм"))
    chat.say("ничего")

    _, text, buttons = replies[-1]
    assert "Ничего не нашлось" in text
    assert buttons == []


def test_picked_result_is_added_and_its_card_is_shown(tracker, replies):
    add_movie(Chat_(tracker), replies)

    _, text, _ = replies[-1]
    assert "Добавлено" in text
    assert "Дюна: Часть вторая" in text and "Dune: Part Two" in text
    assert "27 февраля 2024" in text and "15 апреля 2024" in text
    assert "Хочу" in text
    [entry] = run(tracker.list_titles())
    assert entry.name == "Дюна: Часть вторая" and entry.status == "want"


def test_adding_the_same_movie_again_opens_the_card_without_a_duplicate(tracker, replies):
    chat = Chat_(tracker)
    add_movie(chat, replies)
    add_movie(chat, replies)

    _, text, _ = replies[-1]
    assert "Уже в списке" in text
    assert "Дюна: Часть вторая" in text
    assert len(run(tracker.list_titles())) == 1


def test_unannounced_dates_read_not_announced(tracker, replies):
    add_movie(Chat_(tracker), replies, pick="Часть третья")

    assert "Цифровой релиз: не объявлена" in replies[-1][1]


def test_source_failure_gives_a_friendly_answer_and_stores_nothing(tracker, movies, replies):
    chat = Chat_(tracker)
    chat.say(ADD_BUTTON)
    chat.press(callback_of(replies[-1][2], "Фильм"))
    chat.say("дюна")
    movies.failing = True
    chat.press(callback_of(replies[-1][2], "Часть вторая"))

    assert replies[-1][0] == "message" and "TMDb" in replies[-1][1]  # the press itself was answered early
    assert run(tracker.list_titles()) == []


def test_id_without_a_movie_is_answered_not_crashed(tracker, replies):
    Chat_(tracker).press("tpick:movie:1396")

    assert replies[-1][0] == "message" and "не нашёл" in replies[-1][1].lower()
    assert run(tracker.list_titles()) == []


def test_text_without_pressing_add_is_not_taken_as_a_search(tracker, movies, replies):
    Chat_(tracker).say("дюна")

    assert movies.queries == []
    assert replies == []


def test_only_one_search_per_press_of_add(tracker, movies, replies):
    chat = Chat_(tracker)
    chat.say(ADD_BUTTON)
    chat.press(callback_of(replies[-1][2], "Фильм"))
    chat.say("дюна")
    chat.say("ещё раз")

    assert movies.queries == ["дюна"]


# --- the list ---------------------------------------------------------------------------------


def test_empty_list_says_how_to_add(tracker, replies):
    Chat_(tracker).say(MY_TITLES_BUTTON)

    _, text, buttons = replies[-1]
    assert "пуст" in text.lower() and "Добавить" in text
    assert buttons == []


def test_list_shows_every_title_and_a_tap_opens_the_card(tracker, replies):
    chat = Chat_(tracker)
    add_movie(chat, replies)
    add_movie(chat, replies, query="дюна", pick="Часть третья")

    chat.say(MY_TITLES_BUTTON)
    _, _, buttons = replies[-1]
    assert labels(buttons) == ["🎬 Дюна: Часть вторая (2024)", "🎬 Дюна: Часть третья (2026)", "🗑 Удалить несколько"]

    chat.press(callback_of(buttons, "Часть третья"))
    _, card, _ = replies[-1]
    assert "Дюна: Часть третья" in card and "16 декабря 2026" in card


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
    assert run(tracker.list_titles()) == []
