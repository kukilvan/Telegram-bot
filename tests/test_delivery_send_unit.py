"""A send and its «delivered» mark are one unit a stop does not cut (KI-5, spec 9.1a 2.1); `Tracker.finish_sends`.

Driven through the facade: a sender that blocks until the test lets it go, in-memory SQLite.
"""

import asyncio
import logging
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import DeliveryItem, DeliveryStatus

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
UNFINISHED = "остановка: отправка не закончилась за 0.05 с — сообщение может прийти ещё раз"


class BlockingSender:
    """Every send waits for `release`; `started` is set when the first one begins."""

    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.sent = []

    async def send(self, message, actions=()):
        self.started.set()
        await self.release.wait()
        self.sent.append(message)


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def sender():
    return BlockingSender()


@pytest.fixture
def tracker(session_factory, sender):
    tracker = Tracker(session_factory, clock=lambda: NOW, sender=sender, sources={})
    for text in ("первое", "второе"):
        asyncio.run(tracker.record_event("test", {"text": text}, dedup_key=text))
    return tracker


def statuses(session_factory):
    with session_factory() as session:
        return [item.status for item in session.scalars(select(DeliveryItem).order_by(DeliveryItem.id))]


def test_a_cancel_during_a_send_waits_for_its_mark_and_starts_no_next_send(tracker, sender, session_factory):
    async def scenario():
        job = asyncio.create_task(tracker.deliver_pending(force=True))  # one by one: two sends
        await sender.started.wait()
        job.cancel()  # the stop cancels the delivery job while Telegram takes the first message
        await asyncio.sleep(0.05)
        still_waiting = not job.done()
        sender.release.set()
        with pytest.raises(asyncio.CancelledError):
            await job
        return still_waiting

    assert asyncio.run(scenario()) is True  # the cancel waits for the unit to end
    assert [text.split()[-1] for text in sender.sent] == ["первое"]  # no second unit after the cancel
    assert statuses(session_factory) == [DeliveryStatus.DELIVERED, DeliveryStatus.PENDING]


def test_finish_sends_gives_up_after_its_timeout_and_logs_then_says_true_when_the_send_ends(tracker, sender, caplog):
    async def scenario():
        job = asyncio.create_task(tracker.deliver_pending(force=True))
        await sender.started.wait()
        with caplog.at_level(logging.WARNING):
            hanging = await tracker.finish_sends(0.05)
        sender.release.set()
        finished = await tracker.finish_sends(5)
        await job
        return hanging, finished

    assert asyncio.run(scenario()) == (False, True)
    assert caplog.text.count(UNFINISHED) == 1


def test_finish_sends_is_true_at_once_when_nothing_is_sent_and_a_done_unit_leaves_the_set(tracker, sender):
    sender.release.set()

    async def scenario():
        nothing = await tracker.finish_sends(0)
        await tracker.deliver_pending(force=True)
        return nothing, await tracker.finish_sends(0)

    assert asyncio.run(scenario()) == (True, True)
    assert [text.split()[-1] for text in sender.sent] == ["первое", "второе"]
