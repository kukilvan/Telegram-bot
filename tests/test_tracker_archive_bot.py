"""«Посмотрел» and «Следить» in the bot: buttons under messages and cards, owner only, through a real Dispatcher.

Telegram itself is replaced by capturing what the bot would say; the tracker core is real.
"""

import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from sqlalchemy import select

from app.bot.access import AccessMiddleware
from app.bot.tracker_handlers import TelegramSender, register_tracker_handlers
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import Event
from app.tracker.sources.tmdb_movies import MovieSnapshot
from app.tracker.sources.tmdb_sequels import CollectionPart, SequelSnapshot

OWNER, STRANGER = 42, 7
DUNE, DUNE_3 = "438631", "1170608"
T0 = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


def movie(external_id, title, theatrical=None):
    return MovieSnapshot(
        external_id=external_id, title=title, original_title=title, year=2021, genres=[], theatrical_date=theatrical
    )


class FakeMovieSource:
    source_key = "tmdb_movie"

    def __init__(self):
        self.by_id = {
            DUNE: movie(DUNE, "Дюна", date(2021, 9, 15)),
            DUNE_3: movie(DUNE_3, "Дюна: Часть третья", date(2026, 12, 15)),
        }
        self.failing = False

    async def suggest(self, query):
        return []

    async def snapshot(self, external_id):
        if self.failing:
            raise ConnectionError("tmdb is down")
        return self.by_id.get(external_id)


class FakeSequelSource:
    source_key = "tmdb_sequels"

    def __init__(self):
        self.parts: list[CollectionPart] = []

    async def snapshot(self, external_id):
        return SequelSnapshot(own_date=date(2021, 9, 15), parts=list(self.parts))


class FakeBot:
    """Stands in for aiogram's Bot where the sender needs it: records what would go to Telegram."""

    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None):
        buttons = [b for row in getattr(reply_markup, "inline_keyboard", []) for b in row]
        self.sent.append((chat_id, text, buttons))


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


@pytest.fixture
def movies():
    return FakeMovieSource()


@pytest.fixture
def sequels():
    return FakeSequelSource()


@pytest.fixture
def telegram():
    return FakeBot()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def tracker(movies, sequels, telegram, clock):
    return Tracker(
        create_session_factory("sqlite://"),
        clock=clock,
        sender=TelegramSender(telegram, OWNER),
        sources={"movie": movies},
        sequel_sources={"movie": sequels},
    )


class Said(list):
    """The bot's replies in order; `dropped` holds the keyboards it took off messages."""

    def __init__(self):
        super().__init__()
        self.dropped = []


@pytest.fixture
def replies(monkeypatch):
    """What the bot said: ("message", text, buttons) or ("callback", text, None); plus spent keyboards."""
    said = Said()
    dropped = said.dropped

    async def message_answer(self, text=None, **kwargs):
        markup = kwargs.get("reply_markup")
        rows = getattr(markup, "inline_keyboard", []) if markup else []
        said.append(("message", text, [b for row in rows for b in row]))

    async def callback_answer(self, text=None, **kwargs):
        said.append(("callback", text, None))

    async def edit_markup(self, **kwargs):
        dropped.append(kwargs.get("reply_markup"))

    monkeypatch.setattr(Message, "answer", message_answer)
    monkeypatch.setattr(CallbackQuery, "answer", callback_answer)
    monkeypatch.setattr(Message, "edit_reply_markup", edit_markup)
    return said


class Chat_:
    """One conversation with the bot through a real Dispatcher."""

    def __init__(self, tracker, uid=OWNER):
        self.uid = uid
        self.dp = Dispatcher()
        self.dp.update.outer_middleware(AccessMiddleware([OWNER]))
        register_tracker_handlers(self.dp, tracker, [OWNER])
        self._update_id = 0

    def press(self, data):
        self._update_id += 1
        user = User(id=self.uid, is_bot=False, first_name="x")
        message = Message(message_id=1, date=0, chat=Chat(id=self.uid, type="private"), from_user=user, text="m")
        update = Update(
            update_id=self._update_id,
            callback_query=CallbackQuery(id="1", from_user=user, chat_instance="c", data=data, message=message),
        )
        asyncio.run(self.dp.feed_update(Bot(token="123456:TEST"), update))


def run(coro):
    return asyncio.run(coro)


def messages(replies):
    return [r for r in replies if r[0] == "message"]


def add(tracker, external_id=DUNE):
    return run(tracker.add_title("movie", external_id)).title_id


def event_text_and_buttons(telegram, part):
    return next((text, buttons) for _, text, buttons in telegram.sent if part in text)


# --- «Посмотрел» ---------------------------------------------------------------------------------


def test_the_card_of_a_wanted_movie_has_a_watched_button(tracker, replies):
    title_id = add(tracker)

    Chat_(tracker).press(f"tcard:{title_id}")

    [(_, text, buttons)] = messages(replies)
    assert [b.text for b in buttons] == ["✅ Посмотрел"]
    assert buttons[0].callback_data == f"tact:watched:{title_id}"


def test_pressing_watched_on_a_card_archives_the_movie(tracker, replies):
    title_id = add(tracker)

    Chat_(tracker).press(f"tact:watched:{title_id}")

    assert tracker.title_card(title_id).status == "watched"
    assert [r[1] for r in replies if r[0] == "callback"] == ["Отмечено как просмотренное"]
    [(_, text, _)] = [r for r in replies if r[0] == "message"]
    assert "Дюна" in text and "архиве" in text
    assert replies.dropped == [None]  # the spent button is taken off the message


def test_the_card_of_a_watched_movie_shows_the_status_and_no_button(tracker, replies):
    title_id = add(tracker)
    chat = Chat_(tracker)
    chat.press(f"tact:watched:{title_id}")
    replies.clear()

    chat.press(f"tcard:{title_id}")

    [(_, text, buttons)] = messages(replies)
    assert "Просмотрено" in text
    assert buttons == []


def test_pressing_watched_again_says_it_is_already_done(tracker, replies):
    title_id = add(tracker)
    chat = Chat_(tracker)
    chat.press(f"tact:watched:{title_id}")
    replies.clear()

    chat.press(f"tact:watched:{title_id}")

    assert replies == [("callback", "Уже отмечено как просмотренное.", None)]


def test_watched_on_a_title_that_is_gone_says_so(tracker, replies):
    Chat_(tracker).press("tact:watched:999")

    assert replies == [("callback", "Этого тайтла больше нет в списке.", None)]


def test_a_button_with_a_broken_payload_is_answered_not_crashed(tracker, replies):
    chat = Chat_(tracker)
    chat.press("tact:watched:abc")
    chat.press("tact:unknown:1")

    assert [r[1] for r in replies] == ["Эта кнопка больше не работает."] * 2


def test_a_stranger_cannot_mark_anything_watched(tracker, replies):
    title_id = add(tracker)

    Chat_(tracker, uid=STRANGER).press(f"tact:watched:{title_id}")

    assert replies == []
    assert tracker.title_card(title_id).status == "want"


def test_a_movie_event_arrives_with_a_watched_button_that_works(tracker, movies, clock, telegram, replies):
    title_id = add(tracker, DUNE_3)
    movies.by_id[DUNE_3] = movie(DUNE_3, "Дюна: Часть третья", date(2027, 5, 5))
    clock.now += timedelta(days=2)
    run(tracker.poll_due())
    run(tracker.deliver_pending())

    [(chat_id, text, buttons)] = telegram.sent
    assert chat_id == OWNER and "Дюна: Часть третья" in text
    assert [b.text for b in buttons] == ["✅ Посмотрел"]

    Chat_(tracker).press(buttons[0].callback_data)
    assert tracker.title_card(title_id).status == "watched"


def test_a_plain_message_goes_out_without_a_keyboard(tracker, telegram):
    run(tracker.send_test_event("ping"))

    [(_, _, buttons)] = telegram.sent
    assert buttons == []


# --- «Следить» -----------------------------------------------------------------------------------


def announce_sequel(tracker, sequels, clock):
    title_id = add(tracker)
    run(tracker.mark_watched(title_id))
    run(tracker.poll_due())  # the first look at the collection
    sequels.parts = [CollectionPart(DUNE_3, "Дюна: Часть третья", date(2026, 12, 15))]
    clock.now += timedelta(days=7)
    run(tracker.poll_due())
    run(tracker.deliver_pending())


def test_a_sequel_announcement_arrives_with_a_follow_button(tracker, sequels, clock, telegram):
    announce_sequel(tracker, sequels, clock)

    text, buttons = event_text_and_buttons(telegram, "Анонсировано продолжение")

    assert "Дюна: Часть третья" in text
    assert [b.text for b in buttons] == ["👀 Следить"]


def test_nothing_is_added_until_follow_is_pressed(tracker, sequels, clock, telegram):
    announce_sequel(tracker, sequels, clock)

    assert [t.name for t in tracker.list_titles()] == ["Дюна"]


def test_pressing_follow_adds_the_sequel_as_wanted_and_shows_its_card(tracker, sequels, clock, telegram, replies):
    announce_sequel(tracker, sequels, clock)
    _, buttons = event_text_and_buttons(telegram, "Анонсировано продолжение")

    Chat_(tracker).press(buttons[0].callback_data)

    assert [(t.name, t.status) for t in tracker.list_titles()] == [("Дюна", "watched"), ("Дюна: Часть третья", "want")]
    [(_, text, card_buttons)] = [r for r in replies if r[0] == "message"]
    assert "Продолжение добавлено" in text and "Хочу" in text
    assert [b.text for b in card_buttons] == ["✅ Посмотрел"]
    assert replies.dropped == [None]


def test_pressing_follow_twice_does_not_add_a_second_copy(tracker, sequels, clock, telegram, replies):
    announce_sequel(tracker, sequels, clock)
    _, buttons = event_text_and_buttons(telegram, "Анонсировано продолжение")
    chat = Chat_(tracker)
    chat.press(buttons[0].callback_data)
    replies.clear()

    chat.press(buttons[0].callback_data)

    assert len(tracker.list_titles()) == 2
    assert "Уже в списке" in [r for r in replies if r[0] == "message"][0][1]


def test_follow_during_a_tmdb_outage_says_to_try_later_and_adds_nothing(tracker, movies, sequels, clock, telegram, replies):
    announce_sequel(tracker, sequels, clock)
    _, buttons = event_text_and_buttons(telegram, "Анонсировано продолжение")
    movies.failing = True

    Chat_(tracker).press(buttons[0].callback_data)

    assert replies == [("callback", "Не удалось получить данные из TMDb. Попробуйте чуть позже.", None)]
    assert len(tracker.list_titles()) == 1


def test_follow_on_an_event_that_is_not_an_announcement_is_refused(tracker, telegram, replies):
    run(tracker.send_test_event("ping"))
    with tracker.session_factory() as s:
        event_id = s.scalars(select(Event.id)).first()

    Chat_(tracker).press(f"tact:follow:{event_id}")

    assert replies == [("callback", "Это объявление больше недоступно.", None)]


def test_a_stranger_cannot_follow(tracker, sequels, clock, telegram, replies):
    announce_sequel(tracker, sequels, clock)
    _, buttons = event_text_and_buttons(telegram, "Анонсировано продолжение")

    Chat_(tracker, uid=STRANGER).press(buttons[0].callback_data)

    assert replies == []
    assert len(tracker.list_titles()) == 1
