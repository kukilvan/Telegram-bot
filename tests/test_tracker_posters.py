"""Tracker core: the poll keeps the poster of a title up to date (a source may move its pictures).

A check of the title's own source writes the poster of the fresh answer when it is not empty and differs from the
stored one; an empty answer leaves the stored poster; the check of sequels never touches it. Driven through the
facade only: fake clock, fake sources, the real Shikimori adapter over the saved answers, in-memory SQLite.
"""

import asyncio
import dataclasses
from datetime import date, datetime, timedelta, timezone

import pytest

from anime_fakes import FakeAniList, FakeShikimori
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import Title
from app.tracker.seasons import Episode, Season
from app.tracker.sources.shikimori_anime import ShikimoriAnimeSource
from app.tracker.sources.tmdb_movies import MovieSnapshot
from app.tracker.sources.tmdb_sequels import SequelSnapshot
from app.tracker.sources.tmdb_series import SeriesSnapshot

T0 = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
JJK = "40748"
JJK_POSTER = "https://shikimori.io/uploads/poster/animes/40748/af4f2db18f17de4d7c6491f6f92cd9d9.jpeg"
NEW_ADDRESS = "https://shikimori.example/uploads/poster/animes/40748/new.jpeg"


class FakeClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, **delta):
        self.now += timedelta(**delta)


class FakeSender:
    async def send(self, message, actions=()):
        pass


class Source:
    """A source that gives the snapshots it is told to, or the real adapter's snapshot with another poster."""

    def __init__(self, source_key, snapshot=None, real=None):
        self.source_key = source_key
        self.snapshot_now = snapshot
        self.real = real
        self.poster = ...  # Ellipsis: leave what the snapshot has

    async def suggest(self, query):
        return []

    async def snapshot(self, external_id):
        snapshot = self.snapshot_now if self.real is None else await self.real.snapshot(external_id)
        return snapshot if self.poster is ... else dataclasses.replace(snapshot, poster_path=self.poster)


class FakeSequels:
    source_key = "tmdb_sequels"

    async def snapshot(self, external_id):
        return SequelSnapshot(own_date=date(2021, 9, 15), parts=[])


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def clock():
    return FakeClock(T0)


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


def tracker_of(session_factory, clock, **sources):
    return Tracker(session_factory, clock=clock, sender=FakeSender(), **sources)


def poster_of(session_factory, title_id):
    with session_factory() as session:
        return session.get(Title, title_id).poster_path


def poll_later(tracker, clock):
    clock.advance(days=60)
    run(tracker.poll_due())


def movie_snapshot(poster):
    return MovieSnapshot(external_id="1", name="Дюна", original_name="Dune", year=2021, poster_path=poster)


def series_snapshot(poster):
    episodes = tuple(Episode(n, datetime(2026, 10, n * 7)) for n in (1, 2, 3))
    return SeriesSnapshot(
        external_id="1", name="Сериал", original_name="Show", year=2026, seasons=[Season(1, "Сезон 1", 3, episodes)],
        status="Returning Series", poster_path=poster,
    )


# --- the kinds with an own source: movie, series, anime ---------------------------------------------


@pytest.fixture(params=["movie", "series", "anime"])
def case(request, session_factory, clock):
    """A tracker with one title of the kind, its source, and the poster the title starts with."""
    kind = request.param
    if kind == "movie":
        source = Source("tmdb_movie", movie_snapshot("/old.jpg"))
        start, new = "/old.jpg", "/new.jpg"
    elif kind == "series":
        source = Source("tmdb_tv", series_snapshot("/old.jpg"))
        start, new = "/old.jpg", "/new.jpg"
    else:
        source = Source("shikimori", real=ShikimoriAnimeSource(FakeShikimori(), FakeAniList()))
        start, new = JJK_POSTER, NEW_ADDRESS
    tracker = tracker_of(session_factory, clock, sources={kind: source})
    title_id = run(tracker.add_title(kind, JJK if kind == "anime" else "1")).title_id
    return tracker, source, title_id, start, new


def test_a_new_poster_of_the_source_replaces_the_stored_one(case, session_factory, clock):
    tracker, source, title_id, start, new = case
    assert poster_of(session_factory, title_id) == start
    source.poster = new

    poll_later(tracker, clock)

    assert poster_of(session_factory, title_id) == new


@pytest.mark.parametrize("empty", [None, ""])
def test_an_empty_poster_of_the_source_does_not_wipe_the_stored_one(case, session_factory, clock, empty):
    tracker, source, title_id, start, _ = case
    source.poster = empty

    poll_later(tracker, clock)

    assert poster_of(session_factory, title_id) == start


def test_the_same_poster_stays_as_it_is(case, session_factory, clock):
    tracker, _, title_id, start, _ = case

    poll_later(tracker, clock)

    assert poster_of(session_factory, title_id) == start


# --- the check of sequels leaves the poster alone ---------------------------------------------------


def test_the_check_of_sequels_does_not_touch_the_poster(session_factory, clock):
    movies = Source("tmdb_movie", movie_snapshot("/old.jpg"))
    tracker = tracker_of(session_factory, clock, sources={"movie": movies}, sequel_sources={"movie": FakeSequels()})
    title_id = run(tracker.add_title("movie", "1")).title_id
    run(tracker.mark_watched(title_id))
    movies.snapshot_now = movie_snapshot("/new.jpg")  # the movie's own source is no longer asked for an archived title

    run(tracker.poll_due())  # the first look at the collection
    poll_later(tracker, clock)  # and a weekly one

    assert poster_of(session_factory, title_id) == "/old.jpg"
