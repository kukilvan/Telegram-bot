"""The follow-up check after stage 9.1b (ticket 03): «Бросил» drops the snapshot at once (KI-53), a withdrawn event frees
its key (KI-54), the check queues through `EventQueue.enqueue(…, due=game)`, a game whose own check does not run learns
its own type and parent (KI-52), and a game whose own snapshot cannot be read is checked and fails alike (KI-55).

Through the facade: fake clock, fake sender, in-memory SQLite, IGDB a made-up game source, the follow-ups a fake source
of `FollowUpsSnapshot`s (the helpers of `test_tracker_game_follow_ups`).
"""

import logging
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.tracker import games
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.follow_ups import FollowUpsSnapshot
from app.tracker.games import Parent
from app.tracker.models import DeliveryItem, Event, SourceSnapshot, Title, TitleKind, TitleStatus
from app.tracker.sources.igdb_follow_ups import FOLLOW_UPS_QUERY, parse_follow_ups
from test_tracker_game_follow_ups import (
    T0, FakeClock, FakeFollowUps, FakeSender, MadeUpGames, add, announcements, follow_up, game, naive, run, series,
    set_snapshot, snapshot_of,
)

UNCHARTED_4 = Parent("7331", "Uncharted 4: A Thief's End")


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
def igdb():
    return MadeUpGames()


@pytest.fixture
def follow():
    return FakeFollowUps()


@pytest.fixture
def tracker(session_factory, clock, sender, igdb, follow):
    return Tracker(session_factory, clock=clock, sender=sender, sources={TitleKind.GAME: igdb}, follow_up_source=follow)


def own_state(session_factory, title_id):
    with session_factory() as session:
        return session.scalar(
            select(SourceSnapshot.state).where(SourceSnapshot.title_id == title_id, SourceSnapshot.source == "igdb")
        )


def set_own_state(session_factory, title_id, state):
    with session_factory() as session:
        own = session.scalar(select(SourceSnapshot).where(SourceSnapshot.title_id == title_id, SourceSnapshot.source == "igdb"))
        own.state = state
        session.commit()


def events_of(session_factory, title_id=None):
    with session_factory() as session:
        query = select(Event.dedup_key).order_by(Event.id)
        if title_id is not None:
            query = query.where(Event.title_id == title_id)
        return list(session.scalars(query))


def recent_headlines(tracker):
    return [row.headline for day in run(tracker.feed()).recent for row in day.rows]


def witcher_four_is_announced(follow, *external_ids):
    for external_id in external_ids:
        follow.answers[external_id] = series(follow_up("2", "The Witcher IV"))


# --- KI-53: the press drops the snapshot at once ----------------------------------------------------------------------


def test_dropping_drops_the_follow_up_snapshot_at_once(tracker, igdb, session_factory):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())

    run(tracker.mark_dropped(title_id))

    assert snapshot_of(session_factory, title_id) is None  # no pass needed


@pytest.mark.parametrize("press", ["started", "completed"])
def test_a_press_that_keeps_the_game_for_the_check_keeps_its_snapshot(press, tracker, igdb, session_factory):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    before = snapshot_of(session_factory, title_id)

    run(tracker.mark_started(title_id) if press == "started" else tracker.mark_watched(title_id))

    after = snapshot_of(session_factory, title_id)
    assert (after.id, after.state) == (before.id, before.state)


def test_dropping_and_restoring_within_a_minute_starts_with_a_silent_reference_point(
    tracker, igdb, follow, session_factory, clock
):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())  # the reference point: nothing in the series
    witcher_four_is_announced(follow, "1")  # announced since that reference point

    run(tracker.mark_dropped(title_id))
    run(tracker.restore_title(title_id))  # within the same minute: no pass between
    run(tracker.poll_due())

    assert snapshot_of(session_factory, title_id).state["known"] == ["2"]  # the new reference point
    assert follow.calls == ["1", "1"]
    clock.advance(days=7)
    run(tracker.poll_due())
    assert announcements(session_factory) == [] and follow.calls == ["1", "1", "1"]  # the old one is never used


def test_a_check_answering_after_dropping_and_restoring_queues_and_stores_nothing(
    tracker, igdb, follow, session_factory, clock
):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    witcher_four_is_announced(follow, "1")

    async def drop_and_restore(external_id):
        await tracker.mark_dropped(title_id)
        await tracker.restore_title(title_id)

    follow.during = drop_and_restore
    clock.advance(days=7)
    report = run(tracker.poll_due())

    assert announcements(session_factory) == [] and events_of(session_factory) == [] and report.failed == 0
    assert snapshot_of(session_factory, title_id) is None  # dropped by the press, made again by the next pass
    follow.during = None
    clock.advance(minutes=1)
    run(tracker.poll_due())
    assert snapshot_of(session_factory, title_id).state["known"] == ["2"] and announcements(session_factory) == []


# --- KI-54: a withdrawn event frees its key; the queueing through `enqueue(…, due=game)` --------------------------


def two_games_of_one_series(tracker, igdb, session_factory, clock):
    """Ведьмак 3 (due now) and Ведьмак 2 (due a day later), both checked once; then IGDB lists The Witcher IV."""
    first = add(tracker, igdb, "1", "Ведьмак 3")
    second = add(tracker, igdb, "3", "Ведьмак 2")
    run(tracker.poll_due())
    clock.advance(days=7)
    set_snapshot(session_factory, second, next_check_at=naive(clock.now) + timedelta(days=1))
    return first, second


def test_a_withdrawn_announcement_comes_later_from_another_game_of_the_series(
    tracker, igdb, follow, session_factory, clock
):
    first, second = two_games_of_one_series(tracker, igdb, session_factory, clock)
    witcher_four_is_announced(follow, "1", "3")
    run(tracker.poll_due())
    assert events_of(session_factory, first) == ["game:follow_up:2"]  # waits for the summary

    run(tracker.mark_dropped(first))
    assert events_of(session_factory) == []  # the event went with its queue entry: its key is free
    clock.advance(days=1)
    run(tracker.poll_due())

    assert events_of(session_factory, second) == ["game:follow_up:2"]
    assert [key for _, key in announcements(session_factory)] == ["game:follow_up:2"]


def test_the_same_game_cannot_repeat_a_withdrawn_announcement(tracker, igdb, follow, session_factory, clock):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    witcher_four_is_announced(follow, "1")
    clock.advance(days=7)
    run(tracker.poll_due())
    run(tracker.mark_dropped(title_id))

    run(tracker.restore_title(title_id))
    run(tracker.poll_due())  # the reference point after the return

    assert events_of(session_factory) == [] and snapshot_of(session_factory, title_id).state["known"] == ["2"]


def test_withdraw_deletes_the_entries_and_the_events_and_they_leave_recent(
    tracker, igdb, follow, session_factory, clock, sender
):
    run(tracker.set_delivery_rules(tz_name="UTC", workdays=[], quiet_from="00:00", quiet_until="00:00"))
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    follow.answers["1"] = series(follow_up("2", "The Witcher IV"))
    clock.advance(days=7)
    run(tracker.poll_due())
    run(tracker.deliver_pending())  # this one went out: it stays
    follow.answers["1"] = series(follow_up("2", "The Witcher IV"), follow_up("4", "The Witcher: Sirius"))
    set_snapshot(session_factory, title_id, next_check_at=None)  # both events stay inside «Недавно»
    clock.advance(minutes=1)
    run(tracker.poll_due())
    assert any("Sirius" in headline for headline in recent_headlines(tracker))

    run(tracker.mark_dropped(title_id))

    assert events_of(session_factory) == ["game:follow_up:2"]
    with session_factory() as session:
        assert [item.event_id for item in session.scalars(select(DeliveryItem))] == list(session.scalars(select(Event.id)))
    headlines = recent_headlines(tracker)
    assert not any("Sirius" in headline for headline in headlines)
    assert any("The Witcher IV" in headline for headline in headlines)
    assert len(sender.texts) == 1


def test_a_game_dropped_while_igdb_answers_spends_no_key(tracker, igdb, follow, session_factory, clock):
    first, second = two_games_of_one_series(tracker, igdb, session_factory, clock)
    witcher_four_is_announced(follow, "1", "3")

    async def drop(external_id):
        if external_id == "1":
            await tracker.mark_dropped(first)

    follow.during = drop
    run(tracker.poll_due())
    assert events_of(session_factory) == []

    clock.advance(days=1)
    run(tracker.poll_due())
    assert events_of(session_factory, second) == ["game:follow_up:2"]


# --- KI-52: the game's own type and parent --------------------------------------------------------------------------


def test_the_query_asks_the_parent_of_the_game_itself():
    assert "fields name,game_type,parent_game.name," in FOLLOW_UPS_QUERY


@pytest.mark.parametrize(
    "raw, expansion, parent",
    [
        ({"game_type": 4, "parent_game": {"id": 7331, "name": "Uncharted 4: A Thief's End"}}, games.STANDALONE, UNCHARTED_4),
        ({"game_type": 2, "parent_game": {"id": 7331, "name": "Uncharted 4: A Thief's End"}}, games.EXPANSION, UNCHARTED_4),
        ({"game_type": 9, "parent_game": {"id": 7331, "name": "Uncharted 4: A Thief's End"}}, None, None),  # a remaster
        ({"game_type": 4}, None, None),
        ({"game_type": 4, "parent_game": {"id": 7331}}, None, None),  # no name: no parent, as the own poll reads it
        ({"game_type": 0, "parent_game": 7331}, None, None),
    ],
)
def test_parse_follow_ups_reads_the_own_kind_and_parent_as_the_own_poll_does(raw, expansion, parent):
    snapshot = parse_follow_ups({"id": 1, "name": "Uncharted: The Lost Legacy", **raw})

    assert (snapshot.own_expansion, snapshot.own_parent) == (expansion, parent)
    assert "own_expansion" not in snapshot.state() and "own_parent" not in snapshot.state()  # not stored


def lost_legacy(tracker, igdb, follow, session_factory):
    """A standalone expansion added as a plain game (before stage 6.3) and completed; IGDB now says what it is."""
    title_id = add(tracker, igdb, "1", "Uncharted: The Lost Legacy")
    run(tracker.mark_watched(title_id))
    follow.answers["1"] = FollowUpsSnapshot(own_expansion=games.STANDALONE, own_parent=UNCHARTED_4)
    return title_id


def test_a_completed_standalone_expansion_learns_its_kind_and_parent(tracker, igdb, follow, session_factory):
    title_id = lost_legacy(tracker, igdb, follow, session_factory)
    before = own_state(session_factory, title_id)

    run(tracker.poll_due())

    after = own_state(session_factory, title_id)
    assert after == {**before, "expansion": games.STANDALONE, "parent": UNCHARTED_4.state()}
    [row] = run(tracker.list_titles(TitleKind.GAME))
    assert row.tag == "дополнение"
    assert snapshot_of(session_factory, title_id) is not None  # a standalone expansion is still checked


@pytest.mark.parametrize("tracking", [True, False])
def test_a_game_in_want_leaves_its_own_snapshot_to_its_own_poll_unless_tracking_is_off(
    tracking, tracker, igdb, follow, session_factory
):
    title_id = add(tracker, igdb)
    with session_factory() as session:
        session.get(Title, title_id).tracking_enabled = tracking
        session.commit()
    follow.answers["1"] = FollowUpsSnapshot(own_expansion=games.STANDALONE, own_parent=UNCHARTED_4)

    run(tracker.poll_due())

    assert own_state(session_factory, title_id).get("expansion") == (None if tracking else games.STANDALONE)


def test_a_spoiled_own_state_is_left_alone(tracker, igdb, follow, session_factory):
    title_id = lost_legacy(tracker, igdb, follow, session_factory)
    spoiled = {**own_state(session_factory, title_id), "releases": [{"type": "rumour"}]}  # `expansion` itself reads
    set_own_state(session_factory, title_id, spoiled)

    run(tracker.poll_due())

    assert own_state(session_factory, title_id) == spoiled
    assert snapshot_of(session_factory, title_id).state["known"] == []  # the check itself worked


def test_a_game_that_turns_out_to_need_its_game_is_dropped_by_the_next_reconciliation(
    tracker, igdb, follow, session_factory, clock
):
    title_id = lost_legacy(tracker, igdb, follow, session_factory)
    follow.answers["1"] = FollowUpsSnapshot(own_expansion=games.EXPANSION, own_parent=UNCHARTED_4)

    run(tracker.poll_due())
    assert own_state(session_factory, title_id)["expansion"] == games.EXPANSION
    clock.advance(minutes=1)
    run(tracker.poll_due())

    assert snapshot_of(session_factory, title_id) is None


def test_the_same_kind_writes_nothing(tracker, igdb, follow, session_factory, caplog):
    title_id = add(tracker, igdb, "1", "Uncharted: The Lost Legacy", game(expansion=games.STANDALONE))
    run(tracker.mark_watched(title_id))
    follow.answers["1"] = FollowUpsSnapshot(own_expansion=games.STANDALONE, own_parent=Parent("1942", "The Witcher 3: Wild Hunt"))

    with caplog.at_level(logging.INFO):
        run(tracker.poll_due())

    assert not any("written into its own snapshot" in record.getMessage() for record in caplog.records)


# --- KI-55: an unreadable own snapshot ------------------------------------------------------------------------------


def unreadable_lines(caplog, title_id):
    return [
        record for record in caplog.records
        if "own snapshot cannot be read" in record.getMessage() and f"title {title_id}:" in record.getMessage()
    ]


@pytest.mark.parametrize("history", ["never checked", "checked before"])
def test_an_unreadable_own_snapshot_fails_before_igdb_and_reports_once_a_day(
    history, tracker, igdb, follow, session_factory, clock, caplog
):
    title_id = add(tracker, igdb)
    if history == "checked before":
        run(tracker.poll_due())
        set_snapshot(session_factory, title_id, next_check_at=None)  # due again; its own poll is not
    follow.calls.clear()
    set_own_state(session_factory, title_id, {**own_state(session_factory, title_id), "expansion": "dlc"})

    with caplog.at_level(logging.WARNING):
        report = run(tracker.poll_due())

    assert follow.calls == []  # IGDB is not asked
    assert report.failed == 1 and report.notices == 1
    stored = snapshot_of(session_factory, title_id)  # made if missing
    assert stored is not None and stored.next_check_at == naive(clock.now + timedelta(minutes=30))
    assert len(unreadable_lines(caplog, title_id)) == 1

    for _ in range(3):  # every 30 minutes: a failure each time, the notice and the log line once a day
        clock.advance(minutes=30)
        with caplog.at_level(logging.WARNING):
            report = run(tracker.poll_due())
        assert report.failed == 1 and report.notices == 0
    assert follow.calls == [] and len(unreadable_lines(caplog, title_id)) == 1
    assert snapshot_of(session_factory, title_id).id == stored.id  # never dropped by the reconciliation


def test_an_unreadable_own_snapshot_counts_by_status_alone(tracker, igdb, session_factory):
    kept = add(tracker, igdb, "1", "Ведьмак 3")
    dropped = add(tracker, igdb, "3", "Ведьмак 2")
    run(tracker.poll_due())
    for title_id in (kept, dropped):
        set_own_state(session_factory, title_id, {**own_state(session_factory, title_id), "expansion": "dlc"})
    with session_factory() as session:  # «Бросил» by hand, past the press: the reconciliation decides
        session.get(Title, dropped).status = TitleStatus.DROPPED
        session.commit()

    run(tracker.poll_due())

    assert snapshot_of(session_factory, kept) is not None
    assert snapshot_of(session_factory, dropped) is None
