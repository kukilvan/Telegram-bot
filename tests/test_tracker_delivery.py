"""Tracker core: delivery rules — working days, the 15:00 summary, quiet hours, «Сводка сейчас», folded episodes.

Driven through the facade only: fake clock, fake sender, in-memory SQLite. The owner's time zone is Asia/Jerusalem
(UTC+2 in November), so every moment below is written as the owner's clock shows it. Week of the tests:
Sun 1 Nov and Mon 2 … Thu 5 Nov are working days, Fri 6 and Sat 7 Nov are days off, Sun 8 Nov works again.
"""

import asyncio
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.tracker import delivery, movie_events, sequel_events, test_samples
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import DeliveryItem, Title
from app.tracker.seasons import Episode, Season
from app.tracker.series_events import EPISODE_OUT, SAMPLE_EPISODES_ID, message_episode
from app.tracker.sources.tmdb_movies import MovieSnapshot
from app.tracker.sources.tmdb_series import SeriesSnapshot

JERUSALEM = ZoneInfo("Asia/Jerusalem")
SUN, MON, THU, FRI, SAT, NEXT_SUN = 1, 2, 5, 6, 7, 8  # days of November 2026


def local(day, hour=12, minute=0):
    """A moment of the owner's clock as the aware moment the tracker's clock returns."""
    return datetime(2026, 11, day, hour, minute, tzinfo=JERUSALEM).astimezone(timezone.utc)


class FakeClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now

    def at(self, day, hour=12, minute=0):
        self.now = local(day, hour, minute)


class FakeSender:
    def __init__(self):
        self.sent = []  # (message, actions)
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
    tracker = Tracker(session_factory, clock=clock, sender=sender, sources={})
    set_rules(tracker)
    return tracker


def set_rules(tracker, **override):
    rules = {
        "tz_name": "Asia/Jerusalem",
        "workdays": [6, 0, 1, 2, 3],
        "summary_at": "15:00",
        "quiet_from": "21:00",
        "quiet_until": "07:30",
    }
    run(tracker.set_delivery_rules(**{**rules, **override}))


def queue(tracker, clock, day, hour, minute, text, key=None):
    """An event that appears at this moment of the owner's clock; returns its id."""
    clock.at(day, hour, minute)
    return run(tracker.record_event("test", {"text": text}, dedup_key=key or text))


def deliver(tracker, clock, day, hour, minute=0):
    clock.at(day, hour, minute)
    return run(tracker.deliver_pending())


def statuses(session_factory):
    with session_factory() as s:
        return [i.status for i in s.scalars(select(DeliveryItem).order_by(DeliveryItem.id))]


# --- working days: the summary at 15:00 ------------------------------------------------------------


def test_on_a_working_day_events_before_15_wait_and_come_as_one_summary_at_15(tracker, clock, sender):
    queue(tracker, clock, SUN, 9, 0, "первое")
    queue(tracker, clock, SUN, 11, 30, "второе")

    deliver(tracker, clock, SUN, 14, 59)
    assert sender.messages == []

    report = deliver(tracker, clock, SUN, 15, 0)

    [summary] = sender.messages
    assert summary.startswith("📋 Сводка · вс, 1 ноя")
    assert "🧪 первое" in summary and "🧪 второе" in summary
    assert report.delivered == 2


def test_the_summary_is_sent_once(tracker, clock, sender):
    queue(tracker, clock, SUN, 10, 0, "a")

    deliver(tracker, clock, SUN, 15, 0)
    deliver(tracker, clock, SUN, 15, 1)
    deliver(tracker, clock, SUN, 18, 0)

    assert len(sender.sent) == 1


def test_after_15_on_a_working_day_an_event_comes_at_once_on_its_own(tracker, clock, sender):
    queue(tracker, clock, SUN, 16, 0, "вечернее")

    deliver(tracker, clock, SUN, 16, 0)

    assert sender.messages == ["🧪 вечернее"]


def test_an_event_that_appears_at_15_sharp_is_not_part_of_the_summary(tracker, clock, sender):
    queue(tracker, clock, SUN, 10, 0, "утреннее")
    queue(tracker, clock, SUN, 15, 0, "ровно в три")

    deliver(tracker, clock, SUN, 15, 0)

    assert len(sender.sent) == 2
    assert sender.messages[0] == "🧪 ровно в три"  # the single message goes first
    assert sender.messages[1].startswith("📋 Сводка") and "утреннее" in sender.messages[1]


@pytest.mark.parametrize("day, name", [(FRI, "пятница"), (SAT, "суббота")])
def test_on_days_off_events_come_at_once_even_in_the_morning(tracker, clock, sender, day, name):
    queue(tracker, clock, day, 10, 0, name)

    deliver(tracker, clock, day, 10, 0)

    assert sender.messages == [f"🧪 {name}"]


# --- quiet hours -----------------------------------------------------------------------------------


def test_the_bot_is_silent_from_21_and_a_day_off_morning_brings_one_message_at_730(tracker, clock, sender):
    queue(tracker, clock, THU, 21, 0, "в девять")
    queue(tracker, clock, THU, 23, 59, "перед полуночью")
    queue(tracker, clock, FRI, 3, 0, "ночью")

    for hour, minute in [(21, 0), (23, 59)]:
        deliver(tracker, clock, THU, hour, minute)
    deliver(tracker, clock, FRI, 7, 29)
    assert sender.messages == []

    deliver(tracker, clock, FRI, 7, 30)

    [summary] = sender.messages
    assert summary.startswith("📋 Сводка · пт, 6 ноя")
    assert all(text in summary for text in ("в девять", "перед полуночью", "ночью"))


def test_an_event_just_before_the_night_is_not_held(tracker, clock, sender):
    queue(tracker, clock, THU, 20, 59, "на грани")

    deliver(tracker, clock, THU, 20, 59)

    assert sender.messages == ["🧪 на грани"]


def test_the_night_before_a_working_day_goes_into_the_15_summary_not_the_morning(tracker, clock, sender):
    queue(tracker, clock, SAT, 22, 0, "в субботу вечером")
    queue(tracker, clock, NEXT_SUN, 6, 0, "в воскресенье рано")

    deliver(tracker, clock, NEXT_SUN, 7, 30)
    deliver(tracker, clock, NEXT_SUN, 14, 59)
    assert sender.messages == []

    deliver(tracker, clock, NEXT_SUN, 15, 0)

    [summary] = sender.messages
    assert "в субботу вечером" in summary and "в воскресенье рано" in summary


def test_730_itself_is_open_so_an_event_then_comes_at_once_while_one_a_minute_earlier_waits(tracker, clock, sender):
    queue(tracker, clock, FRI, 7, 29, "за минуту")
    queue(tracker, clock, FRI, 7, 30, "ровно в 7:30")

    deliver(tracker, clock, FRI, 7, 30)

    assert sender.messages[0] == "🧪 ровно в 7:30"
    assert sender.messages[1].startswith("📋 Сводка") and "за минуту" in sender.messages[1]


def test_quiet_hours_across_midnight_gather_both_sides_of_midnight_into_one_message(tracker, clock, sender):
    queue(tracker, clock, FRI, 23, 50, "до полуночи")
    queue(tracker, clock, SAT, 0, 10, "после полуночи")

    deliver(tracker, clock, SAT, 0, 30)
    assert sender.messages == []
    deliver(tracker, clock, SAT, 7, 30)

    [summary] = sender.messages
    assert "до полуночи" in summary and "после полуночи" in summary


def test_a_failed_send_is_not_retried_in_the_quiet_hours_nor_on_a_working_morning(tracker, clock, sender):
    sender.failing = True
    queue(tracker, clock, THU, 20, 0, "не дошло")
    deliver(tracker, clock, THU, 20, 0)  # fails, stays in the queue
    sender.failing = False

    deliver(tracker, clock, THU, 22, 0)
    assert sender.messages == []

    deliver(tracker, clock, FRI, 7, 30)  # a day off: it goes now
    assert len(sender.sent) == 1


# --- no empty summary, «Сводка сейчас» --------------------------------------------------------------


def test_an_empty_summary_is_not_sent(tracker, clock, sender):
    report = deliver(tracker, clock, SUN, 15, 0)
    deliver(tracker, clock, FRI, 7, 30)

    assert sender.sent == []
    assert report.delivered == 0


def test_summary_now_sends_what_is_waiting_in_one_message_and_marks_it_delivered(tracker, clock, sender, session_factory):
    queue(tracker, clock, SUN, 10, 0, "раз")
    queue(tracker, clock, SUN, 10, 5, "два")
    clock.at(SUN, 10, 30)  # a working morning: the rules would keep them

    result = run(tracker.summary_now())

    assert (result.events, result.delivered) == (2, True)
    [summary] = sender.messages
    assert "раз" in summary and "два" in summary
    assert statuses(session_factory) == ["delivered", "delivered"]
    deliver(tracker, clock, SUN, 15, 0)
    assert len(sender.sent) == 1  # nothing is sent a second time


def test_summary_now_works_in_the_quiet_hours(tracker, clock, sender):
    queue(tracker, clock, THU, 22, 0, "ночное")

    clock.at(THU, 23, 0)
    result = run(tracker.summary_now())

    assert result.delivered is True
    assert "ночное" in sender.messages[0]


def test_summary_now_with_nothing_waiting_sends_nothing(tracker, clock, sender):
    result = run(tracker.summary_now())

    assert (result.events, result.delivered) == (0, False)
    assert sender.sent == []


def test_a_failed_summary_stays_queued_and_comes_with_the_next_one(tracker, clock, sender, session_factory):
    queue(tracker, clock, SUN, 10, 0, "a")
    queue(tracker, clock, SUN, 10, 1, "b")
    sender.failing = True
    clock.at(SUN, 10, 30)

    result = run(tracker.summary_now())

    assert (result.events, result.delivered) == (2, False)
    assert statuses(session_factory) == ["pending", "pending"]
    sender.failing = False
    result = run(tracker.summary_now())
    assert result.delivered is True
    assert len(sender.sent) == 1


def test_a_failed_morning_summary_is_retried_and_arrives_once(tracker, clock, sender):
    queue(tracker, clock, THU, 22, 0, "a")
    sender.failing = True
    deliver(tracker, clock, FRI, 7, 30)
    sender.failing = False

    deliver(tracker, clock, FRI, 7, 31)
    deliver(tracker, clock, FRI, 7, 32)

    assert len(sender.sent) == 1


def test_a_long_summary_is_split_into_messages_telegram_accepts(tracker, clock, sender, session_factory):
    for number in range(80):
        queue(tracker, clock, SUN, 10, 0, f"событие {number} " + "я" * 100)

    deliver(tracker, clock, SUN, 15, 0)

    assert len(sender.sent) > 1
    assert all(len(m) <= 4096 for m in sender.messages)
    assert statuses(session_factory) == ["delivered"] * 80


# --- folded episodes -------------------------------------------------------------------------------


def ensure_title(tracker, title_id, name):
    """A bare title row: an event is recorded only for a title that is in the list."""
    now = datetime(2026, 10, 24)
    with tracker.session_factory() as session:
        if session.get(Title, title_id) is None:
            session.add(
                Title(id=title_id, kind="series", name=name, original_name=name, year=2026, genres=[], status="want",
                      tracking_enabled=True, added_at=now, status_changed_at=now)
            )
            session.commit()


def episode_event(tracker, clock, title_id, season, number, day=SUN, hour=10, part=None, name="Укрытие", next_line=None):
    ensure_title(tracker, title_id, name)
    clock.at(day, hour, 0)
    payload = {"text": message_episode(name, Season(season, f"Сезон {season}", 10), number, next_line),
               "season": season, "episode": number}
    if part:
        payload["part"] = part
    return run(tracker.record_event(EPISODE_OUT, payload, f"series:{title_id}:s{season}:e{number}:out", title_id=title_id))


def test_episodes_of_one_season_of_one_title_become_one_line(tracker, clock, sender):
    episode_event(tracker, clock, 1, 2, 5)
    episode_event(tracker, clock, 1, 2, 6, next_line="следующая: пн, 12 окт")

    deliver(tracker, clock, SUN, 15, 0)

    [summary] = sender.messages
    assert summary.splitlines()[1:] == ["📺 Укрытие — вышли серии 5–6 · Сезон 2 · следующая: пн, 12 окт"]


def test_episodes_that_do_not_follow_each_other_are_listed_with_ranges(tracker, clock, sender):
    for number in (3, 5, 6, 9):
        episode_event(tracker, clock, 1, 1, number)

    deliver(tracker, clock, SUN, 15, 0)

    assert "вышли серии 3, 5–6, 9" in sender.messages[0]


def test_episodes_of_different_titles_or_seasons_are_not_folded(tracker, clock, sender):
    episode_event(tracker, clock, 1, 2, 5, name="Первый")
    episode_event(tracker, clock, 2, 2, 6, name="Второй")
    episode_event(tracker, clock, 1, 3, 7, name="Первый")

    deliver(tracker, clock, SUN, 15, 0)

    lines = sender.messages[0].splitlines()[1:]
    assert len(lines) == 3
    assert all("вышли серии" not in line for line in lines)


def test_a_single_episode_is_not_rewritten(tracker, clock, sender):
    episode_event(tracker, clock, 1, 2, 5)

    deliver(tracker, clock, SUN, 15, 0)

    assert "вышла серия 5 из 10 · Сезон 2" in sender.messages[0]


def test_parts_of_a_split_season_are_folded_separately(tracker, clock, sender):
    episode_event(tracker, clock, 1, 3, 8, part=1)
    episode_event(tracker, clock, 1, 3, 9, part=2)
    episode_event(tracker, clock, 1, 3, 10, part=2)

    deliver(tracker, clock, SUN, 15, 0)

    lines = sender.messages[0].splitlines()[1:]
    assert len(lines) == 2
    assert any("вышли серии 9–10" in line for line in lines)


def test_real_episodes_found_by_polling_are_folded_in_the_summary(session_factory, clock, sender):
    class Source:
        source_key = "tmdb_tv"

        def __init__(self):
            self.snapshot_ = None

        async def suggest(self, query):
            return []

        async def snapshot(self, external_id):
            return self.snapshot_

    def show():
        episodes = tuple(Episode(n + 1, datetime(2026, 9, 7) + timedelta(weeks=n)) for n in range(10))
        return SeriesSnapshot(
            external_id="200", name="Идущий", original_name="Идущий", year=2026, genres=[],
            seasons=[Season(1, "Сезон 1", 10, episodes)], status="Returning Series",
        )

    source = Source()
    source.snapshot_ = show()
    tracker = Tracker(session_factory, clock=clock, sender=sender, sources={"series": source})
    set_rules(tracker)
    clock.now = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)  # a Saturday: seven episodes are out
    run(tracker.add_title("series", "200"))

    clock.at(MON, 10)  # episodes 8 (26 Oct) and 9 (2 Nov) are out: a working morning
    run(tracker.poll_due())
    run(tracker.deliver_pending())
    assert sender.sent == []

    deliver(tracker, clock, MON, 15, 0)

    [summary] = sender.messages
    assert "📺 Идущий — вышли серии 8–9" in summary
    assert summary.count("\n") == 1


# --- buttons inside a summary ----------------------------------------------------------------------


def test_a_summary_keeps_the_buttons_of_its_events_and_names_the_title(session_factory, clock, sender):
    class Source:
        source_key = "tmdb_movie"

        async def suggest(self, query):
            return []

        async def snapshot(self, external_id):
            return MovieSnapshot(external_id, "Дюна: Часть третья", "Dune", 2026, [], None, None)

    tracker = Tracker(session_factory, clock=clock, sender=sender, sources={"movie": Source()})
    set_rules(tracker)
    title_id = run(tracker.add_title("movie", "1")).title_id
    clock.at(SUN, 10)
    run(tracker.record_event(
        movie_events.RELEASED, {"text": "🎬 Дюна: Часть третья — вышел в кино"}, "k1", title_id=title_id
    ))

    deliver(tracker, clock, SUN, 15, 0)

    [(message, actions)] = sender.sent
    assert message.startswith("📋 Сводка")
    assert [a.label for a in actions] == ["✅ Посмотрел: Дюна: Часть третья", "📄 Карточка: Дюна: Часть третья"]
    assert [a.arg for a in actions] == [title_id, title_id]


def test_a_summary_offers_one_card_button_per_title(session_factory, clock, sender):
    class Source:
        source_key = "tmdb_movie"

        async def suggest(self, query):
            return []

        async def snapshot(self, external_id):
            return MovieSnapshot(external_id, "Дюна: Часть третья", "Dune", 2026, [], None, None)

    tracker = Tracker(session_factory, clock=clock, sender=sender, sources={"movie": Source()})
    set_rules(tracker)
    title_id = run(tracker.add_title("movie", "1")).title_id
    clock.at(SUN, 10)
    run(tracker.record_event(movie_events.DATE_ANNOUNCED, {"text": "🎬 Дюна — дата объявлена"}, "k1", title_id=title_id))
    run(tracker.record_event(movie_events.RELEASED, {"text": "🎬 Дюна — вышел в кино"}, "k2", title_id=title_id))

    deliver(tracker, clock, SUN, 15, 0)

    [(_, actions)] = sender.sent
    assert [a.label.split(":")[0] for a in actions].count("📄 Карточка") == 1


# --- an event that missed its open window joins the summary ---------------------------------------


def test_an_event_that_outlived_the_quiet_hours_joins_the_morning_summary(tracker, clock, sender):
    sender.failing = True
    queue(tracker, clock, FRI, 12, 0, "застряло")
    deliver(tracker, clock, FRI, 12, 1)  # the send fails, the event stays in the queue
    queue(tracker, clock, FRI, 23, 0, "ночью раз")
    queue(tracker, clock, SAT, 2, 0, "ночью два")
    deliver(tracker, clock, FRI, 21, 0)  # still failing, and now the quiet hours begin
    sender.failing = False

    deliver(tracker, clock, SAT, 7, 29)
    assert sender.sent == []
    deliver(tracker, clock, SAT, 7, 30)

    [summary] = sender.messages
    assert summary.startswith("📋 Сводка")
    assert all(text in summary for text in ("застряло", "ночью раз", "ночью два"))


def test_an_event_stuck_over_a_working_morning_joins_the_15_00_summary(tracker, clock, sender):
    sender.failing = True
    queue(tracker, clock, SUN, 16, 0, "застряло")
    deliver(tracker, clock, SUN, 16, 1)
    sender.failing = False
    queue(tracker, clock, MON, 9, 0, "утреннее")

    deliver(tracker, clock, MON, 15, 0)

    [summary] = sender.messages
    assert summary.startswith("📋 Сводка")
    assert "застряло" in summary and "утреннее" in summary


def test_a_retry_in_the_same_open_window_is_a_message_of_its_own(tracker, clock, sender):
    sender.failing = True
    queue(tracker, clock, FRI, 12, 0, "повтор")
    deliver(tracker, clock, FRI, 12, 1)
    sender.failing = False

    deliver(tracker, clock, FRI, 12, 5)

    assert sender.messages == ["🧪 повтор"]


def test_without_quiet_hours_and_working_days_a_late_event_goes_out_alone(tracker, clock, sender):
    set_rules(tracker, workdays=[], quiet_from="21:00", quiet_until="21:00")
    sender.failing = True
    queue(tracker, clock, FRI, 12, 0, "опоздало")
    deliver(tracker, clock, FRI, 12, 1)
    sender.failing = False

    deliver(tracker, clock, SAT, 9, 0)

    assert sender.messages == ["🧪 опоздало"]


# --- the order of the buttons under a summary -------------------------------------------------------


def movie_event(tracker, clock, title_id, name, key):
    ensure_title(tracker, title_id, name)
    clock.at(SUN, 10)
    return run(tracker.record_event(movie_events.RELEASED, {"text": f"🎬 {name} — вышел в кино"}, key, title_id=title_id))


def sequel_event(tracker, clock, title_id, sequel_id, name):
    ensure_title(tracker, title_id, "Фильм")
    clock.at(SUN, 10)
    payload = {"text": f"🎬 Анонсировано продолжение: {name}", "kind": "movie", "sequel_id": sequel_id,
               "sequel_title": name}
    return run(tracker.record_event(sequel_events.SEQUEL_ANNOUNCED, payload, f"sequel:{sequel_id}", title_id=title_id))


def test_follow_buttons_come_first_and_are_never_cut(tracker, clock, sender):
    for number in range(1, 11):
        movie_event(tracker, clock, number, f"Фильм {number}", f"k{number}")
    sequel_event(tracker, clock, 20, 501, "Продолжение А")
    sequel_event(tracker, clock, 21, 502, "Продолжение Б")

    deliver(tracker, clock, SUN, 15, 0)

    [(message, actions)] = sender.sent
    assert len(message.splitlines()) == 13  # the header and twelve events in one summary
    assert [a.label for a in actions[:2]] == ["👀 Следить: Продолжение А", "👀 Следить: Продолжение Б"]
    assert [a.arg for a in actions[:2]] == ["movie:501", "movie:502"]
    assert len(actions) == 10  # the follow buttons, then the rest up to ten
    assert [a.label.split(":")[0] for a in actions[2:]] == ["✅ Посмотрел"] * 8


def test_watched_goes_before_card_in_the_rest_of_the_buttons(tracker, clock, sender):
    for number in range(1, 7):
        movie_event(tracker, clock, number, f"Фильм {number}", f"k{number}")

    deliver(tracker, clock, SUN, 15, 0)

    [(_, actions)] = sender.sent
    assert [a.label.split(":")[0] for a in actions] == ["✅ Посмотрел"] * 6 + ["📄 Карточка"] * 4


def test_all_follow_buttons_are_shown_even_when_there_are_more_than_ten(tracker, clock, sender):
    for number in range(12):
        sequel_event(tracker, clock, 30, 600 + number, f"Продолжение {number}")
    movie_event(tracker, clock, 31, "Фильм", "k")

    deliver(tracker, clock, SUN, 15, 0)

    [(_, actions)] = sender.sent
    assert [a.arg for a in actions] == [f"movie:{600 + n}" for n in range(12)]


def test_a_follow_button_is_not_repeated_for_one_sequel(tracker, clock, sender):
    sequel_event(tracker, clock, 30, 700, "Продолжение")
    ensure_title(tracker, 31, "Другой")
    run(tracker.record_event(
        sequel_events.SEQUEL_ANNOUNCED,
        {"text": "🎬 то же продолжение", "kind": "movie", "sequel_id": 700, "sequel_title": "Продолжение"},
        "sequel:700:again", title_id=31,
    ))

    deliver(tracker, clock, SUN, 15, 0)

    [(_, actions)] = sender.sent
    assert [a.arg for a in actions] == ["movie:700"]


# --- settings: the time zone, working days, summary hour, quiet hours ------------------------------


def test_the_rules_are_judged_in_the_time_zone_from_the_settings(tracker, clock, sender):
    queue(tracker, clock, SUN, 10, 0, "утро в Иерусалиме")  # 10:00 there is 17:00 in Tokyo
    set_rules(tracker, tz_name="Asia/Tokyo")

    deliver(tracker, clock, SUN, 10, 0)

    assert sender.messages == ["🧪 утро в Иерусалиме"]  # a Sunday afternoon in Tokyo: no longer held


def test_working_days_summary_hour_and_quiet_hours_are_settings(tracker, clock, sender):
    set_rules(tracker, workdays=[4], summary_at="10:00", quiet_from="23:00", quiet_until="05:00")
    queue(tracker, clock, FRI, 8, 0, "пятница утром")  # now Friday is the working day
    queue(tracker, clock, SUN, 8, 0, "воскресенье утром")  # and Sunday is a day off
    queue(tracker, clock, SUN, 22, 0, "воскресный вечер")  # outside the new quiet hours

    deliver(tracker, clock, SUN, 22, 0)
    assert sender.messages == ["🧪 воскресенье утром", "🧪 воскресный вечер"]

    deliver(tracker, clock, FRI, 9, 59)
    assert len(sender.sent) == 2
    deliver(tracker, clock, FRI, 10, 0)
    assert "пятница утром" in sender.messages[2]


def test_no_working_days_means_events_never_wait_for_a_summary(tracker, clock, sender):
    set_rules(tracker, workdays=[])
    queue(tracker, clock, SUN, 9, 0, "ранним утром")

    deliver(tracker, clock, SUN, 9, 0)

    assert sender.messages == ["🧪 ранним утром"]


def test_settings_survive_a_restart_and_win_over_the_default_time_zone(session_factory, clock, sender):
    first = Tracker(session_factory, clock=clock, sender=sender, sources={})
    set_rules(first, tz_name="Asia/Tokyo", workdays=[0], summary_at="09:30", quiet_from="22:00", quiet_until="06:00")

    second = Tracker(session_factory, clock=clock, sender=sender, sources={}, default_tz=ZoneInfo("Europe/Paris"))

    rules = run(second.delivery_rules())
    assert (rules.tz, rules.workdays) == (ZoneInfo("Asia/Tokyo"), frozenset({0}))
    assert (rules.summary_at, rules.quiet_from, rules.quiet_until) == (time(9, 30), time(22, 0), time(6, 0))


def test_without_settings_the_time_zone_is_the_one_the_core_was_given(session_factory, clock, sender):
    tracker = Tracker(session_factory, clock=clock, sender=sender, sources={}, default_tz=ZoneInfo("Europe/Paris"))

    assert run(tracker.delivery_rules()).tz == ZoneInfo("Europe/Paris")


def test_the_built_in_defaults_are_the_owners_week():
    rules = delivery.DeliveryRules()

    assert rules.workdays == frozenset({6, 0, 1, 2, 3})  # Sunday to Thursday
    assert (rules.summary_at, rules.quiet_from, rules.quiet_until) == (time(15, 0), time(21, 0), time(7, 30))


@pytest.mark.parametrize(
    "bad",
    [{"tz_name": "Mars/Olympus"}, {"workdays": [7]}, {"workdays": [-1]}, {"summary_at": "25:00"}, {"quiet_from": "evening"}],
)
def test_a_wrong_setting_is_refused_and_nothing_is_changed(tracker, bad):
    before = run(tracker.delivery_rules())

    with pytest.raises(ValueError):
        run(tracker.set_delivery_rules(**{"workdays": [1], **bad}))

    assert run(tracker.delivery_rules()) == before


def test_a_summary_hour_inside_the_quiet_hours_is_refused_and_the_rules_stay(tracker):
    before = run(tracker.delivery_rules())

    with pytest.raises(ValueError, match=r"час сводки 22:00 попадает в тихие часы 21:00–07:30"):
        run(tracker.set_delivery_rules(summary_at="22:00"))

    assert run(tracker.delivery_rules()) == before


def test_the_whole_rules_are_checked_not_only_what_was_passed(tracker):
    before = run(tracker.delivery_rules())  # the summary is at 15:00

    with pytest.raises(ValueError, match="15:00"):
        run(tracker.set_delivery_rules(quiet_from="14:00", quiet_until="16:00"))

    assert run(tracker.delivery_rules()) == before


def test_a_summary_hour_and_quiet_hours_may_be_changed_together_when_they_fit(tracker):
    run(tracker.set_delivery_rules(summary_at="22:00", quiet_from="23:00", quiet_until="06:00"))

    rules = run(tracker.delivery_rules())
    assert (rules.summary_at, rules.quiet_from, rules.quiet_until) == (time(22, 0), time(23, 0), time(6, 0))


def test_without_quiet_hours_any_summary_hour_is_allowed(tracker):
    run(tracker.set_delivery_rules(quiet_from="21:00", quiet_until="21:00", summary_at="22:00"))

    assert run(tracker.delivery_rules()).summary_at == time(22, 0)


def test_the_summary_hour_at_the_end_of_the_quiet_hours_is_allowed(tracker):
    run(tracker.set_delivery_rules(summary_at="07:30"))  # the quiet hours end at 07:30: that minute is already open

    assert run(tracker.delivery_rules()).summary_at == time(7, 30)


def test_two_changes_at_once_cannot_slip_past_the_check(tracker):
    async def both():
        return await asyncio.gather(
            tracker.set_delivery_rules(summary_at="22:00", quiet_from="23:00", quiet_until="06:00"),
            tracker.set_delivery_rules(quiet_from="21:00", quiet_until="07:30"),
            return_exceptions=True,
        )

    run(both())

    rules = run(tracker.delivery_rules())
    assert not rules.is_quiet(datetime.combine(datetime(2026, 1, 1), rules.summary_at))


def test_rules_stored_before_the_check_do_not_block_a_change_of_something_else(tracker, session_factory):
    from app.tracker.models import SettingRecord

    with session_factory() as s:  # a summary hour inside the quiet hours, as an earlier version allowed
        s.get(SettingRecord, "summary_at").value = "22:00"
        s.commit()

    run(tracker.set_delivery_rules(workdays=[1]))
    with pytest.raises(ValueError, match="22:00"):
        run(tracker.set_delivery_rules(quiet_until="08:00"))  # a change of the hours themselves is still checked

    assert run(tracker.delivery_rules()).workdays == frozenset({1})


def test_rules_that_could_never_send_a_summary_are_still_read_and_a_warning_is_logged(caplog):
    rules = delivery.DeliveryRules(
        workdays=frozenset(range(7)), summary_at=time(22, 0), quiet_from=time(21, 0), quiet_until=time(7, 30)
    )  # stored before the check existed

    with caplog.at_level("WARNING"):
        release, waited = rules.release(datetime(2026, 11, 1, 10, 0))

    assert waited is True and rules.holds(release)
    assert any("22:00" in record.getMessage() for record in caplog.records)


# --- «Тестовое событие» with a substituted time ----------------------------------------------------


def test_a_test_event_without_a_time_goes_out_at_once_even_in_the_quiet_hours(tracker, clock, sender):
    clock.at(THU, 22, 0)

    result = run(tracker.send_test_event("ping"))

    assert result.delivered is True and result.delivered_at_once is True
    assert len(sender.sent) == 1


def test_a_substituted_time_on_a_working_morning_holds_the_sample_and_plays_out_the_summary(tracker, clock, sender):
    result = run(tracker.send_test_event(SAMPLE_EPISODES_ID, at=local(SUN, 10)))

    assert result.delivered is True and result.delivered_at_once is False
    assert result.held_until == local(SUN, 15)
    [summary] = sender.messages
    assert summary.startswith("📋 Сводка") and "вышли серии 5–6" in summary


def test_a_substituted_time_after_the_summary_hour_sends_the_sample_at_once(tracker, clock, sender):
    result = run(tracker.send_test_event(SAMPLE_EPISODES_ID, at=local(SUN, 16)))

    assert result.delivered_at_once is True and result.held_until is None
    assert len(sender.sent) == 2  # two episodes, each in its own message
    assert not any(m.startswith("📋") for m in sender.messages)


def test_a_substituted_time_leaves_the_real_queue_alone(tracker, clock, sender, session_factory):
    queue(tracker, clock, SUN, 9, 0, "настоящее")

    run(tracker.send_test_event("ping", at=local(SUN, 10)))

    assert not any("настоящее" in m for m in sender.messages)
    assert statuses(session_factory)[0] == "pending"
    deliver(tracker, clock, SUN, 15, 0)
    assert "настоящее" in sender.messages[-1]


def test_a_failing_sender_during_a_substituted_time_is_not_reported_as_held(tracker, clock, sender):
    sender.failing = True

    result = run(tracker.send_test_event("ping", at=local(FRI, 12)))

    assert result.delivered is False and result.held_until is None


CHECK_OUTCOMES = {
    "work-morning": local(SUN, 15),
    "work-afternoon": None,
    "friday": None,
    "saturday": None,
    "night-before-day-off": local(FRI, 7, 30),
    "night-before-workday": local(NEXT_SUN, 15),
    "quiet-ends": local(FRI, 7, 30),
    "quiet-ended": None,
}


def test_every_delivery_check_has_an_expected_outcome():
    assert set(CHECK_OUTCOMES) == {s.id for s in test_samples.DELIVERY_CHECKS}


@pytest.mark.parametrize("check", test_samples.DELIVERY_CHECKS, ids=lambda s: s.id)
def test_each_delivery_check_of_the_menu_is_the_moment_it_names_and_ends_as_the_rules_say(tracker, clock, sender, check):
    clock.at(SUN, 12)
    moment = run(tracker.delivery_check_moment(check))

    local_moment = moment.astimezone(JERUSALEM)
    assert (local_moment.weekday(), local_moment.time()) == (check.weekday, check.at)
    assert moment > clock()

    result = run(tracker.send_test_event(SAMPLE_EPISODES_ID, at=moment))

    expected = CHECK_OUTCOMES[check.id]
    assert result.delivered is True
    assert result.delivered_at_once is (expected is None)
    if expected is not None:
        assert result.held_until.astimezone(JERUSALEM).time() == expected.astimezone(JERUSALEM).time()
        assert result.held_until.astimezone(JERUSALEM).weekday() == expected.astimezone(JERUSALEM).weekday()


def test_the_delivery_check_moment_today_counts_when_it_is_still_ahead(tracker, clock):
    clock.at(SUN, 9)
    check = test_samples.delivery_check_by_id("work-morning")  # Sunday 10:00

    assert run(tracker.delivery_check_moment(check)) == local(SUN, 10)


# --- the pure helpers ------------------------------------------------------------------------------


def test_episode_ranges():
    assert delivery.episode_ranges([6, 5]) == "5–6"
    assert delivery.episode_ranges([1, 2, 3, 7, 9, 10]) == "1–3, 7, 9–10"
    assert delivery.episode_ranges([4, 4]) == "4"


def test_time_parsing():
    assert delivery.parse_time("07:30") == time(7, 30)
    assert delivery.parse_time(time(15, 0, 30)) == time(15, 0)
    with pytest.raises(ValueError):
        delivery.parse_time("7")


def test_equal_quiet_bounds_mean_no_quiet_hours():
    rules = delivery.DeliveryRules(quiet_from=time(21, 0), quiet_until=time(21, 0), workdays=frozenset())

    assert not rules.holds(datetime(2026, 11, 1, 23, 0))
    assert not rules.holds(datetime(2026, 11, 1, 3, 0))


def test_quiet_hours_inside_one_day():
    rules = delivery.DeliveryRules(quiet_from=time(1, 0), quiet_until=time(5, 0), workdays=frozenset())

    assert [rules.holds(datetime(2026, 11, 1, h, m)) for h, m in [(0, 59), (1, 0), (4, 59), (5, 0)]] == [
        False, True, True, False,
    ]
    assert rules.release(datetime(2026, 11, 1, 3, 0)) == (datetime(2026, 11, 1, 5, 0), True)


# --- the next start of silence ---------------------------------------------------------------------


def test_the_next_silence_after_a_midday_on_a_day_off_is_the_start_of_the_quiet_hours():
    rules = delivery.DeliveryRules()  # UTC, Sunday to Thursday, summary 15:00, quiet 21:00–07:30

    assert rules.next_silence(datetime(2026, 11, 6, 12, 0)) == datetime(2026, 11, 6, 21, 0)  # a Friday


def test_the_next_silence_after_a_working_afternoon_is_the_quiet_hours_not_midnight():
    rules = delivery.DeliveryRules()

    assert rules.next_silence(datetime(2026, 11, 1, 16, 0)) == datetime(2026, 11, 1, 21, 0)  # a Sunday


def test_the_next_silence_is_the_midnight_of_a_working_day_when_it_comes_first():
    rules = delivery.DeliveryRules(quiet_from=time(1, 0), quiet_until=time(2, 0))

    # Saturday 10:00: Sunday works, so its morning is silent from its midnight, before the quiet hours at 01:00
    assert rules.next_silence(datetime(2026, 11, 7, 10, 0)) == datetime(2026, 11, 8, 0, 0)


def test_the_next_silence_is_the_quiet_hours_when_they_come_before_midnight():
    rules = delivery.DeliveryRules(quiet_from=time(23, 30), quiet_until=time(0, 30))

    assert rules.next_silence(datetime(2026, 11, 7, 10, 0)) == datetime(2026, 11, 7, 23, 30)


def test_without_quiet_hours_the_next_silence_is_the_midnight_of_the_next_working_day():
    rules = delivery.DeliveryRules(quiet_from=time(21, 0), quiet_until=time(21, 0))

    assert rules.next_silence(datetime(2026, 11, 6, 12, 0)) == datetime(2026, 11, 8, 0, 0)  # Friday, then Sunday


def test_without_working_days_the_next_silence_is_the_start_of_the_quiet_hours():
    rules = delivery.DeliveryRules(workdays=frozenset())

    assert rules.next_silence(datetime(2026, 11, 6, 12, 0)) == datetime(2026, 11, 6, 21, 0)


def test_there_is_no_silence_without_quiet_hours_and_working_days():
    rules = delivery.DeliveryRules(workdays=frozenset(), quiet_from=time(21, 0), quiet_until=time(21, 0))

    assert rules.next_silence(datetime(2026, 11, 6, 12, 0)) is None


def test_a_summary_hour_at_midnight_leaves_no_working_morning_to_be_silent_in():
    rules = delivery.DeliveryRules(summary_at=time(0, 0), quiet_from=time(21, 0), quiet_until=time(21, 0))

    assert rules.next_silence(datetime(2026, 11, 6, 12, 0)) is None


def test_the_next_silence_is_strictly_after_the_moment():
    rules = delivery.DeliveryRules()

    assert rules.next_silence(datetime(2026, 11, 6, 21, 0)) == datetime(2026, 11, 7, 21, 0)


def test_the_next_silence_is_found_on_the_owners_clock_and_returned_in_utc():
    rules = delivery.DeliveryRules(tz=JERUSALEM)  # UTC+2 in November

    assert rules.next_silence(datetime(2026, 11, 6, 10, 0)) == datetime(2026, 11, 6, 19, 0)  # 21:00 there
