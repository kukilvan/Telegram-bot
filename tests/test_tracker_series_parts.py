"""Tracker core: a season that airs in portions with a long break is split into parts.

Driven through the facade only (fake clock, fake series source, fake sender, in-memory SQLite). A gap between
neighbouring episodes of one season that is longer than the threshold (6 weeks unless the owner changed it)
starts a new part; with no such gap the season is one part and the texts never mention parts.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.tracker.cards import format_card
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import Event
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

    def update(self, snapshot):
        self.by_id[snapshot.external_id] = snapshot

    async def suggest(self, query):
        return []

    async def snapshot(self, external_id):
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
    return FakeSeriesSource()


@pytest.fixture
def tracker(session_factory, clock, sender, source):
    return Tracker(session_factory, clock=clock, sender=sender, sources={"series": source})


def weekly(first_day, first_number, count):
    start = datetime.fromisoformat(first_day)
    return tuple(Episode(first_number + n, start + timedelta(weeks=n)) for n in range(count))


def season_in_parts(part1_day, part1_count, part2_day, part2_count, number=3):
    """Season `number` that airs `part1_count` episodes weekly, then `part2_count` more weekly after a break."""
    episodes = weekly(part1_day, 1, part1_count) + weekly(part2_day, part1_count + 1, part2_count)
    return Season(number, f"Сезон {number}", part1_count + part2_count, episodes)


def show(external_id, *seasons, name=None):
    name = name or f"Сериал {external_id}"
    return SeriesSnapshot(
        external_id=external_id, title=name, original_title=name, year=2026, genres=[], seasons=list(seasons),
        status="Returning Series",
    )


def add(tracker, source, snapshot):
    source.update(snapshot)
    return run(tracker.add_title("series", snapshot.external_id)).title_id


def poll_and_deliver(tracker, clock, **advance):
    clock.advance(**advance)
    report = run(tracker.poll_due())
    run(tracker.deliver_pending())
    return report


def card_text(tracker, title_id):
    return format_card(run(tracker.title_card(title_id)))


def dedup_keys(session_factory, event_type):
    with session_factory() as s:
        return list(s.scalars(select(Event.dedup_key).where(Event.type == event_type)))


# --- карточка: сезон без разрыва, с разрывом, ровно на пороге -----------------------------------------


def test_a_season_without_a_break_is_one_part_and_the_card_never_mentions_parts(tracker, source):
    title_id = add(tracker, source, show("300", Season(3, "Сезон 3", 8, weekly("2026-08-31", 1, 8))))

    text = card_text(tracker, title_id)

    assert "Сезон 3: вышло 8 из 8" in text
    assert "част" not in text


def test_a_season_with_one_break_reads_as_part_one_and_the_date_of_part_two(tracker, source):
    # part 1 ended on 21 Sep; part 2 starts on 27 Mar, far beyond six weeks later
    title_id = add(tracker, source, show("301", season_in_parts("2026-08-03", 8, "2027-03-27", 8)))

    text = card_text(tracker, title_id)

    assert "Сезон 3, часть 1: вышло 8 из 8; часть 2 — с 27 марта" in text


def test_a_break_of_exactly_the_threshold_does_not_split_the_season(tracker, source):
    first = weekly("2026-09-07", 1, 4)  # the last one is out on 28 Sep
    later = tuple(Episode(5 + n, first[-1].air_at + timedelta(weeks=6) + timedelta(weeks=n)) for n in range(4))
    title_id = add(tracker, source, show("302", Season(3, "Сезон 3", 8, first + later)))

    assert "част" not in card_text(tracker, title_id)


def test_a_break_a_day_beyond_the_threshold_splits_the_season(tracker, source):
    first = weekly("2026-09-07", 1, 4)
    later = tuple(Episode(5 + n, first[-1].air_at + timedelta(weeks=6, days=1) + timedelta(weeks=n)) for n in range(4))
    title_id = add(tracker, source, show("303", Season(3, "Сезон 3", 8, first + later)))

    assert "Сезон 3, часть 1: вышло 4 из 4; часть 2 — с 10 ноября" in card_text(tracker, title_id)


def test_the_card_of_a_running_second_part_counts_only_that_part(tracker, source):
    # part 1: 4 old episodes, part 2: 8 episodes weekly from 14 Sep, of which 6 are out on the 24th
    episodes = weekly("2026-05-04", 1, 4) + weekly("2026-09-14", 5, 8)
    title_id = add(tracker, source, show("304", Season(3, "Сезон 3", 12, episodes)))

    assert "Сезон 3, часть 2: вышло 6 из 8, следующая — пн, 26 окт" in card_text(tracker, title_id)


# --- порог в настройках ------------------------------------------------------------------------------


def test_the_threshold_is_six_weeks_until_the_owner_changes_it(tracker, source):
    assert run(tracker.part_gap_weeks()) == 6

    # a five-week break
    first = weekly("2026-08-03", 1, 4)
    later = tuple(Episode(5 + n, first[-1].air_at + timedelta(weeks=5) + timedelta(weeks=n)) for n in range(4))
    title_id = add(tracker, source, show("305", Season(3, "Сезон 3", 8, first + later)))
    assert "част" not in card_text(tracker, title_id)

    run(tracker.set_part_gap_weeks(4))

    assert run(tracker.part_gap_weeks()) == 4
    assert "Сезон 3, часть 2: вышло 4 из 4" in card_text(tracker, title_id)  # part 1 ended, part 2 is out too


def test_the_threshold_survives_a_restart(session_factory, clock, sender, source):
    first = Tracker(session_factory, clock=clock, sender=sender, sources={"series": source})
    run(first.set_part_gap_weeks(10))

    second = Tracker(session_factory, clock=clock, sender=sender, sources={"series": source})

    assert run(second.part_gap_weeks()) == 10


def test_a_threshold_below_one_week_is_refused(tracker):
    with pytest.raises(ValueError):
        run(tracker.set_part_gap_weeks(0))

    assert run(tracker.part_gap_weeks()) == 6


# --- события: часть началась / закончилась ------------------------------------------------------------


def test_the_last_episode_of_part_one_ends_the_part_and_names_when_part_two_starts(tracker, source, clock, sender):
    # part 1: eight weekly episodes from 7 Sep (the 8th on 26 Oct); part 2 from 27 Mar
    add(tracker, source, show("310", season_in_parts("2026-09-07", 8, "2027-03-27", 8)))

    poll_and_deliver(tracker, clock, days=3)

    assert sender.sent == [
        "📺 Сериал 310 — закончилась часть 1 сезона 3\nВышла последняя серия части — 8; часть 2 — с 27 марта"
    ]


def test_the_first_episode_of_part_two_starts_the_part(tracker, source, clock, sender):
    # part 1 ended on 21 Sep; part 2 starts on Mon 16 Nov and continues weekly
    add(tracker, source, show("311", season_in_parts("2026-08-03", 8, "2026-11-16", 8)))

    poll_and_deliver(tracker, clock, days=24)

    assert sender.sent == ["📺 Сериал 311 — началась часть 2 сезона 3\nВышла серия 9 · следующая: пн, 23 ноя"]


def test_the_first_episode_of_a_season_that_comes_in_parts_starts_part_one(tracker, source, clock, sender):
    add(tracker, source, show("312", season_in_parts("2026-10-26", 4, "2027-03-01", 4)))

    poll_and_deliver(tracker, clock, days=3)

    assert sender.sent == ["📺 Сериал 312 — началась часть 1 сезона 3\nВышла серия 1 · следующая: пн, 2 ноя"]


def test_an_episode_in_the_middle_of_a_part_says_how_far_the_part_has_got(tracker, source, clock, sender):
    # part 1: four episodes in May; part 2: eight weekly from 14 Sep, the 7th of them (no. 11) on 26 Oct
    episodes = weekly("2026-05-04", 1, 4) + weekly("2026-09-14", 5, 8)
    add(tracker, source, show("313", Season(3, "Сезон 3", 12, episodes)))

    poll_and_deliver(tracker, clock, days=3)

    assert sender.sent == ["📺 Сериал 313 — вышла серия 11\nСезон 3, часть 2: вышло 7 из 8 · следующая: пн, 2 ноя"]


def test_the_last_episode_of_the_last_part_ends_that_part(tracker, source, clock, sender):
    # part 2 is eight episodes from 14 Sep; the last (no. 12) is out on 2 Nov
    episodes = weekly("2026-05-04", 1, 4) + weekly("2026-09-14", 5, 8)
    add(tracker, source, show("314", Season(3, "Сезон 3", 12, episodes)))
    poll_and_deliver(tracker, clock, days=3)
    sender.sent.clear()

    poll_and_deliver(tracker, clock, days=8)

    assert sender.sent == ["📺 Сериал 314 — закончилась часть 2 сезона 3\nВышла последняя серия — 12"]


def test_an_ended_part_is_not_reported_twice(tracker, source, clock, sender):
    add(tracker, source, show("315", season_in_parts("2026-09-07", 8, "2027-03-27", 8)))

    poll_and_deliver(tracker, clock, days=3)
    poll_and_deliver(tracker, clock, hours=2)
    poll_and_deliver(tracker, clock, days=2)

    assert len(sender.sent) == 1


def test_dedup_keys_of_a_split_season_carry_the_part_and_an_unsplit_season_keeps_its_old_keys(
    tracker, source, clock, session_factory
):
    first = add(tracker, source, show("316", season_in_parts("2026-09-07", 8, "2027-03-27", 8)))
    second = add(tracker, source, show("317", Season(1, "Сезон 1", 8, weekly("2026-09-07", 1, 8))))

    poll_and_deliver(tracker, clock, days=3)

    assert dedup_keys(session_factory, "series_season_ended") == [
        f"series:{first}:s3:p1:ended",
        f"series:{second}:s1:ended",
    ]


def test_the_end_of_part_one_and_the_end_of_part_two_are_different_events(tracker, source, clock, sender):
    # both parts have eight episodes, so the counts alone cannot tell the two ends apart
    add(tracker, source, show("318", season_in_parts("2026-09-07", 8, "2026-12-28", 8)))

    poll_and_deliver(tracker, clock, days=3)  # part 1 ends
    poll_and_deliver(tracker, clock, days=130)  # everything of part 2 came meanwhile

    ended = [m for m in sender.sent if "закончилась" in m]
    assert ended == [
        "📺 Сериал 318 — закончилась часть 1 сезона 3\nВышла последняя серия части — 8; часть 2 — с 28 декабря",
        "📺 Сериал 318 — закончилась часть 2 сезона 3\nВышла последняя серия — 16",
    ]


# --- события: дата части объявлена / перенесена --------------------------------------------------------


def test_the_date_of_part_two_appearing_after_part_one_has_aired_ends_part_one_once(tracker, source, clock, sender):
    # part 1 (four of an announced eight) aired in September; only now the source dates the rest, far away
    add(tracker, source, show("320", Season(3, "Сезон 3", 8, weekly("2026-09-07", 1, 4))))
    source.update(show("320", season_in_parts("2026-09-07", 4, "2027-03-27", 4)))

    poll_and_deliver(tracker, clock, hours=25)
    poll_and_deliver(tracker, clock, hours=25)

    # one message, not two: the end of the part already says when the next one starts
    assert sender.sent == [
        "📺 Сериал 320 — закончилась часть 1 сезона 3\nВышла последняя серия части — 4; часть 2 — с 27 марта"
    ]


def test_the_date_of_part_two_is_announced_when_part_one_is_still_airing(tracker, source, clock, sender):
    # part 1: eight weekly episodes from 7 Sep (the 8th on 26 Oct, not out yet); part 2 gets its date later
    add(tracker, source, show("323", Season(3, "Сезон 3", 16, weekly("2026-09-07", 1, 8))))
    source.update(show("323", season_in_parts("2026-09-07", 8, "2027-03-27", 8)))

    poll_and_deliver(tracker, clock, hours=25)

    assert sender.sent == ["📺 Сериал 323 — объявлена дата части 2 сезона 3\nПремьера: 27 марта 2027"]


def test_a_season_that_is_already_in_parts_when_added_reports_nothing_old(tracker, source, clock, sender):
    add(tracker, source, show("324", season_in_parts("2026-08-03", 8, "2027-03-27", 8)))

    report = poll_and_deliver(tracker, clock, days=3)

    assert (report.polled, report.events) == (1, 0)
    assert sender.sent == []


def test_a_season_announced_in_two_parts_at_once_is_one_announcement(tracker, source, clock, sender):
    add(tracker, source, show("321", Season(3, "Сезон 3", 8, ())))
    source.update(show("321", season_in_parts("2027-01-11", 4, "2027-06-07", 4)))

    poll_and_deliver(tracker, clock, hours=25)

    assert sender.sent == ["📺 Сериал 321 — объявлена дата сезона 3\nПремьера: 11 января 2027"]


def test_the_premiere_of_part_two_moving_is_reported_as_part_two(tracker, source, clock, sender):
    add(tracker, source, show("322", season_in_parts("2026-08-03", 8, "2027-03-27", 8)))
    source.update(show("322", season_in_parts("2026-08-03", 8, "2027-04-03", 8)))

    poll_and_deliver(tracker, clock, hours=25)

    assert sender.sent == ["📺 Сериал 322 — премьера части 2 сезона 3 перенесена\n27 мар 2027 → 3 апр 2027"]


# --- «Тестовое событие» ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind_id, expected",
    [
        ("series-part-announced", "объявлена дата части 2 сезона 3"),
        ("series-part-started", "началась часть 2 сезона 3"),
        ("series-part-ended", "закончилась часть 1 сезона 3"),
    ],
)
def test_the_part_events_are_in_the_test_event_menu(tracker, sender, kind_id, expected):
    assert kind_id in [k.id for k in tracker.test_event_kinds()]

    result = run(tracker.send_test_event(kind_id))

    assert result.delivered
    assert expected in sender.sent[0]


# --- порог из настроек действует и на события ----------------------------------------------------------


def test_the_threshold_of_the_owner_decides_the_events_and_changing_it_sends_nothing(tracker, source, clock, sender):
    # part 1: eight weekly episodes from 7 Sep (the 8th on 26 Oct); the rest after a five-week break
    first = weekly("2026-09-07", 1, 8)
    later = tuple(Episode(9 + n, first[-1].air_at + timedelta(weeks=5) + timedelta(weeks=n)) for n in range(4))
    add(tracker, source, show("330", Season(3, "Сезон 3", 12, first + later)))

    run(tracker.set_part_gap_weeks(4))  # the five-week break now splits the season
    poll_and_deliver(tracker, clock, hours=2)
    assert sender.sent == []

    poll_and_deliver(tracker, clock, days=3)

    assert sender.sent == [
        "📺 Сериал 330 — закончилась часть 1 сезона 3\nВышла последняя серия части — 8; часть 2 — с 30 ноября"
    ]
