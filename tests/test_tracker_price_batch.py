"""The events of one price check queued in one write session (spec 2.5 of stage 9.1b, KI-51, ticket 02):
`EventQueue.enqueue_all` on its own (a batch, a known key, a game no longer checked, a withdrawn older discount) and
through the check (the delivery sees all the events of a check or none; two discounts fold into one message).

Through the facade: fake clock, fake sender, in-memory SQLite, IGDB a made-up source, the prices a fake source of
looks the test writes.
"""

import pytest
from sqlalchemy import event, func, select

from app.tracker import price_events
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import DeliveryItem, DeliveryStatus, Event, TitleKind
from app.tracker.movie_events import DetectedEvent
from app.tracker.pollers import game_prices
from app.tracker.pollers.base import DueTitle
from app.tracker.queue import EventQueue, Queued
from test_tracker_game_prices import FakeClock, MadeUpGames, naive, run
from test_tracker_steam_events import (
    HADES, LATER_END, T0, FakeSender, Looks, add, check, discount_keys, discounted, game, pending_keys,
)

ELDEN = "1245620"


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


@pytest.fixture
def two_games(tracker, igdb):
    """Hades II and Elden Ring, both for prices, their reference points taken."""
    hades = add(tracker, igdb, game(), "1", "Hades II")
    elden = add(tracker, igdb, game(steam_id=ELDEN), "2", "Elden Ring")
    run(tracker.poll_due())
    return hades, elden


def due(title_id, name, appid):
    return DueTitle(title_id, TitleKind.GAME, name, appid, "steam", sequels=False)


def discount(title_id, pct, name="Hades II"):
    return DetectedEvent(price_events.DISCOUNT, f"game:{title_id}:discount:{pct}", f"{name}: −{pct} %", {"pct": pct})


def enqueue_all(session_factory, clock, batch):
    with session_factory() as session:
        queued = EventQueue.enqueue_all(session, batch, naive(clock.now))
        session.commit()
        return queued


def pending_of(session_factory):
    with session_factory() as session:
        return sorted(session.scalars(
            select(Event.dedup_key)
            .join(DeliveryItem, DeliveryItem.event_id == Event.id)
            .where(DeliveryItem.status == DeliveryStatus.PENDING)
        ))


# --- `enqueue_all` on its own --------------------------------------------------------------------------------------


def test_a_batch_is_queued_in_one_session(two_games, session_factory, clock):
    hades, elden = two_games
    batch = [
        Queued(due(hades, "Hades II", HADES), discount(hades, 30)),
        Queued(due(elden, "Elden Ring", ELDEN), discount(elden, 50, "Elden Ring")),
    ]

    queued = enqueue_all(session_factory, clock, batch)

    assert len(queued) == 2
    assert pending_of(session_factory) == sorted([f"game:{hades}:discount:30", f"game:{elden}:discount:50"])


def test_a_known_key_is_skipped_and_the_rest_of_the_batch_stays(two_games, session_factory, clock):
    hades, elden = two_games
    enqueue_all(session_factory, clock, [Queued(due(hades, "Hades II", HADES), discount(hades, 30))])

    queued = enqueue_all(session_factory, clock, [
        Queued(due(hades, "Hades II", HADES), discount(hades, 30)),
        Queued(due(elden, "Elden Ring", ELDEN), discount(elden, 50, "Elden Ring")),
        Queued(due(elden, "Elden Ring", ELDEN), discount(elden, 50, "Elden Ring")),  # the same key twice
    ])

    assert len(queued) == 1
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Event)) == 2


def test_a_game_no_longer_checked_is_skipped_without_a_rollback(tracker, two_games, session_factory, clock):
    hades, elden = two_games
    run(tracker.mark_started(hades))  # its price snapshot goes at once

    queued = enqueue_all(session_factory, clock, [
        Queued(due(hades, "Hades II", HADES), discount(hades, 30)),
        Queued(due(elden, "Elden Ring", ELDEN), discount(elden, 50, "Elden Ring")),
    ])

    assert len(queued) == 1 and pending_of(session_factory) == [f"game:{elden}:discount:50"]
    with session_factory() as session:  # the key of the skipped one is not spent
        assert session.scalar(select(Event.id).where(Event.dedup_key == f"game:{hades}:discount:30")) is None


def test_a_deeper_discount_takes_the_older_one_out_only_when_it_is_queued_itself(
    tracker, two_games, session_factory, clock
):
    hades, _ = two_games
    hades_due = due(hades, "Hades II", HADES)
    enqueue_all(session_factory, clock, [Queued(hades_due, discount(hades, 30))])
    enqueue_all(session_factory, clock, [Queued(hades_due, discount(hades, 50))])
    enqueue_all(session_factory, clock, [Queued(hades_due, discount(hades, 30), (price_events.DISCOUNT,))])
    assert pending_of(session_factory) == sorted([f"game:{hades}:discount:30", f"game:{hades}:discount:50"])  # known

    enqueue_all(session_factory, clock, [Queued(hades_due, discount(hades, 70), (price_events.DISCOUNT,))])
    assert pending_of(session_factory) == [f"game:{hades}:discount:70"]

    run(tracker.mark_started(hades))
    enqueue_all(session_factory, clock, [Queued(hades_due, discount(hades, 90), (price_events.DISCOUNT,))])
    assert pending_of(session_factory) == []  # «Начал играть» took the 70 out; the 90 is not queued


# --- through the check ---------------------------------------------------------------------------------------------


def test_the_delivery_sees_all_the_events_of_a_check_or_none(two_games, tracker, steam, clock, session_factory):
    """After every commit of the check, the queue holds none or both discounts: never one of them."""
    seen = []

    def count_pending(session):
        with session_factory() as reader:
            seen.append(reader.scalar(
                select(func.count()).select_from(DeliveryItem).where(DeliveryItem.status == DeliveryStatus.PENDING)
            ))

    steam.looks[HADES] = discounted(ends_at=LATER_END)
    steam.looks[ELDEN] = discounted(50, ends_at=LATER_END)
    event.listen(session_factory, "after_commit", count_pending)
    try:
        check(tracker, clock)
    finally:
        event.remove(session_factory, "after_commit", count_pending)

    assert seen and 1 not in seen and seen[-1] == 2


def test_two_discounts_of_one_check_fold_into_one_message(two_games, tracker, steam, sender, clock):
    steam.looks[HADES] = discounted(ends_at=LATER_END)
    steam.looks[ELDEN] = discounted(50, ends_at=LATER_END)
    check(tracker, clock)
    run(tracker.deliver_pending())

    [(text, _)] = sender.sent
    assert text.split("\n")[0] == "🎮 Скидки в Steam:" and len(text.split("\n")) == 3


def test_a_game_dropped_while_steam_answers_queues_nothing_and_the_other_is_queued(
    two_games, tracker, steam, clock, session_factory
):
    hades, elden = two_games
    steam.looks[HADES] = discounted(ends_at=LATER_END)
    steam.looks[ELDEN] = discounted(50, ends_at=LATER_END)
    answer = steam.price_looks

    async def pressed_meanwhile(appids, country):
        looks = await answer(appids, country)
        await tracker.mark_started(hades)  # the owner presses «Начал играть» while Steam answers
        return looks

    steam.price_looks = pressed_meanwhile
    check(tracker, clock)

    assert pending_keys(session_factory) == [f"game:{elden}:discount:50:{LATER_END.isoformat()}"]
    assert discount_keys(session_factory) == [f"game:{elden}:discount:50:{LATER_END.isoformat()}"]


def test_a_failed_queueing_stores_no_look_and_the_game_is_asked_again_in_30_minutes(
    two_games, tracker, steam, clock, session_factory, monkeypatch
):
    hades, _ = two_games
    steam.looks[HADES] = discounted(ends_at=LATER_END)

    def broken(session, batch, now):
        raise RuntimeError("a bug")

    monkeypatch.setattr(EventQueue, "enqueue_all", staticmethod(broken))
    check(tracker, clock)
    monkeypatch.undo()

    assert discount_keys(session_factory) == []
    clock.advance(minutes=30)
    run(tracker.poll_due())
    assert discount_keys(session_factory) == [f"game:{hades}:discount:30:{LATER_END.isoformat()}"]


def test_a_known_fact_found_again_after_a_failed_store_is_not_queued_twice(
    two_games, tracker, steam, clock, session_factory, monkeypatch
):
    hades, _ = two_games
    steam.looks[HADES] = discounted(ends_at=LATER_END)

    def broken(self, game, look, now):
        raise RuntimeError("a bug")

    monkeypatch.setattr(game_prices.GamePrices, "_store", broken)
    check(tracker, clock)
    monkeypatch.undo()
    clock.advance(minutes=30)
    run(tracker.poll_due())

    assert discount_keys(session_factory) == [f"game:{hades}:discount:30:{LATER_END.isoformat()}"]
