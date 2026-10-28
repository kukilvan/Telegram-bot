"""Tracker core: an anime season is known by the first entry of the source, not by its number.

Driven through the facade only: fake clock, the real Shikimori adapter over a chain of made-up entries that a test edits
between two looks, no AniList (every part follows Shikimori), fake sender, in-memory SQLite. No network.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from anime_fakes import FakeAniList, FakeShikimori
from app.tracker.core import Tracker, UnknownSeason
from app.tracker.db import create_session_factory
from app.tracker.models import EpisodeRecord, Event, PartRecord, SeasonRecord, Title
from app.tracker.seasons import Episode, Season
from app.tracker.series_events import ShowState, detect_events
from app.tracker import anime_events
from app.tracker.sources.shikimori_anime import ShikimoriAnimeSource
from season_helpers import season_id

T0 = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)  # a Saturday
A, B, C, X, D = "101", "102", "103", "104", "105"


class FakeClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, **delta):
        self.now += timedelta(**delta)


class FakeSender:
    async def send(self, message, actions=()):
        pass


def run(coro):
    return asyncio.run(coro)


def entry(id_, name, aired_on, episodes=12, aired=None, status="released", next_at=None, duration=24):
    return {
        "id": id_, "malId": id_, "name": name, "russian": name, "kind": "tv", "status": status, "episodes": episodes,
        "episodesAired": episodes if aired is None else aired, "nextEpisodeAt": next_at, "duration": duration,
        "airedOn": {"date": aired_on}, "releasedOn": {"date": None}, "franchise": "made_up", "poster": None,
        "genres": [], "related": [],
    }


def link(shikimori, *ids):
    """Put the entries in a chain, in this order: prequel and sequel both ways."""
    for before, after in zip(ids, ids[1:]):
        shikimori.by_id[before]["related"].append({"relationKind": "sequel", "anime": {"id": after, "kind": "tv"}})
        shikimori.by_id[after]["related"].append({"relationKind": "prequel", "anime": {"id": before, "kind": "tv"}})


def unlink(shikimori, id_):
    """Take the entry out of the chains of the others (it stays in Shikimori)."""
    for other in shikimori.by_id.values():
        other["related"] = [r for r in other["related"] if r["anime"]["id"] != id_]


@pytest.fixture
def shikimori():
    source = FakeShikimori()
    source.by_id = {
        A: entry(A, "Alpha", "2020-01-01"),
        B: entry(B, "Beta", "2021-01-01"),
        C: entry(C, "Gamma", "2026-10-02", aired=4, status="ongoing", next_at="2026-10-30T17:00:00+03:00"),
        X: entry(X, "Xi", "2022-01-01"),
        D: entry(D, "Delta", "2026-10-25", aired=2, status="ongoing", next_at="2026-11-01T17:00:00+03:00"),
    }
    return source


@pytest.fixture
def clock():
    return FakeClock(T0)


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def tracker(session_factory, clock, shikimori):
    return Tracker(
        session_factory,
        clock=clock,
        sender=FakeSender(),
        sources={"anime": ShikimoriAnimeSource(shikimori, FakeAniList(ids={}))},
    )


def add(tracker, external_id):
    return run(tracker.add_title("anime", external_id)).title_id


def poll(tracker, clock, **advance):
    clock.advance(**advance)
    run(tracker.poll_due())


def seasons_in_db(session_factory):
    """(number, watched, episodes as (number, moment)) of every stored season, by number, and the id of each record."""
    with session_factory() as s:
        return [
            (r.id, r.number, r.watched, [(e.number, e.air_at) for e in s.scalars(
                select(EpisodeRecord).where(EpisodeRecord.season_id == r.id).order_by(EpisodeRecord.number))])
            for r in s.scalars(select(SeasonRecord).order_by(SeasonRecord.number))
        ]


def event_keys(session_factory):
    with session_factory() as s:
        return sorted(s.scalars(select(Event.dedup_key)))


def status(session_factory):
    with session_factory() as s:
        return s.scalars(select(Title)).one().status


# --- an entry inserted in the middle of the chain ------------------------------------------------


def test_an_entry_inserted_in_the_middle_moves_the_season_after_it_with_its_mark_and_dates(
    tracker, shikimori, clock, session_factory
):
    link(shikimori, A, C)
    title = add(tracker, A)
    run(tracker.toggle_season(title, season_id(tracker, title, 1)))
    run(tracker.toggle_season(title, season_id(tracker, title, 2)))
    before = seasons_in_db(session_factory)
    assert status(session_factory) == "waiting"  # everything out is marked
    link(shikimori, A, X)  # Shikimori ties an old finished entry in between
    link(shikimori, X, C)
    unlink_chain_edge(shikimori, A, C)

    poll(tracker, clock, hours=12)

    after = seasons_in_db(session_factory)
    assert [(n, w) for _, n, w, _ in after] == [(1, True), (2, False), (3, True)]
    assert after[2][0] == before[1][0] and after[2][3] == before[1][3]  # the same record, the same dates of episodes
    assert [n for n, _ in after[1][3]] == list(range(1, 13))  # the inserted entry: its twelve episodes
    assert event_keys(session_factory) == []  # nothing came out, nothing was announced
    assert status(session_factory) == "in_progress"  # the mark follows the season it was made on


def unlink_chain_edge(shikimori, before, after):
    """The two entries are no longer neighbours."""
    shikimori.by_id[before]["related"] = [
        r for r in shikimori.by_id[before]["related"] if not (r["relationKind"] == "sequel" and r["anime"]["id"] == after)
    ]
    shikimori.by_id[after]["related"] = [
        r for r in shikimori.by_id[after]["related"] if not (r["relationKind"] == "prequel" and r["anime"]["id"] == before)
    ]


# --- an entry that stops being a season ----------------------------------------------------------


def test_an_entry_that_stops_being_a_season_lets_the_next_one_take_its_number_and_a_new_episode_is_news(
    tracker, shikimori, clock, session_factory
):
    link(shikimori, A, B, C)
    title = add(tracker, A)
    run(tracker.toggle_season(title, season_id(tracker, title, 1)))
    with session_factory.begin() as s:  # the owner has been told about episode 5 of season 2 long ago
        s.add(Event(type="series_episode_out", title_id=title, payload={}, dedup_key=f"anime:{title}:s2:e5:out",
                    detected_at=T0))
    before = seasons_in_db(session_factory)
    shikimori.by_id[B]["duration"] = 5  # a short now, not a season

    poll(tracker, clock, hours=12)

    after = seasons_in_db(session_factory)
    assert [(n, w) for _, n, w, _ in after] == [(1, True), (2, False)]
    assert after[1][0] == before[2][0] and after[1][3] == before[2][3]  # season 3 became season 2, dates and all
    assert event_keys(session_factory) == [f"anime:{title}:s2:e5:out"]  # no false alarm about what is out

    shikimori.by_id[C].update(episodesAired=5, nextEpisodeAt="2026-11-06T17:00:00+03:00")
    poll(tracker, clock, days=7)

    assert f"anime:{title}:src{C}:e5:out" in event_keys(session_factory)


# --- an entry that joins the season before it as its next part -----------------------------------


def test_a_season_that_becomes_part_two_of_the_one_before_is_dissolved_and_its_episodes_move_with_their_dates(
    tracker, shikimori, clock, session_factory, caplog
):
    link(shikimori, A, B)
    title = add(tracker, A)
    run(tracker.toggle_season(title, season_id(tracker, title, 2)))
    run(tracker.set_season_score(title, season_id(tracker, title, 2), 28))
    before = seasons_in_db(session_factory)
    shikimori.by_id[B]["name"] = "Beta Part 2"

    with caplog.at_level(logging.WARNING):
        poll(tracker, clock, days=2)  # nothing is airing: the next look is a day away

    [(_, number, watched, episodes)] = seasons_in_db(session_factory)
    assert (number, watched) == (1, False)
    assert episodes == before[0][3] + [(n + 12, moment) for n, moment in before[1][3]]
    assert event_keys(session_factory) == []
    with session_factory() as s:
        parts = [(p.number, p.first_episode, p.shikimori_id) for p in s.scalars(select(PartRecord).order_by(PartRecord.number))]
    assert parts == [(1, 1, A), (2, 13, B)]
    [warning] = [r.getMessage() for r in caplog.records if "dissolved" in r.getMessage()]
    assert f"season 2, entry {B}, watched mark: True, score: 28" in warning  # the score goes with the season


# --- KI-27: a card or a button opened before the seasons were renumbered ------------------------


def test_a_mark_and_a_score_sent_with_the_record_of_a_season_reach_it_after_it_moved_to_another_number(
    tracker, shikimori, clock, session_factory
):
    link(shikimori, A, C)
    title = add(tracker, A)
    gamma = season_id(tracker, title, 2)  # the card shows Gamma as season 2
    link(shikimori, A, X)
    link(shikimori, X, C)
    unlink_chain_edge(shikimori, A, C)
    poll(tracker, clock, hours=12)  # Xi is season 2 now, Gamma season 3

    run(tracker.set_season_watched(title, gamma, True))
    run(tracker.set_season_score(title, gamma, 29))

    rows = {r.number: (r.id, r.watched, r.score) for r in run(tracker.title_card(title)).season_rows}
    assert rows[3] == (gamma, True, 29)
    assert rows[2][1:] == (False, None)  # the season the old number points at now is left alone
    assert [s.watched for s in run(tracker.toggle_season(title, gamma))] == [False, False, False]


def test_a_season_that_dissolved_after_the_card_was_opened_is_an_unknown_season(
    tracker, shikimori, clock, session_factory
):
    link(shikimori, A, B, C)
    title = add(tracker, A)
    beta = season_id(tracker, title, 2)
    shikimori.by_id[B]["duration"] = 5  # a short now, not a season
    poll(tracker, clock, hours=12)

    with pytest.raises(UnknownSeason):
        run(tracker.set_season_watched(title, beta, True))
    with pytest.raises(UnknownSeason):
        run(tracker.toggle_season(title, beta))
    with pytest.raises(UnknownSeason):
        run(tracker.set_season_score(title, beta, 27))
    assert all(not r.watched for r in run(tracker.title_card(title)).season_rows)


# --- an entry the title never had -----------------------------------------------------------------


def test_an_entry_that_started_before_the_previous_look_is_history_even_at_the_end_of_the_chain(
    tracker, shikimori, clock, session_factory
):
    link(shikimori, A)
    add(tracker, A)
    shikimori.by_id[D]["airedOn"] = {"date": "2026-10-20"}  # out before the look at adding
    link(shikimori, A, D)

    poll(tracker, clock, days=2)

    assert [n for _, n, _, _ in seasons_in_db(session_factory)] == [1, 2]
    assert event_keys(session_factory) == []


def test_an_entry_that_started_after_the_previous_look_is_news(tracker, shikimori, clock, session_factory):
    link(shikimori, A)
    title = add(tracker, A)
    link(shikimori, A, D)

    poll(tracker, clock, days=2)  # Delta began on the 25th: two episodes are out

    assert event_keys(session_factory) == [
        f"anime:{title}:src{D}:e2:out",
        f"anime:{title}:src{D}:started",
    ]


# --- keys of events --------------------------------------------------------------------------------


def test_the_keys_of_a_season_with_a_source_entry_name_the_entry_and_a_series_keeps_its_number():
    t = datetime(2026, 10, 1)
    flavored = anime_events.flavor(None)

    def keys(source_id, flavor):
        old = Season(2, "S", 12, (Episode(1, t),), source_id=source_id)
        new = Season(2, "S", 12, (Episode(1, t), Episode(2, t + timedelta(days=7))), source_id=source_id)
        return [
            e.dedup_key
            for e in detect_events(5, "N", ShowState.of([old], {}), ShowState.of([new], {}), t + timedelta(days=1),
                                   t + timedelta(days=8), flavor=flavor)
        ]

    assert keys("77", flavored) == ["anime:5:src77:e2:out"]
    assert keys(None, flavored) == ["anime:5:s2:e2:out"]
    assert keys(None, anime_events.series_events.SERIES) == ["series:5:s2:e2:out"]
