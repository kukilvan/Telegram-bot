"""The score in the card of the bot (a line after the genres, shown only when it is visible) and the cause of a failed
source in the log of the bot (KI-26). The bot only shows a score, it does not set one."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from app.bot.access import AccessMiddleware
from app.bot.tracker_handlers import register_tracker_handlers
from app.tracker.cards import format_card
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.seasons import Episode, Season
from app.tracker.sources.tmdb_movies import MovieSnapshot
from app.tracker.sources.tmdb_series import SeriesSnapshot
from season_helpers import season_id

OWNER = 42
T0 = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
FILM = MovieSnapshot(external_id="1", name="Дюна", original_name="Dune", year=2021, genres=["драма", "фантастика"])
SHOW = SeriesSnapshot(
    external_id="10", name="Идущий", original_name="Running", year=2026, genres=["драма"],
    seasons=[
        Season(n, f"Сезон {n}", 4, tuple(Episode(i + 1, datetime(2026, 1, 5) + timedelta(weeks=i)) for i in range(4)))
        for n in (1, 2)
    ],
)


def run(coro):
    return asyncio.run(coro)


class FakeSender:
    async def send(self, message, actions=()):
        pass


class Source:
    def __init__(self, key, snapshot, *, failing=False):
        self.source_key = key
        self.snapshot_ = snapshot
        self.failing = failing

    async def suggest(self, query):
        if self.failing:
            raise ConnectionError("tmdb is down")
        return []

    async def snapshot(self, external_id):
        if self.failing:
            raise ConnectionError("tmdb is down")
        return self.snapshot_


@pytest.fixture
def movies():
    return Source("tmdb_movie", FILM)


@pytest.fixture
def tracker(movies):
    return Tracker(
        create_session_factory("sqlite://"), clock=lambda: T0, sender=FakeSender(),
        sources={"movie": movies, "series": Source("tmdb_tv", SHOW)},
    )


def card_text(tracker, title_id):
    return format_card(run(tracker.title_card(title_id)))


# ---- the line «Оценка» -----------------------------------------------------------------------------------

def test_a_film_that_is_wanted_has_no_line_of_score_even_when_one_is_stored(tracker):
    film = run(tracker.add_title("movie", "1")).title_id
    run(tracker.mark_watched(film))
    run(tracker.set_title_score(film, 28))
    run(tracker.restore_title(film))

    assert "Оценка" not in card_text(tracker, film)


def test_a_watched_film_shows_its_score_after_the_genres(tracker):
    film = run(tracker.add_title("movie", "1")).title_id
    run(tracker.mark_watched(film))
    assert "Оценка" not in card_text(tracker, film)  # watched, not scored yet

    run(tracker.set_title_score(film, 28))
    lines = card_text(tracker, film).split("\n")

    assert lines[lines.index("Жанры: драма, фантастика") + 1] == "Оценка: 9+"


def test_a_series_shows_the_average_of_its_seasons_and_says_so(tracker):
    show = run(tracker.add_title("series", "10")).title_id
    for number, step in ((1, 27), (2, 25)):
        run(tracker.set_season_watched(show, season_id(tracker, show, number), True))
        run(tracker.set_season_score(show, season_id(tracker, show, number), step))

    assert "Оценка: 9− (среднее по сезонам)" in card_text(tracker, show)


def test_an_own_score_of_a_series_is_shown_without_the_note(tracker):
    show = run(tracker.add_title("series", "10")).title_id
    run(tracker.set_season_watched(show, season_id(tracker, show, 1), True))
    run(tracker.set_season_score(show, season_id(tracker, show, 1), 27))
    run(tracker.set_title_score(show, 30))

    text = card_text(tracker, show)

    assert "Оценка: 10" in text.split("\n") and "среднее" not in text


def test_a_series_with_marks_but_no_scores_has_no_line(tracker):
    show = run(tracker.add_title("series", "10")).title_id
    run(tracker.set_season_watched(show, season_id(tracker, show, 1), True))

    assert "Оценка" not in card_text(tracker, show)


def test_the_bot_has_no_way_to_set_a_score():
    import inspect

    from app.bot import tracker_handlers

    source = inspect.getsource(tracker_handlers)

    assert "set_title_score" not in source and "set_season_score" not in source


# ---- KI-26: the cause of a failed source is in the log of the bot --------------------------------------------

def dispatcher(tracker):
    dp = Dispatcher()
    dp.update.outer_middleware(AccessMiddleware([OWNER]))
    register_tracker_handlers(dp, tracker, [OWNER])
    return dp


def user():
    return User(id=OWNER, is_bot=False, first_name="x")


def message(text):
    return Message(message_id=1, date=0, chat=Chat(id=OWNER, type="private"), from_user=user(), text=text)


def feed(dp, **update):
    run(dp.feed_update(Bot(token="123456:TEST"), Update(update_id=1, **update)))


@pytest.fixture
def telegram(monkeypatch):
    sent = []

    async def answer(self, text=None, **kwargs):
        sent.append(text)

    async def callback_answer(self, text=None, **kwargs):
        pass

    monkeypatch.setattr(Message, "answer", answer)
    monkeypatch.setattr(CallbackQuery, "answer", callback_answer)
    return sent


def test_a_failed_search_logs_the_cause_and_tells_the_owner_the_source(tracker, movies, telegram, caplog):
    movies.failing = True
    dp = dispatcher(tracker)
    callback = CallbackQuery(id="1", from_user=user(), chat_instance="c", data="tadd:movie", message=message("m"))
    feed(dp, callback_query=callback)

    feed(dp, message=message("Дюна"))

    assert telegram[-1] == "Не удалось связаться с TMDb. Попробуйте чуть позже."
    assert any("title search failed" in r.getMessage() and "tmdb is down" in r.getMessage() for r in caplog.records)


def test_a_failed_add_logs_the_cause(tracker, movies, telegram, caplog):
    movies.failing = True
    callback = CallbackQuery(id="1", from_user=user(), chat_instance="c", data="tpick:movie:1", message=message("m"))

    feed(dispatcher(tracker), callback_query=callback)

    assert any("adding a title failed" in r.getMessage() and "tmdb is down" in r.getMessage() for r in caplog.records)
