"""The price check at the end of a polling pass (spec 4 of part 6.2, ticket 03): which games get a price snapshot and
which lose it, the reference point, the interval, the packs of 100, the failures and the price history.

Driven through the facade: fake clock, fake sender, in-memory SQLite. IGDB is a made-up source whose snapshots the
test writes; the prices come from a fake source of looks, and once through the real adapter on a saved answer of Steam.
"""

import asyncio
import json
import logging
import pathlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import event, select

from app.providers.steam import SteamError
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.games import GameState
from app.tracker.models import (
    DeliveryItem, DeliveryStatus, Event, PriceRecord, SettingRecord, SourceSnapshot, Title, TitleKind,
)
from app.tracker import price_events
from app.tracker.pollers.game_prices import PRICE_INTERVAL, GamePrices, is_baseline, lowest_seen
from app.tracker.prices import FREE, PRICE, Price, PriceLook
from app.tracker.queue import EventQueue
from app.tracker.settings_store import MY_PLATFORMS_SETTING, STORE_COUNTRY_SETTING
from app.tracker.sources.igdb_games import GameSnapshot
from app.tracker.sources.steam_prices import SteamPriceSource, UnreadAnswer

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
T0 = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
PC, PS5 = 6, 167
HADES = "1145350"


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
    """A game source whose snapshots the test writes; `gone` — IGDB no longer knows these."""

    source_key = "igdb"

    def __init__(self):
        self.by_id = {}
        self.gone = set()

    def put(self, external_id, game, name):
        self.by_id[external_id] = GameSnapshot(external_id, name, name, 2026, game=game)

    async def suggest(self, query):
        return []

    async def snapshot(self, external_id):
        return None if external_id in self.gone else self.by_id.get(external_id)

    async def snapshot_to_add(self, external_id):
        return self.by_id.get(external_id)


def price_look(appid, country="il", final=27900, original=None, pct=0):
    return PriceLook(appid, country, PRICE, "₪{}", Price(final, original, pct))


class FakePrices:
    """A source of price looks: a price for every number asked (`final` by number), `unread` numbers unreadable,
    `failure` — the whole request fails; `during` runs while Steam is answering."""

    def __init__(self):
        self.calls = []
        self.final = {}
        self.discount = {}  # number → (original, pct)
        self.free = set()
        self.unread = set()
        self.failure = None
        self.during = None

    async def price_looks(self, appids, country):
        self.calls.append((list(appids), country))
        if self.during is not None:
            await self.during()
        if self.failure is not None:
            raise self.failure
        looks = {}
        for appid in appids:
            if appid in self.unread:
                looks[appid] = UnreadAnswer(f"Steam app {appid}: purchase_options is None")
            elif appid in self.free:
                looks[appid] = PriceLook(appid, country, FREE)
            else:
                original, pct = self.discount.get(appid, (None, 0))
                looks[appid] = price_look(appid, country, self.final.get(appid, 27900), original, pct)
        return looks

    @property
    def asked(self):
        return [appids for appids, _ in self.calls]


def game(steam_id=HADES, platforms=(PC, PS5)):
    return GameState(steam_id=steam_id, platforms=tuple(platforms))


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
def prices():
    return FakePrices()


@pytest.fixture
def tracker(session_factory, clock, sender, igdb, prices):
    return Tracker(session_factory, clock=clock, sender=sender, sources={TitleKind.GAME: igdb}, price_source=prices)


def add(tracker, igdb, state=None, external_id="1", name="Hades II"):
    igdb.put(external_id, state if state is not None else game(), name)
    return run(tracker.add_title(TitleKind.GAME, external_id)).title_id


def igdb_says(session_factory, igdb, state, external_id="1"):
    """IGDB answers `state` from now on, and the game's IGDB check is due in this pass."""
    igdb.by_id[external_id] = replace(igdb.by_id[external_id], game=state)
    with session_factory() as session:
        for stored in session.scalars(select(SourceSnapshot).where(SourceSnapshot.source == "igdb")):
            stored.next_check_at = None
        session.commit()


def put_setting(session_factory, key, value):
    with session_factory() as session:
        session.merge(SettingRecord(key=key, value=value))
        session.commit()


def price_snapshot(session_factory, title_id):
    with session_factory() as session:
        return session.scalar(
            select(SourceSnapshot).where(SourceSnapshot.title_id == title_id, SourceSnapshot.source == "steam")
        )


def history(session_factory, title_id):
    with session_factory() as session:
        return [
            (r.appid, r.country, r.currency, r.final, r.original, r.pct)
            for r in session.scalars(select(PriceRecord).where(PriceRecord.title_id == title_id).order_by(PriceRecord.id))
        ]


def pending_types(session_factory, title_id):
    with session_factory() as session:
        return sorted(session.scalars(
            select(Event.type)
            .join(DeliveryItem, DeliveryItem.event_id == Event.id)
            .where(Event.title_id == title_id, DeliveryItem.status == DeliveryStatus.PENDING)
        ))


def baselines(caplog):
    return [r.getMessage() for r in caplog.records if "first price check" in r.getMessage()]


# --- which games (spec 4.1) ---------------------------------------------------------------------------------------


def test_a_game_for_prices_gets_a_snapshot_and_is_checked_in_the_same_pass(tracker, igdb, prices, session_factory):
    title_id = add(tracker, igdb)
    assert price_snapshot(session_factory, title_id) is None  # adding does not touch the prices

    report = run(tracker.poll_due())

    stored = price_snapshot(session_factory, title_id)
    assert prices.calls == [([HADES], "il")]
    assert stored.state == price_look(HADES).state()
    assert stored.observed_at == naive(T0) and stored.next_check_at == naive(T0) + PRICE_INTERVAL
    assert history(session_factory, title_id) == [(HADES, "il", "₪{}", 27900, None, 0)]
    assert report.polled == 0 and report.failed == 0  # the pass over the titles had nothing due


@pytest.mark.parametrize(
    "why",
    ["started", "completed", "dropped", "mark off", "pc not mine", "igdb took pc away", "igdb took the number away"],
)
def test_a_game_no_longer_for_prices_loses_its_snapshot_and_its_steam_messages_keep_the_history(
    why, tracker, igdb, prices, session_factory
):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    discount = run(tracker.record_event("game_discount", {"text": "−30 %"}, "game:1:discount", title_id=title_id))
    run(tracker.record_event("game_release", {"text": "вышла"}, "game:1:released", title_id=title_id))
    assert discount is not None

    if why == "started":
        run(tracker.mark_started(title_id))
    elif why == "completed":
        run(tracker.mark_watched(title_id))
    elif why == "dropped":
        run(tracker.mark_dropped(title_id))
    elif why == "mark off":
        run(tracker.set_platform_playing(title_id, "pc", False))
    elif why == "pc not mine":
        put_setting(session_factory, MY_PLATFORMS_SETTING, ["ps5"])
    elif why == "igdb took pc away":
        igdb_says(session_factory, igdb, game(platforms=(PS5,)))
    else:
        igdb_says(session_factory, igdb, game(steam_id=None))
    assert price_snapshot(session_factory, title_id) is not None or why == "dropped"  # buttons leave the snapshot
    run(tracker.poll_due())

    assert price_snapshot(session_factory, title_id) is None
    assert history(session_factory, title_id) == [(HADES, "il", "₪{}", 27900, None, 0)]
    # «Бросил» takes every message out at once, as before; the others only the messages of Steam
    assert pending_types(session_factory, title_id) == ([] if why == "dropped" else ["game_release"])
    assert len(prices.calls) == 1


def test_the_buttons_and_the_settings_do_not_touch_the_price_snapshot_by_themselves(tracker, igdb, session_factory):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())

    run(tracker.mark_started(title_id))
    run(tracker.set_platform_playing(title_id, "pc", False))
    put_setting(session_factory, MY_PLATFORMS_SETTING, ["ps5"])

    assert price_snapshot(session_factory, title_id).state == price_look(HADES).state()


@pytest.mark.parametrize("change", ["started", "completed", "dropped", "mark off"])
def test_without_the_rule_there_is_neither_a_check_nor_a_snapshot(change, tracker, igdb, prices, session_factory):
    title_id = add(tracker, igdb)
    if change == "started":
        run(tracker.mark_started(title_id))
    elif change == "completed":
        run(tracker.mark_watched(title_id))
    elif change == "dropped":
        run(tracker.mark_dropped(title_id))
    else:
        run(tracker.set_platform_playing(title_id, "pc", False))

    run(tracker.poll_due())

    assert prices.calls == [] and price_snapshot(session_factory, title_id) is None


def test_a_game_without_pc_or_without_a_steam_number_has_no_prices(tracker, igdb, prices, session_factory):
    console = add(tracker, igdb, game(platforms=(PS5,)), "1", "Bloodborne")
    no_page = add(tracker, igdb, game(steam_id=None), "2", "The Witcher 4")

    run(tracker.poll_due())

    assert prices.calls == []
    assert price_snapshot(session_factory, console) is None and price_snapshot(session_factory, no_page) is None


def test_the_mark_taken_off_and_set_again_within_a_minute_leaves_the_snapshot(tracker, igdb, prices, session_factory):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    before = price_snapshot(session_factory, title_id)

    run(tracker.set_platform_playing(title_id, "pc", False))
    run(tracker.set_platform_playing(title_id, "pc", True))
    run(tracker.poll_due())

    after = price_snapshot(session_factory, title_id)
    assert (after.id, after.state, after.next_check_at) == (before.id, before.state, before.next_check_at)
    assert len(prices.calls) == 1


def test_deleting_the_title_deletes_its_snapshot_and_its_history(tracker, igdb, session_factory):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())

    run(tracker.delete_title(title_id))

    assert price_snapshot(session_factory, title_id) is None
    with session_factory() as session:
        assert session.scalars(select(PriceRecord)).all() == []


def test_without_a_source_of_prices_nothing_is_checked(session_factory, clock, sender, igdb):
    tracker = Tracker(session_factory, clock=clock, sender=sender, sources={TitleKind.GAME: igdb})
    title_id = add(tracker, igdb)

    run(tracker.poll_due())

    assert price_snapshot(session_factory, title_id) is None


# --- the reference point (spec 4.3) -------------------------------------------------------------------------------


def test_a_first_check_and_a_check_of_another_number_or_country_are_the_reference_point():
    il = price_look(HADES)
    assert is_baseline(None, il)
    assert is_baseline(price_look("1"), il)
    assert is_baseline(price_look(HADES, "ua"), il)
    assert not is_baseline(price_look(HADES, final=19530, original=27900, pct=30), il)


def test_the_first_check_is_the_baseline_and_the_next_one_is_not(tracker, igdb, clock, caplog):
    caplog.set_level(logging.INFO)
    add(tracker, igdb)

    run(tracker.poll_due())
    assert len(baselines(caplog)) == 1

    clock.advance(hours=6)
    run(tracker.poll_due())
    assert len(baselines(caplog)) == 1


@pytest.mark.parametrize("how", ["restored", "mark set", "pc mine again", "steam number from igdb"])
def test_a_game_that_becomes_one_for_prices_again_starts_with_the_baseline(
    how, tracker, igdb, prices, session_factory, clock, caplog
):
    caplog.set_level(logging.INFO)
    title_id = add(tracker, igdb, game(steam_id=None) if how == "steam number from igdb" else None)
    if how == "restored":
        run(tracker.poll_due())
        run(tracker.mark_watched(title_id))
    elif how == "mark set":
        run(tracker.poll_due())
        run(tracker.set_platform_playing(title_id, "pc", False))
    elif how == "pc mine again":
        run(tracker.poll_due())
        put_setting(session_factory, MY_PLATFORMS_SETTING, ["ps5"])
    run(tracker.poll_due())
    assert price_snapshot(session_factory, title_id) is None
    caplog.clear()
    clock.advance(minutes=1)

    if how == "restored":
        run(tracker.restore_title(title_id))
    elif how == "mark set":
        run(tracker.set_platform_playing(title_id, "pc", True))
    elif how == "pc mine again":
        put_setting(session_factory, MY_PLATFORMS_SETTING, ["pc", "ps5"])
    else:
        igdb_says(session_factory, igdb, game())
    run(tracker.poll_due())

    assert price_snapshot(session_factory, title_id).state == price_look(HADES).state()
    assert len(baselines(caplog)) == 1 and prices.calls[-1] == ([HADES], "il")


def test_a_new_country_of_the_stores_is_checked_at_once_as_the_baseline(tracker, igdb, prices, session_factory, clock, caplog):
    caplog.set_level(logging.INFO)
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    caplog.clear()

    clock.advance(minutes=1)
    put_setting(session_factory, STORE_COUNTRY_SETTING, "ua")
    run(tracker.poll_due())

    assert prices.calls[-1] == ([HADES], "ua")
    assert price_snapshot(session_factory, title_id).state["country"] == "ua"
    assert len(baselines(caplog)) == 1
    assert [record[1] for record in history(session_factory, title_id)] == ["il", "ua"]


def test_a_new_steam_number_from_igdb_is_checked_at_once_as_the_baseline(tracker, igdb, prices, session_factory, clock, caplog):
    caplog.set_level(logging.INFO)
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    caplog.clear()

    clock.advance(minutes=1)
    igdb_says(session_factory, igdb, game(steam_id="2"))
    run(tracker.poll_due())

    assert prices.calls[-1] == (["2"], "il")
    assert price_snapshot(session_factory, title_id).state["appid"] == "2"
    assert len(baselines(caplog)) == 1


# --- when and how (spec 4.2) --------------------------------------------------------------------------------------


def test_prices_are_checked_again_six_hours_after_a_check_that_worked(tracker, igdb, prices, clock):
    add(tracker, igdb)
    run(tracker.poll_due())

    clock.advance(hours=5, minutes=59)
    run(tracker.poll_due())
    assert len(prices.calls) == 1

    clock.advance(minutes=1)
    run(tracker.poll_due())
    assert len(prices.calls) == 2


def test_prices_are_checked_again_thirty_minutes_after_a_failure(tracker, igdb, prices, session_factory, clock):
    title_id = add(tracker, igdb)
    prices.failure = SteamError("timeout", cause=httpx.ReadTimeout("slow"))
    run(tracker.poll_due())
    assert price_snapshot(session_factory, title_id).next_check_at == naive(T0) + timedelta(minutes=30)
    assert price_snapshot(session_factory, title_id).state == {}

    clock.advance(minutes=29)
    run(tracker.poll_due())
    assert len(prices.calls) == 1

    prices.failure = None
    clock.advance(minutes=1)
    run(tracker.poll_due())
    assert len(prices.calls) == 2 and price_snapshot(session_factory, title_id).state == price_look(HADES).state()


@pytest.mark.parametrize("change", ["country", "number"])
def test_a_failed_check_of_a_new_country_or_number_waits_thirty_minutes_too(
    change, tracker, igdb, prices, session_factory, clock, caplog
):
    """A check of another country or Steam number is due at once; when Steam fails it, the next one is in 30 minutes,
    as after any failure, not every minute (review of part 6.2)."""
    caplog.set_level(logging.INFO)
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    clock.advance(minutes=1)
    if change == "country":
        put_setting(session_factory, STORE_COUNTRY_SETTING, "ua")
    else:
        igdb_says(session_factory, igdb, game(steam_id="2"))
    prices.failure = SteamError("down", 503)
    run(tracker.poll_due())
    assert len(prices.calls) == 2
    assert price_snapshot(session_factory, title_id).state == {}  # the look of the old one says nothing of now

    for _ in range(29):
        clock.advance(minutes=1)
        run(tracker.poll_due())
    assert len(prices.calls) == 2

    prices.failure = None
    caplog.clear()
    clock.advance(minutes=1)
    run(tracker.poll_due())
    expected = ([HADES], "ua") if change == "country" else (["2"], "il")
    assert len(prices.calls) == 3 and prices.calls[-1] == expected
    assert len(baselines(caplog)) == 1  # the check of the new one is still the reference point


def test_230_games_are_asked_about_in_three_requests(tracker, igdb, prices, session_factory):
    ids = [add(tracker, igdb, game(steam_id=str(1000 + n)), str(n + 1), f"Игра {n}") for n in range(230)]

    run(tracker.poll_due())

    assert [len(appids) for appids in prices.asked] == [100, 100, 30]
    assert sorted(sum(prices.asked, [])) == sorted(str(1000 + n) for n in range(230))
    assert all(price_snapshot(session_factory, title_id).state != {} for title_id in ids)


def test_two_games_of_one_steam_number_are_asked_about_once_and_both_get_the_look(tracker, igdb, prices, session_factory):
    first = add(tracker, igdb, game(), "1", "Hades II")
    second = add(tracker, igdb, game(), "2", "Hades II (дубль IGDB)")

    run(tracker.poll_due())

    assert prices.asked == [[HADES]]
    assert price_snapshot(session_factory, first).state == price_snapshot(session_factory, second).state
    assert len(history(session_factory, first)) == len(history(session_factory, second)) == 1


def test_the_reconciliation_reads_as_much_for_fifty_games_as_for_one(session_factory, clock, sender, igdb, prices):
    tracker = Tracker(session_factory, clock=clock, sender=sender, sources={TitleKind.GAME: igdb}, price_source=prices)

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

    add(tracker, igdb, game(), "1")
    run(tracker.poll_due())
    one = reads_of_a_quiet_pass()
    for n in range(2, 51):
        add(tracker, igdb, game(steam_id=str(n)), str(n), f"Игра {n}")
    run(tracker.poll_due())
    fifty = reads_of_a_quiet_pass()

    assert one == fifty and len(prices.calls) == 2


# --- failures (spec 4.4) ------------------------------------------------------------------------------------------


def test_a_failed_request_is_a_failure_of_every_game_of_it_told_once_by_steam(tracker, igdb, prices, sender, clock):
    add(tracker, igdb, game(), "1", "Hades II")
    add(tracker, igdb, game(steam_id="2"), "2", "Elden Ring")
    prices.failure = SteamError("timeout", cause=httpx.ReadTimeout("slow"))

    report = run(tracker.poll_due())
    run(tracker.deliver_pending())

    assert report.failed == 2 and report.notices == 2
    assert len(sender.texts) == 1
    assert "Steam не ответил вовремя" in sender.texts[0] and "Hades II" in sender.texts[0] and "Elden Ring" in sender.texts[0]

    clock.advance(minutes=30)
    run(tracker.poll_due())
    run(tracker.deliver_pending())
    assert len(sender.texts) == 1  # once a day per title


def test_one_failed_game_reads_as_the_message_of_one_title(tracker, igdb, prices, sender):
    add(tracker, igdb)
    prices.failure = SteamError("timeout", cause=httpx.ReadTimeout("slow"))

    run(tracker.poll_due())
    run(tracker.deliver_pending())

    assert sender.texts == ["⚠️ Не удалось проверить «Hades II»: Steam не ответил вовремя. Повторю через 30 мин."]


def test_an_unreadable_record_is_a_failure_of_its_game_only(tracker, igdb, prices, sender, session_factory, caplog):
    broken = add(tracker, igdb, game(), "1", "Hades II")
    fine = add(tracker, igdb, game(steam_id="2"), "2", "Elden Ring")
    prices.unread = {HADES}

    report = run(tracker.poll_due())
    run(tracker.deliver_pending())

    assert report.failed == 1
    assert sender.texts == [
        "⚠️ Не удалось проверить «Hades II»: у Steam неизвестная ошибка, подробности в журнале. Повторю через 30 мин."
    ]
    assert "purchase_options" in caplog.text
    assert price_snapshot(session_factory, broken).state == {}
    assert price_snapshot(session_factory, fine).state == price_look("2").state()


def test_the_window_of_one_message_a_day_is_shared_with_igdb(tracker, igdb, prices, sender, session_factory, clock):
    title_id = add(tracker, igdb)
    igdb.gone = {"1"}
    igdb_says(session_factory, igdb, game())
    prices.failure = SteamError("timeout", cause=httpx.ReadTimeout("slow"))

    report = run(tracker.poll_due())
    run(tracker.deliver_pending())

    assert report.failed == 2 and len(sender.texts) == 1  # IGDB and Steam failed in one pass: one message
    clock.advance(hours=1)
    run(tracker.poll_due())
    run(tracker.deliver_pending())
    assert len(sender.texts) == 1
    with session_factory() as session:
        assert session.get(Title, title_id).failure_notified_at == naive(T0)


def test_a_steam_failure_leaves_the_igdb_check_as_usual(tracker, igdb, prices, session_factory):
    title_id = add(tracker, igdb)
    igdb_says(session_factory, igdb, game())
    prices.failure = SteamError("down", status=503)

    report = run(tracker.poll_due())

    assert report.polled == 1 and report.failed == 1
    with session_factory() as session:
        igdb_snapshot = session.scalar(
            select(SourceSnapshot).where(SourceSnapshot.title_id == title_id, SourceSnapshot.source == "igdb")
        )
        assert igdb_snapshot.observed_at == naive(T0)


@pytest.mark.parametrize("fails", [False, True])
def test_a_game_deleted_while_steam_answers_is_neither_written_nor_a_failure(fails, tracker, igdb, prices, session_factory, sender):
    title_id = add(tracker, igdb)
    prices.during = lambda: tracker.delete_title(title_id)
    if fails:
        prices.failure = SteamError("timeout", cause=httpx.ReadTimeout("slow"))

    report = run(tracker.poll_due())
    run(tracker.deliver_pending())

    assert report.failed == 0 and sender.texts == []
    assert price_snapshot(session_factory, title_id) is None and history(session_factory, title_id) == []


def test_a_bug_in_the_price_check_goes_to_the_log_and_leaves_the_pass(tracker, igdb, session_factory, monkeypatch, caplog):
    add(tracker, igdb)
    igdb_says(session_factory, igdb, game())

    def broken(self):
        raise RuntimeError("a bug")

    monkeypatch.setattr(GamePrices, "_reconcile", broken)
    report = run(tracker.poll_due())

    assert report.polled == 1 and report.failed == 0
    failed = [r for r in caplog.records if "end of the pass" in r.getMessage()]
    assert failed and failed[0].exc_info is not None


# --- the price history (spec 4.5) ---------------------------------------------------------------------------------


def test_a_record_is_added_only_when_the_price_or_the_discount_changes(tracker, igdb, prices, session_factory, clock):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())  # the reference point writes too

    for change in ("same", "discount", "deeper", "same", "over", "dearer", "free"):
        if change == "discount":
            prices.final[HADES], prices.discount[HADES] = 19530, (27900, 30)
        elif change == "deeper":
            prices.final[HADES], prices.discount[HADES] = 13950, (27900, 50)
        elif change == "over":
            prices.final.pop(HADES), prices.discount.pop(HADES)
        elif change == "dearer":
            prices.final[HADES] = 29900
        elif change == "free":
            prices.free = {HADES}
        clock.advance(hours=6)
        run(tracker.poll_due())

    assert history(session_factory, title_id) == [
        (HADES, "il", "₪{}", 27900, None, 0),
        (HADES, "il", "₪{}", 19530, 27900, 30),
        (HADES, "il", "₪{}", 13950, 27900, 50),
        (HADES, "il", "₪{}", 27900, None, 0),
        (HADES, "il", "₪{}", 29900, None, 0),
    ]


def test_the_lowest_counts_the_records_of_its_number_country_and_currency(tracker, igdb, prices, session_factory, clock):
    title_id = add(tracker, igdb)
    prices.final[HADES], prices.discount[HADES] = 19530, (27900, 30)
    run(tracker.poll_due())
    clock.advance(hours=6)
    prices.final[HADES], prices.discount[HADES] = 27900, (None, 0)
    run(tracker.poll_due())
    clock.advance(hours=6)
    prices.final[HADES] = 19530  # the same lowest again, without a discount: its moment is the latest
    run(tracker.poll_due())
    clock.advance(hours=6)
    put_setting(session_factory, STORE_COUNTRY_SETTING, "ua")
    prices.final[HADES] = 100
    run(tracker.poll_due())

    with session_factory() as session:
        il = lowest_seen(session, title_id, price_look(HADES))
        ua = lowest_seen(session, title_id, price_look(HADES, "ua"))
        other = lowest_seen(session, title_id, price_look("2"))
        free = lowest_seen(session, title_id, PriceLook(HADES, "il", FREE))
    assert (il.money.cents, il.seen_at) == (19530, naive(T0) + timedelta(hours=12))
    assert (ua.money.cents, ua.seen_at) == (100, naive(T0) + timedelta(hours=18))
    assert other is None and free is None


# --- the real adapter, the queue and the assembly -----------------------------------------------------------------


class SavedSteam:
    """`store_items` from the saved answer of six games of Israel."""

    def __init__(self):
        self.calls = []

    async def store_items(self, appids, country):
        self.calls.append((list(appids), country))
        answer = json.loads((FIXTURES / "steam/getitems_six_games_il.json").read_text(encoding="utf-8"))
        return [item for item in answer["response"]["store_items"] if str(item["appid"]) in appids]


def test_the_real_adapter_gives_hades_ii_its_price_in_shekels(session_factory, clock, sender, igdb):
    steam = SavedSteam()
    tracker = Tracker(
        session_factory, clock=clock, sender=sender, sources={TitleKind.GAME: igdb}, price_source=SteamPriceSource(steam)
    )
    title_id = add(tracker, igdb)

    run(tracker.poll_due())

    look = PriceLook.from_state(price_snapshot(session_factory, title_id).state)
    assert steam.calls == [([HADES], "il")]
    assert look.answer == PRICE and look.currency.startswith("₪")
    assert history(session_factory, title_id)[0][:3] == (HADES, "il", look.currency)


def test_withdraw_takes_all_the_undelivered_entries_of_a_title_or_only_those_of_the_types(tracker, igdb, session_factory):
    title_id = add(tracker, igdb)
    for kind_of_event in ("game_discount", "game_bundle", "game_release"):
        run(tracker.record_event(kind_of_event, {"text": kind_of_event}, f"k:{kind_of_event}", title_id=title_id))

    with tracker._queue.ctx.write_session() as session:
        EventQueue.withdraw(session, title_id, price_events.TYPES)
        session.commit()
    assert pending_types(session_factory, title_id) == ["game_release"]

    with tracker._queue.ctx.write_session() as session:
        EventQueue.withdraw(session, title_id)
        session.commit()
    assert pending_types(session_factory, title_id) == []


def test_build_tracker_gives_both_sources_one_steam_client(monkeypatch):
    from app import main

    monkeypatch.setattr(main, "create_session_factory", lambda: create_session_factory("sqlite://"))
    settings = SimpleNamespace(
        owner_chat=1, igdb_client_id="", igdb_client_secret="", bot_timezone="UTC", model_fields_set={"bot_timezone"},
        google_drive_client_id="", google_drive_client_secret="", backup_password="", web_port_number=8080,
    )

    tracker = main.build_tracker(settings, None)

    assert isinstance(tracker.price_source, SteamPriceSource)
    assert tracker.price_source.steam is tracker.sources[TitleKind.GAME]._steam


def test_the_steam_events_are_listed_in_one_place():
    assert price_events.TYPES == ("game_discount", "game_bundle", "game_steam_page")
