"""Tracker core: a series changes its own status as seasons are marked and as the source reports.

Driven through the facade only: fake clock, fake series source, fake sender, in-memory SQLite. Seasons are
built by hand. The rule is shared with anime (ticket 10), so nothing here depends on TMDb.
"""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.tracker.cards import format_card
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import Event, Title
from app.tracker.seasons import Episode, Season
from app.tracker.sources.tmdb_series import SeriesSnapshot

T0 = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)  # a Saturday


class FakeClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, **delta):
        self.now += timedelta(**delta)


class FakeSender:
    def __init__(self):
        self.sent = []

    async def send(self, message, actions=()):
        self.sent.append(message)


class FakeSeriesSource:
    source_key = "tmdb_tv"

    def __init__(self):
        self.by_id = {}
        self.snapshot_calls = 0

    def update(self, snapshot):
        self.by_id[snapshot.external_id] = snapshot

    async def suggest(self, query):
        return []

    async def snapshot(self, external_id):
        self.snapshot_calls += 1
        return self.by_id.get(external_id)


def weekly(first_day, count):
    start = datetime.fromisoformat(first_day)
    return tuple(Episode(n + 1, start + timedelta(weeks=n)) for n in range(count))


def season(number, first_day, count=6):
    return Season(number, f"Сезон {number}", count, weekly(first_day, count) if first_day else ())


def show(external_id, *seasons, status="Returning Series"):
    return SeriesSnapshot(
        external_id=external_id, name=f"Сериал {external_id}", original_name=f"Сериал {external_id}",
        year=2026, genres=[], seasons=list(seasons), status=status,
    )


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def clock():
    return FakeClock(T0)


@pytest.fixture
def sender():
    return FakeSender()


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def source():
    return FakeSeriesSource()


@pytest.fixture
def tracker(session_factory, clock, sender, source):
    return Tracker(session_factory, clock=clock, sender=sender, sources={"series": source})


def add(tracker, source, snapshot):
    source.update(snapshot)
    return run(tracker.add_title("series", snapshot.external_id)).title_id


def mark(tracker, title_id, *numbers, watched=True):
    for number in numbers:
        run(tracker.set_season_watched(title_id, number, watched))


def status(tracker, title_id):
    return next(t.status for t in run(tracker.list_titles()) if t.id == title_id)


def tracking(session_factory, title_id):
    with session_factory() as s:
        return s.get(Title, title_id).tracking_enabled


def poll(tracker, clock, **advance):
    clock.advance(**advance)
    report = run(tracker.poll_due())
    run(tracker.deliver_pending())
    return report


# two seasons that are out (Mar and Jun 2026) and a third one that is announced for next year
OPEN = show("1", season(1, "2026-03-02"), season(2, "2026-06-01"), season(3, "2027-03-01"))
# the same two seasons, and the source says the show is over
ENDED = show("2", season(1, "2026-03-02"), season(2, "2026-06-01"), status="Ended")
CANCELED = show("3", season(1, "2026-03-02"), season(2, "2026-06-01"), status="Canceled")


# --- «Жду» ---------------------------------------------------------------------------------------


def test_everything_released_is_watched_and_a_season_is_expected_so_the_status_is_waiting(tracker, source, session_factory):
    title_id = add(tracker, source, OPEN)

    mark(tracker, title_id, 1, 2)

    assert status(tracker, title_id) == "waiting"
    assert tracking(session_factory, title_id) is True


def test_a_series_with_nothing_marked_stays_want(tracker, source, session_factory):
    title_id = add(tracker, source, OPEN)

    assert status(tracker, title_id) == "want"
    assert tracking(session_factory, title_id) is True


def test_an_airing_series_with_some_released_seasons_marked_is_in_progress_and_followed(tracker, source, session_factory):
    title_id = add(tracker, source, OPEN)

    mark(tracker, title_id, 1)

    assert status(tracker, title_id) == "in_progress"
    assert tracking(session_factory, title_id) is True


def test_taking_a_mark_off_returns_waiting_to_in_progress(tracker, source):
    title_id = add(tracker, source, OPEN)
    mark(tracker, title_id, 1, 2)

    mark(tracker, title_id, 2, watched=False)

    assert status(tracker, title_id) == "in_progress"


def test_taking_every_mark_off_returns_in_progress_to_want(tracker, source, session_factory):
    title_id = add(tracker, source, OPEN)
    mark(tracker, title_id, 1)

    mark(tracker, title_id, 1, watched=False)

    assert status(tracker, title_id) == "want"
    assert tracking(session_factory, title_id) is True


def test_marking_every_released_season_of_an_in_progress_series_makes_it_waiting(tracker, source):
    title_id = add(tracker, source, OPEN)
    mark(tracker, title_id, 1)

    mark(tracker, title_id, 2)

    assert status(tracker, title_id) == "waiting"


def test_a_series_with_nothing_released_yet_is_not_waiting(tracker, source):
    title_id = add(tracker, source, show("4", season(1, "2027-03-01")))

    assert status(tracker, title_id) == "want"


def test_a_waiting_series_is_still_polled(tracker, source, clock):
    title_id = add(tracker, source, OPEN)
    mark(tracker, title_id, 1, 2)
    calls = source.snapshot_calls

    report = poll(tracker, clock, days=2)

    assert report.polled == 1
    assert source.snapshot_calls == calls + 1


def test_an_in_progress_series_is_still_polled_and_a_new_episode_arrives_as_an_event(tracker, source, clock, sender):
    title_id = add(tracker, source, show("9", season(1, "2026-03-02"), season(2, "2026-06-01", count=30)))
    mark(tracker, title_id, 1)
    assert status(tracker, title_id) == "in_progress"
    calls = source.snapshot_calls

    poll(tracker, clock, hours=52)  # Mon 26 Oct, 16:00: past the summary hour, so the event goes out at once

    assert source.snapshot_calls == calls + 1
    assert any("вышла серия 22" in message for message in sender.sent)


def test_a_new_season_that_starts_airing_takes_a_waiting_series_to_in_progress(tracker, source, clock):
    title_id = add(tracker, source, show("5", season(1, "2026-03-02"), season(2, "2026-11-02")))
    mark(tracker, title_id, 1)
    assert status(tracker, title_id) == "waiting"

    poll(tracker, clock, days=9)  # Mon 2 Nov: the first episode of season 2 is out

    assert status(tracker, title_id) == "in_progress"


# --- «Просмотрено» -------------------------------------------------------------------------------


@pytest.mark.parametrize("closed", [ENDED, CANCELED])
def test_a_closed_series_with_every_season_watched_is_watched_and_no_longer_followed(tracker, source, session_factory, closed):
    title_id = add(tracker, source, closed)

    mark(tracker, title_id, 1, 2)

    assert status(tracker, title_id) == "watched"
    assert tracking(session_factory, title_id) is False


def test_a_watched_series_is_not_polled(tracker, source, clock):
    title_id = add(tracker, source, ENDED)
    mark(tracker, title_id, 1, 2)
    calls = source.snapshot_calls

    report = poll(tracker, clock, days=30)

    assert report.polled == 0
    assert source.snapshot_calls == calls


def test_the_source_closing_a_waiting_series_whose_seasons_are_all_watched_archives_it(tracker, source, clock, session_factory):
    title_id = add(tracker, source, show("6", season(1, "2026-03-02"), season(2, "2026-06-01")))
    mark(tracker, title_id, 1, 2)
    assert status(tracker, title_id) == "waiting"

    source.update(show("6", season(1, "2026-03-02"), season(2, "2026-06-01"), status="Ended"))
    poll(tracker, clock, days=8)

    assert status(tracker, title_id) == "watched"
    assert tracking(session_factory, title_id) is False


# --- «Досмотреть» --------------------------------------------------------------------------------


def test_a_closed_series_with_a_season_unwatched_is_to_finish_and_no_longer_followed(tracker, source, session_factory):
    title_id = add(tracker, source, ENDED)

    mark(tracker, title_id, 1)

    assert status(tracker, title_id) == "to_finish"
    assert tracking(session_factory, title_id) is False


def test_a_closed_series_with_nothing_marked_stays_want_and_is_still_checked(tracker, source, session_factory):
    title_id = add(tracker, source, CANCELED)

    assert status(tracker, title_id) == "want"
    assert tracking(session_factory, title_id) is True


def test_taking_the_only_mark_off_a_series_to_finish_returns_it_to_want_and_follows_it_again(tracker, source, session_factory):
    title_id = add(tracker, source, ENDED)
    mark(tracker, title_id, 1)
    assert tracking(session_factory, title_id) is False

    mark(tracker, title_id, 1, watched=False)

    assert status(tracker, title_id) == "want"
    assert tracking(session_factory, title_id) is True


def test_the_source_closing_a_series_with_unwatched_seasons_makes_it_to_finish(tracker, source, clock, session_factory):
    title_id = add(tracker, source, show("7", season(1, "2026-03-02"), season(2, "2026-06-01")))
    mark(tracker, title_id, 1)

    source.update(show("7", season(1, "2026-03-02"), season(2, "2026-06-01"), status="Canceled"))
    poll(tracker, clock, days=8)

    assert status(tracker, title_id) == "to_finish"
    assert tracking(session_factory, title_id) is False


def test_a_series_to_finish_becomes_watched_once_the_last_season_is_marked(tracker, source, session_factory):
    title_id = add(tracker, source, ENDED)
    mark(tracker, title_id, 1)

    mark(tracker, title_id, 2)

    assert status(tracker, title_id) == "watched"
    assert tracking(session_factory, title_id) is False


def test_unmarking_a_season_of_a_watched_series_takes_it_out_of_the_archive_but_does_not_follow_it_again(tracker, source, session_factory):
    title_id = add(tracker, source, ENDED)
    mark(tracker, title_id, 1, 2)

    mark(tracker, title_id, 1, watched=False)

    assert status(tracker, title_id) == "to_finish"
    assert tracking(session_factory, title_id) is False


# --- what the owner sees -------------------------------------------------------------------------


def test_the_closing_event_still_arrives_and_the_card_shows_the_new_status(tracker, source, clock, sender):
    title_id = add(tracker, source, show("8", season(1, "2026-03-02")))
    mark(tracker, title_id, 1)

    source.update(show("8", season(1, "2026-03-02"), status="Ended"))
    poll(tracker, clock, days=8)

    assert any("сериал закрыт" in message for message in sender.sent)
    assert format_card(run(tracker.title_card(title_id))).splitlines()[0] == "📺 Сериал · Просмотрено"


@pytest.mark.parametrize(
    ("raw", "label"),
    [("waiting", "Жду"), ("in_progress", "В процессе"), ("to_finish", "Досмотреть"), ("watched", "Просмотрено"), ("want", "Хочу")],
)
def test_the_card_names_every_status_in_russian(tracker, source, raw, label):
    title_id = add(tracker, source, OPEN)
    card = run(tracker.title_card(title_id))

    assert format_card(replace(card, status=raw)).splitlines()[0] == f"📺 Сериал · {label}"


def test_the_status_time_changes_only_when_the_status_does(tracker, source, clock, session_factory):
    title_id = add(tracker, source, OPEN)
    with session_factory() as s:
        added = s.get(Title, title_id).status_changed_at

    clock.advance(hours=1)
    mark(tracker, title_id, 1)  # «В процессе»
    with session_factory() as s:
        assert s.get(Title, title_id).status_changed_at == added + timedelta(hours=1)

    clock.advance(hours=1)
    mark(tracker, title_id, 1)  # the same mark again: still «В процессе»
    with session_factory() as s:
        assert s.get(Title, title_id).status_changed_at == added + timedelta(hours=1)

    clock.advance(hours=1)
    mark(tracker, title_id, 2)  # «Жду»
    with session_factory() as s:
        assert s.get(Title, title_id).status_changed_at == added + timedelta(hours=3)


def test_marking_a_season_creates_no_event(tracker, source, session_factory):
    title_id = add(tracker, source, ENDED)

    mark(tracker, title_id, 1, 2)

    with session_factory() as s:
        assert list(s.scalars(select(Event))) == []
