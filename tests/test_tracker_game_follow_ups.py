"""The weekly follow-up check of the games (spec 5 of stage 6.3, ticket 02): which games are checked and which lose the
check (the table of 5.1), 10 a pass, 7 days and 30 minutes, the reference point, the announcements queued before the
store, «Бросил» during the request, the failures and their notices, one IGDB client for both sources.

Driven through the facade: fake clock, fake sender, in-memory SQLite. IGDB is a made-up game source whose snapshots the
test writes; the follow-ups come from a fake source of `FollowUpsSnapshot`s.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import event, select

from app.providers.igdb import IgdbError
from app.tracker import follow_ups, games
from app.tracker.core import SourceNotConfigured, Tracker
from app.tracker.db import create_session_factory
from app.tracker.failures import TitleGone
from app.tracker.follow_ups import Candidate, FollowUpsSnapshot
from app.tracker.games import GameState, Parent
from app.tracker.models import DeliveryItem, DeliveryStatus, Event, SourceSnapshot, TitleKind, TitleStatus
from app.tracker.pollers.game_follow_ups import (
    FOLLOW_UP_INTERVAL, FOLLOW_UPS_PER_PASS, GameFollowUps, for_follow_ups,
)
from app.tracker.pollers.game_prices import GamePrices
from app.tracker.sources.igdb_follow_ups import IgdbFollowUpSource
from app.tracker.sources.igdb_games import GameSnapshot

T0 = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
PC, PS5 = 6, 167
SOURCE = "igdb_follow_ups"


def run(coro):
    return asyncio.run(coro)


def naive(moment):
    return moment.astimezone(timezone.utc).replace(tzinfo=None)


class FakeClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, **delta):
        self.now += timedelta(**delta)


class FakeSender:
    def __init__(self):
        self.texts = []

    async def send(self, message, actions=()):
        self.texts.append(message)


class MadeUpGames:
    """A game source whose snapshots the test writes."""

    source_key = "igdb"

    def __init__(self):
        self.by_id = {}

    def put(self, external_id, game, name):
        self.by_id[external_id] = GameSnapshot(external_id, name, name, 2026, game=game)

    async def suggest(self, query):
        return []

    async def snapshot(self, external_id):
        return self.by_id.get(external_id)

    async def snapshot_to_add(self, external_id):
        return self.by_id.get(external_id)


class FakeFollowUps:
    """A source of the follow-up check: `answers` by IGDB id (an empty snapshot for the others), `failures` raise;
    `during` runs while IGDB is answering."""

    source_key = SOURCE

    def __init__(self):
        self.answers = {}
        self.failures = {}
        self.calls = []
        self.during = None

    async def follow_ups(self, external_id):
        self.calls.append(external_id)
        if self.during is not None:
            await self.during(external_id)
        if external_id in self.failures:
            raise self.failures[external_id]
        return self.answers.get(external_id, FollowUpsSnapshot())


def candidate(id_, name, platforms=(PC,)):
    return Candidate(id_, name, platforms=tuple(platforms))


def series(*games_, expansions=()):
    return FollowUpsSnapshot(games=tuple(games_), expansions=tuple(expansions))


def game(platforms=(PC, PS5), expansion=None):
    parent = Parent("1942", "The Witcher 3: Wild Hunt") if expansion else None
    return GameState(platforms=tuple(platforms), expansion=expansion, parent=parent)


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


def add(tracker, igdb, external_id="1", name="Ведьмак 3", state=None):
    igdb.put(external_id, state if state is not None else game(), name)
    return run(tracker.add_title(TitleKind.GAME, external_id)).title_id


def snapshot_of(session_factory, title_id, source=SOURCE):
    with session_factory() as session:
        return session.scalar(
            select(SourceSnapshot).where(SourceSnapshot.title_id == title_id, SourceSnapshot.source == source)
        )


def set_snapshot(session_factory, title_id, source=SOURCE, **values):
    with session_factory() as session:
        stored = session.scalar(
            select(SourceSnapshot).where(SourceSnapshot.title_id == title_id, SourceSnapshot.source == source)
        )
        for key, value in values.items():
            setattr(stored, key, value)
        session.commit()


def pending(session_factory):
    with session_factory() as session:
        return [
            (row.type, row.dedup_key, row.payload)
            for row in session.scalars(
                select(Event)
                .join(DeliveryItem, DeliveryItem.event_id == Event.id)
                .where(DeliveryItem.status == DeliveryStatus.PENDING)
                .order_by(Event.id)
            )
        ]


def announcements(session_factory):
    return [(type_, key) for type_, key, _ in pending(session_factory) if type_ in follow_ups.TYPES]


# --- the rule (spec 5.1) --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status, expansion, checked",
    [
        (TitleStatus.WANT, None, True),
        (TitleStatus.IN_PROGRESS, None, True),
        (TitleStatus.COMPLETED, None, True),
        (TitleStatus.DROPPED, None, False),
        (TitleStatus.WANT, games.EXPANSION, False),
        (TitleStatus.COMPLETED, games.EXPANSION, False),
        (TitleStatus.WANT, games.STANDALONE, True),
    ],
)
def test_the_rule_of_a_game_for_the_check(status, expansion, checked):
    assert for_follow_ups(status, expansion) is checked


def test_only_the_key_expansion_of_the_own_snapshot_is_read_strictly():
    assert games.expansion_of({"releases": "garbage"}) is None
    assert games.expansion_of({"expansion": "standalone"}) == games.STANDALONE
    for spoiled in ({"expansion": "dlc"}, ["expansion"], None):
        with pytest.raises(ValueError):
            games.expansion_of(spoiled)


# --- the reconciliation (spec 5.1, 5.2) -----------------------------------------------------------------------------


def test_an_added_game_gets_a_snapshot_and_its_reference_point_in_the_same_pass(tracker, igdb, follow, session_factory):
    follow.answers["1"] = series(candidate("2", "The Witcher IV"))
    title_id = add(tracker, igdb)
    assert snapshot_of(session_factory, title_id) is None  # adding does not touch the check

    report = run(tracker.poll_due())

    stored = snapshot_of(session_factory, title_id)
    assert follow.calls == ["1"]
    assert stored.state["known"] == ["2"]
    assert stored.observed_at == naive(T0) and stored.next_check_at == naive(T0 + FOLLOW_UP_INTERVAL)
    assert announcements(session_factory) == []  # the reference point is silent
    assert report.failed == 0


@pytest.mark.parametrize("change", ["started", "completed"])
def test_starting_and_completing_go_on_as_they_were(change, tracker, igdb, follow, session_factory):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    before = snapshot_of(session_factory, title_id)

    run(tracker.mark_started(title_id) if change == "started" else tracker.mark_watched(title_id))
    run(tracker.poll_due())

    after = snapshot_of(session_factory, title_id)
    assert (after.id, after.state, after.next_check_at) == (before.id, before.state, before.next_check_at)
    assert follow.calls == ["1"]


def test_dropping_removes_the_snapshot_and_restoring_starts_with_a_new_reference_point(
    tracker, igdb, follow, session_factory, clock
):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())

    run(tracker.mark_dropped(title_id))
    run(tracker.poll_due())
    assert snapshot_of(session_factory, title_id) is None

    follow.answers["1"] = series(candidate("2", "The Witcher IV"))  # announced while the game was dropped
    clock.advance(minutes=1)
    run(tracker.restore_title(title_id))
    run(tracker.poll_due())

    assert snapshot_of(session_factory, title_id).state["known"] == ["2"]
    assert announcements(session_factory) == []
    assert follow.calls == ["1", "1"]


def test_restoring_from_completed_goes_on_as_it_was(tracker, igdb, follow, session_factory):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    before = snapshot_of(session_factory, title_id)
    run(tracker.mark_watched(title_id))
    run(tracker.poll_due())

    run(tracker.restore_title(title_id))
    run(tracker.poll_due())

    after = snapshot_of(session_factory, title_id)
    assert (after.id, after.state, after.next_check_at) == (before.id, before.state, before.next_check_at)
    assert follow.calls == ["1"]


def test_an_expansion_needing_its_game_has_no_check_and_a_standalone_one_has(tracker, igdb, follow, session_factory):
    blood_and_wine = add(tracker, igdb, "2", "Кровь и Вино", game(expansion=games.EXPANSION))
    lost_legacy = add(tracker, igdb, "3", "Uncharted: The Lost Legacy", game(expansion=games.STANDALONE))
    run(tracker.mark_watched(blood_and_wine))  # «Пройдено» does not start it either

    run(tracker.poll_due())

    assert snapshot_of(session_factory, blood_and_wine) is None
    assert snapshot_of(session_factory, lost_legacy) is not None
    assert follow.calls == ["3"]


def test_a_game_igdb_turns_into_an_expansion_loses_its_check(tracker, igdb, follow, session_factory):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())

    with session_factory() as session:
        own = session.scalar(select(SourceSnapshot).where(SourceSnapshot.title_id == title_id, SourceSnapshot.source == "igdb"))
        own.state = game(expansion=games.EXPANSION).state()
        session.commit()
    run(tracker.poll_due())

    assert snapshot_of(session_factory, title_id) is None


def test_deleting_the_game_deletes_its_snapshot(tracker, igdb, session_factory):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())

    run(tracker.delete_title(title_id))

    assert snapshot_of(session_factory, title_id) is None


def test_without_a_source_of_the_check_there_are_no_snapshots(session_factory, clock, sender, igdb):
    tracker = Tracker(session_factory, clock=clock, sender=sender, sources={TitleKind.GAME: igdb})
    title_id = add(tracker, igdb)

    run(tracker.poll_due())

    assert snapshot_of(session_factory, title_id) is None


def test_the_reconciliation_reads_as_much_for_thirty_games_as_for_one(tracker, igdb, follow, session_factory, clock):
    def reads_of_a_quiet_pass():
        statements = []
        engine = session_factory.kw["bind"]
        listener = lambda *args: statements.append(args[2])  # noqa: E731
        event.listen(engine, "before_cursor_execute", listener)
        try:
            run(tracker.poll_due())
        finally:
            event.remove(engine, "before_cursor_execute", listener)
        return len([s for s in statements if s.lstrip().upper().startswith("SELECT")])

    add(tracker, igdb, "1")
    run(tracker.poll_due())
    one = reads_of_a_quiet_pass()
    for n in range(2, 31):
        add(tracker, igdb, str(n), f"Игра {n}")
    for _ in range(3):  # 29 new games, 10 a pass
        run(tracker.poll_due())
    thirty = reads_of_a_quiet_pass()

    assert one == thirty and len(follow.calls) == 30


# --- when (spec 5.3) ------------------------------------------------------------------------------------------------


def test_ten_games_a_pass_the_earliest_first_the_others_next_pass(tracker, igdb, follow, session_factory, clock):
    ids = [add(tracker, igdb, str(n), f"Игра {n}") for n in range(1, 13)]
    run(tracker.poll_due())
    assert follow.calls == [str(n) for n in range(1, FOLLOW_UPS_PER_PASS + 1)]

    clock.advance(minutes=1)
    run(tracker.poll_due())
    assert follow.calls[FOLLOW_UPS_PER_PASS:] == ["11", "12"]

    # the earliest `next_check_at` first, whatever the title number
    set_snapshot(session_factory, ids[11], next_check_at=naive(T0))
    set_snapshot(session_factory, ids[0], next_check_at=naive(T0 + timedelta(seconds=30)))
    follow.calls.clear()
    run(tracker.poll_due())
    assert follow.calls == ["12", "1"]


def test_a_game_is_checked_again_a_week_after_a_check_that_worked(tracker, igdb, follow, clock):
    add(tracker, igdb)
    run(tracker.poll_due())

    clock.advance(days=7, minutes=-1)
    run(tracker.poll_due())
    assert follow.calls == ["1"]

    clock.advance(minutes=1)
    run(tracker.poll_due())
    assert follow.calls == ["1", "1"]


# --- what is new and the queueing (spec 5.3–5.5) --------------------------------------------------------------------


def test_a_later_check_announces_each_new_follow_up_once_with_its_key(tracker, igdb, follow, session_factory, clock):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())

    follow.answers["1"] = series(
        candidate("2", "The Witcher IV"), expansions=[candidate("3", "Баллады прошлого")]
    )
    clock.advance(days=7)
    run(tracker.poll_due())

    events = pending(session_factory)
    assert [(type_, key) for type_, key, _ in events] == [
        (follow_ups.EXPANSION_ANNOUNCED, "game:follow_up:3"),
        (follow_ups.SEQUEL_ANNOUNCED, "game:follow_up:2"),
    ]
    expansion = events[0][2]
    assert expansion["text"] == "🎮 Анонсировано дополнение: Баллады прошлого\nДополнение к игре «Ведьмак 3»\nВыход: дата не объявлена"
    assert expansion["kind"] == "game" and expansion["sequel_id"] == "3" and expansion["sequel_title"] == "Баллады прошлого"
    with session_factory() as session:
        assert {e.title_id for e in session.scalars(select(Event).where(Event.type.in_(follow_ups.TYPES)))} == {title_id}
    assert sorted(snapshot_of(session_factory, title_id).state["known"]) == ["2", "3"]

    clock.advance(days=7)
    run(tracker.poll_due())
    assert len(announcements(session_factory)) == 2  # nothing twice


def test_a_follow_up_in_the_list_is_not_announced_but_is_known(tracker, igdb, follow, session_factory, clock):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    add(tracker, igdb, "2", "The Witcher IV")  # the owner follows it already

    follow.answers["1"] = series(candidate("2", "The Witcher IV"))
    set_snapshot(session_factory, title_id, next_check_at=None)
    run(tracker.poll_due())

    assert announcements(session_factory) == []
    assert snapshot_of(session_factory, title_id).state["known"] == ["2"]


def test_two_games_of_one_series_give_one_announcement(tracker, igdb, follow, session_factory, clock):
    add(tracker, igdb, "1", "Ведьмак 3")
    add(tracker, igdb, "5", "Ведьмак 2")
    run(tracker.poll_due())

    witcher_iv = candidate("2", "The Witcher IV")
    follow.answers["1"] = series(witcher_iv)
    follow.answers["5"] = series(witcher_iv)
    clock.advance(days=7)
    run(tracker.poll_due())

    assert announcements(session_factory) == [(follow_ups.SEQUEL_ANNOUNCED, "game:follow_up:2")]


def test_the_announcements_are_queued_before_the_state_is_stored(tracker, igdb, follow, session_factory, clock, monkeypatch, caplog):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    before = snapshot_of(session_factory, title_id).state

    def broken(self, *args):
        raise RuntimeError("the store failed")

    monkeypatch.setattr(GameFollowUps, "_store", broken)
    follow.answers["1"] = series(candidate("2", "The Witcher IV"))
    clock.advance(days=7)
    report = run(tracker.poll_due())

    assert announcements(session_factory) == [(follow_ups.SEQUEL_ANNOUNCED, "game:follow_up:2")]
    stored = snapshot_of(session_factory, title_id)
    assert stored.state == before and stored.next_check_at == naive(clock.now + timedelta(minutes=30))
    assert report.failed == 0  # a bug, not a failure to tell about
    assert any(r.exc_info for r in caplog.records if "follow-up check of title" in r.getMessage())

    monkeypatch.undo()
    clock.advance(minutes=30)
    run(tracker.poll_due())
    assert announcements(session_factory) == [(follow_ups.SEQUEL_ANNOUNCED, "game:follow_up:2")]  # the key drops it


@pytest.mark.parametrize("change", ["dropped", "deleted"])
def test_dropped_or_deleted_during_the_request_queues_and_stores_nothing(
    change, tracker, igdb, follow, session_factory, clock, sender
):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    follow.answers["1"] = series(candidate("2", "The Witcher IV"))

    async def press(external_id):
        await (tracker.mark_dropped(title_id) if change == "dropped" else tracker.delete_title(title_id))

    follow.during = press
    clock.advance(days=7)
    stored_before = snapshot_of(session_factory, title_id)
    report = run(tracker.poll_due())

    assert announcements(session_factory) == [] and report.failed == 0
    if change == "dropped":
        stored = snapshot_of(session_factory, title_id)
        assert (stored.state, stored.observed_at) == (stored_before.state, stored_before.observed_at)
        follow.during = None
        clock.advance(minutes=1)
        run(tracker.poll_due())
    assert snapshot_of(session_factory, title_id) is None


def test_a_game_dropped_while_igdb_fails_gets_no_notice(tracker, igdb, follow, session_factory, clock):
    title_id = add(tracker, igdb)
    follow.failures["1"] = IgdbError("timeout", cause=httpx.ReadTimeout("slow"))

    async def press(external_id):
        await tracker.mark_dropped(title_id)

    follow.during = press
    report = run(tracker.poll_due())

    assert report.failed == 0 and report.notices == 0


# --- failures (spec 5.6) --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "failure, reason",
    [
        (IgdbError("timeout", cause=httpx.ReadTimeout("slow")), "IGDB не ответил вовремя"),
        (TitleGone("IGDB has no game 1"), "IGDB"),
        (SourceNotConfigured("IGDB_CLIENT_ID or IGDB_CLIENT_SECRET is empty"), "IGDB"),
    ],
)
def test_a_failure_waits_thirty_minutes_and_is_told_once_a_day(failure, reason, tracker, igdb, follow, session_factory, sender, clock):
    title_id = add(tracker, igdb)
    follow.failures["1"] = failure

    report = run(tracker.poll_due())
    run(tracker.deliver_pending())

    assert report.failed == 1 and report.notices == 1
    assert snapshot_of(session_factory, title_id).next_check_at == naive(T0 + timedelta(minutes=30))
    assert snapshot_of(session_factory, title_id).state == {}
    assert len(sender.texts) == 1 and reason in sender.texts[0] and "Ведьмак 3" in sender.texts[0]

    clock.advance(minutes=29)
    run(tracker.poll_due())
    assert follow.calls == ["1"]
    clock.advance(minutes=1)
    run(tracker.poll_due())
    run(tracker.deliver_pending())
    assert follow.calls == ["1", "1"] and len(sender.texts) == 1  # one notice a game a day


def test_one_failing_game_does_not_stop_the_others(tracker, igdb, follow, session_factory):
    broken = add(tracker, igdb, "1", "Ведьмак 3")
    fine = add(tracker, igdb, "2", "Hades II")
    follow.failures["1"] = IgdbError("boom", status=500)

    report = run(tracker.poll_due())

    assert report.failed == 1
    assert snapshot_of(session_factory, broken).state == {}
    assert snapshot_of(session_factory, fine).state["known"] == []


def test_a_spoiled_state_fails_only_its_game_and_deleting_the_row_heals_it(
    tracker, igdb, follow, session_factory, sender, clock
):
    spoiled = add(tracker, igdb, "1", "Ведьмак 3")
    fine = add(tracker, igdb, "2", "Hades II")
    run(tracker.poll_due())
    set_snapshot(session_factory, spoiled, state={"known": 5}, next_check_at=None)
    set_snapshot(session_factory, fine, next_check_at=None)
    follow.calls.clear()

    report = run(tracker.poll_due())
    run(tracker.deliver_pending())

    assert follow.calls == ["2"]  # the spoiled game is not asked about
    assert report.failed == 1 and "Ведьмак 3" in sender.texts[-1]
    assert snapshot_of(session_factory, spoiled).next_check_at == naive(T0 + timedelta(minutes=30))

    with session_factory() as session:
        session.delete(session.get(SourceSnapshot, snapshot_of(session_factory, spoiled).id))
        session.commit()
    follow.answers["1"] = series(candidate("9", "The Witcher IV"))
    run(tracker.poll_due())
    assert snapshot_of(session_factory, spoiled).state["known"] == ["9"]  # a new reference point
    assert announcements(session_factory) == []


def test_a_spoiled_own_snapshot_leaves_the_game_out_and_fails_its_due_check(
    tracker, igdb, follow, session_factory, caplog
):
    checked = add(tracker, igdb, "1", "Ведьмак 3")
    run(tracker.poll_due())
    never_checked = add(tracker, igdb, "2", "Hades II")
    fine = add(tracker, igdb, "3", "Elden Ring")
    with session_factory() as session:
        for own in session.scalars(
            select(SourceSnapshot).where(SourceSnapshot.source == "igdb", SourceSnapshot.title_id.in_([checked, never_checked]))
        ):
            own.state = {**own.state, "expansion": "dlc"}
        session.commit()
    set_snapshot(session_factory, checked, next_check_at=None)
    follow.calls.clear()

    with caplog.at_level(logging.WARNING):
        report = run(tracker.poll_due())

    assert snapshot_of(session_factory, never_checked) is None  # left out: no snapshot made
    assert snapshot_of(session_factory, checked) is not None  # left out: its snapshot is not removed either
    assert snapshot_of(session_factory, fine).state == {"own_date": None, "collections": [], "expansions": [], "games": [], "known": []}
    assert report.failed == 1  # the game that was due fails, with a notice
    assert any("cannot be read" in r.getMessage() and f"title {never_checked}" in r.getMessage() for r in caplog.records)


# --- the end of the pass ----------------------------------------------------------------------------------------------


def test_a_bug_in_the_follow_up_check_goes_to_the_log_and_leaves_the_pass(tracker, igdb, monkeypatch, caplog, session_factory):
    add(tracker, igdb)
    with session_factory() as session:
        for own in session.scalars(select(SourceSnapshot).where(SourceSnapshot.source == "igdb")):
            own.next_check_at = None
        session.commit()

    def broken(self):
        raise RuntimeError("a bug")

    monkeypatch.setattr(GameFollowUps, "_reconcile", broken)
    report = run(tracker.poll_due())

    assert report.polled == 1 and report.failed == 0
    failed = [r for r in caplog.records if "end of the pass" in r.getMessage()]
    assert failed and failed[0].exc_info is not None


def test_a_bug_in_the_price_check_leaves_the_follow_up_check(tracker, igdb, follow, monkeypatch, session_factory):
    title_id = add(tracker, igdb)

    async def broken(self):
        raise RuntimeError("a bug")

    monkeypatch.setattr(GamePrices, "check", broken)
    run(tracker.poll_due())

    assert follow.calls == ["1"] and snapshot_of(session_factory, title_id).state != {}


def test_the_prices_are_checked_before_the_follow_ups(tracker, igdb, follow, monkeypatch):
    order = []
    prices_check = GamePrices.check
    follow_check = GameFollowUps.check

    async def prices(self):
        order.append("prices")
        return await prices_check(self)

    async def follow_ups_(self):
        order.append("follow-ups")
        return await follow_check(self)

    monkeypatch.setattr(GamePrices, "check", prices)
    monkeypatch.setattr(GameFollowUps, "check", follow_ups_)
    run(tracker.poll_due())

    assert order == ["prices", "follow-ups"]


def test_the_follow_up_snapshot_is_not_polled_as_the_own_source(tracker, igdb, follow, session_factory, clock):
    """The pass over the titles takes only the own source; the check's snapshot is the check's alone."""
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    set_snapshot(session_factory, title_id, next_check_at=None)
    follow.calls.clear()

    report = run(tracker.poll_due())

    assert report.polled == 0 and follow.calls == ["1"]


# --- the sources (spec 2.2) -----------------------------------------------------------------------------------------


def test_build_tracker_gives_both_igdb_sources_one_client(monkeypatch):
    from app import main

    monkeypatch.setattr(main, "create_session_factory", lambda: create_session_factory("sqlite://"))
    settings = SimpleNamespace(
        owner_chat=1, igdb_client_id="", igdb_client_secret="", bot_timezone="UTC", model_fields_set={"bot_timezone"}
    )

    tracker = main.build_tracker(settings, None)

    assert isinstance(tracker.follow_up_source, IgdbFollowUpSource)
    assert tracker.follow_up_source._provider is tracker.sources[TitleKind.GAME]._provider
    with pytest.raises(SourceNotConfigured):  # without keys both are «not connected»
        run(tracker.follow_up_source.follow_ups("1942"))


def test_the_sources_of_a_game_go_to_the_game_poller_only(tracker):
    from app.tracker.pollers.base import Poller

    pollers = tracker._polling.pollers
    assert not hasattr(Poller(TitleKind.MOVIE, None, None, None, None), "price_source")
    assert pollers.reader_of(TitleKind.GAME).follow_ups.source is tracker.follow_up_source
    for kind in (TitleKind.MOVIE, TitleKind.SERIES, TitleKind.ANIME):
        assert not hasattr(pollers.reader_of(kind), "follow_ups")
