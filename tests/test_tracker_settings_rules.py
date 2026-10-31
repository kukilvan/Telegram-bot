"""Tracker core: new settings apply to what is already queued and to what is stored, with no new events.

Driven through the facade only (fake clock, fake sender, in-memory SQLite). The delivery rules are read at every pass of
the queue, so a change saved on the settings page works from the next pass for what already waits (section 2.6 of the
spec of part 5.4); the break that splits a season into parts is read where it is needed, and a change of it makes no
event of its own (2.7). The owner's clock is Asia/Jerusalem (UTC+2 in November); Sun 1 Nov is a working day.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from anime_fakes import FakeShikimori, real_anilist
from app.tracker.cards import format_card
from app.tracker.core import SettingsChange, Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import DeliveryItem, DeliveryStatus, Event
from app.tracker.seasons import Episode, Season
from app.tracker.sources.shikimori_anime import ShikimoriAnimeSource
from app.tracker.sources.tmdb_series import SeriesSnapshot

JERUSALEM = ZoneInfo("Asia/Jerusalem")
SUN = 1  # 1 Nov 2026, a working day


def local(day, hour=12, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=JERUSALEM).astimezone(timezone.utc)


class FakeClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now

    def at(self, day, hour=12, minute=0):
        self.now = local(day, hour, minute)

    def advance(self, **delta):
        self.now += timedelta(**delta)


class FakeSender:
    def __init__(self):
        self.sent = []
        self.failing = False

    @property
    def messages(self):
        return [message for message, _ in self.sent]

    async def send(self, message, actions=()):
        if self.failing:
            raise ConnectionError("telegram is down")
        self.sent.append((message, list(actions)))


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def clock():
    return FakeClock(local(SUN, 9))


@pytest.fixture
def sender():
    return FakeSender()


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def tracker(session_factory, clock, sender):
    tracker = Tracker(session_factory, clock=clock, sender=sender, sources={}, default_tz=JERUSALEM)
    run(tracker.set_delivery_rules(
        tz_name="Asia/Jerusalem", workdays=[6, 0, 1, 2, 3], summary_at="15:00", quiet_from="21:00", quiet_until="07:30"
    ))
    return tracker


def save(tracker, **override):
    """The settings page pressed «Сохранить»: the stored values with these changed."""
    view = run(tracker.settings())
    values = {
        "tz_name": view.tz_name or "",
        "workdays": view.workdays,
        "summary_at": view.summary_at,
        "quiet_from": view.quiet_from,
        "quiet_until": view.quiet_until,
        "part_gap_weeks": str(view.part_gap_weeks),
        "my_platforms": view.saved.my_platforms,
        "store_country": view.saved.store_country,
    }
    run(tracker.save_settings(SettingsChange(**{**values, **override})))


def queue(tracker, clock, day, hour, minute, text):
    clock.at(day, hour, minute)
    return run(tracker.record_event("test", {"text": text}, dedup_key=text))


def deliver(tracker, clock, day, hour, minute=0):
    clock.at(day, hour, minute)
    return run(tracker.deliver_pending())


def item_statuses(session_factory):
    with session_factory() as s:
        return [i.status for i in s.scalars(select(DeliveryItem).order_by(DeliveryItem.id))]


# --- the rules change while events wait ---------------------------------------------------------------


def test_a_summary_moved_later_after_it_went_out_does_not_come_again_and_the_next_event_waits_for_the_new_hour(
    tracker, clock, sender
):
    queue(tracker, clock, SUN, 9, 0, "первое")
    deliver(tracker, clock, SUN, 15, 0)
    assert len(sender.messages) == 1 and "первое" in sender.messages[0]

    clock.at(SUN, 16, 0)
    save(tracker, summary_at="18:00")
    deliver(tracker, clock, SUN, 16, 0)
    queue(tracker, clock, SUN, 16, 5, "второе")
    deliver(tracker, clock, SUN, 17, 59)

    assert len(sender.messages) == 1  # the first one is not sent twice, the second one waits

    report = deliver(tracker, clock, SUN, 18, 0)

    assert report.delivered == 1
    assert len(sender.messages) == 2
    assert sender.messages[1].startswith("📋 Сводка") and "второе" in sender.messages[1] and "первое" not in sender.messages[1]


def test_a_summary_moved_earlier_sends_what_gathered_since_morning_at_the_next_pass(tracker, clock, sender):
    queue(tracker, clock, SUN, 9, 0, "утреннее")
    queue(tracker, clock, SUN, 11, 0, "полуденное")
    deliver(tracker, clock, SUN, 14, 30)
    assert sender.messages == []

    clock.at(SUN, 14, 30)
    save(tracker, summary_at="14:00")
    report = deliver(tracker, clock, SUN, 14, 31)

    assert report.delivered == 2
    [summary] = sender.messages
    assert summary.startswith("📋 Сводка · вс, 1 ноя") and "утреннее" in summary and "полуденное" in summary


def test_quiet_hours_taken_away_let_the_night_out_at_the_next_pass(tracker, clock, sender, session_factory):
    queue(tracker, clock, SUN, 21, 30, "вечернее")
    queue(tracker, clock, SUN, 22, 30, "ночное")
    deliver(tracker, clock, SUN, 22, 59)
    assert sender.messages == []  # quiet hours: they wait for Monday

    clock.at(SUN, 23, 0)
    save(tracker, quiet_from="21:00", quiet_until="21:00")  # equal times: no quiet hours
    report = deliver(tracker, clock, SUN, 23, 0)

    # with no quiet hours the two events no longer have to wait by any rule, so each goes as a message of its own
    assert report.delivered == 2
    assert sorted(sender.messages) == ["🧪 вечернее", "🧪 ночное"]
    assert item_statuses(session_factory) == [DeliveryStatus.DELIVERED] * 2


def test_an_event_whose_send_failed_waits_for_the_new_summary_hour_counted_from_its_own_moment(
    tracker, clock, sender, session_factory
):
    queue(tracker, clock, SUN, 9, 0, "упавшее")
    sender.failing = True
    report = deliver(tracker, clock, SUN, 15, 0)
    assert (report.delivered, report.failed) == (0, 1)
    assert item_statuses(session_factory) == [DeliveryStatus.PENDING]

    sender.failing = False
    clock.at(SUN, 15, 10)
    save(tracker, summary_at="18:00")
    deliver(tracker, clock, SUN, 15, 20)
    deliver(tracker, clock, SUN, 17, 59)
    assert sender.messages == []

    report = deliver(tracker, clock, SUN, 18, 0)

    assert report.delivered == 1
    [summary] = sender.messages
    assert summary.startswith("📋 Сводка") and "упавшее" in summary
    assert item_statuses(session_factory) == [DeliveryStatus.DELIVERED]


# --- the break between parts --------------------------------------------------------------------------

T0 = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


class FakeSeriesSource:
    source_key = "tmdb_tv"

    def __init__(self):
        self.by_id = {}

    async def suggest(self, query):
        return []

    async def snapshot(self, external_id):
        return self.by_id.get(external_id)


def weekly(first_day, first_number, count):
    start = datetime.fromisoformat(first_day)
    return tuple(Episode(first_number + n, start + timedelta(weeks=n)) for n in range(count))


def five_week_break_show():
    """Season 3, all out by 24 Oct: four weekly episodes from 3 Aug, then four more after a five-week break."""
    first = weekly("2026-08-03", 1, 4)
    later = tuple(Episode(5 + n, first[-1].air_at + timedelta(weeks=5) + timedelta(weeks=n)) for n in range(4))
    return SeriesSnapshot(
        external_id="500", name="Сериал 500", original_name="Сериал 500", year=2026, genres=[],
        seasons=[Season(3, "Сезон 3", 8, first + later)], status="Returning Series",
    )


@pytest.fixture
def series_tracker(session_factory, sender):
    clock = FakeClock(T0)
    source = FakeSeriesSource()
    source.by_id["500"] = five_week_break_show()
    tracker = Tracker(session_factory, clock=clock, sender=sender, sources={"series": source})
    return tracker, clock


def event_types(session_factory):
    with session_factory() as s:
        return list(s.scalars(select(Event.dedup_key)))


def test_a_new_threshold_changes_the_card_at_once_and_a_poll_with_the_same_answer_finds_nothing_new(
    series_tracker, sender, session_factory
):
    tracker, clock = series_tracker
    title_id = run(tracker.add_title("series", "500")).title_id
    assert "част" not in format_card(run(tracker.title_card(title_id)))
    keys_before = event_types(session_factory)

    save(tracker, part_gap_weeks="4")  # the five-week break now splits the season

    assert "Сезон 3, часть 2: вышло 4 из 4" in format_card(run(tracker.title_card(title_id)))
    clock.advance(days=8)  # past the next check of a series that has nothing left to come
    report = run(tracker.poll_due())
    run(tracker.deliver_pending())
    assert report.polled == 1 and report.events == 0
    assert event_types(session_factory) == keys_before and sender.messages == []

    save(tracker, part_gap_weeks="6")  # and back: the same

    assert "част" not in format_card(run(tracker.title_card(title_id)))
    clock.advance(days=8)  # past the next check of a series that has nothing left to come
    report = run(tracker.poll_due())
    run(tracker.deliver_pending())
    assert report.polled == 1 and report.events == 0
    assert event_types(session_factory) == keys_before and sender.messages == []


def test_the_threshold_does_not_touch_the_parts_of_an_anime(session_factory, sender):
    tracker = Tracker(
        session_factory, clock=FakeClock(T0), sender=sender, default_tz=JERUSALEM,
        sources={"anime": ShikimoriAnimeSource(FakeShikimori(), real_anilist())},
    )
    title_id = run(tracker.add_title("anime", "54492")).title_id  # Kusuriya: its parts come from Shikimori
    card = format_card(run(tracker.title_card(title_id)))
    assert "Сезон 3, часть 1:" in card

    for weeks in ("1", "52", "6"):
        save(tracker, part_gap_weeks=weeks)
        assert format_card(run(tracker.title_card(title_id))) == card
