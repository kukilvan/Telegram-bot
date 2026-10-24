"""Tracker core: anime events found by polling and delivered once, and the poll schedule.

Driven through the facade only: fake clock, the real Shikimori adapter over the saved real answers of the audit's
franchises (edited per test to say what changed since), AniList answers saved from the real service, fake sender,
in-memory SQLite. No network. The owner lives in Asia/Jerusalem: after 25 Oct 2026 that is UTC+2.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from anime_fakes import FakeShikimori, real_anilist
from app.tracker.cards import format_card
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import EpisodeRecord, Event, MovieRecord, PartRecord, SeasonRecord, SourceSnapshot, Title
from app.tracker.sources.shikimori_anime import ShikimoriAnimeSource

T0 = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)  # a Saturday
ISRAEL = ZoneInfo("Asia/Jerusalem")

KUSURIYA, JJK, ABYSS = "54492", "40748", "34599"
K3, K3_PART_2, JJK_4 = "61987", "62841", "63824"  # Shikimori ids of the entries the tests change
AL_K3, AL_K3_PART_2, AL_JJK_4 = 195516, 200927, 209895  # the same entries in AniList

KUSURIYA_NAME = "Монолог фармацевта (Kusuriya no Hitorigoto)"
JJK_NAME = "Магическая битва (Jujutsu Kaisen)"


class FakeClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, **delta):
        self.now += timedelta(**delta)

    def set(self, year, month, day, hour=12, minute=0):
        self.now = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


class FakeSender:
    def __init__(self):
        self.sent = []

    async def send(self, message, actions=()):
        self.sent.append(message)


def run(coro):
    return asyncio.run(coro)


def shikimori_at(year, month, day, hour=14, minute=0):
    """A moment as Shikimori writes it (with an offset)."""
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc).isoformat()


@pytest.fixture
def clock():
    return FakeClock(T0)


@pytest.fixture
def sender():
    return FakeSender()


@pytest.fixture
def shikimori():
    return FakeShikimori()


@pytest.fixture
def anilist():
    return real_anilist()


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def tracker(session_factory, clock, sender, shikimori, anilist):
    return Tracker(
        session_factory,
        clock=clock,
        sender=sender,
        sources={"anime": ShikimoriAnimeSource(shikimori, anilist)},
        local_tz=ISRAEL,
    )


def add(tracker, external_id):
    return run(tracker.add_title("anime", external_id)).title_id


def poll_and_deliver(tracker, clock, **advance):
    clock.advance(**advance)
    report = run(tracker.poll_due())
    run(tracker.deliver_pending())
    return report


def next_check(session_factory, title_id):
    with session_factory() as s:
        return s.scalar(select(SourceSnapshot.next_check_at).where(SourceSnapshot.title_id == title_id))


def event_keys(session_factory, type_):
    with session_factory() as s:
        return list(s.scalars(select(Event.dedup_key).where(Event.type == type_)))


# --- «вышла серия N» -------------------------------------------------------------------------------


def test_an_episode_is_delivered_once_with_the_number_that_came_out_and_the_next_moment_in_the_owners_time(
    tracker, shikimori, anilist, clock, sender
):
    add(tracker, KUSURIYA)  # episodes 1-4 are out, AniList says episode 5 is on Fri 30 Oct at 14:00 UTC
    anilist.next_episode(AL_K3, 6, datetime(2026, 11, 6, 14, 0))  # so episode 5 came out; the next one is 6

    poll_and_deliver(tracker, clock, days=6, hours=3)
    poll_and_deliver(tracker, clock, hours=7)
    poll_and_deliver(tracker, clock, days=2)

    assert sender.sent == [
        f"🎌 {KUSURIYA_NAME} — вышла серия 5\n"
        "Сезон 3, часть 1: вышло 5 из 12 · следующая: пт, 6 ноя в 16:00"
    ]


def test_several_episodes_out_at_once_each_get_a_message_and_only_the_last_names_the_next_moment(
    tracker, anilist, clock, sender
):
    add(tracker, KUSURIYA)
    anilist.next_episode(AL_K3, 8, datetime(2026, 11, 20, 14, 0))  # episodes 5, 6 and 7 came while nobody looked

    poll_and_deliver(tracker, clock, days=14)

    assert sender.sent == [
        f"🎌 {KUSURIYA_NAME} — вышла серия 5\nСезон 3, часть 1: вышло 5 из 12",
        f"🎌 {KUSURIYA_NAME} — вышла серия 6\nСезон 3, часть 1: вышло 6 из 12",
        f"🎌 {KUSURIYA_NAME} — вышла серия 7\nСезон 3, часть 1: вышло 7 из 12 · следующая: пт, 20 ноя в 16:00",
    ]


def test_the_owners_day_of_the_week_is_the_local_one_not_the_one_in_utc(tracker, anilist, clock, sender):
    add(tracker, KUSURIYA)
    anilist.next_episode(AL_K3, 6, datetime(2026, 11, 7, 23, 30))  # Saturday night in UTC, already Sunday in Jerusalem

    poll_and_deliver(tracker, clock, days=6, hours=3)

    assert sender.sent[-1].endswith("следующая: вс, 8 ноя в 01:30")


def test_nothing_is_announced_right_after_adding(tracker, clock, sender):
    for franchise in (KUSURIYA, JJK, ABYSS, "21"):
        add(tracker, franchise)

    report = poll_and_deliver(tracker, clock, hours=25)

    assert (report.polled, report.failed, report.events) == (4, 0, 0)  # even where AniList and Shikimori disagree
    assert sender.sent == []


def test_an_episode_still_arrives_from_shikimori_when_anilist_is_down(tracker, shikimori, anilist, clock, sender, session_factory):
    add(tracker, KUSURIYA)
    anilist.broken = True
    shikimori.by_id[K3].update(episodesAired=5, nextEpisodeAt=shikimori_at(2026, 11, 6))

    poll_and_deliver(tracker, clock, days=6, hours=3)

    assert sender.sent == [
        f"🎌 {KUSURIYA_NAME} — вышла серия 5\nСезон 3, часть 1: вышло 5 из 12 · следующая: пт, 6 ноя в 16:00"
    ]
    with session_factory() as s:  # the AniList ids found at the start are still there
        assert [p.anilist_id for p in s.scalars(select(PartRecord).order_by(PartRecord.id))] == [
            "161645", "176301", "195516", "200927"
        ]


# --- начало и конец части и сезона ------------------------------------------------------------------


def finish_first_part_of_season_three(shikimori, anilist):
    shikimori.by_id[K3].update(episodesAired=12, nextEpisodeAt=None, status="released")
    anilist.finish(AL_K3, 12)


def test_the_last_episode_of_a_part_ends_it_and_names_the_start_of_the_next_part(tracker, shikimori, anilist, clock, sender):
    shikimori.by_id[K3].update(episodesAired=11, nextEpisodeAt=shikimori_at(2026, 10, 26))
    anilist.next_episode(AL_K3, 12, datetime(2026, 10, 26, 14, 0))
    add(tracker, KUSURIYA)
    finish_first_part_of_season_three(shikimori, anilist)

    poll_and_deliver(tracker, clock, days=3)
    poll_and_deliver(tracker, clock, days=1)

    assert sender.sent == [
        f"🎌 {KUSURIYA_NAME} — закончилась часть 1 сезона 3\n"
        "Вышла последняя серия части — 12; часть 2 — с 1 апреля"
    ]


def test_anilist_alone_can_end_a_part_while_shikimori_is_behind(tracker, shikimori, anilist, clock, sender):
    shikimori.by_id[K3].update(episodesAired=11, nextEpisodeAt=shikimori_at(2026, 10, 26))
    anilist.next_episode(AL_K3, 12, datetime(2026, 10, 26, 14, 0))
    add(tracker, KUSURIYA)
    anilist.finish(AL_K3, 12)  # Shikimori still says «ongoing, 11 episodes»

    poll_and_deliver(tracker, clock, days=3)

    assert [m.split("\n")[0] for m in sender.sent] == [f"🎌 {KUSURIYA_NAME} — закончилась часть 1 сезона 3"]


@pytest.mark.parametrize("known_to_anilist", [True, False], ids=["anilist-has-not-caught-up", "anilist-does-not-know-it"])
def test_the_change_of_the_current_part_is_not_lost_when_anilist_has_no_data_for_it(
    shikimori, session_factory, clock, sender, known_to_anilist
):
    anilist = real_anilist(without=() if known_to_anilist else (62841,))
    tracker = Tracker(
        session_factory, clock=clock, sender=sender, local_tz=ISRAEL,
        sources={"anime": ShikimoriAnimeSource(shikimori, anilist)},
    )
    finish_first_part_of_season_three(shikimori, anilist)
    shikimori.by_id[K3_PART_2]["airedOn"] = {"date": "2026-11-20", "year": 2026}
    add(tracker, KUSURIYA)  # part 2 is announced for 20 Nov
    shikimori.by_id[K3_PART_2].update(status="ongoing", episodesAired=1, nextEpisodeAt=shikimori_at(2026, 11, 27))

    poll_and_deliver(tracker, clock, days=28)

    assert sender.sent == [
        f"🎌 {KUSURIYA_NAME} — началась часть 2 сезона 3\nВышла серия 13 · следующая: пт, 27 ноя в 16:00"
    ]


def test_the_change_of_the_current_part_is_not_lost_while_anilist_is_down(tracker, shikimori, anilist, clock, sender):
    finish_first_part_of_season_three(shikimori, anilist)
    shikimori.by_id[K3_PART_2]["airedOn"] = {"date": "2026-11-20", "year": 2026}
    add(tracker, KUSURIYA)
    anilist.broken = True
    shikimori.by_id[K3_PART_2].update(status="ongoing", episodesAired=1, nextEpisodeAt=shikimori_at(2026, 11, 27))

    poll_and_deliver(tracker, clock, days=28)

    assert [m.split("\n")[0] for m in sender.sent] == [f"🎌 {KUSURIYA_NAME} — началась часть 2 сезона 3"]


def announce_the_fourth_season(shikimori):
    shikimori.by_id[JJK_4].update(airedOn={"date": "2026-11-05", "year": 2026}, episodes=12)


def start_the_fourth_season(shikimori):
    shikimori.by_id[JJK_4].update(status="ongoing", episodesAired=1, nextEpisodeAt=shikimori_at(2026, 11, 12, 11, 30))


def test_a_new_season_is_announced_and_its_first_episode_is_not_lost(tracker, shikimori, anilist, clock, sender):
    add(tracker, JJK)  # season 4 exists, without a date
    announce_the_fourth_season(shikimori)

    poll_and_deliver(tracker, clock, hours=25)
    start_the_fourth_season(shikimori)
    anilist.next_episode(AL_JJK_4, 2, datetime(2026, 11, 12, 11, 30))
    poll_and_deliver(tracker, clock, days=11)
    poll_and_deliver(tracker, clock, days=1)

    assert sender.sent == [
        f"🎌 {JJK_NAME} — объявлена дата сезона 4\nПремьера: 5 ноября 2026",
        f"🎌 {JJK_NAME} — начался сезон 4\nВышла серия 1 из 12 · следующая: чт, 12 ноя в 13:30",
    ]


def test_the_first_episode_of_a_new_season_arrives_without_any_anilist_data_too(tracker, shikimori, anilist, clock, sender):
    anilist.broken = True
    add(tracker, JJK)
    announce_the_fourth_season(shikimori)
    poll_and_deliver(tracker, clock, hours=25)

    start_the_fourth_season(shikimori)
    poll_and_deliver(tracker, clock, days=11)

    assert sender.sent[-1] == f"🎌 {JJK_NAME} — начался сезон 4\nВышла серия 1 из 12 · следующая: чт, 12 ноя в 13:30"


def test_a_season_with_the_same_number_of_episodes_as_the_one_before_still_ends(tracker, shikimori, clock, sender, session_factory):
    shikimori.by_id.update(two_short_seasons())
    add(tracker, "9001")

    shikimori.by_id["9001"].update(status="released", episodesAired=2, nextEpisodeAt=None)
    poll_and_deliver(tracker, clock, days=3)  # season 1 ends
    shikimori.by_id["9002"].update(status="released", episodesAired=2)
    poll_and_deliver(tracker, clock, days=42)  # all of season 2 came meanwhile

    assert sender.sent == [
        "🎌 Тест (Test) — сезон 1 закончился\nВышла последняя серия — 2 из 2",
        "🎌 Тест (Test) — начался сезон 2\nВышла серия 1 из 2",
        "🎌 Тест (Test) — сезон 2 закончился\nВышла последняя серия — 2 из 2",
    ]
    keys = event_keys(session_factory, "series_season_ended")
    assert len(keys) == len(set(keys)) == 2


def entry(id_, status, aired, aired_on, next_at=None, related=()):
    return {
        "id": id_, "malId": id_, "name": "Test", "russian": "Тест", "english": "Test", "kind": "tv", "status": status,
        "episodes": 2, "episodesAired": aired, "nextEpisodeAt": next_at, "duration": 24, "airedOn": {"date": aired_on},
        "releasedOn": {"date": None}, "franchise": "test", "poster": None, "genres": [],
        "related": [{"relationKind": kind, "relationText": "", "anime": {"id": other, "kind": "tv"}} for kind, other in related],
    }


def two_short_seasons():
    return {
        "9001": entry("9001", "ongoing", 1, "2026-10-20", shikimori_at(2026, 10, 26), related=[("sequel", "9002")]),
        "9002": entry("9002", "anons", 0, "2026-12-07", related=[("prequel", "9001")]),
    }


# --- «дата следующей серии сдвинулась» ---------------------------------------------------------------


def test_a_moved_episode_is_reported_as_before_and_after_in_the_owners_time(tracker, anilist, clock, sender):
    add(tracker, KUSURIYA)
    anilist.next_episode(AL_K3, 5, datetime(2026, 11, 2, 14, 0))  # episode 5 moves from Fri 30 Oct to Mon 2 Nov

    poll_and_deliver(tracker, clock, hours=7)
    poll_and_deliver(tracker, clock, hours=7)

    assert sender.sent == [
        f"🎌 {KUSURIYA_NAME} — дата серии 5 сдвинулась\nСезон 3 · пт, 30 окт в 16:00 → пн, 2 ноя в 16:00"
    ]


def test_a_moved_episode_is_reported_once_and_the_one_after_the_move_arrives_on_the_new_day(tracker, anilist, clock, sender):
    add(tracker, KUSURIYA)
    anilist.next_episode(AL_K3, 5, datetime(2026, 11, 2, 14, 0))
    poll_and_deliver(tracker, clock, hours=7)

    anilist.next_episode(AL_K3, 6, datetime(2026, 11, 9, 14, 0))
    poll_and_deliver(tracker, clock, days=9)  # Mon 2 Nov passed: episode 5 is out

    assert [m.split("\n")[0] for m in sender.sent] == [
        f"🎌 {KUSURIYA_NAME} — дата серии 5 сдвинулась",
        f"🎌 {KUSURIYA_NAME} — вышла серия 5",
    ]


def test_a_second_move_of_the_same_episode_on_the_same_day_is_reported_too(tracker, anilist, clock, sender):
    add(tracker, KUSURIYA)
    anilist.next_episode(AL_K3, 5, datetime(2026, 10, 30, 18, 0))  # 14:00 -> 18:00 UTC
    poll_and_deliver(tracker, clock, hours=7)
    anilist.next_episode(AL_K3, 5, datetime(2026, 10, 30, 20, 0))  # and then 18:00 -> 20:00 UTC
    poll_and_deliver(tracker, clock, hours=7)

    assert [m.split("\n")[1] for m in sender.sent] == [
        "Сезон 3 · пт, 30 окт в 16:00 → пт, 30 окт в 20:00",
        "Сезон 3 · пт, 30 окт в 20:00 → пт, 30 окт в 22:00",
    ]


def test_the_exact_moment_replacing_a_day_only_date_of_the_same_day_is_not_a_move(tracker, shikimori, anilist, clock, sender):
    finish_first_part_of_season_three(shikimori, anilist)  # nothing is ahead but part 2
    add(tracker, KUSURIYA)  # part 2 is announced for the day 1 April 2027, with no hour
    anilist.next_episode(AL_K3_PART_2, 1, datetime(2027, 4, 1, 9, 0))  # AniList knows the hour of that day

    poll_and_deliver(tracker, clock, hours=7)

    assert sender.sent == []


def test_a_schedule_numbered_on_through_the_season_is_not_taken_for_the_parts_own(tracker, anilist, clock, sender):
    add(tracker, KUSURIYA)
    anilist.next_episode(AL_K3, 15, datetime(2026, 11, 6, 14, 0))  # the part has 12 episodes: this is not its numbering

    report = poll_and_deliver(tracker, clock, days=7)

    assert (report.failed, report.events) == (0, 1)  # episode 5 came out by the clock, nothing else is invented
    assert sender.sent[0].split("\n")[0] == f"🎌 {KUSURIYA_NAME} — вышла серия 5"
    assert len(sender.sent) == 1


# --- сбойный или пустой ответ источника не затирает прошлое -------------------------------------------


def card_line(tracker, title_id):
    return next(line for line in format_card(tracker.title_card(title_id)).splitlines() if line.startswith("Сезон 3"))


@pytest.mark.parametrize("break_it", [
    lambda shikimori, anilist: setattr(anilist, "broken", True),
    lambda shikimori, anilist: setattr(anilist, "schedules_broken", True),
    lambda shikimori, anilist: anilist.schedules.clear(),
], ids=["anilist-down", "schedule-request-fails", "empty-answer"])
def test_a_broken_or_empty_anilist_answer_changes_nothing(
    tracker, shikimori, anilist, clock, sender, session_factory, break_it
):
    title = add(tracker, KUSURIYA)
    anilist.next_episode(AL_K3, 5, datetime(2026, 11, 2, 14, 0))  # AniList moved episode 5 ...
    poll_and_deliver(tracker, clock, hours=7)
    sender.sent.clear()
    before = card_line(tracker, title)
    break_it(shikimori, anilist)  # ... and then stops answering, while Shikimori still has the old date

    report = poll_and_deliver(tracker, clock, hours=7)

    assert (report.polled, report.failed, report.events) == (1, 0, 0)
    assert sender.sent == []
    assert card_line(tracker, title) == before == "Сезон 3, часть 1: вышло 4 из 12, следующая — пн, 2 ноя в 16:00"


def test_a_shikimori_answer_that_forgot_the_aired_episodes_does_not_erase_them(tracker, shikimori, anilist, clock, sender, session_factory):
    title = add(tracker, KUSURIYA)
    with session_factory() as s:
        stored = len(list(s.scalars(select(EpisodeRecord))))
    anilist.schedules.clear()
    shikimori.by_id[K3].update(episodesAired=0, nextEpisodeAt=None)

    report = poll_and_deliver(tracker, clock, hours=7)

    assert (report.failed, report.events) == (0, 0)
    assert card_line(tracker, title).startswith("Сезон 3, часть 1: вышло 4 из 12")
    with session_factory() as s:
        assert len(list(s.scalars(select(EpisodeRecord)))) == stored  # nothing was deleted


def test_a_failing_shikimori_postpones_the_title_and_loses_nothing(tracker, shikimori, anilist, clock, sender, session_factory):
    title = add(tracker, KUSURIYA)
    shikimori.broken = True

    report = poll_and_deliver(tracker, clock, hours=7)

    assert (report.polled, report.failed) == (0, 1)
    assert next_check(session_factory, title) == clock.now.replace(tzinfo=None) + timedelta(minutes=30)
    shikimori.broken = False
    anilist.next_episode(AL_K3, 6, datetime(2026, 11, 6, 14, 0))
    poll_and_deliver(tracker, clock, days=6)

    assert [m.split("\n")[0] for m in sender.sent] == [f"🎌 {KUSURIYA_NAME} — вышла серия 5"]


# --- фильмы франшизы ---------------------------------------------------------------------------------


def test_a_film_that_comes_out_is_reported_once(tracker, shikimori, clock, sender):
    add(tracker, ABYSS)  # «Тайна пробуждения. Часть 2» is announced
    shikimori.by_id["65248"].update(status="released", airedOn={"date": "2026-10-25", "year": 2026})

    poll_and_deliver(tracker, clock, hours=25)
    poll_and_deliver(tracker, clock, hours=25)

    assert sender.sent == ["🎌 Созданный в Бездне (Made in Abyss) — вышел фильм франшизы\n«Созданный в бездне: Тайна пробуждения. Часть 2»"]


def test_a_film_that_is_announced_is_reported_once_with_its_date_and_then_when_it_comes_out(tracker, shikimori, clock, sender):
    add(tracker, JJK)
    shikimori.by_id["99001"] = film("99001", "Новый фильм", "anons", "2027-02-05")
    link_film(shikimori, JJK, "99001")

    poll_and_deliver(tracker, clock, hours=25)
    poll_and_deliver(tracker, clock, hours=25)
    shikimori.by_id["99001"]["status"] = "released"
    poll_and_deliver(tracker, clock, hours=25)

    assert sender.sent == [
        f"🎌 {JJK_NAME} — анонсирован фильм франшизы\n«Новый фильм» · премьера: 5 февраля 2027",
        f"🎌 {JJK_NAME} — вышел фильм франшизы\n«Новый фильм»",
    ]


def test_an_announced_film_without_a_date_says_so(tracker, shikimori, clock, sender):
    add(tracker, JJK)
    shikimori.by_id["99002"] = film("99002", "Без даты", "anons", None)
    link_film(shikimori, JJK, "99002")

    poll_and_deliver(tracker, clock, hours=25)

    assert sender.sent == [f"🎌 {JJK_NAME} — анонсирован фильм франшизы\n«Без даты» · дата не объявлена"]


def test_a_film_found_in_the_chain_that_came_out_long_ago_is_history_not_news(tracker, shikimori, clock, sender):
    add(tracker, JJK)
    shikimori.by_id["99003"] = film("99003", "Старый фильм", "released", "2015-05-01")
    link_film(shikimori, JJK, "99003")

    poll_and_deliver(tracker, clock, hours=25)

    assert sender.sent == []


def film(id_, name, status, aired_on):
    return {**entry(id_, status, 0, aired_on), "kind": "movie", "name": name, "russian": name, "episodes": 1,
            "airedOn": {"date": aired_on} if aired_on else {"date": None}}


def link_film(shikimori, franchise_id, film_id):
    shikimori.by_id[franchise_id]["related"].append(
        {"relationKind": "sequel", "relationText": "", "anime": {"id": film_id, "kind": "movie"}}
    )
    shikimori.by_id[film_id]["related"] = [
        {"relationKind": "prequel", "relationText": "", "anime": {"id": franchise_id, "kind": "tv"}}
    ]


def test_the_films_stored_with_the_title_follow_the_source(tracker, shikimori, clock, session_factory):
    add(tracker, ABYSS)
    shikimori.by_id["65248"].update(status="released")

    poll_and_deliver(tracker, clock, hours=25)

    with session_factory() as s:
        assert [m.released for m in s.scalars(select(MovieRecord).order_by(MovieRecord.id))][-1] is True


# --- статусы работают и для аниме --------------------------------------------------------------------


def test_a_new_season_returns_a_waiting_anime_to_wanted(tracker, shikimori, clock):
    title = add(tracker, JJK)
    for number in (1, 2, 3):
        run(tracker.set_season_watched(title, number, True))
    assert tracker.title_card(title).status == "waiting"
    announce_the_fourth_season(shikimori)
    start_the_fourth_season(shikimori)

    poll_and_deliver(tracker, clock, days=15)  # the premiere day, 5 Nov, has passed

    assert tracker.title_card(title).status == "want"


def test_a_waiting_anime_is_still_polled(tracker, shikimori, clock):
    title = add(tracker, JJK)
    for number in (1, 2, 3):
        run(tracker.set_season_watched(title, number, True))

    assert poll_and_deliver(tracker, clock, hours=25).polled == 1


def test_a_watched_anime_is_not_polled(tracker, clock):
    title = add(tracker, JJK)
    with tracker.session_factory() as s:
        row = s.get(Title, title)
        row.status, row.tracking_enabled = "watched", False
        s.commit()

    assert poll_and_deliver(tracker, clock, hours=25).polled == 0


# --- id AniList и расписание опроса ------------------------------------------------------------------


def test_the_anilist_ids_left_empty_at_adding_are_filled_by_the_next_poll(tracker, anilist, clock, session_factory):
    anilist.broken = True
    add(tracker, KUSURIYA)
    anilist.broken = False

    poll_and_deliver(tracker, clock, hours=7)

    with session_factory() as s:
        assert [p.anilist_id for p in s.scalars(select(PartRecord).order_by(PartRecord.id))] == [
            "161645", "176301", "195516", "200927"
        ]


def test_only_the_parts_that_are_not_over_are_asked_about(tracker, anilist, clock):
    add(tracker, KUSURIYA)

    poll_and_deliver(tracker, clock, hours=7)

    assert anilist.asked_schedules[-1] == [AL_K3, AL_K3_PART_2]  # seasons 1 and 2 are finished: nothing to ask


@pytest.mark.parametrize(
    "episode_in, expected",
    [(timedelta(hours=30), timedelta(hours=1)), (timedelta(days=9), timedelta(hours=6)), (timedelta(days=90), timedelta(hours=24))],
    ids=["soon", "near", "far"],
)
def test_the_next_look_depends_on_how_near_the_next_episode_is(
    tracker, shikimori, anilist, session_factory, episode_in, expected
):
    moment = T0.replace(tzinfo=None) + episode_in
    anilist.next_episode(AL_K3, 5, moment)
    shikimori.by_id[K3]["nextEpisodeAt"] = moment.replace(tzinfo=timezone.utc).isoformat()

    title = add(tracker, KUSURIYA)

    assert next_check(session_factory, title) == T0.replace(tzinfo=None) + expected


def test_an_anime_is_looked_at_only_when_its_time_has_come(tracker, anilist, clock):
    anilist.next_episode(AL_K3, 5, T0.replace(tzinfo=None) + timedelta(hours=30))
    add(tracker, KUSURIYA)

    clock.advance(minutes=59)
    assert run(tracker.poll_due()).polled == 0
    clock.advance(minutes=2)
    assert run(tracker.poll_due()).polled == 1


# --- карточка и «Тестовое событие» -------------------------------------------------------------------


def test_the_card_shows_the_next_episode_in_the_owners_time(tracker):
    title = add(tracker, KUSURIYA)

    assert "Сезон 3, часть 1: вышло 4 из 12, следующая — пт, 30 окт в 16:00" in format_card(tracker.title_card(title))


def test_a_stored_season_keeps_its_parts_after_a_poll(tracker, clock, session_factory):
    title = add(tracker, KUSURIYA)

    poll_and_deliver(tracker, clock, hours=7)

    assert "Сезон 3, часть 1:" in format_card(tracker.title_card(title))
    with session_factory() as s:
        assert len(list(s.scalars(select(PartRecord)))) == 4
        assert len(list(s.scalars(select(SeasonRecord)))) == 3


@pytest.mark.parametrize(
    "kind_id, expected",
    [
        ("anime-announced", "объявлена дата сезона"),
        ("anime-started", "начался сезон"),
        ("anime-episode", "вышла серия"),
        ("anime-ended", "закончился"),
        ("anime-moved", "→"),
        ("anime-part-episode", "Сезон 3, часть 1: вышло"),
        ("anime-part-announced", "объявлена дата части"),
        ("anime-part-started", "началась часть"),
        ("anime-part-ended", "закончилась часть"),
        ("anime-movie-announced", "анонсирован фильм франшизы"),
        ("anime-movie-released", "вышел фильм франшизы"),
    ],
)
def test_every_anime_event_is_in_the_test_event_menu(tracker, sender, kind_id, expected):
    assert kind_id in [k.id for k in tracker.test_event_kinds()]

    result = run(tracker.send_test_event(kind_id))

    assert result.delivered is True
    assert sender.sent[-1].startswith("🧪 Тестовое событие")
    assert "🎌" in sender.sent[-1]
    assert expected in sender.sent[-1]
