"""Tracker core: adding a movie and reading its state back (search, add, list, card).

Driven through the facade only: fake clock, fake movie source, in-memory SQLite.
"""

import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.tracker.cards import format_card
from app.tracker.core import Tracker, TitleNotFound
from app.tracker.db import create_session_factory
from app.tracker.models import ExternalId, SourceSnapshot, Title
from app.tracker.sources.tmdb_movies import MovieSnapshot, Suggestion

T0 = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class FakeSender:
    async def send(self, message, actions=()):
        pass


DUNE_2 = MovieSnapshot(
    external_id="693134",
    title="Дюна: Часть вторая",
    original_title="Dune: Part Two",
    year=2024,
    genres=["фантастика", "приключения"],
    poster_path="/p.jpg",
    overview="Пол Атрейдес...",
    theatrical_date=date(2024, 2, 27),
    digital_date=date(2024, 4, 15),
)
DUNE_3 = MovieSnapshot(
    external_id="1170608",
    title="Дюна: Часть третья",
    original_title="Dune: Part Three",
    year=2026,
    genres=["фантастика"],
    theatrical_date=date(2026, 12, 16),
    digital_date=None,
)
NOT_ANNOUNCED = MovieSnapshot(
    external_id="77", title="Безымянный", original_title="Безымянный", year=None, genres=[]
)


class FakeMovieSource:
    source_key = "tmdb_movie"

    def __init__(self, *snapshots):
        self.by_id = {s.external_id: s for s in snapshots}
        self.snapshot_calls = 0
        self.failing = False

    async def suggest(self, query):
        return [Suggestion("movie", s.external_id, s.title, s.original_title, s.year) for s in self.by_id.values()]

    async def snapshot(self, external_id):
        self.snapshot_calls += 1
        if self.failing:
            raise ConnectionError("tmdb is down")
        return self.by_id.get(external_id)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def clock():
    return FakeClock(T0)


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def movies():
    return FakeMovieSource(DUNE_2, DUNE_3, NOT_ANNOUNCED)


@pytest.fixture
def tracker(session_factory, clock, movies):
    return Tracker(session_factory, clock=clock, sender=FakeSender(), sources={"movie": movies})


def test_search_returns_suggestions_from_the_source_of_that_kind(tracker):
    suggestions = run(tracker.search("movie", "дюна"))

    assert [s.external_id for s in suggestions] == ["693134", "1170608", "77"]


def test_added_movie_appears_in_the_list_with_status_want(tracker):
    result = run(tracker.add_title("movie", "693134"))

    assert result.created is True
    [entry] = tracker.list_titles()
    assert entry.id == result.title_id
    assert entry.name == "Дюна: Часть вторая"
    assert entry.year == 2024
    assert entry.kind == "movie"
    assert entry.status == "want"


def test_card_has_names_year_genres_and_both_release_dates(tracker):
    result = run(tracker.add_title("movie", "693134"))

    card = tracker.title_card(result.title_id)

    assert card.title == "Дюна: Часть вторая"
    assert card.original_title == "Dune: Part Two"
    assert card.year == 2024
    assert card.genres == ["фантастика", "приключения"]
    assert card.theatrical_date == date(2024, 2, 27)
    assert card.digital_date == date(2024, 4, 15)
    assert card.status == "want"


def test_adding_the_same_movie_again_opens_the_existing_title(tracker, session_factory, movies):
    first = run(tracker.add_title("movie", "693134"))
    second = run(tracker.add_title("movie", "693134"))

    assert second.created is False
    assert second.title_id == first.title_id
    assert movies.snapshot_calls == 1  # a known title is not fetched again
    with session_factory() as s:
        assert len(list(s.scalars(select(Title)))) == 1


def test_two_adds_at_the_same_moment_make_one_title(tracker, session_factory):
    async def both():
        return await asyncio.gather(tracker.add_title("movie", "693134"), tracker.add_title("movie", "693134"))

    first, second = run(both())

    assert first.title_id == second.title_id
    assert sorted([first.created, second.created]) == [False, True]
    with session_factory() as s:
        assert len(list(s.scalars(select(Title)))) == 1


def test_unknown_id_is_reported_and_nothing_is_stored(tracker, session_factory):
    with pytest.raises(TitleNotFound):
        run(tracker.add_title("movie", "1396"))

    assert tracker.list_titles() == []


def test_source_failure_is_not_hidden_and_nothing_is_stored(tracker, movies):
    movies.failing = True

    with pytest.raises(ConnectionError):
        run(tracker.add_title("movie", "693134"))

    assert tracker.list_titles() == []


def test_unknown_kind_is_rejected(tracker):
    with pytest.raises(KeyError):
        run(tracker.add_title("game", "1"))


def test_external_id_is_unique_per_source_in_the_schema(tracker, session_factory):
    run(tracker.add_title("movie", "693134"))

    with session_factory() as s:
        other = Title(
            kind="movie", title="x", original_title="x", genres=[], status="want",
            tracking_enabled=True, added_at=T0.replace(tzinfo=None), status_changed_at=T0.replace(tzinfo=None),
        )
        s.add(other)
        s.flush()
        s.add(ExternalId(title_id=other.id, source="tmdb_movie", external_id="693134", role="primary"))
        with pytest.raises(IntegrityError):
            s.flush()


def test_timestamps_come_from_the_clock_at_insert_time(tracker, session_factory, clock):
    run(tracker.add_title("movie", "693134"))
    clock.now = T0 + timedelta(hours=2)
    run(tracker.add_title("movie", "1170608"))

    with session_factory() as s:
        titles = list(s.scalars(select(Title).order_by(Title.id)))
        snapshots = list(s.scalars(select(SourceSnapshot).order_by(SourceSnapshot.id)))
    assert titles[0].added_at == T0.replace(tzinfo=None)
    assert titles[1].added_at == (T0 + timedelta(hours=2)).replace(tzinfo=None)
    assert titles[1].status_changed_at == titles[1].added_at
    assert snapshots[1].observed_at == titles[1].added_at


def test_the_list_keeps_the_order_titles_were_added(tracker):
    run(tracker.add_title("movie", "1170608"))
    run(tracker.add_title("movie", "693134"))

    assert [t.name for t in tracker.list_titles()] == ["Дюна: Часть третья", "Дюна: Часть вторая"]


def test_missing_title_card_is_none(tracker):
    assert tracker.title_card(999) is None


# --- how a card reads ---------------------------------------------------------------------------


def test_card_text_shows_names_year_genres_and_dates(tracker):
    result = run(tracker.add_title("movie", "693134"))

    text = format_card(tracker.title_card(result.title_id))

    assert "Дюна: Часть вторая" in text
    assert "Dune: Part Two" in text
    assert "2024" in text
    assert "фантастика, приключения" in text
    assert "27 февраля 2024" in text
    assert "15 апреля 2024" in text
    assert "Хочу" in text


def test_card_text_says_not_announced_for_missing_dates(tracker):
    result = run(tracker.add_title("movie", "1170608"))

    text = format_card(tracker.title_card(result.title_id))

    assert "16 декабря 2026" in text
    assert "Цифровой релиз: не объявлена" in text


def test_card_text_for_a_movie_with_no_data_at_all(tracker):
    result = run(tracker.add_title("movie", "77"))

    text = format_card(tracker.title_card(result.title_id))

    assert "Безымянный" in text
    assert "Премьера в кино: не объявлена" in text
    assert "Цифровой релиз: не объявлена" in text
    assert text.count("Безымянный") == 1  # the same name is not printed twice
