"""A press ends the price check at once (spec 3.1 and 3.2 of stage 9.1b, KI-47, ticket 02): «Начал играть», «Прошёл»,
«Бросил», the mark «играю здесь» on PC and a save of Settings without PC drop the price snapshot and the undelivered
events of Steam in the press's own write session; a check answering after the press queues nothing; no press makes a
snapshot.

Through the facade: fake clock, fake sender, in-memory SQLite, IGDB a made-up source, the prices a fake source of
looks the test writes.
"""

from dataclasses import replace

import pytest
from sqlalchemy import select

from app.tracker import price_events
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import DeliveryItem, DeliveryStatus, Event, SourceSnapshot, TitleKind
from test_tracker_game_prices import FakeClock, MadeUpGames, run
from test_tracker_steam_events import HADES, LATER_END, T0, FakeSender, Looks, add, check, discounted, game

PRESSES = ["started", "completed", "dropped", "pc mark off", "settings without pc"]


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
def steam():
    return Looks()


@pytest.fixture
def tracker(session_factory, clock, sender, igdb, steam):
    tracker = Tracker(session_factory, clock=clock, sender=sender, sources={TitleKind.GAME: igdb}, price_source=steam)
    run(tracker.set_delivery_rules(tz_name="UTC", workdays=[], quiet_from="00:00", quiet_until="00:00"))
    return tracker


def press(tracker, title_id, how):
    run(press_async(tracker, title_id, how))


async def press_async(tracker, title_id, how):
    if how == "started":
        await tracker.mark_started(title_id)
    elif how == "completed":
        await tracker.mark_watched(title_id)
    elif how == "dropped":
        await tracker.mark_dropped(title_id)
    elif how == "pc mark off":
        await tracker.set_platform_playing(title_id, "pc", False)
    else:
        saved = (await tracker.settings()).saved
        await tracker.save_settings(replace(saved, my_platforms=["ps5"]))


def settings_with(tracker, platforms):
    saved = run(tracker.settings()).saved
    run(tracker.save_settings(replace(saved, my_platforms=platforms)))


def price_snapshot(session_factory, title_id):
    with session_factory() as session:
        return session.scalar(
            select(SourceSnapshot).where(SourceSnapshot.title_id == title_id, SourceSnapshot.source == "steam")
        )


def queue_of(session_factory, title_id):
    """(type, status) of the queue entries of the title."""
    with session_factory() as session:
        return sorted(session.execute(
            select(Event.type, DeliveryItem.status)
            .join(DeliveryItem, DeliveryItem.event_id == Event.id)
            .where(Event.title_id == title_id)
        ).all())


def delivered(session_factory, event_id):
    with session_factory() as session:
        session.scalar(select(DeliveryItem).where(DeliveryItem.event_id == event_id)).status = DeliveryStatus.DELIVERED
        session.commit()


@pytest.mark.parametrize("how", PRESSES)
def test_a_press_drops_the_price_snapshot_and_the_undelivered_steam_events_at_once(how, tracker, igdb, session_factory):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    old = run(tracker.record_event(price_events.BUNDLE, {"text": "бандл"}, "game:1:bundle:old", title_id=title_id))
    delivered(session_factory, old)
    run(tracker.record_event(price_events.DISCOUNT, {"text": "−30 %"}, "game:1:discount", title_id=title_id))
    run(tracker.record_event("game_release", {"text": "вышла"}, "game:1:released", title_id=title_id))

    press(tracker, title_id, how)

    assert price_snapshot(session_factory, title_id) is None
    expected = [(price_events.BUNDLE, DeliveryStatus.DELIVERED)]  # a delivered one stays
    if how != "dropped":  # «Бросил» takes every undelivered message out, as before
        expected.append(("game_release", DeliveryStatus.PENDING))
    assert queue_of(session_factory, title_id) == sorted(expected)


def test_a_settings_save_with_pc_keeps_the_snapshot(tracker, igdb, session_factory):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())

    settings_with(tracker, ["pc", "ps5"])

    assert price_snapshot(session_factory, title_id) is not None


def test_a_settings_save_without_pc_ends_every_price_check(tracker, igdb, session_factory):
    first = add(tracker, igdb, game(), "1", "Hades II")
    second = add(tracker, igdb, game(steam_id="2"), "2", "Elden Ring")
    run(tracker.poll_due())

    settings_with(tracker, ["ps5"])

    assert price_snapshot(session_factory, first) is None and price_snapshot(session_factory, second) is None


def test_a_press_on_one_game_leaves_the_others(tracker, igdb, session_factory):
    first = add(tracker, igdb, game(), "1", "Hades II")
    second = add(tracker, igdb, game(steam_id="2"), "2", "Elden Ring")
    run(tracker.poll_due())

    run(tracker.mark_started(first))

    assert price_snapshot(session_factory, first) is None and price_snapshot(session_factory, second) is not None


@pytest.mark.parametrize("how", PRESSES)
def test_a_check_answering_after_the_press_queues_nothing(how, tracker, igdb, steam, clock, session_factory):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    steam.looks[HADES] = discounted(ends_at=LATER_END)
    answer = steam.price_looks

    async def pressed_meanwhile(appids, country):
        looks = await answer(appids, country)
        await press_async(tracker, title_id, how)
        return looks

    steam.price_looks = pressed_meanwhile
    check(tracker, clock)

    with session_factory() as session:
        assert session.scalars(select(Event).where(Event.type.in_(price_events.TYPES))).all() == []
    assert price_snapshot(session_factory, title_id) is None  # the late store wrote nothing back


@pytest.mark.parametrize("how", ["pc mark on", "settings with pc", "restored"])
def test_no_press_makes_a_snapshot_only_the_reconciliation_does(how, tracker, igdb, steam, session_factory):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    if how == "pc mark on":
        run(tracker.set_platform_playing(title_id, "pc", False))
        run(tracker.set_platform_playing(title_id, "pc", True))
    elif how == "settings with pc":
        settings_with(tracker, ["ps5"])
        settings_with(tracker, ["pc", "ps5"])
    else:
        run(tracker.mark_dropped(title_id))
        run(tracker.restore_title(title_id))

    assert price_snapshot(session_factory, title_id) is None
    run(tracker.poll_due())
    assert price_snapshot(session_factory, title_id) is not None
