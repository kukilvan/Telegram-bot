"""Tracker core: series events found by polling and delivered once, and the poll schedule.

Driven through the facade only: fake clock, fake series source, fake sender, in-memory SQLite. Episodes are
built by hand, except the «Укрытие» case that runs on the saved real TMDb answers.
"""

import asyncio
import json
import pathlib
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.tracker.core import Tracker
from app.tracker.cards import format_card
from app.tracker.db import create_session_factory
from app.tracker.models import EpisodeRecord, Event, SourceSnapshot
from app.tracker.seasons import Episode, Season
from app.tracker.sources.tmdb_series import SeriesSnapshot, parse_show

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "tmdb"
T0 = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)  # a Saturday


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, **delta):
        self.now += timedelta(**delta)

    def set(self, year, month, day, hour=12):
        self.now = datetime(year, month, day, hour, 0, tzinfo=timezone.utc)


class FakeSender:
    def __init__(self):
        self.sent = []
        self.failing = False

    async def send(self, message, actions=()):
        if self.failing:
            raise ConnectionError("telegram is down")
        self.sent.append(message)


class FakeSeriesSource:
    source_key = "tmdb_tv"

    def __init__(self):
        self.by_id = {}
        self.failing = set()

    def update(self, snapshot):
        self.by_id[snapshot.external_id] = snapshot

    async def suggest(self, query):
        return []

    async def snapshot(self, external_id):
        if external_id in self.failing:
            raise ConnectionError("tmdb is down")
        return self.by_id.get(external_id)


def weekly(first_day, count):
    start = datetime.fromisoformat(first_day)
    return tuple(Episode(n + 1, start + timedelta(weeks=n)) for n in range(count))


def season(number, first_day, count, expected=None):
    return Season(number, f"Сезон {number}", expected if expected is not None else count, weekly(first_day, count) if first_day else ())


def show(external_id, *seasons, status="Returning Series", name=None):
    name = name or f"Сериал {external_id}"
    return SeriesSnapshot(
        external_id=external_id, title=name, original_title=name, year=2026, genres=[], seasons=list(seasons), status=status
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


def poll_and_deliver(tracker, clock, **advance):
    clock.advance(**advance)
    report = run(tracker.poll_due())
    run(tracker.deliver_pending())
    return report


def next_check(session_factory, title_id):
    with session_factory() as s:
        return s.scalar(select(SourceSnapshot.next_check_at).where(SourceSnapshot.title_id == title_id))


# --- «вышла серия» ---------------------------------------------------------------------------------


def airing():
    """Ten weekly episodes from Mon 7 Sep: on T0 seven are out, the eighth comes on Mon 26 Oct."""
    return show("200", season(1, "2026-09-07", 10), name="Идущий")


def test_an_episode_is_delivered_once_with_its_number_and_the_next_date(tracker, source, clock, sender):
    add(tracker, source, airing())

    poll_and_deliver(tracker, clock, days=2)
    poll_and_deliver(tracker, clock, hours=2)
    poll_and_deliver(tracker, clock, days=3)

    assert sender.sent == ["📺 Идущий — вышла серия 8 из 10\nСезон 1 · следующая: пн, 2 ноя"]


def test_nothing_is_announced_right_after_adding(tracker, source, clock, sender):
    add(tracker, source, airing())  # seven episodes are already out

    report = poll_and_deliver(tracker, clock, hours=2)

    assert report.events == 0
    assert sender.sent == []


def test_a_title_added_mid_season_does_not_report_the_backlog(tracker, source, clock, sender):
    add(tracker, source, show("201", season(1, "2026-09-07", 10)))
    source.update(show("201", Season(1, "Сезон 1", 10, weekly("2026-09-07", 10) + (Episode(11, datetime(2026, 10, 20)),)), name="x"))

    poll_and_deliver(tracker, clock, hours=2)

    assert sender.sent == []  # an episode listed late with a date behind the previous look is history


def test_several_episodes_out_at_once_each_get_a_message_and_only_the_last_names_the_next_date(
    tracker, source, clock, sender
):
    add(tracker, source, airing())

    poll_and_deliver(tracker, clock, days=10)  # episodes 8 (26 Oct) and 9 (2 Nov) came while nobody looked

    assert sender.sent == [
        "📺 Идущий — вышла серия 8 из 10\nСезон 1",
        "📺 Идущий — вышла серия 9 из 10\nСезон 1 · следующая: пн, 9 ноя",
    ]


def test_an_unknown_episode_count_reads_as_a_question_mark_and_never_ends_the_season(tracker, source, clock, sender):
    add(tracker, source, show("202", Season(1, "Сезон 1", None, weekly("2026-10-05", 3))))
    source.update(show("202", Season(1, "Сезон 1", None, weekly("2026-10-05", 5))))

    poll_and_deliver(tracker, clock, hours=2)  # episodes 4 and 5 are dated 26 Oct and 2 Nov: not out yet
    assert sender.sent == []
    poll_and_deliver(tracker, clock, days=3)

    assert sender.sent == ["📺 Сериал 202 — вышла серия 4 из ?\nСезон 1 · следующая: пн, 2 ноя"]


# --- «сезон начался» и «сезон закончился» ----------------------------------------------------------


def test_the_first_episode_of_a_new_season_is_a_season_start_not_a_lost_message(tracker, source, clock, sender):
    add(tracker, source, show("210", season(1, "2026-03-02", 6), season(2, "2026-11-02", 6)))

    poll_and_deliver(tracker, clock, days=9)

    assert sender.sent == ["📺 Сериал 210 — начался сезон 2\nВышла серия 1 из 6 · следующая: пн, 9 ноя"]


def test_the_last_episode_ends_the_season(tracker, source, clock, sender):
    add(tracker, source, show("211", season(1, "2026-10-12", 3), season(2, "2026-11-09", 3)))

    poll_and_deliver(tracker, clock, days=2)

    assert sender.sent == ["📺 Сериал 211 — сезон 1 закончился\nВышла последняя серия — 3 из 3"]


def test_the_end_of_season_two_with_the_same_number_of_episodes_is_not_a_duplicate(
    tracker, source, clock, sender, session_factory
):
    add(tracker, source, show("212", season(1, "2026-10-12", 3), season(2, "2026-11-09", 3)))

    poll_and_deliver(tracker, clock, days=2)  # season 1 ends
    poll_and_deliver(tracker, clock, days=29)  # all of season 2 came meanwhile: started, one in between, ended

    assert sender.sent == [
        "📺 Сериал 212 — сезон 1 закончился\nВышла последняя серия — 3 из 3",
        "📺 Сериал 212 — начался сезон 2\nВышла серия 1 из 3",
        "📺 Сериал 212 — вышла серия 2 из 3\nСезон 2",
        "📺 Сериал 212 — сезон 2 закончился\nВышла последняя серия — 3 из 3",
    ]
    with session_factory() as s:
        keys = list(s.scalars(select(Event.dedup_key).where(Event.type == "series_season_ended")))
    assert len(keys) == len(set(keys)) == 2


def test_a_one_episode_season_both_starts_and_ends(tracker, source, clock, sender):
    add(tracker, source, show("213", season(1, "2026-03-02", 2), season(2, "2026-11-02", 1)))

    poll_and_deliver(tracker, clock, days=9)

    assert sender.sent == [
        "📺 Сериал 213 — начался сезон 2\nВышла серия 1 из 1",
        "📺 Сериал 213 — сезон 2 закончился\nВышла последняя серия — 1 из 1",
    ]


# --- «объявлена дата сезона» -----------------------------------------------------------------------


def test_a_new_season_with_a_date_is_announced_once(tracker, source, clock, sender):
    add(tracker, source, show("220", season(1, "2026-06-01", 4)))
    source.update(show("220", season(1, "2026-06-01", 4), season(2, "2027-03-01", 4)))

    poll_and_deliver(tracker, clock, hours=25)
    poll_and_deliver(tracker, clock, hours=25)

    assert sender.sent == ["📺 Сериал 220 — объявлена дата сезона 2\nПремьера: 1 марта 2027"]


def test_a_season_whose_date_appears_later_is_announced_then(tracker, source, clock, sender):
    add(tracker, source, show("221", season(1, "2026-06-01", 4), Season(2, "Сезон 2", 8, ())))
    poll_and_deliver(tracker, clock, hours=25)
    assert sender.sent == []  # the season exists but has no date yet

    source.update(show("221", season(1, "2026-06-01", 4), season(2, "2027-01-11", 8)))
    poll_and_deliver(tracker, clock, hours=25)

    assert sender.sent == ["📺 Сериал 221 — объявлена дата сезона 2\nПремьера: 11 января 2027"]


def test_a_date_known_when_the_series_was_added_is_not_news(tracker, source, clock, sender):
    silo = parse_show(load("tv_125988.json"), {n: load(f"tv_125988_season_{n}.json") for n in (1, 2, 3, 4)})
    source.update(silo)
    run(tracker.add_title("series", "125988"))  # season 4 is a stub dated 8 July 2027

    report = poll_and_deliver(tracker, clock, days=30)

    assert (report.polled, report.events) == (1, 0)
    assert sender.sent == []


# --- «дата следующей серии сдвинулась» --------------------------------------------------------------


def moved_show(first_new_date):
    """Season 1 of ten weekly episodes where the schedule from episode 8 on starts at `first_new_date`."""
    done = weekly("2026-09-07", 7)
    later = tuple(
        Episode(8 + n, datetime.fromisoformat(first_new_date) + timedelta(weeks=n)) for n in range(3)
    )
    return show("230", Season(1, "Сезон 1", 10, done + later), name="Сдвиг")


def test_the_next_episode_moved_is_reported_as_before_and_after(tracker, source, clock, sender):
    add(tracker, source, moved_show("2026-10-26"))
    source.update(moved_show("2026-11-02"))

    poll_and_deliver(tracker, clock, hours=2)
    poll_and_deliver(tracker, clock, hours=7)

    assert sender.sent == ["📺 Сдвиг — дата серии 8 сдвинулась\nСезон 1 · пн, 26 окт → пн, 2 ноя"]


def test_moving_again_is_a_new_event_and_moving_back_to_a_reported_date_is_not_repeated(tracker, source, clock, sender):
    add(tracker, source, moved_show("2026-10-26"))
    source.update(moved_show("2026-11-02"))
    poll_and_deliver(tracker, clock, hours=2)
    source.update(moved_show("2026-11-09"))
    poll_and_deliver(tracker, clock, hours=7)

    assert sender.sent == [
        "📺 Сдвиг — дата серии 8 сдвинулась\nСезон 1 · пн, 26 окт → пн, 2 ноя",
        "📺 Сдвиг — дата серии 8 сдвинулась\nСезон 1 · пн, 2 ноя → пн, 9 ноя",
    ]


def test_a_later_episode_moving_is_not_news(tracker, source, clock, sender):
    add(tracker, source, moved_show("2026-10-26"))
    changed = moved_show("2026-10-26")
    later = [e for e in changed.seasons[0].episodes]
    later[8] = Episode(9, later[8].air_at + timedelta(weeks=3))
    source.update(show("230", Season(1, "Сезон 1", 10, tuple(later)), name="Сдвиг"))

    poll_and_deliver(tracker, clock, hours=2)

    assert sender.sent == []


def test_the_move_of_the_episode_after_one_that_came_out_is_still_reported(tracker, source, clock, sender):
    add(tracker, source, moved_show("2026-10-26"))
    changed = list(moved_show("2026-10-26").seasons[0].episodes)
    changed[8] = Episode(9, datetime(2026, 11, 16))  # was 2 Nov
    source.update(show("230", Season(1, "Сезон 1", 10, tuple(changed)), name="Сдвиг"))

    poll_and_deliver(tracker, clock, days=3)  # episode 8 came out on the 26th

    assert sorted(m.split("\n")[0] for m in sender.sent) == [
        "📺 Сдвиг — вышла серия 8 из 10",
        "📺 Сдвиг — дата серии 9 сдвинулась",
    ]


def test_the_premiere_of_an_announced_season_moving_says_so(tracker, source, clock, sender):
    add(tracker, source, show("231", season(1, "2026-06-01", 4), season(2, "2027-03-01", 4), name="Анонс"))
    source.update(show("231", season(1, "2026-06-01", 4), season(2, "2027-03-15", 4), name="Анонс"))

    poll_and_deliver(tracker, clock, hours=25)

    assert sender.sent == ["📺 Анонс — премьера сезона 2 перенесена\n1 мар 2027 → 15 мар 2027"]


def test_an_episode_that_came_out_is_not_reported_as_moved(tracker, source, clock, sender):
    add(tracker, source, moved_show("2026-10-26"))

    poll_and_deliver(tracker, clock, days=2)

    assert [m.split("\n")[0] for m in sender.sent] == ["📺 Сдвиг — вышла серия 8 из 10"]


# --- «сериал закрыт или отменён» -------------------------------------------------------------------


def test_a_series_that_ended_is_reported_once(tracker, source, clock, sender):
    add(tracker, source, show("240", season(1, "2026-06-01", 4), season(2, "2026-08-03", 4), name="Финал"))
    source.update(show("240", season(1, "2026-06-01", 4), season(2, "2026-08-03", 4), status="Ended", name="Финал"))

    poll_and_deliver(tracker, clock, hours=25)
    poll_and_deliver(tracker, clock, days=8)

    assert sender.sent == ["📺 Финал — сериал закрыт\nПоследний сезон — 2"]


def test_a_cancelled_series_is_reported_as_cancelled(tracker, source, clock, sender):
    add(tracker, source, show("241", season(1, "2026-06-01", 4), name="Отмена"))
    source.update(show("241", season(1, "2026-06-01", 4), status="Canceled", name="Отмена"))

    poll_and_deliver(tracker, clock, hours=25)

    assert sender.sent == ["📺 Отмена — сериал отменён\nПоследний сезон — 1"]


def test_a_series_added_already_closed_is_not_reported(tracker, source, clock, sender):
    add(tracker, source, show("242", season(1, "2026-06-01", 4), status="Ended"))

    poll_and_deliver(tracker, clock, days=8)

    assert sender.sent == []


def test_a_series_stored_before_polling_began_records_its_status_without_an_event(
    tracker, source, clock, sender, session_factory
):
    title_id = add(tracker, source, show("243", season(1, "2026-06-01", 4), status="Ended"))
    with session_factory() as s:  # how ticket 05 left its rows: empty state, no check time
        row = s.scalar(select(SourceSnapshot).where(SourceSnapshot.title_id == title_id))
        row.state, row.next_check_at = {}, None
        s.commit()

    report = poll_and_deliver(tracker, clock, hours=1)

    assert (report.polled, report.events) == (1, 0)
    with session_factory() as s:
        assert s.scalar(select(SourceSnapshot.state).where(SourceSnapshot.title_id == title_id)) == {"show_status": "Ended"}


def test_the_closing_of_a_series_that_came_back_and_ended_again_is_reported_again(tracker, source, clock, sender):
    add(tracker, source, show("244", season(1, "2026-06-01", 4), name="Возврат"))
    source.update(show("244", season(1, "2026-06-01", 4), status="Ended", name="Возврат"))
    poll_and_deliver(tracker, clock, hours=25)
    source.update(show("244", season(1, "2026-06-01", 4), season(2, "2027-01-04", 4), name="Возврат"))
    poll_and_deliver(tracker, clock, days=8)
    source.update(show("244", season(1, "2026-06-01", 4), season(2, "2027-01-04", 4), status="Canceled", name="Возврат"))
    poll_and_deliver(tracker, clock, days=8)

    assert [m.split("\n")[0] for m in sender.sent] == [
        "📺 Возврат — сериал закрыт",
        "📺 Возврат — объявлена дата сезона 2",
        "📺 Возврат — сериал отменён",
    ]


# --- exactly once, failures, gaps in the answer ----------------------------------------------------


def test_an_event_that_could_not_be_sent_goes_out_later_and_only_once(tracker, source, clock, sender):
    add(tracker, source, airing())
    sender.failing = True
    poll_and_deliver(tracker, clock, days=2)
    assert sender.sent == []

    sender.failing = False
    run(tracker.deliver_pending())
    run(tracker.deliver_pending())
    poll_and_deliver(tracker, clock, hours=2)

    assert len(sender.sent) == 1


def test_a_failing_source_postpones_only_its_own_series(tracker, source, clock, sender, session_factory):
    broken = add(tracker, source, show("250", season(1, "2026-09-07", 10), name="Сбой"))
    add(tracker, source, show("251", season(1, "2026-09-07", 10), name="Живой"))
    source.failing.add("250")

    report = poll_and_deliver(tracker, clock, days=2)

    assert (report.polled, report.failed) == (1, 1)
    assert [m.split("\n")[0] for m in sender.sent] == ["📺 Живой — вышла серия 8 из 10"]
    assert next_check(session_factory, broken) == clock.now.replace(tzinfo=None) + timedelta(minutes=30)

    source.failing.clear()  # the broken one comes back and reports its episode
    poll_and_deliver(tracker, clock, minutes=31)
    assert [m.split("\n")[0] for m in sender.sent][-1] == "📺 Сбой — вышла серия 8 из 10"


def test_an_empty_answer_does_not_wipe_the_series_nor_announce_everything_again(tracker, source, clock, sender):
    full = show("252", season(1, "2026-06-01", 4), season(2, "2027-03-01", 4), name="Пустота")
    title_id = add(tracker, source, full)
    source.update(show("252", name="Пустота"))  # a blip: no seasons at all

    poll_and_deliver(tracker, clock, hours=25)
    assert "Сезон 2 анонсирован" in format_card(tracker.title_card(title_id))

    source.update(full)
    poll_and_deliver(tracker, clock, hours=25)

    assert sender.sent == []


def test_a_season_without_episodes_in_the_answer_keeps_what_was_known(tracker, source, clock, sender):
    title_id = add(tracker, source, show("253", season(1, "2026-09-07", 10), name="Дыра"))
    source.update(show("253", Season(1, "Сезон 1", 10, ()), name="Дыра"))
    poll_and_deliver(tracker, clock, hours=2)
    assert "Сезон 1: вышло 7 из 10" in format_card(tracker.title_card(title_id))

    source.update(show("253", season(1, "2026-09-07", 10), name="Дыра"))
    poll_and_deliver(tracker, clock, days=2)

    assert [m.split("\n")[0] for m in sender.sent] == ["📺 Дыра — вышла серия 8 из 10"]


def test_an_episode_that_lost_its_date_in_the_answer_keeps_it(tracker, source, clock, sender):
    episodes = list(weekly("2026-09-07", 10))
    add(tracker, source, show("254", Season(1, "Сезон 1", 10, tuple(episodes)), name="Без даты"))
    episodes[7] = Episode(8, None)
    source.update(show("254", Season(1, "Сезон 1", 10, tuple(episodes)), name="Без даты"))

    poll_and_deliver(tracker, clock, days=2)

    assert [m.split("\n")[0] for m in sender.sent] == ["📺 Без даты — вышла серия 8 из 10"]


# --- what polling does to the stored data ----------------------------------------------------------


def test_the_owners_watched_marks_survive_a_poll_and_new_episodes_are_stored(tracker, source, clock, session_factory):
    title_id = add(tracker, source, airing())
    run(tracker.set_season_watched(title_id, 1, True))
    source.update(show("200", Season(1, "Сезон 1", 12, weekly("2026-09-07", 12)), name="Идущий"))

    poll_and_deliver(tracker, clock, days=2)

    card = tracker.title_card(title_id)
    assert card.seasons.watched == (1,)
    assert card.seasons.current.total == 12
    with session_factory() as s:
        assert len(list(s.scalars(select(EpisodeRecord)))) == 12


def test_the_stored_state_is_stamped_with_the_poll_time(tracker, source, clock, session_factory):
    title_id = add(tracker, source, airing())

    poll_and_deliver(tracker, clock, days=2)

    with session_factory() as s:
        observed = s.scalar(select(SourceSnapshot.observed_at).where(SourceSnapshot.title_id == title_id))
    assert observed == clock.now.replace(tzinfo=None)


# --- how soon to look again ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "snapshot, expected",
    [
        (show("260", season(1, "2026-09-07", 10)), timedelta(hours=1)),  # next episode in 36 hours
        (show("261", season(1, "2026-03-02", 6), season(2, "2026-11-02", 6)), timedelta(hours=6)),  # in 9 days
        (show("262", season(1, "2026-03-02", 6), season(2, "2027-03-01", 6)), timedelta(hours=24)),  # months away
        (show("263", Season(1, "Сезон 1", 10, weekly("2026-10-03", 4))), timedelta(hours=24)),  # nothing scheduled
        (show("264", season(1, "2026-06-01", 4), status="Ended"), timedelta(days=7)),  # nothing more expected
    ],
    ids=["episode-soon", "episode-near", "season-far", "nothing-scheduled", "closed"],
)
def test_the_next_look_depends_on_how_near_the_next_episode_is(tracker, source, session_factory, snapshot, expected):
    title_id = add(tracker, source, snapshot)

    assert next_check(session_factory, title_id) == T0.replace(tzinfo=None) + expected


def test_after_a_poll_the_interval_follows_the_new_state(tracker, source, clock, session_factory):
    title_id = add(tracker, source, airing())

    poll_and_deliver(tracker, clock, days=2)  # episode 8 is out, episode 9 is a week away

    assert next_check(session_factory, title_id) == clock.now.replace(tzinfo=None) + timedelta(hours=6)


def test_a_series_is_looked_at_only_when_its_time_has_come(tracker, source, clock):
    add(tracker, source, airing())

    clock.advance(minutes=59)
    assert run(tracker.poll_due()).polled == 0
    clock.advance(minutes=2)
    assert run(tracker.poll_due()).polled == 1


# --- «Тестовое событие» ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind_id, expected",
    [
        ("series-announced", "объявлена дата сезона"),
        ("series-started", "начался сезон"),
        ("series-episode", "вышла серия"),
        ("series-ended", "закончился"),
        ("series-moved", "→"),
        ("series-closed", "сериал закрыт"),
        ("series-canceled", "сериал отменён"),
    ],
)
def test_every_series_event_is_in_the_test_event_menu(tracker, sender, kind_id, expected):
    assert kind_id in [k.id for k in tracker.test_event_kinds()]

    result = run(tracker.send_test_event(kind_id))

    assert result.delivered is True
    assert sender.sent[-1].startswith("🧪 Тестовое событие")
    assert expected in sender.sent[-1]
