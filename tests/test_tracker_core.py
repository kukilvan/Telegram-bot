"""Tracker core: events go through a delivery queue and reach the sender exactly once.

The core is driven only through its facade, with a fake clock, a fake sender and in-memory SQLite.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from app.tracker.core import TestEventKind, Tracker
from app.tracker.db import create_tracker_engine, create_session_factory, migrate
from app.tracker.models import DeliveryItem, Event


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
        self.failing = False

    async def send(self, message, actions=()):
        if self.failing:
            raise ConnectionError("telegram is down")
        self.sent.append(message)


T0 = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


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
def tracker(session_factory, clock, sender):
    return Tracker(session_factory, clock=clock, sender=sender, sources={})


def run(coro):
    return asyncio.run(coro)


def queue_rows(session_factory):
    with session_factory() as s:
        return list(s.scalars(select(DeliveryItem).order_by(DeliveryItem.id)))


def test_test_event_reaches_the_sender(tracker, sender):
    kind = tracker.test_event_kinds()[0]

    result = run(tracker.send_test_event(kind.id))

    assert result.delivered is True
    assert len(sender.sent) == 1
    assert kind.label in sender.sent[0]


def test_event_is_marked_delivered_only_after_a_successful_send(tracker, sender, session_factory):
    kind = tracker.test_event_kinds()[0]
    sender.failing = True

    result = run(tracker.send_test_event(kind.id))

    assert result.delivered is False
    [row] = queue_rows(session_factory)
    assert row.status == "pending"
    assert row.attempts == 1
    assert row.delivered_at is None


def test_failed_event_is_delivered_on_the_next_attempt(tracker, sender, session_factory, clock):
    kind = tracker.test_event_kinds()[0]
    sender.failing = True
    run(tracker.send_test_event(kind.id))

    sender.failing = False
    clock.advance(minutes=1)
    run(tracker.deliver_pending())

    assert len(sender.sent) == 1
    [row] = queue_rows(session_factory)
    assert row.status == "delivered"
    assert row.attempts == 2
    assert row.delivered_at == clock().replace(tzinfo=None)


def test_a_delivered_event_is_never_sent_twice(tracker, sender):
    kind = tracker.test_event_kinds()[0]
    run(tracker.send_test_event(kind.id))

    run(tracker.deliver_pending())
    run(tracker.deliver_pending())

    assert len(sender.sent) == 1


def test_concurrent_delivery_runs_send_once(tracker, sender):
    run(tracker.record_event("test", {"text": "hi"}, dedup_key="k1"))

    async def both():
        await asyncio.gather(tracker.deliver_pending(), tracker.deliver_pending())

    run(both())

    assert len(sender.sent) == 1


def test_same_dedup_key_makes_one_event(tracker, sender, session_factory):
    first = run(tracker.record_event("test", {"text": "hi"}, dedup_key="same"))
    second = run(tracker.record_event("test", {"text": "hi"}, dedup_key="same"))

    run(tracker.deliver_pending())

    assert first is not None
    assert second is None
    assert len(sender.sent) == 1
    with session_factory() as s:
        assert len(list(s.scalars(select(Event)))) == 1


def test_every_test_event_press_is_a_new_event(tracker, sender):
    kind = tracker.test_event_kinds()[0]

    run(tracker.send_test_event(kind.id))
    run(tracker.send_test_event(kind.id))

    assert len(sender.sent) == 2


def test_timestamps_come_from_the_clock_at_insert_time(tracker, session_factory, clock):
    run(tracker.record_event("test", {"text": "a"}, dedup_key="a"))
    clock.advance(hours=3)
    run(tracker.record_event("test", {"text": "b"}, dedup_key="b"))

    with session_factory() as s:
        events = list(s.scalars(select(Event).order_by(Event.id)))
    assert [e.detected_at for e in events] == [
        T0.replace(tzinfo=None),
        (T0 + timedelta(hours=3)).replace(tzinfo=None),
    ]
    rows = queue_rows(session_factory)
    assert rows[1].created_at == (T0 + timedelta(hours=3)).replace(tzinfo=None)


def test_unknown_test_event_kind_is_rejected(tracker, sender):
    with pytest.raises(KeyError):
        run(tracker.send_test_event("no-such-kind"))
    assert sender.sent == []


def test_new_kinds_appear_in_the_menu_without_touching_the_core(tracker, sender):
    tracker.register_test_event_kind(
        TestEventKind(id="movie-announced", label="Фильм: объявлена дата", build=lambda: {"text": "Фильм скоро"})
    )

    ids = [k.id for k in tracker.test_event_kinds()]
    assert "movie-announced" in ids

    run(tracker.send_test_event("movie-announced"))
    assert "Фильм скоро" in sender.sent[0]


def test_sources_are_given_from_outside(session_factory, clock, sender):
    sources = {"tmdb": object()}
    tracker = Tracker(session_factory, clock=clock, sender=sender, sources=sources)

    assert tracker.sources["tmdb"] is sources["tmdb"]


def test_one_failing_event_does_not_stop_the_others(session_factory, clock):
    class PickySender:
        def __init__(self):
            self.sent = []

        async def send(self, message, actions=()):
            if "bad" in message:
                raise ConnectionError("rejected")
            self.sent.append(message)

    sender = PickySender()
    tracker = Tracker(session_factory, clock=clock, sender=sender, sources={})
    run(tracker.record_event("test", {"text": "bad one"}, dedup_key="1"))
    run(tracker.record_event("test", {"text": "good one"}, dedup_key="2"))

    run(tracker.deliver_pending())

    assert sender.sent == ["🧪 good one"]
    statuses = [r.status for r in queue_rows(session_factory)]
    assert statuses == ["pending", "delivered"]


def test_new_database_is_created_by_the_migration_in_wal_mode(tmp_path):
    db_file = tmp_path / "nested" / "tracker.db"
    url = f"sqlite:///{db_file.as_posix()}"
    engine = create_tracker_engine(url)

    migrate(engine)

    with engine.connect() as c:
        assert c.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        tables = {r[0] for r in c.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    assert {"events", "delivery_queue", "alembic_version"} <= tables
    # a second migrate is a no-op, not an error
    migrate(engine)
