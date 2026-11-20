"""Moving the parts of an anime season (spec 4.3 of stage 9.1a, KI-1): a part takes its new place only when the place is
free after the moves; exchanges and chains of moves still work. `AnimePoller._sync_entries` on stored rows, in-memory
SQLite, no source.
"""

import logging
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.tracker.db import create_session_factory
from app.tracker.models import PartRecord, SeasonRecord, Title
from app.tracker.pollers.anime import AnimePoller, _free_moves
from app.tracker.sources.shikimori_anime import SeasonPart, SourceIds

NOW = datetime(2026, 11, 20, 12, 0)


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


def stored(session_factory, layout):
    """A title with season 1 and its parts: `layout` is the Shikimori ids in the order of their places 1, 2, …"""
    with session_factory() as session:
        title = Title(
            kind="anime", name="Аниме", original_name="Anime", year=2026, genres=[], status="want",
            tracking_enabled=True, added_at=NOW, status_changed_at=NOW,
        )
        session.add(title)
        session.flush()
        season = SeasonRecord(title_id=title.id, number=1, name="Сезон 1", episode_count=None, watched=False)
        session.add(season)
        session.flush()
        for number, sid in enumerate(layout, start=1):
            session.add(
                PartRecord(
                    title_id=title.id, season_id=season.id, number=number, first_episode=12 * (number - 1) + 1,
                    episode_count=12, shikimori_id=sid, mal_id=sid, anilist_id=None,
                )
            )
        session.commit()
        return title.id


def chain(*sids):
    """The parts of season 1 as Shikimori gives them now, in the order of their places."""
    parts = [
        SeasonPart(season=1, number=number, first_episode=12 * (number - 1) + 1, episode_count=12, ids=SourceIds(sid, sid))
        for number, sid in enumerate(sids, start=1)
    ]
    return SimpleNamespace(parts=parts, movies=[])


def sync(session_factory, title_id, snapshot):
    with session_factory() as session:
        AnimePoller._sync_entries(session, title_id, snapshot)
        session.commit()


def places(session_factory, title_id):
    with session_factory() as session:
        rows = session.scalars(select(PartRecord).where(PartRecord.title_id == title_id).order_by(PartRecord.number))
        return [row.shikimori_id for row in rows]


def test_the_example_of_ki_1_moves_nothing_and_says_so_once(session_factory, caplog):
    title_id = stored(session_factory, ["P1", "C", "B", "A"])

    with caplog.at_level(logging.INFO):
        sync(session_factory, title_id, chain("P1", "B", "A"))  # C left the chain: B wants 2, A wants 3

    assert places(session_factory, title_id) == ["P1", "C", "B", "A"]
    lines = [r.getMessage() for r in caplog.records if "keep their places" in r.getMessage()]
    assert lines == [f"title {title_id}: parts [3, 4] keep their places, the places they move to are taken"]


def test_an_exchange_of_two_parts_still_works(session_factory, caplog):
    title_id = stored(session_factory, ["P1", "A", "B"])

    with caplog.at_level(logging.INFO):
        sync(session_factory, title_id, chain("P1", "B", "A"))

    assert places(session_factory, title_id) == ["P1", "B", "A"]
    assert not [r for r in caplog.records if "keep their places" in r.getMessage()]


def test_a_chain_of_moves_into_a_free_place_still_works(session_factory):
    title_id = stored(session_factory, ["P1", "A", "B"])

    sync(session_factory, title_id, chain("P1", "X", "A", "B"))  # a new entry X before A: A and B move on one place

    assert places(session_factory, title_id) == ["P1", "X", "A", "B"]


@pytest.mark.parametrize(
    "wanted, places_now, expected",
    [
        ({3: (1, 2), 4: (1, 3)}, {1: (1, 1), 2: (1, 2), 3: (1, 3), 4: (1, 4)}, {}),  # KI-1: 2 stays, so 3, so 4
        ({2: (1, 3), 3: (1, 3)}, {1: (1, 1), 2: (1, 2), 3: (1, 4)}, {}),  # two parts want one place: neither moves
        ({2: (1, 3), 3: (1, 2)}, {2: (1, 2), 3: (1, 3)}, {2: (1, 3), 3: (1, 2)}),  # an exchange
        ({2: (1, 3), 3: (1, 4)}, {2: (1, 2), 3: (1, 3)}, {2: (1, 3), 3: (1, 4)}),  # a chain into a free place
        ({2: (1, 3), 3: (1, 4)}, {2: (1, 2), 3: (1, 3), 4: (1, 4)}, {}),  # a chain into a place that stays taken
    ],
)
def test_the_moves_that_may_be_made(wanted, places_now, expected):
    assert _free_moves(wanted, places_now) == expected
