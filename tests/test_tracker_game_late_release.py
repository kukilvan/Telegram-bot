"""A late release (KI-36, spec 1.2 of stage 9.1b) through the poll: the 30 days count from the day the tracker began
following the game, and a release earlier than yesterday is named by its day.

Driven through the facade: fake clock, in-memory SQLite, a made-up game source whose snapshots the test writes.
"""

import pytest
from sqlalchemy import select

from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.games import FULL, GameDate, GameState, Release
from app.tracker.models import Event, TitleKind
from app.tracker.platforms import WORLD
from test_tracker_game_prices import T0, FakeClock, FakePrices, FakeSender, MadeUpGames, add, igdb_says, run

PC = 6


def released(text):
    return GameState(platforms=(PC,), releases=(Release(PC, WORLD, FULL, GameDate.parse(text)),))


@pytest.fixture
def clock():
    return FakeClock(T0)  # 9 November 2026


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def igdb():
    return MadeUpGames()


@pytest.fixture
def tracker(session_factory, clock, igdb):
    return Tracker(
        session_factory, clock=clock, sender=FakeSender(), sources={TitleKind.GAME: igdb}, price_source=FakePrices()
    )


def told(session_factory, title_id):
    """The events of the game as (type, the late day or None)."""
    with session_factory() as session:
        events = session.scalars(select(Event).where(Event.title_id == title_id).order_by(Event.id))
        return [(event.type, event.payload.get("late")) for event in events]


def after(tracker, session_factory, igdb, state, clock, minutes=2):
    igdb_says(session_factory, igdb, state)
    clock.advance(minutes=minutes)
    run(tracker.poll_due())


def test_a_release_20_days_before_the_game_was_added_is_told_late(tracker, igdb, session_factory, clock):
    title = add(tracker, igdb, GameState(platforms=(PC,)))

    after(tracker, session_factory, igdb, released("2026-10-20"), clock)

    assert told(session_factory, title) == [("game_released", "2026-10-20")]


def test_a_release_40_days_before_the_game_was_added_is_a_correction(tracker, igdb, session_factory, clock):
    title = add(tracker, igdb, GameState(platforms=(PC,)))

    after(tracker, session_factory, igdb, released("2026-09-30"), clock)

    assert told(session_factory, title) == []


def test_a_year_that_becomes_an_old_day_is_silent(tracker, igdb, session_factory, clock):
    title = add(tracker, igdb, GameState(platforms=(PC,), releases=released("2015").releases))

    after(tracker, session_factory, igdb, released("2015-05-19"), clock)

    assert told(session_factory, title) == []


def test_a_game_added_in_the_past_gets_the_news_of_its_first_weeks_but_not_of_the_return_after_months(
    tracker, igdb, session_factory, clock
):
    title = add(tracker, igdb, GameState(platforms=(PC,)))
    run(tracker.mark_dropped(title))
    clock.advance(days=60)  # 8 January 2027
    run(tracker.restore_title(title))
    run(tracker.poll_due())  # the first check after the return is the reference point

    after(tracker, session_factory, igdb, released("2026-11-20"), clock)  # 49 days before the return

    assert told(session_factory, title) == []


def test_a_release_within_30_days_before_the_return_is_told(tracker, igdb, session_factory, clock):
    title = add(tracker, igdb, GameState(platforms=(PC,)))
    run(tracker.mark_dropped(title))
    clock.advance(days=60)
    run(tracker.restore_title(title))
    run(tracker.poll_due())

    after(tracker, session_factory, igdb, released("2026-12-20"), clock)  # 19 days before the return

    assert told(session_factory, title) == [("game_released", "2026-12-20")]
