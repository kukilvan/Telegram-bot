"""The login report outside the delivery rules (ticket 05 of stage 9.1c, spec 6, KI-73): a queued report goes out as a
message of its own at the first pass — in the quiet hours, on a working morning, while the rules hold everything — never
joins a summary, never expires, is retried at the next pass and is never sent twice by the send at once and a pass together.

The pure rule (`DeliveryRules.due`) and the real core with a fake sender; the owner's clock is UTC, the rules are the default
ones (work days Sunday to Thursday, summary 15:00, quiet 21:00–07:30). 17 Nov 2026 is a Tuesday.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.tracker import delivery, login_events
from app.tracker.core import WEB_LOGIN, WEB_LOGIN_LOCKED, Tracker
from app.tracker.db import create_session_factory
from app.tracker.delivery import DeliveryRules, Pending

DAY = datetime(2026, 11, 17)  # a Tuesday, a work day
RULES = DeliveryRules()


def at(hour: int, minute: int = 0, days: int = 0) -> datetime:
    return DAY + timedelta(days=days, hours=hour, minutes=minute)


def pending(event_type: str, queued_at: datetime, item_id: int = 1, data: dict | None = None) -> Pending:
    return Pending(item_id, item_id, event_type, None, "текст", data or {}, queued_at)


# ---- the pure rule -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "queued, now",
    [
        (at(22), at(22, 41)),  # quiet hours: the network was down, back at 22:40
        (at(9), at(9, 1)),  # a work day before the summary hour
        (at(22), at(23)),  # the rules hold everything
        (at(22), at(7, 0, days=1)),  # the whole night
        (at(11), at(11, 1)),  # an open stretch of time
    ],
)
@pytest.mark.parametrize("event_type", login_events.TYPES)
def test_a_queued_report_is_always_due_as_a_message_of_its_own(event_type, queued, now):
    report = pending(event_type, queued)

    assert RULES.due([report], now) == ([report], [])


def test_a_report_goes_before_the_other_events_and_the_others_still_follow_the_rules():
    other = pending("test", at(22), item_id=1)
    report = pending(WEB_LOGIN, at(22, 10), item_id=2)

    assert RULES.due([other, report], at(23)) == ([report], [])  # the rules hold the other one
    assert RULES.due([other, report], at(8, 0, days=1)) == ([report], [])  # a working morning
    assert RULES.due([other, report], at(15, 1, days=1)) == ([report], [other])  # the summary hour: only the other waited


def test_a_report_that_sat_through_the_night_never_joins_the_summary():
    report = pending(WEB_LOGIN_LOCKED, at(22))

    single, summary = RULES.due([report], at(15, 1, days=1))

    assert single == [report] and summary == []


def test_a_report_never_expires():
    old = pending(WEB_LOGIN, at(1), data={"text": "🔐"})

    assert not delivery.expired(old, at(1) + timedelta(days=30))


# ---- the core ----------------------------------------------------------------------------------------------------

class Sender:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.failing = False

    async def send(self, message, actions=()):
        await asyncio.sleep(0)  # a point where a second pass could step in
        if self.failing:
            raise ConnectionError("telegram is down")
        self.messages.append(message)


class Clock:
    def __init__(self) -> None:
        self.now = at(22).replace(tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def sender():
    return Sender()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def tracker(sender, clock):
    return Tracker(create_session_factory("sqlite://"), clock=clock, sender=sender, sources={})


def run(coro):
    return asyncio.run(coro)


def record(tracker, unique="a" * 32, event_type=WEB_LOGIN):
    return run(tracker.record_login_report(event_type, unique, "Android, Chrome", None, at(22).replace(tzinfo=timezone.utc)))


def test_the_network_down_at_22_00_and_back_at_22_40_the_report_comes_at_22_41(tracker, sender, clock):
    sender.failing = True
    record(tracker)  # 22:00, in the quiet hours
    run(tracker.deliver_pending(force=True))  # the send at once fails
    clock.now = at(22, 20).replace(tzinfo=timezone.utc)
    run(tracker.deliver_pending())  # the network is still down
    assert sender.messages == []

    sender.failing = False
    clock.now = at(22, 41).replace(tzinfo=timezone.utc)
    run(tracker.deliver_pending())

    assert len(sender.messages) == 1 and sender.messages[0].startswith("🔐 Вход в приложение")
    run(tracker.deliver_pending())
    assert len(sender.messages) == 1  # delivered, not again


def test_a_failed_send_is_retried_at_the_next_pass_whatever_the_rules(tracker, sender, clock):
    clock.now = at(9).replace(tzinfo=timezone.utc)  # a work morning
    record(tracker)
    sender.failing = True
    run(tracker.deliver_pending())
    assert sender.messages == []

    sender.failing = False
    run(tracker.deliver_pending())

    assert len(sender.messages) == 1


def test_a_report_queued_before_the_update_goes_at_the_next_pass(tracker, sender, clock):
    record(tracker, event_type=WEB_LOGIN_LOCKED)  # waits since 22:00, held by the old rules
    clock.now = at(23).replace(tzinfo=timezone.utc)

    run(tracker.deliver_pending())

    assert len(sender.messages) == 1 and sender.messages[0].startswith("⚠️ Вход в приложение закрыт")


def test_a_report_older_than_a_day_is_not_expired(tracker, sender, clock):
    record(tracker)
    clock.now = clock.now + timedelta(days=3)

    run(tracker.deliver_pending())

    assert len(sender.messages) == 1


def test_summary_now_sends_the_report_apart_and_never_in_the_summary(tracker, sender):
    record(tracker)
    run(tracker.record_event("test", {"text": "обычное событие"}, dedup_key="k1"))

    result = run(tracker.summary_now())

    assert result.events == 2 and result.delivered
    login, summary = sender.messages
    assert login.startswith("🔐 Вход в приложение")
    assert summary.startswith("📋 Сводка") and "Вход в приложение" not in summary and "обычное событие" in summary


def test_summary_now_with_only_a_report_sends_just_the_report(tracker, sender):
    record(tracker)

    result = run(tracker.summary_now())

    assert result.delivered and len(sender.messages) == 1 and sender.messages[0].startswith("🔐")


def test_the_send_at_once_and_a_pass_together_send_a_report_once(tracker, sender, clock):
    event_id = record(tracker)
    clock.now = at(23).replace(tzinfo=timezone.utc)

    async def together():
        await asyncio.gather(
            tracker.deliver_pending(force=True, only=frozenset({event_id})),
            tracker.deliver_pending(),
            tracker.deliver_pending(),
        )

    run(together())

    assert len(sender.messages) == 1
