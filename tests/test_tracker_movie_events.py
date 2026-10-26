"""Tracker core: movie events found by polling, delivered once, and the poll schedule.

Driven through the facade only: fake clock, fake movie source, fake sender, in-memory SQLite.
"""

import asyncio
import threading
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.tracker import movie_events
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import Event, SourceSnapshot
from app.tracker.sources.tmdb_movies import MovieSnapshot

T0 = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, **delta):
        self.now += timedelta(**delta)

    def set_day(self, day: date):
        self.now = datetime(day.year, day.month, day.day, 12, 0, tzinfo=timezone.utc)


class FakeSender:
    def __init__(self):
        self.sent = []

    async def send(self, message, actions=()):
        self.sent.append(message)


def movie(external_id, name="Дюна: Часть третья", theatrical=None, digital=None):
    return MovieSnapshot(
        external_id=external_id,
        name=name,
        original_name=name,
        year=2026,
        genres=[],
        theatrical_date=theatrical,
        digital_date=digital,
    )


class FakeMovieSource:
    source_key = "tmdb_movie"

    def __init__(self, *snapshots):
        self.by_id = {s.external_id: s for s in snapshots}
        self.failing: set[str] = set()
        self.calls: list[str] = []

    def update(self, snapshot):
        self.by_id[snapshot.external_id] = snapshot

    async def suggest(self, query):
        return []

    async def snapshot(self, external_id):
        self.calls.append(external_id)
        if external_id in self.failing:
            raise ConnectionError("tmdb is down")
        return self.by_id.get(external_id)


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
    return FakeMovieSource()


@pytest.fixture
def tracker(session_factory, clock, sender, source):
    return Tracker(session_factory, clock=clock, sender=sender, sources={"movie": source})


def add(tracker, source, snapshot):
    source.update(snapshot)
    return run(tracker.add_title("movie", snapshot.external_id)).title_id


def poll_and_deliver(tracker, clock, **advance):
    clock.advance(**advance)
    run(tracker.poll_due())
    run(tracker.deliver_pending())


def next_check(session_factory, title_id):
    with session_factory() as s:
        return s.scalar(select(SourceSnapshot.next_check_at).where(SourceSnapshot.title_id == title_id))


# --- the four movie events -----------------------------------------------------------------------


def test_announced_premiere_date_is_delivered_once(tracker, source, clock, sender):
    add(tracker, source, movie("1"))
    source.update(movie("1", theatrical=date(2026, 12, 16)))

    poll_and_deliver(tracker, clock, days=2)
    poll_and_deliver(tracker, clock, days=2)

    [message] = sender.sent
    assert "Дюна: Часть третья" in message
    assert "объявлена дата премьеры" in message
    assert "16 декабря 2026" in message


def test_moved_premiere_shows_old_and_new_date(tracker, source, clock, sender):
    add(tracker, source, movie("1", theatrical=date(2026, 12, 15)))
    source.update(movie("1", theatrical=date(2027, 1, 22)))

    poll_and_deliver(tracker, clock, days=2)

    [message] = sender.sent
    assert "перенесена" in message
    assert "15 дек 2026 → 22 янв 2027" in message


def test_a_second_move_is_a_new_event_but_the_same_move_is_not_repeated(tracker, source, clock, sender):
    add(tracker, source, movie("1", theatrical=date(2026, 12, 15)))
    source.update(movie("1", theatrical=date(2027, 1, 22)))
    poll_and_deliver(tracker, clock, days=2)
    poll_and_deliver(tracker, clock, days=2)  # nothing changed
    source.update(movie("1", theatrical=date(2027, 3, 5)))

    poll_and_deliver(tracker, clock, days=2)

    assert len(sender.sent) == 2
    assert "22 янв 2027 → 5 мар 2027" in sender.sent[1]


def moved_events(session_factory):
    with session_factory() as s:
        return list(s.scalars(select(Event).where(Event.type == "movie_date_moved").order_by(Event.id)))


def test_a_move_there_and_back_and_there_again_is_three_events(tracker, source, clock, session_factory):
    add(tracker, source, movie("1", theatrical=date(2026, 12, 15)))
    for new_date in (date(2027, 1, 22), date(2026, 12, 15), date(2027, 1, 22)):
        source.update(movie("1", theatrical=new_date))
        poll_and_deliver(tracker, clock, days=2)

    events = moved_events(session_factory)

    assert [e.payload["new"] for e in events] == ["2027-01-22", "2026-12-15", "2027-01-22"]
    assert len({e.dedup_key for e in events}) == 3


def test_a_move_found_again_after_a_failed_save_is_one_event(tracker, source, clock, session_factory, monkeypatch):
    add(tracker, source, movie("1", theatrical=date(2026, 12, 15)))
    source.update(movie("1", theatrical=date(2027, 1, 22)))
    with monkeypatch.context() as patch:
        def broken(*args):
            raise RuntimeError("database is locked")

        patch.setattr(movie_events, "check_interval", broken)  # fails after the event is queued, before the state is saved
        clock.advance(days=2)
        run(tracker.poll_due())
    assert len(moved_events(session_factory)) == 1

    poll_and_deliver(tracker, clock, hours=1)  # the failed title is due again after 30 minutes

    assert len(moved_events(session_factory)) == 1


def test_a_move_queued_by_the_earlier_version_of_the_key_is_not_sent_again(tracker, source, clock, session_factory):
    title_id = add(tracker, source, movie("1", theatrical=date(2026, 12, 15)))
    source.update(movie("1", theatrical=date(2027, 1, 22)))
    clock.advance(days=2)
    # the earlier version queued the move under a key with only the new date, and then failed to save the state
    run(tracker.record_event(
        "movie_date_moved", {"text": "x", "new": "2027-01-22"}, f"movie:{title_id}:date_moved:2027-01-22", title_id=title_id
    ))

    run(tracker.poll_due())

    assert len(moved_events(session_factory)) == 1


def test_an_old_move_to_the_same_date_does_not_hide_a_new_one(tracker, source, clock, session_factory):
    title_id = add(tracker, source, movie("1", theatrical=date(2026, 12, 15)))
    run(tracker.record_event(  # a move to 22 Jan queued under the earlier key, long since saved and looked past
        "movie_date_moved", {"text": "x", "new": "2027-01-22"}, f"movie:{title_id}:date_moved:2027-01-22", title_id=title_id
    ))
    clock.advance(days=1)
    run(tracker.poll_due())  # a look with nothing new: the previous look is now later than that event
    source.update(movie("1", theatrical=date(2027, 1, 22)))

    poll_and_deliver(tracker, clock, days=2)

    assert len(moved_events(session_factory)) == 2


def test_movie_released_in_cinemas_is_delivered_once(tracker, source, clock, sender):
    add(tracker, source, movie("1", theatrical=date(2026, 12, 16)))

    clock.set_day(date(2026, 12, 16))
    run(tracker.poll_due())
    run(tracker.deliver_pending())
    poll_and_deliver(tracker, clock, days=3)

    [message] = sender.sent
    assert "вышел в кино" in message
    assert "Дюна: Часть третья" in message


def test_nothing_is_sent_before_the_premiere_day(tracker, source, clock, sender):
    add(tracker, source, movie("1", theatrical=date(2026, 12, 16)))

    clock.set_day(date(2026, 12, 15))
    run(tracker.poll_due())
    run(tracker.deliver_pending())

    assert sender.sent == []


def test_digital_release_is_delivered_once(tracker, source, clock, sender):
    add(tracker, source, movie("1", theatrical=date(2026, 12, 16)))
    source.update(movie("1", theatrical=date(2026, 12, 16), digital=date(2027, 2, 10)))
    poll_and_deliver(tracker, clock, days=1)  # the digital date is announced: not one of the four events
    sender.sent.clear()

    clock.set_day(date(2027, 2, 10))
    run(tracker.poll_due())
    run(tracker.deliver_pending())
    poll_and_deliver(tracker, clock, days=3)

    digital = [m for m in sender.sent if "цифровой релиз" in m]
    assert len(digital) == 1


def test_digital_date_that_appears_already_in_the_past_is_a_release(tracker, source, clock, sender):
    add(tracker, source, movie("1", theatrical=date(2026, 9, 1)))
    source.update(movie("1", theatrical=date(2026, 9, 1), digital=date(2026, 10, 20)))

    poll_and_deliver(tracker, clock, days=2)

    assert [m for m in sender.sent if "цифровой релиз" in m]


def test_events_of_different_movies_do_not_mix(tracker, source, clock, sender):
    add(tracker, source, movie("1", name="Первый"))
    add(tracker, source, movie("2", name="Второй"))
    source.update(movie("1", name="Первый", theatrical=date(2026, 12, 16)))
    source.update(movie("2", name="Второй", theatrical=date(2026, 12, 16)))

    poll_and_deliver(tracker, clock, days=2)

    assert len(sender.sent) == 2
    assert {"Первый" in m for m in sender.sent} == {True, False}


# --- the first poll after adding -----------------------------------------------------------------


def test_first_poll_does_not_report_old_dates_as_news(tracker, source, clock, sender):
    add(tracker, source, movie("1", theatrical=date(2024, 2, 27), digital=date(2024, 4, 15)))
    add(tracker, source, movie("2", theatrical=date(2027, 5, 5)))

    poll_and_deliver(tracker, clock, days=2)

    assert sender.sent == []


def test_a_date_that_appears_after_adding_is_news(tracker, source, clock, sender):
    add(tracker, source, movie("1"))
    poll_and_deliver(tracker, clock, days=2)  # first poll: still nothing announced
    assert sender.sent == []
    source.update(movie("1", theatrical=date(2027, 5, 5)))

    poll_and_deliver(tracker, clock, days=2)

    assert len(sender.sent) == 1


def test_an_empty_answer_does_not_erase_known_dates(tracker, source, clock, sender):
    add(tracker, source, movie("1", theatrical=date(2026, 12, 16)))
    source.update(movie("1"))  # the source lost the date for a moment
    poll_and_deliver(tracker, clock, days=2)
    source.update(movie("1", theatrical=date(2026, 12, 16)))  # and has it again

    poll_and_deliver(tracker, clock, days=2)

    assert sender.sent == []


# --- the poll schedule ---------------------------------------------------------------------------


def test_every_title_gets_a_next_check_time_when_added(tracker, source, session_factory):
    title_id = add(tracker, source, movie("1"))

    assert next_check(session_factory, title_id) is not None


def test_a_title_is_not_polled_before_its_time(tracker, source, clock):
    add(tracker, source, movie("1"))
    source.calls.clear()

    run(tracker.poll_due())

    assert source.calls == []


def test_polling_moves_the_next_check_into_the_future(tracker, source, clock, session_factory):
    title_id = add(tracker, source, movie("1"))
    clock.advance(days=2)

    run(tracker.poll_due())

    assert next_check(session_factory, title_id) > clock().replace(tzinfo=None)


def _interval_after_poll(tracker, source, clock, session_factory, snapshot):
    title_id = add(tracker, source, snapshot)
    clock.advance(days=30)
    run(tracker.poll_due())
    return next_check(session_factory, title_id) - clock().replace(tzinfo=None)


def test_release_soon_is_checked_often(tracker, source, clock, session_factory):
    today = T0.date() + timedelta(days=30)
    snapshot = movie("1", theatrical=today + timedelta(days=1))

    assert _interval_after_poll(tracker, source, clock, session_factory, snapshot) == timedelta(hours=1)


def test_release_in_a_couple_of_weeks_is_checked_every_few_hours(tracker, source, clock, session_factory):
    today = T0.date() + timedelta(days=30)
    snapshot = movie("1", theatrical=today + timedelta(days=10))

    assert _interval_after_poll(tracker, source, clock, session_factory, snapshot) == timedelta(hours=6)


def test_distant_or_unannounced_release_is_checked_daily(tracker, source, clock, session_factory):
    today = T0.date() + timedelta(days=30)

    far = _interval_after_poll(tracker, source, clock, session_factory, movie("1", theatrical=today + timedelta(days=200)))
    none = _interval_after_poll(tracker, source, clock, session_factory, movie("2"))

    assert far == timedelta(hours=24)
    assert none == timedelta(hours=24)


def test_nothing_expected_is_checked_rarely(tracker, source, clock, session_factory):
    snapshot = movie("1", theatrical=date(2024, 2, 27), digital=date(2024, 4, 15))

    assert _interval_after_poll(tracker, source, clock, session_factory, snapshot) == timedelta(days=7)


# --- failures stay isolated ----------------------------------------------------------------------


def test_a_failing_source_is_postponed_and_the_others_are_still_polled(
    tracker, source, clock, sender, session_factory
):
    bad = add(tracker, source, movie("1", name="Сбойный"))
    add(tracker, source, movie("2", name="Рабочий"))
    source.update(movie("2", name="Рабочий", theatrical=date(2026, 12, 16)))
    source.failing.add("1")
    clock.advance(days=2)

    report = run(tracker.poll_due())
    run(tracker.deliver_pending())

    assert report.failed == 1
    assert report.polled == 1
    assert [m for m in sender.sent if "Рабочий" in m]
    assert next_check(session_factory, bad) == clock().replace(tzinfo=None) + timedelta(minutes=30)


def test_a_failed_title_is_not_retried_until_it_is_due_and_recovers(tracker, source, clock, sender):
    add(tracker, source, movie("1"))
    source.failing.add("1")
    clock.advance(days=2)
    run(tracker.poll_due())
    source.failing.clear()
    source.update(movie("1", theatrical=date(2026, 12, 16)))
    source.calls.clear()

    run(tracker.poll_due())  # too early
    assert source.calls == []

    poll_and_deliver(tracker, clock, minutes=31)
    assert len([m for m in sender.sent if not m.startswith("⚠️")]) == 1


def test_a_failed_poll_keeps_the_stored_state(tracker, source, clock, sender, session_factory):
    title_id = add(tracker, source, movie("1", theatrical=date(2026, 12, 16)))
    source.failing.add("1")
    clock.advance(days=2)

    run(tracker.poll_due())

    with session_factory() as s:
        state = s.scalar(select(SourceSnapshot.state).where(SourceSnapshot.title_id == title_id))
    assert state["theatrical_date"] == "2026-12-16"


def test_a_movie_the_source_no_longer_knows_is_postponed_not_fatal(tracker, source, clock, session_factory):
    title_id = add(tracker, source, movie("1"))
    del source.by_id["1"]
    clock.advance(days=2)

    report = run(tracker.poll_due())

    assert report.failed == 1
    assert next_check(session_factory, title_id) > clock().replace(tzinfo=None)


# --- the owner's test-event button ---------------------------------------------------------------


@pytest.mark.parametrize(
    "sample_id, expected",
    [
        ("movie-announced", "объявлена дата премьеры"),
        ("movie-moved", "→"),
        ("movie-released", "вышел в кино"),
        ("movie-digital", "цифровой релиз"),
    ],
)
def test_all_four_movie_events_are_in_the_test_event_menu(tracker, sender, sample_id, expected):
    assert sample_id in [k.id for k in tracker.test_samples()]

    result = run(tracker.send_test_event(sample_id))

    assert result.delivered is True
    assert expected in sender.sent[0]


def test_test_events_do_not_block_real_ones(tracker, source, clock, sender):
    add(tracker, source, movie("1"))
    run(tracker.send_test_event("movie-announced"))
    source.update(movie("1", theatrical=date(2026, 12, 16)))

    poll_and_deliver(tracker, clock, days=2)

    assert len(sender.sent) == 2


# --- the event loop stays free -------------------------------------------------------------------


def test_database_work_of_polling_and_delivery_runs_off_the_event_loop(session_factory, clock, sender, source):
    loop_thread = threading.get_ident()
    seen: list[int] = []

    def spying_factory():
        seen.append(threading.get_ident())
        return session_factory()

    tracker = Tracker(spying_factory, clock=clock, sender=sender, sources={"movie": source})
    add(tracker, source, movie("1"))
    source.update(movie("1", theatrical=date(2026, 12, 16)))
    seen.clear()

    poll_and_deliver(tracker, clock, days=2)

    assert seen, "polling and delivery must touch the database"
    assert loop_thread not in seen


def test_events_are_stored_with_a_dedup_key_per_fact(tracker, source, clock, session_factory):
    add(tracker, source, movie("1", theatrical=date(2026, 12, 15)))
    source.update(movie("1", theatrical=date(2027, 1, 22)))

    poll_and_deliver(tracker, clock, days=2)

    with session_factory() as s:
        [event] = list(s.scalars(select(Event)))
    assert "2027-01-22" in event.dedup_key  # a move is keyed by its new date ...
    assert ":from:20261024T120000" in event.dedup_key  # ... and by the moment of the look it was seen from


def test_a_failed_postponement_does_not_stop_the_pass(tracker, source, clock, sender, monkeypatch):
    add(tracker, source, movie("1", name="Сбойный"))
    add(tracker, source, movie("2", name="Рабочий"))
    source.update(movie("2", name="Рабочий", theatrical=date(2026, 12, 16)))
    source.failing.add("1")
    clock.advance(days=2)

    def broken_postpone(title_id, delay):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(tracker._polling, "_postpone", broken_postpone)

    report = run(tracker.poll_due())
    run(tracker.deliver_pending())

    assert report.failed == 1
    assert [m for m in sender.sent if "Рабочий" in m]
