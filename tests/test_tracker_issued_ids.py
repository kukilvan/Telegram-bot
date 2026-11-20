"""Numbers of titles are never reused (spec 5 of stage 9.1a, KI-24): `issued_ids` keeps the last number given; a new title
takes the biggest of it and of the titles there are, plus one. Driven through the facade, the checks of the table through
a read session; in-memory SQLite."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select

from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import IssuedId, Title
from test_tracker_titles import DUNE_2, DUNE_3, NOT_ANNOUNCED, FakeMovieSource, FakeSender, run


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def tracker(session_factory):
    return Tracker(
        session_factory, clock=lambda: datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc), sender=FakeSender(),
        sources={"movie": FakeMovieSource(DUNE_2, DUNE_3, NOT_ANNOUNCED)},
    )


def last_issued(session_factory):
    with session_factory() as session:
        row = session.get(IssuedId, "titles")
        return None if row is None else row.last_id


def test_a_fresh_database_starts_at_one_and_keeps_the_last_number(tracker, session_factory):
    first = run(tracker.add_title("movie", DUNE_2.external_id)).title_id
    second = run(tracker.add_title("movie", DUNE_3.external_id)).title_id

    assert (first, second) == (1, 2)
    assert last_issued(session_factory) == 2


def test_the_number_of_a_deleted_last_title_does_not_come_back(tracker, session_factory):
    run(tracker.add_title("movie", DUNE_2.external_id))
    last = run(tracker.add_title("movie", DUNE_3.external_id)).title_id
    run(tracker.delete_title(last))

    again = run(tracker.add_title("movie", NOT_ANNOUNCED.external_id)).title_id

    assert again == last + 1
    assert last_issued(session_factory) == again


def test_opening_a_title_already_there_gives_no_number(tracker, session_factory):
    first = run(tracker.add_title("movie", DUNE_2.external_id)).title_id

    again = run(tracker.add_title("movie", DUNE_2.external_id))

    assert again.title_id == first and not again.created
    assert last_issued(session_factory) == first


def test_a_missing_row_is_made_again_from_the_titles(tracker, session_factory):
    run(tracker.add_title("movie", DUNE_2.external_id))
    with session_factory() as session:
        session.execute(delete(IssuedId))
        session.commit()

    second = run(tracker.add_title("movie", DUNE_3.external_id)).title_id

    assert second == 2 and last_issued(session_factory) == 2


def test_a_row_behind_the_titles_is_not_trusted(tracker, session_factory):
    run(tracker.add_title("movie", DUNE_2.external_id))
    with session_factory() as session:
        session.get(IssuedId, "titles").last_id = 0  # a hand edit
        session.commit()

    second = run(tracker.add_title("movie", DUNE_3.external_id)).title_id

    assert second == 2


def test_a_title_written_straight_into_the_table_does_not_break_the_count(tracker, session_factory):
    run(tracker.add_title("movie", DUNE_2.external_id))
    with session_factory() as session:  # as a test (or a hand) does: the row of `issued_ids` is not told
        session.add(Title(
            id=10, kind="movie", name="Прямой", original_name="Direct", genres=[], status="want", tracking_enabled=True,
            added_at=datetime(2026, 11, 20), status_changed_at=datetime(2026, 11, 20),
        ))
        session.commit()

    new = run(tracker.add_title("movie", DUNE_3.external_id)).title_id

    assert new == 11 and last_issued(session_factory) == 11
    with session_factory() as session:
        assert sorted(session.scalars(select(Title.id))) == [1, 10, 11]


def test_the_row_stays_when_all_the_titles_are_deleted(tracker, session_factory):
    first = run(tracker.add_title("movie", DUNE_2.external_id)).title_id
    run(tracker.delete_title(first))

    again = run(tracker.add_title("movie", DUNE_2.external_id)).title_id

    assert again == first + 1
