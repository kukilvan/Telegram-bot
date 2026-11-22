"""Tracker core: the airings of the last 8 days from AniList (spec 1.5 of stage 9.1c) reach the stored episodes.

Driven through the facade: fake clock, the real Shikimori adapter over the saved franchises, AniList's saved answer
with an airing put in by the test, in-memory SQLite. No network. «Монолог фармацевта», season 3 part 1: episodes 1-4
are out at T0, episode 5 comes on Fri 30 Oct 2026 at 14:00 UTC.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from anime_fakes import FakeShikimori, real_anilist
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import EpisodeRecord, EpisodeTiming, SeasonRecord
from app.tracker.sources.shikimori_anime import ShikimoriAnimeSource

T0 = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
KUSURIYA, AL_K3 = "54492", 195516
EPISODE_5 = datetime(2026, 10, 30, 14, 0)  # naive UTC, as stored


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


class Silent:
    async def send(self, message, actions=()):
        pass


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def anilist():
    return real_anilist()


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def tracker(session_factory, clock, anilist):
    source = ShikimoriAnimeSource(FakeShikimori(), anilist, clock)
    return Tracker(session_factory, clock=clock, sender=Silent(), sources={"anime": source})


def moments(session_factory):
    """Episode number -> (stored moment, timing) of season 3."""
    with session_factory() as s:
        rows = s.execute(
            select(EpisodeRecord.number, EpisodeRecord.air_at, EpisodeRecord.timing)
            .join(SeasonRecord, SeasonRecord.id == EpisodeRecord.season_id)
            .where(SeasonRecord.number == 3)
        ).all()
    return {number: (at, timing) for number, at, timing in rows}


def poll_at(tracker, clock, **later):
    clock.now = T0 + timedelta(**later)
    run(tracker.poll_due())


def test_the_airings_are_asked_back_from_the_clock_of_the_core(tracker, anilist, clock):
    run(tracker.add_title("anime", KUSURIYA))

    assert anilist.asked_at == [T0]


def test_a_title_added_with_an_episode_out_three_days_ago_stores_that_episode_with_its_airing_moment(
    tracker, anilist, session_factory
):
    three_days_ago = datetime(2026, 10, 21, 14, 0)
    anilist.aired(AL_K3, 4, three_days_ago)

    run(tracker.add_title("anime", KUSURIYA))

    found = moments(session_factory)
    assert found[4] == (three_days_ago, EpisodeTiming.EXACT)
    assert found[3][1] == EpisodeTiming.UNKNOWN  # no airing for it: Shikimori's start day, not a moment of its own


EPISODE_6 = datetime(2026, 11, 6, 14, 0)


def test_an_episode_a_check_finds_after_it_aired_is_stored_at_the_airing_moment_not_the_moment_of_the_check(
    tracker, anilist, clock, session_factory
):
    run(tracker.add_title("anime", KUSURIYA))  # episode 5 is stored as the next one: Fri 30 Oct, 14:00
    anilist.next_episode(AL_K3, 7, datetime(2026, 11, 13, 14, 0))  # episode 6 came out ...
    anilist.aired(AL_K3, 6, EPISODE_6)  # ... at 14:00; the check finds it at 14:37

    poll_at(tracker, clock, days=13, hours=2, minutes=37)

    found = moments(session_factory)
    assert found[6] == (EPISODE_6, EpisodeTiming.EXACT)
    assert found[5] == (EPISODE_5, EpisodeTiming.EXACT)  # the first recorded moment of an episode stays


def test_with_no_airing_the_episode_has_the_moment_of_the_look_as_unknown(tracker, anilist, clock, session_factory):
    run(tracker.add_title("anime", KUSURIYA))
    anilist.next_episode(AL_K3, 7, datetime(2026, 11, 13, 14, 0))  # AniList does not give the airing of episode 6

    poll_at(tracker, clock, days=13, hours=2, minutes=37)

    at, timing = moments(session_factory)[6]
    assert timing == EpisodeTiming.UNKNOWN
    assert at == clock.now.replace(tzinfo=None)


def test_a_broken_answer_for_airings_does_not_spoil_the_schedule(tracker, anilist, session_factory):
    anilist.schedules[AL_K3]["recentAirings"] = "garbage"

    run(tracker.add_title("anime", KUSURIYA))

    assert moments(session_factory)[5] == (EPISODE_5, EpisodeTiming.EXACT)  # the next episode, as before
    assert {n: t for n, (_, t) in moments(session_factory).items() if n <= 4} == {
        1: EpisodeTiming.DAY, 2: EpisodeTiming.UNKNOWN, 3: EpisodeTiming.UNKNOWN, 4: EpisodeTiming.UNKNOWN
    }
