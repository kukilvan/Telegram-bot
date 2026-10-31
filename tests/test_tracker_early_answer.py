"""A press that goes to the network is answered first: «answer → work → tell» (rule 8 in docs/coding-standards.md).

Telegram takes one answer per press and drops it ("query is too old") if it comes late. The fake Telegram here
rejects an answer that arrives after a source has started, like the real one does for a slow source.
"""

import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import AnswerCallbackQuery
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from app.bot.access import AccessMiddleware
from app.bot.tracker_handlers import register_tracker_handlers
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.seasons import Episode, Season
from app.tracker.sources.tmdb_movies import MovieSnapshot
from app.tracker.sources.tmdb_sequels import CollectionPart, SequelSnapshot
from app.tracker.sources.tmdb_series import SeriesSnapshot

OWNER = 42
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
ADDING = "Добавляю…"
SILO, DUNE_3, DUNE = "125988", "1170608", "438631"


def run(coro):
    return asyncio.run(coro)


class Journal(list):
    """What happened, in order: ("answer", text), ("source", id) and ("message", text, buttons)."""

    def of(self, what):
        return [entry for entry in self if entry[0] == what]

    @property
    def started(self):
        return bool(self.of("source"))


class SlowSource:
    """A source that takes its time (a series with dozens of seasons) and can fail."""

    def __init__(self, source_key, journal, snapshots):
        self.source_key = source_key
        self.journal = journal
        self.by_id = snapshots
        self.failing = False

    async def suggest(self, query):
        return []

    async def snapshot(self, external_id):
        self.journal.append(("source", external_id))
        await asyncio.sleep(0.02)
        if self.failing:
            raise ConnectionError("tmdb is down")
        return self.by_id.get(external_id)


class FakeSequelSource:
    source_key = "tmdb_sequels"

    async def snapshot(self, external_id):
        return SequelSnapshot(own_date=date(2021, 9, 15), parts=[CollectionPart(DUNE_3, "Дюна: Часть третья", date(2026, 12, 15))])


class FakeSender:
    async def send(self, message, actions=()):
        pass


def silo():
    episodes = tuple(Episode(n + 1, datetime(2023, 5, 4) + timedelta(weeks=n)) for n in range(10))
    return SeriesSnapshot(
        external_id=SILO, name="Укрытие", original_name="Silo", year=2023, genres=["драма"],
        seasons=[Season(1, "Сезон 1", 10, episodes)],
    )


def movie(external_id, name):
    return MovieSnapshot(
        external_id=external_id, name=name, original_name=name, year=2026, genres=[], theatrical_date=date(2026, 12, 15)
    )


@pytest.fixture
def journal():
    return Journal()


@pytest.fixture
def series(journal):
    return SlowSource("tmdb_tv", journal, {SILO: silo()})


@pytest.fixture
def movies(journal):
    return SlowSource("tmdb_movie", journal, {DUNE_3: movie(DUNE_3, "Дюна: Часть третья"), DUNE: movie(DUNE, "Дюна")})


@pytest.fixture
def tracker(series, movies):
    return Tracker(
        create_session_factory("sqlite://"),
        clock=lambda: NOW,
        sender=FakeSender(),
        sources={"series": series, "movie": movies},
        sequel_sources={"movie": FakeSequelSource()},
    )


@pytest.fixture
def telegram(monkeypatch, journal):
    """The bot's side of Telegram: one answer per press, rejected when a source has already started."""
    answered = []

    async def callback_answer(self, text=None, **kwargs):
        if answered:
            raise AssertionError(f"the press was answered twice: {answered[-1]!r}, then {text!r}")
        if journal.started:
            raise TelegramBadRequest(
                method=AnswerCallbackQuery(callback_query_id="1"), message="query is too old and response timeout expired"
            )
        answered.append(text)
        journal.append(("answer", text))

    async def message_answer(self, text=None, **kwargs):
        markup = kwargs.get("reply_markup")
        rows = getattr(markup, "inline_keyboard", []) if markup else []
        journal.append(("message", text, [b for row in rows for b in row]))

    async def edit_markup(self, **kwargs):
        pass

    monkeypatch.setattr(CallbackQuery, "answer", callback_answer)
    monkeypatch.setattr(Message, "answer", message_answer)
    monkeypatch.setattr(Message, "edit_reply_markup", edit_markup)
    return journal


def press(tracker, data, with_message=True):
    dp = Dispatcher()
    dp.update.outer_middleware(AccessMiddleware([OWNER]))
    register_tracker_handlers(dp, tracker, [OWNER])
    user = User(id=OWNER, is_bot=False, first_name="x")
    message = Message(message_id=1, date=0, chat=Chat(id=OWNER, type="private"), from_user=user, text="m")
    callback = CallbackQuery(
        id="1", from_user=user, chat_instance="c", data=data, message=message if with_message else None
    )
    run(dp.feed_update(Bot(token="123456:TEST"), Update(update_id=1, callback_query=callback)))


def texts(journal):
    return [entry[1] for entry in journal.of("message")]


# --- adding from the suggestions --------------------------------------------------------------------


def test_adding_answers_the_press_before_the_source_is_asked(tracker, telegram):
    press(tracker, f"tpick:series:{SILO}")

    assert [entry[0] for entry in telegram][:2] == ["answer", "source"]
    assert telegram.of("answer") == [("answer", ADDING)]


def test_a_slow_source_does_not_lose_the_card_or_the_question_about_seasons(tracker, telegram):
    press(tracker, f"tpick:series:{SILO}")

    card, question = texts(telegram)
    assert card.startswith("✅ Добавлено в список") and "Укрытие" in card
    assert "Какие сезоны" in question
    assert [t.name for t in run(tracker.list_titles())] == ["Укрытие"]


def test_a_source_failure_while_adding_comes_as_a_message_and_not_a_second_answer(tracker, series, telegram):
    series.failing = True

    press(tracker, f"tpick:series:{SILO}")

    assert telegram.of("answer") == [("answer", ADDING)]
    assert texts(telegram) == ["Не удалось получить данные из TMDb. Попробуйте чуть позже."]
    assert run(tracker.list_titles()) == []


def test_a_title_the_source_does_not_know_comes_as_a_message(tracker, telegram):
    press(tracker, "tpick:series:1")

    assert telegram.of("answer") == [("answer", ADDING)]
    assert texts(telegram) == ["Не нашёл такой тайтл в TMDb, попробуйте поискать заново."]


def test_a_kind_the_core_lost_comes_as_a_message(tracker, telegram):
    press(tracker, "tpick:anime:1")  # a kind of the bot's, but no source is plugged in for it

    assert telegram.of("answer") == [("answer", ADDING)]
    assert texts(telegram) == ["Такого типа больше нет, нажмите «➕ Добавить» заново."]


def test_a_kind_that_is_no_kind_is_a_popup_and_never_reaches_a_source(tracker, telegram):
    press(tracker, "tpick:book:1")

    assert list(telegram) == [("answer", "Такого типа больше нет, нажмите «➕ Добавить» заново.")]


def test_without_a_message_a_failure_goes_to_the_log_only(tracker, series, telegram, caplog):
    series.failing = True

    press(tracker, f"tpick:series:{SILO}", with_message=False)

    assert telegram.of("answer") == [("answer", ADDING)]
    assert texts(telegram) == []
    assert any("adding a title failed" in r.getMessage() and "tmdb is down" in r.getMessage() for r in caplog.records)


# --- «Следить» -----------------------------------------------------------------------------------------


def test_following_answers_the_press_before_the_source_is_asked(tracker, telegram):
    press(tracker, f"tact:follow:movie:{DUNE_3}")

    assert [entry[0] for entry in telegram][:2] == ["answer", "source"]
    assert telegram.of("answer") == [("answer", ADDING)]
    [card] = texts(telegram)
    assert card.startswith("✅ Продолжение добавлено в список") and "Дюна: Часть третья" in card


def test_a_source_failure_while_following_comes_as_a_message(tracker, movies, telegram):
    movies.failing = True

    press(tracker, f"tact:follow:movie:{DUNE_3}")

    assert telegram.of("answer") == [("answer", ADDING)]
    assert texts(telegram) == ["Не удалось получить данные из TMDb. Попробуйте чуть позже."]
    assert run(tracker.list_titles()) == []


def test_a_sequel_the_source_does_not_know_comes_as_a_message(tracker, telegram):
    press(tracker, "tact:follow:movie:1")

    assert telegram.of("answer") == [("answer", ADDING)]
    assert texts(telegram) == ["Не нашёл это продолжение в TMDb. Попробуйте чуть позже."]


def test_an_old_button_without_its_announcement_comes_as_a_message(tracker, telegram):
    press(tracker, "tact:follow:999")

    assert telegram.of("answer") == [("answer", ADDING)]
    assert texts(telegram) == ["Это объявление больше недоступно."]
    assert not telegram.started


def test_a_kind_without_sequels_comes_as_a_message(tracker, telegram):
    press(tracker, f"tact:follow:series:{SILO}")  # a real kind, but only films have sequels

    assert telegram.of("answer") == [("answer", ADDING)]
    assert texts(telegram) == ["Эта кнопка больше не работает."]
    assert not telegram.started


@pytest.mark.parametrize("data", ["tact:follow:book:1", "tact:follow:movie:", "tact:follow::1", "tact:follow:x"])
def test_a_dead_follow_button_is_a_popup_and_never_reaches_a_source(tracker, telegram, data):
    press(tracker, data)

    assert list(telegram) == [("answer", "Эта кнопка больше не работает.")]


def test_following_without_a_message_goes_to_the_log_only(tracker, movies, telegram, caplog):
    movies.failing = True

    press(tracker, f"tact:follow:movie:{DUNE_3}", with_message=False)

    assert telegram.of("answer") == [("answer", ADDING)]
    assert texts(telegram) == []
    assert any("following a sequel failed" in r.getMessage() and "tmdb is down" in r.getMessage() for r in caplog.records)
