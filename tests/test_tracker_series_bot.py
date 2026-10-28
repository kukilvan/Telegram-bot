"""Adding a series in the bot and marking its watched seasons: owner only, through a real aiogram Dispatcher.

Telegram itself is replaced by capturing what the bot would say; the tracker core is real.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from app.bot.access import AccessMiddleware
from app.bot.tracker_handlers import ADD_BUTTON, register_tracker_handlers
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.seasons import Episode, Season
from app.tracker.sources.tmdb_series import SeriesSnapshot, Suggestion

OWNER, STRANGER = 42, 7
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


def run(coro):
    return asyncio.run(coro)


def out(first_day, count):
    start = datetime.fromisoformat(first_day)
    return tuple(Episode(n + 1, start + timedelta(weeks=n)) for n in range(count))


SILO = SeriesSnapshot(
    external_id="125988",
    name="Укрытие",
    original_name="Silo",
    year=2023,
    genres=["драма"],
    seasons=[
        Season(1, "Сезон 1", 10, out("2023-05-04", 10)),
        Season(2, "Сезон 2", 10, out("2024-11-14", 10)),
        Season(3, "Сезон 3", 10, out("2026-07-02", 10)),
        Season(4, "Сезон 4", 1, out("2027-07-08", 1)),
    ],
)
NEWCOMER = SeriesSnapshot(
    external_id="201", name="Новичок", original_name="Newcomer", year=2027, seasons=[Season(1, "Сезон 1", 6, ())]
)


class FakeSeriesSource:
    source_key = "tmdb_tv"

    def __init__(self):
        self.by_id = {s.external_id: s for s in (SILO, NEWCOMER)}
        self.queries = []
        self.failing = False

    async def suggest(self, query):
        self.queries.append(query)
        return [Suggestion("series", s.external_id, s.name, s.original_name, s.year) for s in self.by_id.values()]

    async def snapshot(self, external_id):
        if self.failing:
            raise ConnectionError("tmdb is down")
        return self.by_id.get(external_id)


class FakeSender:
    async def send(self, message, actions=()):
        pass


@pytest.fixture
def series():
    return FakeSeriesSource()


@pytest.fixture
def tracker(series):
    return Tracker(
        create_session_factory("sqlite://"), clock=lambda: NOW, sender=FakeSender(), sources={"series": series}
    )


@pytest.fixture
def replies(monkeypatch):
    """What the bot said: ("message", text, buttons), ("callback", text, None) or ("edit", None, buttons)."""
    said = []

    def buttons_of(markup):
        return [b for row in getattr(markup, "inline_keyboard", []) for b in row] if markup else []

    async def message_answer(self, text=None, **kwargs):
        said.append(("message", text, buttons_of(kwargs.get("reply_markup"))))

    async def callback_answer(self, text=None, **kwargs):
        said.append(("callback", text, None))

    async def edit_reply_markup(self, reply_markup=None, **kwargs):
        said.append(("edit", None, buttons_of(reply_markup)))

    monkeypatch.setattr(Message, "answer", message_answer)
    monkeypatch.setattr(CallbackQuery, "answer", callback_answer)
    monkeypatch.setattr(Message, "edit_reply_markup", edit_reply_markup)
    return said


class Chat_:
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


def last_message(replies):
    return next(r for r in reversed(replies) if r[0] == "message")


def add_series(chat, replies, pick="Укрытие"):
    chat.say(ADD_BUTTON)
    chat.press(callback_of(last_message(replies)[2], "Сериал"))
    chat.say("укрытие")
    chat.press(callback_of(last_message(replies)[2], pick))


# --- adding ---------------------------------------------------------------------------------------


def test_add_button_offers_the_series_type(tracker, replies):
    Chat_(tracker).say(ADD_BUTTON)

    assert labels(replies[-1][2]) == ["Сериал"]


def test_choosing_series_asks_for_a_series_name(tracker, replies):
    chat = Chat_(tracker)
    chat.say(ADD_BUTTON)
    chat.press(callback_of(replies[-1][2], "Сериал"))

    assert "сериала" in replies[-1][1].lower()


def test_picked_series_is_added_and_its_card_shows_the_current_season_and_the_announcement(tracker, replies):
    add_series(Chat_(tracker), replies)

    card = next(r[1] for r in replies if r[0] == "message" and r[1] and "Добавлено" in r[1])
    assert "Укрытие · Silo" in card
    assert "Сезон 3: вышло 10 из 10" in card
    assert "Сезон 4 анонсирован" in card
    [entry] = run(tracker.list_titles())
    assert (entry.kind, entry.status) == ("series", "want")


def test_after_adding_the_bot_asks_which_seasons_are_watched(tracker, replies):
    add_series(Chat_(tracker), replies)

    _, text, buttons = last_message(replies)
    assert "сезоны" in text.lower() and "посмотрел" in text.lower()
    assert labels(buttons) == ["Сезон 1", "Сезон 2", "Сезон 3", "Готово"]  # the announced season 4 is not offered


def test_a_series_with_nothing_released_asks_nothing(tracker, replies):
    add_series(Chat_(tracker), replies, pick="Новичок")

    _, text, buttons = last_message(replies)
    assert "Добавлено" in text
    assert "Сезон 1 анонсирован" in text
    assert "Готово" not in labels(buttons)


def test_adding_a_known_series_again_opens_its_card_without_the_question(tracker, replies):
    chat = Chat_(tracker)
    add_series(chat, replies)
    replies.clear()
    chat.say(ADD_BUTTON)
    chat.press(callback_of(last_message(replies)[2], "Сериал"))
    chat.say("укрытие")
    chat.press(callback_of(last_message(replies)[2], "Укрытие"))

    assert "Уже в списке" in last_message(replies)[1]
    assert not any(r[1] and "какие сезоны" in r[1].lower() for r in replies)


def test_source_failure_gives_a_friendly_answer_and_stores_nothing(tracker, series, replies):
    chat = Chat_(tracker)
    chat.say(ADD_BUTTON)
    chat.press(callback_of(replies[-1][2], "Сериал"))
    chat.say("укрытие")
    series.failing = True
    chat.press(callback_of(replies[-1][2], "Укрытие"))

    assert replies[-1][0] == "message" and "TMDb" in replies[-1][1]  # the press itself was answered early
    assert run(tracker.list_titles()) == []


def test_id_without_a_series_is_answered_not_crashed(tracker, replies):
    Chat_(tracker).press("tpick:series:1396")

    assert replies[-1][0] == "message" and "не нашёл" in replies[-1][1].lower()


# --- marking seasons ------------------------------------------------------------------------------


def test_pressing_a_season_marks_it_and_pressing_again_takes_the_mark_off(tracker, replies):
    chat = Chat_(tracker)
    add_series(chat, replies)
    buttons = last_message(replies)[2]

    chat.press(callback_of(buttons, "Сезон 1"))
    assert labels(replies[-1][2]) == ["✅ Сезон 1", "Сезон 2", "Сезон 3", "Готово"]  # the keyboard is refreshed
    assert [(s.number, s.watched) for s in run(tracker.watchable_seasons(1))] == [(1, True), (2, False), (3, False)]

    chat.press(callback_of(buttons, "Сезон 1"))
    assert [s.watched for s in run(tracker.watchable_seasons(1))] == [False, False, False]


def test_a_dropped_series_keeps_its_season_buttons_and_its_status(tracker, replies):
    chat = Chat_(tracker)
    add_series(chat, replies)
    buttons = last_message(replies)[2]
    run(tracker.mark_dropped(1))

    chat.press(callback_of(buttons, "Сезон 1"))

    assert [(s.number, s.watched) for s in run(tracker.watchable_seasons(1))][0] == (1, True)
    assert run(tracker.title_card(1)).status == "dropped"
    chat.press("tcard:1")
    assert "Бросил" in last_message(replies)[1] and "📺 Просмотренные сезоны" in labels(last_message(replies)[2])


def test_a_season_press_is_one_call_to_the_core_and_done_loads_the_card_once(tracker, replies, monkeypatch):
    chat = Chat_(tracker)
    add_series(chat, replies)
    buttons = last_message(replies)[2]
    calls = []
    for name in ("title_card", "watchable_seasons", "set_season_watched", "toggle_season"):
        real = getattr(tracker, name)

        def spy(*args, _real=real, _name=name):
            calls.append(_name)
            return _real(*args)

        monkeypatch.setattr(tracker, name, spy)

    chat.press(callback_of(buttons, "Сезон 1"))
    assert calls == ["toggle_season"]

    calls.clear()
    chat.press(callback_of(buttons, "Готово"))
    assert calls == ["title_card"]


def test_done_closes_the_choice_and_shows_the_card_with_the_marks(tracker, replies):
    chat = Chat_(tracker)
    add_series(chat, replies)
    buttons = last_message(replies)[2]
    chat.press(callback_of(buttons, "Сезон 1"))
    chat.press(callback_of(buttons, "Сезон 2"))

    chat.press(callback_of(buttons, "Готово"))

    assert ("edit", None, []) in replies  # the buttons of the question are taken away
    assert "Просмотрены сезоны: 1, 2" in last_message(replies)[1]


def test_the_card_button_opens_the_same_choice_later(tracker, replies):
    chat = Chat_(tracker)
    add_series(chat, replies)
    chat.press(callback_of(last_message(replies)[2], "Готово"))  # skip it at adding
    card_buttons = last_message(replies)[2]
    assert labels(card_buttons) == ["📺 Просмотренные сезоны", "🗑 Удалить"]

    chat.press(callback_of(card_buttons, "Просмотренные сезоны"))

    assert labels(last_message(replies)[2]) == ["Сезон 1", "Сезон 2", "Сезон 3", "Готово"]


def test_the_series_card_has_no_watched_button(tracker, replies):
    add_series(Chat_(tracker), replies)

    card_message = next(r for r in replies if r[0] == "message" and r[1] and "Добавлено" in r[1])
    assert not any("Посмотрел" == b.text.split(" ", 1)[-1] for b in card_message[2])


def test_marking_a_removed_title_is_answered_not_crashed(tracker, replies):
    Chat_(tracker).press("tsea:999:1")

    assert replies[-1][0] == "callback" and replies[-1][1]


def test_marking_a_season_that_does_not_exist_is_answered_not_crashed(tracker, replies):
    chat = Chat_(tracker)
    add_series(chat, replies)

    chat.press("tsea:1:9")

    assert replies[-1][0] == "callback" and replies[-1][1]
    assert all(not s.watched for s in run(tracker.watchable_seasons(1)))


@pytest.mark.parametrize("data", ["tsea:1:oops", "tsea:x:1", "tsea:"])
def test_broken_season_buttons_are_answered_not_crashed(tracker, replies, data):
    Chat_(tracker).press(data)

    assert replies[-1][0] == "callback"


# --- the owner only -------------------------------------------------------------------------------


@pytest.mark.parametrize("with_middleware", [True, False])
def test_stranger_cannot_add_or_mark_anything(tracker, series, replies, with_middleware):
    owner = Chat_(tracker)
    add_series(owner, replies)
    replies.clear()
    stranger = Chat_(tracker, uid=STRANGER, with_middleware=with_middleware)

    stranger.press("tadd:series")
    stranger.press("tpick:series:201")
    stranger.press("tsea:1:1")
    stranger.press("tact:seasons:1")

    assert replies == []
    assert len(run(tracker.list_titles())) == 1
    assert all(not s.watched for s in run(tracker.watchable_seasons(1)))
