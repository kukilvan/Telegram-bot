"""Tests for adaptive polling cycle (fake provider, in-memory SQLite, no network)."""

import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import ExternalId, MediaItem, User


class FakeProvider:
    """Simulates a state change across calls (no real HTTP)."""

    def __init__(self):
        self.calls = 0

    async def get_movie_release_dates(self, movie_id):
        self.calls += 1
        if self.calls == 1:
            return []  # first poll: no digital date yet (baseline empty)
        else:
            return [{"iso_3166_1": "US", "release_dates": [{"type": 4, "release_date": "2026-09-10T00:00:00.000Z"}]}]


class SequenceTVProvider:
    """Simulates TMDb's real two-call TV flow (no real HTTP).

    get_tv_seasons returns season metadata only — as the live API does, with
    NO embedded episodes. get_tv_season_episodes returns per-call episode lists.
    Both sequences advance once per poll; extra calls clamp to the last entry.
    """

    def __init__(self, seasons_sequences, episodes_sequences):
        self.seasons_seq = seasons_sequences
        self.episodes_seq = episodes_sequences
        self.calls = {"seasons": 0, "episodes": 0}

    async def get_tv_seasons(self, tv_id):
        i = min(self.calls["seasons"], len(self.seasons_seq) - 1)
        self.calls["seasons"] += 1
        return self.seasons_seq[i]

    async def get_tv_season_episodes(self, tv_id, season_number):
        i = min(self.calls["episodes"], len(self.episodes_seq) - 1)
        self.calls["episodes"] += 1
        return self.episodes_seq[i]


def _make_session():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return factory()


def test_poll_item_cycle():
    from app.scheduler.polling import poll_item

    s = _make_session()
    user = User(telegram_user_id=454501218)
    s.add(user)
    s.commit()
    item = MediaItem(media_type="movie", canonical_title_en="Dune")
    s.add(item)
    s.flush()  # generate UUID primary key before FK reference
    s.commit()
    ext = ExternalId(media_item_id=item.id, source="tmdb", external_id="841")
    s.add(ext)
    s.commit()

    from app.services.notifications import set_rule
    set_rule(s, user.id, item.id, "DIGITAL_DATE_ANNOUNCED", True)

    provider = FakeProvider()
    # Poll 1: baseline (no prior state).
    r1 = asyncio.run(poll_item(s, provider, item, user_id=user.id))
    assert r1 == [], "first poll stores baseline, no event"
    # Poll 2: state change detected + enabled-rule gate passes.
    r2 = asyncio.run(poll_item(s, provider, item, user_id=user.id))
    assert len(r2) == 1 and r2[0].event_type == "DIGITAL_DATE_ANNOUNCED", (
        "state change should produce exactly one event"
    )
    # Poll 3: no re-detection (stored state now matches).
    r3 = asyncio.run(poll_item(s, provider, item, user_id=user.id))
    assert r3 == [], "no duplicate on re-poll"
    s.close()


def _tv_item(session, title="The Last of Us"):
    user = User(telegram_user_id=454501218)
    session.add(user)
    item = MediaItem(media_type="tv", canonical_title_en=title)
    session.add(item)
    session.flush()  # generate UUID primary key before FK reference
    ext = ExternalId(media_item_id=item.id, source="tmdb", external_id="100088")
    session.add(ext)
    return user, item


def test_tv_baseline_no_event():
    from app.scheduler.polling import poll_item

    s = _make_session()
    user, item = _tv_item(s)
    s.commit()
    seasons_meta = [{"season_number": 1, "episode_count": 3}]
    episodes_seq = [[{"air_date": "2023-01-15"}, {"air_date": None}, {"air_date": None}]]
    provider = SequenceTVProvider([seasons_meta], [episodes_seq[0]])
    r1 = asyncio.run(poll_item(s, provider, item, user_id=user.id))
    assert r1 == [], "first poll stores baseline without events"
    s.close()


def test_tv_new_season_announced():
    from app.scheduler.polling import poll_item
    from app.services.notifications import set_rule

    s = _make_session()
    user, item = _tv_item(s)
    s.commit()
    set_rule(s, user.id, item.id, "NEW_SEASON_ANNOUNCED", True)
    seasons_seq = [
        [{"season_number": 1, "episode_count": 2}],
        [
            {"season_number": 1, "episode_count": 2},
            {"season_number": 2, "episode_count": 2},
        ],
    ]
    episodes_seq = [
        [{"air_date": "2023-01-15"}, {"air_date": None}],  # poll 1: season 1 partial
        [{"air_date": None}, {"air_date": None}],            # poll 2: season 2 fresh
    ]
    provider = SequenceTVProvider(seasons_seq, episodes_seq)
    r1 = asyncio.run(poll_item(s, provider, item, user_id=user.id))
    assert r1 == [], "baseline poll stores state without events"
    r2 = asyncio.run(poll_item(s, provider, item, user_id=user.id))
    assert len(r2) == 1 and r2[0].event_type == "NEW_SEASON_ANNOUNCED", (
        "season bump should produce exactly one NEW_SEASON_ANNOUNCED"
    )
    assert r2[0].payload == {"season": 2}
    r3 = asyncio.run(poll_item(s, provider, item, user_id=user.id))
    assert r3 == [], "no re-detection on next poll (dedup gate)"
    s.close()


def test_tv_all_episodes_out():
    from app.scheduler.polling import poll_item
    from app.services.notifications import set_rule

    s = _make_session()
    user, item = _tv_item(s)
    s.commit()
    set_rule(s, user.id, item.id, "ALL_EPISODES_OUT", True)
    seasons_seq = [
        [{"season_number": 1, "episode_count": 3}],
        [{"season_number": 1, "episode_count": 3}],
    ]
    episodes_seq = [
        [{"air_date": "2023-01-15"}, {"air_date": None}, {"air_date": None}],
        [{"air_date": "2023-01-15"}, {"air_date": "2023-01-22"}, {"air_date": "2023-01-29"}],
    ]
    provider = SequenceTVProvider(seasons_seq, episodes_seq)
    r1 = asyncio.run(poll_item(s, provider, item, user_id=user.id))
    assert r1 == [], "baseline poll stores state without events"
    r2 = asyncio.run(poll_item(s, provider, item, user_id=user.id))
    assert len(r2) == 1 and r2[0].event_type == "ALL_EPISODES_OUT", (
        "all-episodes-out should produce exactly one event"
    )
    assert r2[0].payload == {"season": 1}
    s.close()


def test_tv_state_normalization():
    from app.domain.events import (ALL_EPISODES_OUT, NEW_SEASON_ANNOUNCED,
                                  compare_states)
    from app.scheduler.polling import _tv_state_from_seasons

    seasons = [
        {"season_number": 1, "episodes": [
            {"air_date": "2023-01-15"},
            {"air_date": None},
            {"air_date": None},
        ]},
        {"season_number": 2, "episodes": [
            {"air_date": "2024-05-01"},
            {"air_date": "2024-05-08"},
            {"air_date": None},
        ]},
    ]
    TODAY = "2026-09-15"  # injected date; pure function, no clock reads
    state = _tv_state_from_seasons(seasons, TODAY)
    assert state["latest_season"] == 2
    assert state["total_episodes_current_season"] == 3
    assert state["episodes_aired_current_season"] == 2

    old_full = {"latest_season": 1, "total_episodes_current_season": 3,
                "episodes_aired_current_season": 1}
    evs = compare_states(old_full, state)
    types = [e.event_type for e in evs]
    assert NEW_SEASON_ANNOUNCED in types
    assert ALL_EPISODES_OUT not in types, "not all episodes aired yet"

    new_all = {"latest_season": 2, "total_episodes_current_season": 3,
              "episodes_aired_current_season": 3}
    evs2 = compare_states(old_full, new_all)
    assert any(e.event_type == ALL_EPISODES_OUT for e in evs2)

    none_events = compare_states(state, state)
    assert none_events == [], "no event when nothing changed"

    # Announced season whose episode is a FUTURE-dated placeholder must not be
    # counted as fully out (live Silo S4 shape: placeholder ep dated 2027-07-08).
    silo_like = [
        {"season_number": 4, "episodes": [
            {"air_date": "2026-08-20"},   # past -> aired
            {"air_date": "2027-07-08"},   # future placeholder -> NOT counted as aired
            {"air_date": None},           # unscheduled -> NOT counted as aired
        ]}
    ]
    silo_state = _tv_state_from_seasons(silo_like, TODAY)
    assert silo_state == {
        "latest_season": 4,
        "total_episodes_current_season": 3,
        "episodes_aired_current_season": 1,
    }, f"{silo_state}"


if __name__ == "__main__":
    # Run directly without pytest (pytest not yet installed in .venv).
    test_poll_item_cycle()
    test_tv_baseline_no_event()
    test_tv_new_season_announced()
    test_tv_all_episodes_out()
    test_tv_state_normalization()
    print("scheduler polling tests passed")
