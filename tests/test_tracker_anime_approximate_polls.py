"""The approximate premiere through the facade (spec 4.2–4.6 of stage 9.1d, KI-81): «Монолог фармацевта», season 3
part 2, as the owner's base had it — stored on a made-up first day before the update, known by the month in Shikimori.

The stub is stored at 00:00 of the first day of its period with the timing `month` and read back with no moment; it
replaces the made-up day with no message, is never out (not on the first day of April, not after it), reads «в апреле
2027» in the card, «апрель 2027» in «Позже» and `approximate` in the export; the exact day that comes later is announced
under the key of the look that still had the stub, so the old plain key does not swallow it. Fake clock, the real
Shikimori adapter over the saved answers, AniList answers saved from the real service, in-memory SQLite.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from anime_fakes import FakeShikimori, real_anilist
from app.tracker.cards import format_card
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.dedup import moved_key
from app.tracker.models import EpisodeRecord, EpisodeTiming, Event, SeasonRecord, SourceSnapshot
from app.tracker.sources.shikimori_anime import ShikimoriAnimeSource

T0 = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
ISRAEL = ZoneInfo("Asia/Jerusalem")
KUSURIYA, K3, K3_PART_2, AL_K3 = "54492", "61987", "62841", 195516
MADE_UP_DAY = {"date": "2027-04-01", "year": 2027}  # the shape read before 9.1d: the day of `date`
APRIL = {"date": "2027-04-01", "year": 2027, "month": 4, "day": None}
NINTH_OF_APRIL = {"date": "2027-04-09", "year": 2027, "month": 4, "day": 9}


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


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def clock():
    return FakeClock(T0)


@pytest.fixture
def sender():
    return FakeSender()


@pytest.fixture
def shikimori():
    shikimori = FakeShikimori()
    shikimori.by_id[K3].update(episodesAired=12, nextEpisodeAt=None, status="released")  # part 1 is out in full
    shikimori.by_id[K3_PART_2].update(status="anons", episodesAired=0, nextEpisodeAt=None, airedOn=MADE_UP_DAY)
    return shikimori


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def tracker(session_factory, clock, sender, shikimori):
    anilist = real_anilist()
    anilist.finish(AL_K3, 12)
    return Tracker(
        session_factory, clock=clock, sender=sender, default_tz=ISRAEL,
        sources={"anime": ShikimoriAnimeSource(shikimori, anilist)},
    )


def poll(tracker, clock, **advance):
    clock.advance(**advance)
    run(tracker.poll_due())
    run(tracker.deliver_pending())


def premiere_row(session_factory, title_id):
    """(air_at, timing) of episode 13 of season 3: the first of part 2."""
    with session_factory() as s:
        season = s.scalar(select(SeasonRecord.id).where(SeasonRecord.title_id == title_id, SeasonRecord.number == 3))
        row = s.scalar(select(EpisodeRecord).where(EpisodeRecord.season_id == season, EpisodeRecord.number == 13))
        return row.air_at, row.timing


def season_line(tracker, title_id):
    return next(line for line in format_card(run(tracker.title_card(title_id))).splitlines() if line.startswith("Сезон 3"))


@pytest.fixture
def title_id(tracker, session_factory, shikimori, clock, sender):
    """Added before the update: the made-up day is stored; then Shikimori is read with the precision."""
    title_id = run(tracker.add_title("anime", KUSURIYA)).title_id
    assert premiere_row(session_factory, title_id) == (datetime(2027, 4, 1), EpisodeTiming.DAY)
    shikimori.by_id[K3_PART_2]["airedOn"] = APRIL
    with session_factory() as s:
        snapshot = s.scalar(select(SourceSnapshot).where(SourceSnapshot.title_id == title_id))
        snapshot.next_check_at = clock().replace(tzinfo=None)  # as migration 0018 does
        s.commit()
    return title_id


def test_the_first_look_stores_the_stub_in_place_of_the_made_up_day_and_says_nothing(tracker, clock, sender, session_factory, title_id):
    poll(tracker, clock, minutes=1)

    assert premiere_row(session_factory, title_id) == (datetime(2027, 4, 1), EpisodeTiming.MONTH)
    assert season_line(tracker, title_id) == "Сезон 3, часть 1: вышло 12 из 12; часть 2 — в апреле 2027"
    assert sender.sent == []


def test_the_stub_is_never_out_on_the_first_day_of_its_month_or_after_it(tracker, clock, sender, session_factory, title_id):
    poll(tracker, clock, minutes=1)

    for moment in (datetime(2027, 4, 1, 0, 1), datetime(2027, 4, 1, 12, 0), datetime(2027, 5, 3, 12, 0)):
        clock.now = moment.replace(tzinfo=timezone.utc)
        poll(tracker, clock, days=1)

    assert sender.sent == []
    assert season_line(tracker, title_id).endswith("часть 2 — в апреле 2027")
    with session_factory() as s:
        assert not list(s.scalars(select(Event.type).where(Event.title_id == title_id)))


def test_later_shows_the_month_and_the_export_the_period(tracker, clock, session_factory, title_id):
    poll(tracker, clock, minutes=1)

    later = [(row.when, row.text) for row in run(tracker.feed()).later if row.title.id == title_id]
    document = json.loads(run(tracker.export_all()).content)
    [title] = [t for t in document["titles"] if t["id"] == title_id]
    [season] = [s for s in title["seasons"] if s["number"] == 3]

    assert later == [("апрель 2027", "Сезон 3, часть 2 — премьера")]
    assert season["episodes"][-1] == {"number": 13, "air_at": None, "approximate": "2027-04"}


def test_the_exact_day_that_comes_later_is_announced_and_an_old_plain_key_does_not_swallow_it(
    tracker, clock, sender, session_factory, shikimori, title_id
):
    poll(tracker, clock, minutes=1)
    with session_factory() as s:
        looked_at = s.scalar(select(SourceSnapshot.observed_at).where(SourceSnapshot.title_id == title_id))
    plain = f"anime:{title_id}:src{K3}:p2:date_announced"
    run(tracker.record_event("series_date_announced", {"text": "made-up day"}, plain, title_id=title_id))  # before 9.1d
    run(tracker.deliver_pending())
    sender.sent.clear()
    shikimori.by_id[K3_PART_2]["airedOn"] = NINTH_OF_APRIL

    poll(tracker, clock, days=1)

    assert sender.sent == [
        "🎌 Монолог фармацевта (Kusuriya no Hitorigoto) — объявлена дата части 2 сезона 3\nПремьера: 9 апреля 2027"
    ]
    with session_factory() as s:
        keys = set(s.scalars(select(Event.dedup_key).where(Event.type == "series_date_announced")))
    assert keys == {plain, moved_key(plain, looked_at)}
    assert premiere_row(session_factory, title_id) == (datetime(2027, 4, 9), EpisodeTiming.DAY)
