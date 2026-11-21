"""The known issues of the price check (spec 2.1–2.4 of stage 9.1b, ticket 02): the bundle price of the whole set
(KI-43, won't fix), a live preorder (KI-44), short discounts against the delivery rules (KI-46, won't fix) and a
spoiled price snapshot (KI-50).

Through the facade: fake clock, fake sender, in-memory SQLite, IGDB a made-up source, the prices a fake source of
looks; the preorder on a saved live answer of Steam (`tests/fixtures/steam/getitems_preorder_il_live.json`).
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.tracker import price_rows
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import Event, SourceSnapshot, TitleKind
from app.tracker.pollers.game_prices import PRICE_INTERVAL
from app.tracker.prices import PRICE, Price
from app.tracker.settings_store import MY_PLATFORMS_SETTING
from app.tracker.sources.steam_prices import parse_items
from test_tracker_game_prices import FakeClock, MadeUpGames, naive, run
from test_tracker_steam_events import HADES, FakeSender, Looks, add, discounted, game, put_setting

FIXTURES = Path(__file__).parent / "fixtures" / "steam"
MONDAY = datetime(2026, 11, 9, 16, 0, tzinfo=timezone.utc)  # a work day
DAWN_OF_WAR, DRAGON_QUEST, RAYMAN = "2272360", "3681610", "4084710"


@pytest.fixture
def clock():
    return FakeClock(MONDAY)


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


def make_tracker(session_factory, clock, sender, igdb, steam):
    return Tracker(session_factory, clock=clock, sender=sender, sources={TitleKind.GAME: igdb}, price_source=steam)


@pytest.fixture
def tracker(session_factory, clock, sender, igdb, steam):
    tracker = make_tracker(session_factory, clock, sender, igdb, steam)
    run(tracker.set_delivery_rules(tz_name="UTC", workdays=[], quiet_from="00:00", quiet_until="00:00"))
    return tracker


# --- KI-43: the price of the whole set (won't fix) -------------------------------------------------------------------


def test_the_bundle_sample_says_the_price_is_of_the_whole_set(tracker, sender):
    """The sample «Игра: бандл в Steam» of «Тестовое событие» reads as a real bundle message."""
    labels = {sample.id: sample.label for sample in tracker.test_samples()}
    assert labels["steam-bundle"] == "Игра: бандл в Steam"

    run(tracker.send_test_event("steam-bundle"))

    [(text, _)] = sender.sent
    assert text.endswith(
        "🎮 Resident Evil Requiem продаётся в бандле «Resident Evil Requiem + Village» (2 игры) — ₪250, "
        "цена набора целиком"
    )


# --- KI-44: a live preorder ------------------------------------------------------------------------------------------


def preorders():
    found = json.loads((FIXTURES / "getitems_preorder_il_live.json").read_text(encoding="utf-8"))
    items = found["response"]["store_items"]
    return parse_items(items, [str(item["appid"]) for item in items], "il")


def test_the_live_preorders_are_read_unchanged():
    looks = preorders()

    assert {appid: look.answer for appid, look in looks.items()} == {
        DAWN_OF_WAR: PRICE, DRAGON_QUEST: PRICE, RAYMAN: PRICE,
    }
    assert looks[DAWN_OF_WAR].price == Price(21420, 23800, 10, looks[DAWN_OF_WAR].price.ends_at, preorder=True)
    assert looks[DRAGON_QUEST].price == Price(20900, preorder=True)
    assert looks[RAYMAN].price == Price(15900, preorder=True)


def test_the_live_preorders_read_on_the_card():
    looks = preorders()
    now = datetime(2026, 11, 21, 12, 0)
    tz = ZoneInfo("Asia/Jerusalem")

    def line(appid):
        return price_rows.steam_view("il", appid, looks[appid], now, [], now, tz).line

    assert line(DAWN_OF_WAR) == "Предзаказ со скидкой −10 %: ₪238 → ₪214,20, до 3 декабря"
    assert line(DRAGON_QUEST) == "Предзаказ: ₪209"


# --- KI-46: short discounts and the delivery rules (won't fix) -------------------------------------------------------


def test_prices_are_checked_every_six_hours():
    assert PRICE_INTERVAL == timedelta(hours=6)


@pytest.mark.parametrize("ends_at, sent", [("08:00", False), ("18:00", True)])
def test_a_discount_found_at_22_on_a_work_day_goes_in_the_summary_only_if_it_is_not_over_by_15(
    ends_at, sent, session_factory, clock, sender, igdb, steam
):
    """Work days Monday to Friday, the summary at 15:00, quiet hours 21:00–07:30 (the defaults' hours): a discount
    found on Monday at 22:00 waits for Tuesday's summary; one over at 08:00 is old by then and leaves the queue unsent,
    one over at 18:00 goes."""
    tracker = make_tracker(session_factory, clock, sender, igdb, steam)
    run(tracker.set_delivery_rules(
        tz_name="UTC", workdays=[0, 1, 2, 3, 4], summary_at="15:00", quiet_from="21:00", quiet_until="07:30",
    ))
    add(tracker, igdb)
    run(tracker.poll_due())  # Monday 16:00, the reference point
    end = datetime(2026, 11, 10, *map(int, ends_at.split(":")))
    steam.looks[HADES] = discounted(ends_at=end)

    clock.advance(hours=6)  # Monday 22:00: the next check
    run(tracker.poll_due())
    run(tracker.deliver_pending())
    assert sender.sent == []  # quiet hours, then a work day: it waits for the summary

    clock.now = datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc)  # Tuesday 15:00
    run(tracker.deliver_pending())

    texts = [text for text, _ in sender.sent]
    assert any("Hades II: скидка" in text for text in texts) == sent
    assert len(texts) == (1 if sent else 0)


# --- KI-50: a spoiled price snapshot ---------------------------------------------------------------------------------


def spoil(session_factory, title_id):
    with session_factory() as session:
        stored = session.scalar(
            select(SourceSnapshot).where(SourceSnapshot.title_id == title_id, SourceSnapshot.source == "steam")
        )
        stored.state = {"appid": HADES, "country": "il", "answer": "nonsense"}
        stored.next_check_at = None
        session.commit()


def price_snapshot(session_factory, title_id):
    with session_factory() as session:
        return session.scalar(
            select(SourceSnapshot).where(SourceSnapshot.title_id == title_id, SourceSnapshot.source == "steam")
        )


def spoiled_lines(caplog):
    return [r.getMessage() for r in caplog.records if "price snapshot cannot be read" in r.getMessage()]


class Counting(Looks):
    def __init__(self):
        super().__init__()
        self.asked = []

    async def price_looks(self, appids, country):
        self.asked.append(list(appids))
        return await super().price_looks(appids, country)


def test_a_spoiled_snapshot_is_a_failure_of_its_game_and_the_others_are_checked(
    session_factory, clock, sender, igdb, caplog
):
    caplog.set_level(logging.INFO)
    steam = Counting()
    tracker = make_tracker(session_factory, clock, sender, igdb, steam)
    run(tracker.set_delivery_rules(tz_name="UTC", workdays=[], quiet_from="00:00", quiet_until="00:00"))
    spoiled = add(tracker, igdb, game(), "1", "Hades II")
    other = add(tracker, igdb, game(steam_id="2"), "2", "Elden Ring")
    run(tracker.poll_due())
    spoil(session_factory, spoiled)
    caplog.clear()

    clock.advance(hours=6)
    report = run(tracker.poll_due())
    run(tracker.deliver_pending())

    assert steam.asked[-1] == ["2"]  # not asked about, not reset
    assert price_snapshot(session_factory, spoiled).state["answer"] == "nonsense"
    assert price_snapshot(session_factory, spoiled).next_check_at == naive(clock.now) + timedelta(minutes=30)
    assert price_snapshot(session_factory, other).observed_at == naive(clock.now)
    assert report.failed == 1 and report.notices == 1
    [(text, _)] = sender.sent
    assert text == "⚠️ Не удалось проверить «Hades II»: у Steam неизвестная ошибка, подробности в журнале. Повторю через 30 мин."
    [line] = spoiled_lines(caplog)
    assert line.startswith(f"title {spoiled}: its price snapshot cannot be read: ValueError(")


def test_a_spoiled_snapshot_fails_each_time_it_is_due_but_logs_and_tells_once_a_day(
    session_factory, clock, sender, igdb, caplog
):
    caplog.set_level(logging.INFO)
    steam = Counting()
    tracker = make_tracker(session_factory, clock, sender, igdb, steam)
    run(tracker.set_delivery_rules(tz_name="UTC", workdays=[], quiet_from="00:00", quiet_until="00:00"))
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    spoil(session_factory, title_id)
    caplog.clear()

    failed = []
    for _ in range(4):  # every minute for 4 minutes, then three more due times 30 minutes apart
        clock.advance(minutes=1)
        failed.append(run(tracker.poll_due()).failed)
    for _ in range(3):
        clock.advance(minutes=30)
        failed.append(run(tracker.poll_due()).failed)
    run(tracker.deliver_pending())

    assert failed == [1, 0, 0, 0, 1, 1, 1]  # one failure per due time
    assert len(spoiled_lines(caplog)) == 1  # one log line a day
    assert len(sender.sent) == 1  # one «could not check» a day by the usual window
    assert len(steam.asked) == 1  # only the reference point; the spoiled one is never asked about

    clock.advance(days=1)
    caplog.clear()
    run(tracker.poll_due())
    assert len(spoiled_lines(caplog)) == 1


def test_a_spoiled_snapshot_of_a_game_no_longer_for_prices_is_dropped(session_factory, clock, sender, igdb, steam):
    tracker = make_tracker(session_factory, clock, sender, igdb, steam)
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    spoil(session_factory, title_id)

    put_setting(session_factory, MY_PLATFORMS_SETTING, ["ps5"])
    report = run(tracker.poll_due())

    assert price_snapshot(session_factory, title_id) is None and report.failed == 0
    with session_factory() as session:
        assert session.scalars(select(Event)).all() == []
