"""Tracker core: the sequels of a watched movie as the web card shows them — whether the collection was looked at, the
sequels found there by date, and which of them the list already has. The pure function and the card through the facade."""

import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest

from app.tracker import cards
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.sequel_events import Part, Sequels
from app.tracker.sources.tmdb_movies import MovieSnapshot
from app.tracker.sources.tmdb_sequels import CollectionPart, SequelSnapshot

T0 = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
OWN = date(2021, 9, 15)
DUNE = MovieSnapshot(external_id="1", name="Дюна", original_name="Dune", year=2021, genres=[])
PART_TWO = MovieSnapshot(external_id="2", name="Дюна: Часть вторая", original_name="Dune: Part Two", year=2024, genres=[])
OLDER = CollectionPart("0", "Дюна (1984)", date(1984, 12, 14))
TWO = CollectionPart("2", "Дюна: Часть вторая", date(2024, 2, 27))
THREE = CollectionPart("3", "Дюна: Часть третья", date(2028, 12, 15))
FOUR = CollectionPart("4", "Дюна: Часть четвёртая", None)


class FakeClock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


class FakeSender:
    async def send(self, message, actions=()):
        pass


class FakeMovieSource:
    source_key = "tmdb_movie"
    by_id = {s.external_id: s for s in (DUNE, PART_TWO)}

    async def suggest(self, query):
        return []

    async def snapshot(self, external_id):
        return self.by_id.get(external_id)


class FakeSequelSource:
    source_key = "tmdb_sequels"

    def __init__(self):
        self.parts = []

    async def snapshot(self, external_id):
        return SequelSnapshot(own_date=OWN, parts=list(self.parts))


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def sequels():
    return FakeSequelSource()


@pytest.fixture
def tracker(clock, sequels):
    return Tracker(
        create_session_factory("sqlite://"), clock=clock, sender=FakeSender(),
        sources={"movie": FakeMovieSource()}, sequel_sources={"movie": sequels},
    )


def add(tracker, external_id="1"):
    return run(tracker.add_title("movie", external_id)).title_id


# ---- the pure function -----------------------------------------------------------------------------------------

def test_the_sequels_come_by_date_with_the_undated_last_and_the_earlier_films_left_out():
    parts = (Part("4", "Четвёртая", None), Part("3", "Третья", date(2028, 12, 15)), Part("0", "Старая", date(1984, 1, 1)),
             Part("2", "Вторая", date(2024, 2, 27)))

    view = cards.sequel_view(Sequels(OWN, parts), True, {})

    assert view.checked is True
    assert [(line.external_id, line.date) for line in view.lines] == [
        ("2", date(2024, 2, 27)), ("3", date(2028, 12, 15)), ("4", None),
    ]


def test_a_sequel_in_the_list_carries_the_number_of_its_title():
    view = cards.sequel_view(Sequels(OWN, (Part("2", "Вторая", date(2024, 2, 27)), Part("3", "Третья", None))), True, {"2": 7})

    assert [(line.name, line.title_id) for line in view.lines] == [("Вторая", 7), ("Третья", None)]


def test_a_collection_not_looked_at_yet_has_no_lines():
    assert cards.sequel_view(Sequels(), False, {}) == cards.SequelsView(False, ())


# ---- the card through the facade -------------------------------------------------------------------------------

def test_a_wanted_or_a_dropped_movie_has_no_sequels_on_its_card(tracker):
    film = add(tracker)
    assert run(tracker.title_card(film)).sequels is None

    run(tracker.mark_dropped(film))
    assert run(tracker.title_card(film)).sequels is None


def test_right_after_watched_the_collection_is_not_looked_at_yet(tracker):
    film = add(tracker)
    run(tracker.mark_watched(film))

    assert run(tracker.title_card(film)).sequels == cards.SequelsView(False, ())


def test_a_collection_with_no_later_films_is_checked_and_empty(tracker, sequels):
    film = add(tracker)
    sequels.parts = [OLDER]
    run(tracker.mark_watched(film))
    run(tracker.poll_due())

    assert run(tracker.title_card(film)).sequels == cards.SequelsView(True, ())


def test_the_sequels_found_are_listed_and_the_one_already_followed_is_marked(tracker, sequels):
    film = add(tracker)
    followed = add(tracker, "2")
    sequels.parts = [FOUR, THREE, OLDER, TWO]
    run(tracker.mark_watched(film))
    run(tracker.poll_due())

    view = run(tracker.title_card(film)).sequels

    assert view.checked is True
    assert [(line.name, line.date, line.title_id) for line in view.lines] == [
        ("Дюна: Часть вторая", date(2024, 2, 27), followed),
        ("Дюна: Часть третья", date(2028, 12, 15), None),
        ("Дюна: Часть четвёртая", None, None),
    ]


def test_following_a_sequel_marks_it_in_the_list_on_the_next_card(tracker, sequels):
    film = add(tracker)
    sequels.parts = [TWO]
    run(tracker.mark_watched(film))
    run(tracker.poll_due())

    result = run(tracker.follow_sequel_of("movie", "2"))

    assert run(tracker.title_card(film)).sequels.lines[0].title_id == result.title_id


def test_a_movie_brought_back_has_no_sequels_any_more(tracker, sequels, clock):
    film = add(tracker)
    sequels.parts = [THREE]
    run(tracker.mark_watched(film))
    run(tracker.poll_due())
    clock.now += timedelta(days=1)

    run(tracker.restore_title(film))

    assert run(tracker.title_card(film)).sequels is None
