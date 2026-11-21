"""Polling rules of spec 4.1 and 4.2 of stage 9.1a, piece by piece: whether a check still runs (`checks.still_checked`,
KI-22), an event of a check no longer running is not queued and spends no dedup key, the moment each event says its
fact came out (`happened_at`) and the first check after «Вернуть в список» that queues only what came out after it
(KI-23). The whole way through the facade is in `test_tracker_dropped_restore.py`.
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.tracker import anime_events, game_events, movie_events, series_events
from app.tracker.checks import still_checked
from app.tracker.context import CoreContext
from app.tracker.db import create_session_factory
from app.tracker.games import GameDate, GameState, Release
from app.tracker.models import Event, ExternalId, SourceSnapshot, Title, TitleKind, TitleStatus
from app.tracker.movie_events import DetectedEvent, MovieDates, day_start
from app.tracker.platforms import WORLD, Platform
from app.tracker.pollers.base import DueTitle, Poller
from app.tracker.queue import EventQueue
from app.tracker.seasons import Episode, Season
from app.tracker.sources.shikimori_anime import SourceIds

NOW = datetime(2026, 11, 20, 12, 0)


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


def make_title(session_factory, *, kind="movie", status=TitleStatus.WANT, tracking=True, snapshots=("tmdb_movie",),
               primary="tmdb_movie"):
    with session_factory() as session:
        title = Title(
            kind=kind, name="Дюна", original_name="Dune", year=2021, genres=[], status=status, tracking_enabled=tracking,
            added_at=NOW, status_changed_at=NOW,
        )
        session.add(title)
        session.flush()
        session.add(ExternalId(title_id=title.id, source=primary, external_id="1", role="primary"))
        for source in snapshots:
            session.add(SourceSnapshot(title_id=title.id, source=source, state={}, observed_at=NOW, next_check_at=NOW))
        session.commit()
        return title.id


def due_of(title_id, source="tmdb_movie", sequels=False, kind=TitleKind.MOVIE):
    return DueTitle(title_id, kind, "Дюна", "1", source, sequels)


def checked(session_factory, due):
    with session_factory() as session:
        return still_checked(session, due)


# --- 4.1: whether a check still runs ---------------------------------------------------------------------------------


def test_a_title_that_is_gone_is_not_checked(session_factory):
    assert not checked(session_factory, due_of(999))


def test_a_check_whose_snapshot_is_gone_is_not_checked(session_factory):
    title_id = make_title(session_factory, status=TitleStatus.WATCHED, snapshots=("tmdb_movie",))

    assert not checked(session_factory, due_of(title_id, "tmdb_sequels", sequels=True))


@pytest.mark.parametrize("status, expected", [(TitleStatus.WATCHED, True), (TitleStatus.WANT, False), (TitleStatus.DROPPED, False)])
def test_a_sequel_check_runs_only_for_a_watched_title(session_factory, status, expected):
    title_id = make_title(session_factory, status=status, snapshots=("tmdb_movie", "tmdb_sequels"))

    assert checked(session_factory, due_of(title_id, "tmdb_sequels", sequels=True)) is expected


@pytest.mark.parametrize(
    "status, tracking, expected",
    [
        (TitleStatus.WANT, True, True),
        (TitleStatus.IN_PROGRESS, True, True),
        (TitleStatus.WAITING, True, True),
        (TitleStatus.DROPPED, True, False),
        (TitleStatus.WATCHED, True, False),
        (TitleStatus.WANT, False, False),
    ],
)
def test_an_own_release_check_runs_for_a_polled_status_with_tracking_on(session_factory, status, tracking, expected):
    title_id = make_title(session_factory, status=status, tracking=tracking)

    assert checked(session_factory, due_of(title_id)) is expected


@pytest.mark.parametrize("status", [TitleStatus.WANT, TitleStatus.COMPLETED, TitleStatus.DROPPED])
def test_a_check_at_the_end_of_a_pass_needs_only_its_snapshot(session_factory, status):
    title_id = make_title(session_factory, kind="game", status=status, snapshots=("igdb", "steam"), primary="igdb")

    assert checked(session_factory, due_of(title_id, "steam", kind=TitleKind.GAME))
    assert not checked(session_factory, due_of(title_id, "igdb_follow_ups", kind=TitleKind.GAME))


def test_an_event_of_a_check_that_no_longer_runs_is_not_queued_and_spends_no_dedup_key(session_factory):
    title_id = make_title(session_factory, status=TitleStatus.DROPPED)
    queue = EventQueue(CoreContext(session_factory, lambda: NOW.replace(tzinfo=timezone.utc), None, timezone.utc))
    due = due_of(title_id)

    assert queue.record("movie_released", {"text": "вышел"}, "movie:1:released", title_id, due=due) is None
    with session_factory() as session:
        assert session.scalars(select(Event)).all() == []
        session.get(Title, title_id).status = TitleStatus.WANT
        session.commit()
    assert queue.record("movie_released", {"text": "вышел"}, "movie:1:released", title_id, due=due) is not None


# --- 4.2: the moment of each event -----------------------------------------------------------------------------------


def test_a_movie_release_carries_its_day():
    old = MovieDates()
    new = MovieDates(theatrical=date(2026, 11, 19), digital=date(2026, 11, 20))

    events = {e.type: e for e in movie_events.detect_events(1, "Дюна", old, new, NOW - timedelta(days=5), NOW.date())}

    assert events[movie_events.RELEASED].happened_at == datetime(2026, 11, 19)
    assert events[movie_events.DIGITAL].happened_at == datetime(2026, 11, 20)


def test_a_movie_date_announced_or_moved_has_no_moment():
    announced = movie_events.detect_events(1, "Дюна", MovieDates(), MovieDates(date(2027, 1, 1)), NOW, NOW.date())
    moved = movie_events.detect_events(
        1, "Дюна", MovieDates(date(2027, 1, 1)), MovieDates(date(2027, 2, 1)), NOW, NOW.date()
    )

    assert [e.happened_at for e in announced + moved] == [None, None]


def weekly(first, count):
    return tuple(Episode(n + 1, first + timedelta(weeks=n)) for n in range(count))


def test_series_events_carry_the_day_of_their_episode():
    first = datetime(2026, 11, 2)
    old = series_events.ShowState.of([Season(1, "Сезон 1", 3, weekly(first, 3))], {})
    new = old

    events = series_events.detect_events(1, "Сериал", old, new, first - timedelta(days=1), first + timedelta(weeks=3))

    moments = {(e.type, e.data.get("episode")): e.happened_at for e in events}
    assert moments == {
        (series_events.SEASON_STARTED, 1): datetime(2026, 11, 2),
        (series_events.EPISODE_OUT, 2): datetime(2026, 11, 9),
        (series_events.SEASON_ENDED, 3): datetime(2026, 11, 16),
    }


def test_a_season_date_announced_has_no_moment():
    old = series_events.ShowState.of([], {})
    new = series_events.ShowState.of([Season(1, "Сезон 1", 3, weekly(datetime(2027, 1, 4), 3))], {})

    (event,) = series_events.detect_events(1, "Сериал", old, new, NOW, NOW)

    assert event.type == series_events.DATE_ANNOUNCED and event.happened_at is None


def test_the_episode_events_of_an_anime_have_no_moment():
    first = datetime(2026, 11, 2, 15, 30)
    old = series_events.ShowState.of([Season(1, "Сезон 1", 3, weekly(first, 3))], {})

    events = series_events.detect_events(
        1, "Аниме", old, old, first - timedelta(days=1), first + timedelta(weeks=3), flavor=anime_events.flavor(None)
    )

    assert events and all(e.happened_at is None for e in events)


class Film:
    def __init__(self, sid, aired_on, released):
        self.ids = SourceIds(sid, None)
        self.name = "Фильм"
        self.aired_on = aired_on
        self.released = released


def test_an_anime_film_out_carries_its_day_and_an_announced_one_none():
    films = [Film("1", date(2026, 11, 19), True), Film("2", date(2027, 5, 1), False)]

    events = {e.type: e for e in anime_events.detect_movie_events(1, "Аниме", {"1": False}, films, date(2026, 11, 1))}

    assert events[anime_events.MOVIE_RELEASED].happened_at == datetime(2026, 11, 19)
    assert events[anime_events.MOVIE_ANNOUNCED].happened_at is None


PC = 6  # IGDB's platform id


def game(*releases):
    """Releases as (kind, date text) on PC, worldwide."""
    records = tuple(Release(platform=PC, region=WORLD, type=kind, date=GameDate.parse(text)) for kind, text in releases)
    return GameState(platforms=(PC,), releases=records)


@pytest.mark.parametrize(
    "kind, text, expected_type", [("full", "2026-11-19", game_events.RELEASED), ("early", "2026-11-18", game_events.EARLY_ACCESS)]
)
def test_a_game_release_and_an_early_access_carry_the_day_of_the_platform(kind, text, expected_type):
    [event] = game_events.detect_events(
        1, "Hades II", game(), game((kind, text)), "il", tuple(Platform), NOW - timedelta(days=5), NOW.date(), NOW.date()
    )

    assert (event.type, event.happened_at) == (expected_type, day_start(date.fromisoformat(text)))


def test_a_game_date_announced_has_no_moment():
    [event] = game_events.detect_events(
        1, "Hades II", game(), game(("full", "2027-03-12")), "il", tuple(Platform), NOW - timedelta(days=5), NOW.date(), NOW.date()
    )

    assert event.type == game_events.DATE_ANNOUNCED and event.happened_at is None


# --- 4.2: the first check after «Вернуть в список» -------------------------------------------------------------------


class StubQueue:
    def __init__(self):
        self.recorded = []

    def queued_since(self, key, since):
        return False

    def record(self, type, payload, dedup_key, title_id=None, at=None, due=None):
        self.recorded.append(dedup_key)
        return len(self.recorded)


RESTORED = datetime(2026, 10, 25, 23, 59, 30)


def event(key, happened_at):
    return DetectedEvent("series_episode_out", key, "вышла серия", {}, happened_at=happened_at)


@pytest.mark.parametrize("baseline, queued", [(True, ["after"]), (False, ["before", "after", "none"])])
def test_the_first_check_after_the_return_queues_only_what_came_out_after_it(baseline, queued):
    queue = StubQueue()
    poller = Poller(TitleKind.SERIES, None, None, None, queue)
    due = DueTitle(1, TitleKind.SERIES, "Сериал", "10", "tmdb_tv", False, baseline, RESTORED)
    events = [
        event("before", datetime(2026, 10, 25)),  # aired the day of the return, before it
        event("after", datetime(2026, 10, 26)),  # the 23:59:30 / 00:00 example of KI-23
        event("none", None),  # no moment: the reference point
    ]

    assert poller.record_all(due, events) == len(queued)
    assert queue.recorded == queued
