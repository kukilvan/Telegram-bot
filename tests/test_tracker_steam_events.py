"""The events of Steam (spec 5 of part 6.2, ticket 04): a discount, a bundle and the page in Steam — when they come,
their texts and keys, the folding of discounts, the old messages, the link buttons and the samples.

The pure `price_events` is tested on its own; the rest through the facade: fake clock, fake sender, in-memory SQLite,
IGDB a made-up source whose snapshots the test writes, the prices a fake source of looks the test writes.
"""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.bot.tracker_handlers import actions_markup
from app.tracker import delivery, game_events, price_events
from app.tracker.actions import CARD, STEAM, Action, event_actions
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.delivery import MESSAGE_LIMIT, Pending
from app.tracker.games import GameState
from app.tracker.models import DeliveryItem, DeliveryStatus, Event, SettingRecord, SourceSnapshot, TitleKind
from app.tracker.prices import COMING_SOON, PRICE, Bundle, Lowest, Money, Price, PriceLook
from app.tracker.settings_store import MY_PLATFORMS_SETTING, STORE_COUNTRY_SETTING
from app.tracker.sources.igdb_games import GameSnapshot

T0 = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)  # Monday
PC, PS5 = 6, 167
HADES = "1145350"
SHEKEL = "₪{}"
END = datetime(2026, 11, 3, 18, 0)  # naive UTC: 3 ноября 20:00 in Jerusalem
LATER_END = datetime(2026, 11, 20, 18, 0)


def run(coro):
    return asyncio.run(coro)


def naive(moment):
    return moment.astimezone(timezone.utc).replace(tzinfo=None)


def look(final=27900, original=None, pct=0, ends_at=None, bundles=(), appid=HADES, country="il", **price):
    return PriceLook(appid, country, PRICE, SHEKEL, Price(final, original, pct, ends_at, **price), tuple(bundles))


def discounted(pct=30, ends_at=END, original=27900, **price):
    return look(original * (100 - pct) // 100, original, pct, ends_at, **price)


HADES_BUNDLE = Bundle("bundle:1", "Hades + Hades II", 2, 25000)


def detect(old, new, now=datetime(2026, 11, 1, 12, 0), lowest=None, tz=ZoneInfo("Asia/Jerusalem")):
    return price_events.detect_events(7, "Hades II", old, new, now, tz, lowest, datetime(2026, 11, 1, 6, 0))


# --- texts (spec 5.2) ---------------------------------------------------------------------------------------------


def test_the_texts_of_a_discount():
    price = Price(19530, 27900, 30, END)
    day = END.date()
    name = "Resident Evil Requiem"
    assert price_events.discount_text(name, price, SHEKEL, day, False) == (
        "🎮 Resident Evil Requiem: скидка −30 % в Steam — ₪279 → ₪195,30, до 3 ноября"
    )
    assert price_events.discount_text(name, price, SHEKEL, None, False) == (
        "🎮 Resident Evil Requiem: скидка −30 % в Steam — ₪279 → ₪195,30"
    )
    assert price_events.discount_text(name, price, SHEKEL, day, True).split("\n") == [
        "🎮 Resident Evil Requiem: скидка −30 % в Steam — ₪279 → ₪195,30, до 3 ноября",
        "Самая низкая цена с тех пор, как игра в списке",
    ]
    assert price_events.discount_text(name, Price(0, 27900, 100, END), SHEKEL, day, False) == (
        "🎮 Resident Evil Requiem: в Steam раздают бесплатно до 3 ноября (обычно ₪279)"
    )
    assert price_events.discount_text(name, Price(25110, 27900, 10, END, preorder=True), SHEKEL, day, False) == (
        "🎮 Resident Evil Requiem: скидка −10 % на предзаказ в Steam — ₪279 → ₪251,10, до 3 ноября"
    )
    edition = Price(19530, 27900, 30, END, edition="Resident Evil Requiem Deluxe Edition")
    assert price_events.discount_text(name, edition, SHEKEL, day, False).endswith(
        "до 3 ноября («Resident Evil Requiem Deluxe Edition»)"
    )


def test_the_texts_of_a_bundle_and_of_the_page():
    assert price_events.bundle_text("Hades II", HADES_BUNDLE, SHEKEL) == (
        "🎮 Hades II продаётся в бандле «Hades + Hades II» (2 игры) — ₪250"
    )
    assert price_events.steam_page_text("Ведьмак 4") == "🎮 Ведьмак 4: появилась страница в Steam"


@pytest.mark.parametrize(
    "count, words", [(1, "1 игра"), (2, "2 игры"), (4, "4 игры"), (5, "5 игр"), (11, "11 игр"), (12, "12 игр"),
                     (21, "21 игра"), (22, "22 игры"), (111, "111 игр")],
)
def test_the_number_of_games_of_a_bundle(count, words):
    assert price_events.games_word(count) == words


def test_the_lines_of_the_folded_message():
    day = END.date()
    assert price_events.discount_line("Resident Evil Requiem", Price(19530, 27900, 30, END), SHEKEL, day, False) == (
        "Resident Evil Requiem — −30 %, ₪279 → ₪195,30, до 3 ноября"
    )
    assert price_events.discount_line("Hades II", Price(8876, 11095, 20), SHEKEL, None, True) == (
        "Hades II — −20 %, ₪110,95 → ₪88,76, самая низкая с добавления"
    )
    assert price_events.discount_line("Elden Ring", Price(0, 19900, 100, END), SHEKEL, day, False) == (
        "Elden Ring — раздают бесплатно до 3 ноября"
    )
    assert price_events.discount_line("X", Price(25110, 27900, 10, preorder=True, edition="Deluxe"), SHEKEL, None, False) == (
        "X — −10 % на предзаказ, ₪279 → ₪251,10 («Deluxe»)"
    )


# --- when (spec 5.1) ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "old",
    [look(), PriceLook(HADES, "il", COMING_SOON)],  # no discount before; no price before (it came out with a discount)
)
def test_a_discount_that_starts_is_told(old):
    [event] = detect(old, discounted())
    assert event.type == price_events.DISCOUNT
    assert event.dedup_key == "game:7:discount:30:2026-11-03T18:00:00"
    assert event.text == "🎮 Hades II: скидка −30 % в Steam — ₪279 → ₪195,30, до 3 ноября"
    assert event.data == {
        "name": "Hades II", "steam_id": HADES, "pct": 30, "final": 19530, "original": 27900, "currency": SHEKEL,
        "ends_at": "2026-11-03T18:00:00", "lowest": False, "edition": None, "preorder": False,
        "expires_at": "2026-11-03T18:00:00", "line": "Hades II — −30 %, ₪279 → ₪195,30, до 3 ноября",
    }


def test_the_next_sale_after_the_end_of_the_previous_one_is_told_even_with_the_same_percent():
    [event] = detect(discounted(ends_at=END), discounted(ends_at=LATER_END), now=END + timedelta(hours=1))
    assert event.dedup_key == "game:7:discount:30:2026-11-20T18:00:00"


def test_a_deeper_discount_of_the_same_sale_is_told():
    [event] = detect(discounted(30), discounted(50))
    assert event.dedup_key == "game:7:discount:50:2026-11-03T18:00:00" and "−50 %" in event.text


@pytest.mark.parametrize(
    "old, new",
    [
        (discounted(30), discounted(30)),  # the same
        (discounted(30, ends_at=END), discounted(30, ends_at=LATER_END)),  # extended, the old end not come yet
        (discounted(50), discounted(30)),  # smaller
        (discounted(30), look()),  # over
        (look(), look(29900)),  # dearer without a discount
        (look(), look(19900)),  # cheaper without a discount
        (look(bundles=[HADES_BUNDLE]), look()),  # the bundle gone
        (look(bundles=[HADES_BUNDLE]), look(bundles=[replace(HADES_BUNDLE, final=20000)])),  # the bundle cheaper
        (discounted(30, ends_at=None), discounted(30, ends_at=None)),  # the same, its end unknown
    ],
)
def test_what_is_silent(old, new):
    assert detect(old, new) == []


def test_a_discount_without_a_known_end_is_keyed_by_the_previous_look():
    [event] = detect(look(), discounted(ends_at=None))
    assert event.dedup_key == "game:7:discount:30:none:from:20261101T060000"
    assert event.data["ends_at"] is None and event.data["expires_at"] is None
    assert event.text == "🎮 Hades II: скидка −30 % в Steam — ₪279 → ₪195,30"


def test_the_end_reads_on_the_owners_clock():
    late = datetime(2026, 11, 3, 23, 0)  # 4 ноября 01:00 in Jerusalem
    [event] = detect(look(), discounted(ends_at=late))
    assert event.text.endswith("до 4 ноября")
    [utc] = detect(look(), discounted(ends_at=late), tz=timezone.utc)
    assert utc.text.endswith("до 3 ноября")


def test_the_lowest_is_decided_by_the_history_before_the_check():
    new = discounted()  # ₪195,30
    assert detect(look(), new, lowest=Lowest(Money(19530, SHEKEL), datetime(2026, 1, 1)))[0].data["lowest"] is True
    assert detect(look(), new, lowest=Lowest(Money(19000, SHEKEL), datetime(2026, 1, 1)))[0].data["lowest"] is False
    assert detect(look(), new, lowest=Lowest(Money(1, "{}₴"), datetime(2026, 1, 1)))[0].data["lowest"] is False
    lowest = detect(look(), new, lowest=Lowest(Money(27900, SHEKEL), datetime(2026, 1, 1)))[0]
    assert lowest.text.split("\n")[1] == price_events.LOWEST_LINE
    assert lowest.data["line"].endswith(", самая низкая с добавления")


def test_a_new_bundle_is_told_once_a_bundle_each():
    other = Bundle("package:9", "Supergiant Pack", 5, 50000)
    events = detect(look(bundles=[HADES_BUNDLE]), look(bundles=[HADES_BUNDLE, other]))
    assert [(e.type, e.dedup_key) for e in events] == [(price_events.BUNDLE, "game:7:bundle:package:9")]
    assert events[0].text == "🎮 Hades II продаётся в бандле «Supergiant Pack» (5 игр) — ₪500"
    assert events[0].data == {
        "name": "Hades II", "steam_id": HADES, "bundle": "Supergiant Pack", "games": 5, "final": 50000, "currency": SHEKEL,
    }
    assert "expires_at" not in events[0].data


def test_a_bundle_and_a_discount_at_once_are_two_events():
    events = detect(look(), replace(discounted(), bundles=(HADES_BUNDLE,)))
    assert [e.type for e in events] == [price_events.DISCOUNT, price_events.BUNDLE]


# --- folding (spec 5.4) -------------------------------------------------------------------------------------------


def pending(number, event_type, data, title_id=None):
    payload = {"text": data.get("text", f"event {number}"), **data}
    return Pending(number, number, event_type, title_id, payload["text"], payload, datetime(2026, 11, 1))


def discount_pending(number, name="Hades II", steam_id=HADES, **price):
    data = price_events.discount_payload(name, steam_id, Price(**{"final": 19530, "original": 27900, "pct": 30, **price}), SHEKEL, None, False)
    return pending(number, price_events.DISCOUNT, data, title_id=number)


def test_discounts_fold_in_messages_of_their_own_only():
    queue = [discount_pending(1, "Resident Evil Requiem", "3764200"), discount_pending(2), discount_pending(3, "Elden Ring", "1245620")]

    [unit] = delivery.fold(queue, episodes=False, discounts=True)
    assert unit.discounts and len(unit.members) == 3
    assert unit.text.split("\n") == [
        "🎮 Скидки в Steam:",
        "Resident Evil Requiem — −30 %, ₪279 → ₪195,30",
        "Hades II — −30 %, ₪279 → ₪195,30",
        "Elden Ring — −30 %, ₪279 → ₪195,30",
    ]
    assert len(delivery.fold(queue, episodes=True)) == 3  # a summary and «Недавно»: a line each


def test_one_discount_and_bundles_and_pages_do_not_fold():
    page = price_events.steam_page_event(5, "Ведьмак 4", "1")
    bundle_data = price_events.bundle_payload("Hades II", HADES, HADES_BUNDLE, SHEKEL)
    queue = [
        discount_pending(1),
        pending(2, price_events.BUNDLE, bundle_data, 2),
        pending(3, price_events.BUNDLE, bundle_data, 3),
        pending(4, price_events.STEAM_PAGE, {"text": page.text, **page.data}, 4),
        pending(5, price_events.STEAM_PAGE, {"text": page.text, **page.data}, 5),
    ]
    units = delivery.fold(queue, episodes=False, discounts=True)
    assert [len(u.members) for u in units] == [1, 1, 1, 1, 1] and not any(u.discounts for u in units)


def test_a_long_folded_message_is_split_by_lines_each_part_with_the_header():
    long_name = "Игра " + "о" * 200
    queue = [discount_pending(n, f"{long_name} {n}", str(n)) for n in range(1, 31)]

    units = delivery.fold(queue, episodes=False, discounts=True)

    assert len(units) > 1 and all(u.discounts for u in units)
    assert all(u.text.startswith("🎮 Скидки в Steam:\n") and len(u.text) <= MESSAGE_LIMIT for u in units)
    assert [m.event_id for u in units for m in u.members] == list(range(1, 31))


def test_the_platforms_of_a_game_fold_as_before_beside_discounts():
    two = game_events.sample_two_platforms_events()
    queue = [pending(1, *two[0]), discount_pending(2), pending(3, *two[1]), discount_pending(4, "Elden Ring", "1245620")]
    units = delivery.fold(queue, episodes=False, discounts=True)
    assert [len(u.members) for u in units] == [2, 2]
    assert "вышла на ПК и PS5" in units[0].text and units[1].discounts


# --- buttons (spec 5.5) -------------------------------------------------------------------------------------------


def test_an_event_of_steam_has_the_card_and_the_link_to_steam():
    for event_type in price_events.TYPES:
        actions = event_actions(event_type, 1, 7, {"steam_id": HADES})
        assert [(a.label, a.name, a.url) for a in actions] == [
            ("📄 Карточка", CARD, None),
            ("🛒 Открыть в Steam", STEAM, "https://store.steampowered.com/app/1145350/"),
        ]
    # a sample belongs to no title: the link alone
    assert [a.name for a in event_actions(price_events.DISCOUNT, 1, None, {"steam_id": HADES})] == [STEAM]


def test_the_bot_makes_a_link_of_a_button_with_an_address_and_a_call_of_the_others():
    markup = actions_markup([Action("📄 Карточка", CARD, 7), Action("🛒 Открыть в Steam", STEAM, HADES, "https://x/")])
    card, link = (row[0] for row in markup.inline_keyboard)
    assert card.callback_data and card.url is None
    assert link.url == "https://x/" and link.callback_data is None


# --- through the facade -------------------------------------------------------------------------------------------


class FakeClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, **delta):
        self.now += timedelta(**delta)


class FakeSender:
    def __init__(self):
        self.sent = []  # (message, actions)

    async def send(self, message, actions=()):
        self.sent.append((message, list(actions)))


class MadeUpGames:
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


class Looks:
    """A source of price looks: `looks[number]` is what Steam answers now (₪279 by default), for the number and the
    country asked."""

    def __init__(self):
        self.looks = {}

    async def price_looks(self, appids, country):
        return {appid: replace(self.looks.get(appid, look()), appid=appid, country=country) for appid in appids}


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
def steam():
    return Looks()


@pytest.fixture
def tracker(session_factory, clock, sender, igdb, steam):
    tracker = Tracker(session_factory, clock=clock, sender=sender, sources={TitleKind.GAME: igdb}, price_source=steam)
    # every day off, no quiet hours: what is found goes out at once
    run(tracker.set_delivery_rules(tz_name="UTC", workdays=[], quiet_from="00:00", quiet_until="00:00"))
    return tracker


def add(tracker, igdb, state=None, external_id="1", name="Hades II"):
    igdb.put(external_id, state if state is not None else game(), name)
    return run(tracker.add_title(TitleKind.GAME, external_id)).title_id


def check(tracker, clock, hours=6):
    clock.advance(hours=hours)
    run(tracker.poll_due())


def events(session_factory, title_id=None):
    with session_factory() as session:
        query = select(Event).order_by(Event.id)
        if title_id is not None:
            query = query.where(Event.title_id == title_id)
        return [(e.type, e.dedup_key) for e in session.scalars(query)]


def pending_keys(session_factory):
    with session_factory() as session:
        return [
            key for key in session.scalars(
                select(Event.dedup_key)
                .join(DeliveryItem, DeliveryItem.event_id == Event.id)
                .where(DeliveryItem.status == DeliveryStatus.PENDING)
                .order_by(Event.id)
            )
        ]


def igdb_says(session_factory, igdb, state, external_id="1"):
    igdb.by_id[external_id] = replace(igdb.by_id[external_id], game=state)
    with session_factory() as session:
        for stored in session.scalars(select(SourceSnapshot).where(SourceSnapshot.source == "igdb")):
            stored.next_check_at = None
        session.commit()


def put_setting(session_factory, key, value):
    with session_factory() as session:
        session.merge(SettingRecord(key=key, value=value))
        session.commit()


def discount_keys(session_factory):
    return [key for kind, key in events(session_factory) if kind == price_events.DISCOUNT]


def test_the_first_check_is_silent_and_a_discount_after_it_comes_once(tracker, igdb, steam, sender, clock, session_factory):
    steam.looks[HADES] = discounted(ends_at=LATER_END)
    title_id = add(tracker, igdb)
    run(tracker.poll_due())  # the reference point: the discount is in the snapshot, no message
    assert events(session_factory) == []

    steam.looks[HADES] = look()
    check(tracker, clock)
    steam.looks[HADES] = discounted(ends_at=LATER_END)
    check(tracker, clock)
    check(tracker, clock)  # the same discount again
    run(tracker.deliver_pending())

    assert discount_keys(session_factory) == [f"game:{title_id}:discount:30:2026-11-20T18:00:00"]
    [(text, actions)] = sender.sent
    assert text.split("\n") == [
        "🎮 Hades II: скидка −30 % в Steam — ₪279 → ₪195,30, до 20 ноября",
        price_events.LOWEST_LINE,  # no dearer than every record of the history before this check
    ]
    assert [(a.name, a.url) for a in actions] == [(CARD, None), (STEAM, "https://store.steampowered.com/app/1145350/")]


def test_a_deeper_discount_takes_the_undelivered_one_out_of_the_queue(tracker, igdb, steam, clock, session_factory):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    steam.looks[HADES] = discounted(30, ends_at=LATER_END)
    check(tracker, clock)
    steam.looks[HADES] = discounted(50, ends_at=LATER_END)
    check(tracker, clock)

    keys = discount_keys(session_factory)
    assert keys == [f"game:{title_id}:discount:30:2026-11-20T18:00:00", f"game:{title_id}:discount:50:2026-11-20T18:00:00"]
    assert pending_keys(session_factory) == keys[1:]  # one line about the discount of the game in the summary


def test_the_same_percent_again_after_the_end_is_new_and_an_extension_is_silent(tracker, igdb, steam, clock, session_factory):
    add(tracker, igdb)
    run(tracker.poll_due())
    first_end = naive(T0) + timedelta(days=2)
    steam.looks[HADES] = discounted(ends_at=first_end)
    check(tracker, clock)
    steam.looks[HADES] = discounted(ends_at=first_end + timedelta(days=1))  # Steam extended it
    check(tracker, clock)
    clock.advance(days=4)
    steam.looks[HADES] = discounted(ends_at=naive(clock.now) + timedelta(days=9))  # the next sale, the same −30 %
    check(tracker, clock)

    assert len(discount_keys(session_factory)) == 2


def test_a_discount_without_an_end_comes_again_after_a_break(tracker, igdb, steam, clock, session_factory):
    add(tracker, igdb)
    run(tracker.poll_due())
    for state in (discounted(ends_at=None), discounted(ends_at=None), look(), discounted(ends_at=None)):
        steam.looks[HADES] = state
        check(tracker, clock)
    assert len(discount_keys(session_factory)) == 2


def test_a_bundle_comes_once_gone_and_back_is_silent(tracker, igdb, steam, clock, session_factory):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    for bundles in ([HADES_BUNDLE], [HADES_BUNDLE], [], [HADES_BUNDLE]):
        steam.looks[HADES] = look(bundles=bundles)
        check(tracker, clock)
    assert events(session_factory) == [(price_events.BUNDLE, f"game:{title_id}:bundle:bundle:1")]


def test_the_lowest_comes_from_the_history_before_this_check(tracker, igdb, steam, clock, session_factory):
    add(tracker, igdb)
    run(tracker.poll_due())  # ₪279 in the history
    steam.looks[HADES] = discounted(30, ends_at=LATER_END)
    check(tracker, clock)
    steam.looks[HADES] = look()
    check(tracker, clock)
    steam.looks[HADES] = discounted(20, ends_at=naive(clock.now) + timedelta(days=30))  # dearer than −30 %
    clock.advance(days=12)
    check(tracker, clock)
    with session_factory() as session:
        lowest = [e.payload["lowest"] for e in session.scalars(select(Event).order_by(Event.id))]
    assert lowest == [True, False]


def test_a_new_country_or_number_is_the_reference_point(tracker, igdb, steam, clock, session_factory):
    add(tracker, igdb)
    run(tracker.poll_due())
    steam.looks[HADES] = discounted(ends_at=LATER_END)
    put_setting(session_factory, STORE_COUNTRY_SETTING, "ua")
    check(tracker, clock, hours=0)
    steam.looks["2"] = discounted(appid="2", ends_at=LATER_END)
    igdb_says(session_factory, igdb, game(steam_id="2"))
    check(tracker, clock, hours=0)
    assert events(session_factory) == []


def test_an_old_discount_goes_out_no_more_but_stays_in_the_log(tracker, igdb, steam, sender, clock, session_factory):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    steam.looks[HADES] = discounted(ends_at=naive(T0) + timedelta(hours=8))
    check(tracker, clock)  # found at T0 + 6 h, ends at T0 + 8 h
    clock.advance(hours=3)

    for send in (tracker.deliver_pending, tracker.summary_now):
        run(send())
    assert sender.sent == [] and pending_keys(session_factory) == []
    with session_factory() as session:
        assert session.scalars(select(DeliveryItem)).all() == []
    assert discount_keys(session_factory) == [f"game:{title_id}:discount:30:{(naive(T0) + timedelta(hours=8)).isoformat()}"]


def test_an_old_discount_is_left_out_of_the_summary_and_the_others_go(tracker, igdb, steam, sender, clock, session_factory):
    add(tracker, igdb)
    run(tracker.poll_due())
    steam.looks[HADES] = discounted(ends_at=naive(T0) + timedelta(hours=8))
    check(tracker, clock)
    run(tracker.record_event("test", {"text": "другое"}, "other"))
    clock.advance(hours=3)
    result = run(tracker.summary_now())
    assert result.events == 1 and len(sender.sent) == 1 and "другое" in sender.sent[0][0]


def test_two_discounts_at_once_are_one_message_with_a_link_a_game(tracker, igdb, steam, sender, clock, session_factory):
    add(tracker, igdb, name="Hades II")
    add(tracker, igdb, game(steam_id="1245620"), external_id="2", name="Elden Ring")
    run(tracker.poll_due())
    steam.looks[HADES] = discounted(ends_at=LATER_END)
    steam.looks["1245620"] = discounted(100, original=19900, ends_at=LATER_END)
    check(tracker, clock)
    run(tracker.deliver_pending())

    [(text, actions)] = sender.sent
    assert text.split("\n") == [
        "🎮 Скидки в Steam:",
        "Hades II — −30 %, ₪279 → ₪195,30, до 20 ноября, самая низкая с добавления",
        "Elden Ring — раздают бесплатно до 20 ноября, самая низкая с добавления",
    ]
    assert [(a.label, a.url) for a in actions] == [
        ("🛒 Steam: Hades II", "https://store.steampowered.com/app/1145350/"),
        ("🛒 Steam: Elden Ring", "https://store.steampowered.com/app/1245620/"),
    ]


def test_in_a_summary_discounts_keep_a_line_each_and_the_steam_button_stands_before_the_card(
    tracker, igdb, steam, sender, clock, session_factory
):
    add(tracker, igdb, name="Hades II")
    add(tracker, igdb, game(steam_id="1245620"), external_id="2", name="Elden Ring")
    run(tracker.poll_due())
    steam.looks[HADES] = discounted(ends_at=LATER_END)
    steam.looks["1245620"] = discounted(ends_at=LATER_END)
    check(tracker, clock)
    run(tracker.summary_now())

    [(text, actions)] = sender.sent
    assert text.split("\n")[1:] == [
        f"🎮 Hades II: скидка −30 % в Steam — ₪279 → ₪195,30, до 20 ноября · {price_events.LOWEST_LINE}",
        f"🎮 Elden Ring: скидка −30 % в Steam — ₪279 → ₪195,30, до 20 ноября · {price_events.LOWEST_LINE}",
    ]
    assert [a.label for a in actions] == [
        "🛒 Открыть в Steam: Hades II", "🛒 Открыть в Steam: Elden Ring", "📄 Карточка: Hades II", "📄 Карточка: Elden Ring",
    ]


def test_recent_shows_each_event_of_steam_on_its_row_without_buttons(tracker, igdb, steam, clock):
    add(tracker, igdb, name="Hades II")
    add(tracker, igdb, game(steam_id="1245620"), external_id="2", name="Elden Ring")
    run(tracker.poll_due())
    steam.looks[HADES] = discounted(ends_at=LATER_END, bundles=[HADES_BUNDLE])
    steam.looks["1245620"] = discounted(ends_at=LATER_END)
    check(tracker, clock)

    feed = run(tracker.feed())
    [day] = feed.recent
    assert sorted(row.headline for row in day.rows) == sorted([
        "🎮 Hades II: скидка −30 % в Steam — ₪279 → ₪195,30, до 20 ноября",
        "🎮 Hades II продаётся в бандле «Hades + Hades II» (2 игры) — ₪250",
        "🎮 Elden Ring: скидка −30 % в Steam — ₪279 → ₪195,30, до 20 ноября",
    ])
    assert all(not row.watched and row.follow is None for row in day.rows)


# --- the page in Steam --------------------------------------------------------------------------------------------


def test_the_page_in_steam_comes_once_when_igdb_gives_the_number(tracker, igdb, sender, clock, session_factory):
    title_id = add(tracker, igdb, game(steam_id=None), name="Ведьмак 4")
    igdb_says(session_factory, igdb, game())
    run(tracker.poll_due())
    run(tracker.deliver_pending())
    [(text, actions)] = sender.sent
    assert text == "🎮 Ведьмак 4: появилась страница в Steam"
    assert [a.name for a in actions] == [CARD, STEAM]

    igdb_says(session_factory, igdb, game(steam_id=None))  # the number went and came back: once a game
    run(tracker.poll_due())
    igdb_says(session_factory, igdb, game())
    run(tracker.poll_due())
    assert [e for e in events(session_factory) if e[0] == price_events.STEAM_PAGE] == [
        (price_events.STEAM_PAGE, f"game:{title_id}:steam_page")
    ]


@pytest.mark.parametrize("why", ["added with the number", "mark off", "pc not mine", "not on pc", "started", "restored"])
def test_the_page_in_steam_does_not_come(why, tracker, igdb, session_factory, clock):
    title_id = add(tracker, igdb, game() if why == "added with the number" else game(steam_id=None))
    new = game()
    if why == "mark off":
        run(tracker.set_platform_playing(title_id, "pc", False))
    elif why == "pc not mine":
        put_setting(session_factory, MY_PLATFORMS_SETTING, ["ps5"])
    elif why == "not on pc":
        new = game(platforms=(PS5,))
    elif why == "started":
        run(tracker.mark_started(title_id))
    elif why == "restored":
        clock.advance(minutes=1)  # the snapshot is older than «Вернуть в список»
        run(tracker.mark_dropped(title_id))
        run(tracker.restore_title(title_id))
    igdb_says(session_factory, igdb, new)
    run(tracker.poll_due())
    assert [e for e in events(session_factory) if e[0] == price_events.STEAM_PAGE] == []


def test_a_new_steam_number_gives_no_page(tracker, igdb, session_factory):
    add(tracker, igdb)
    igdb_says(session_factory, igdb, game(steam_id="2"))
    run(tracker.poll_due())
    assert [e for e in events(session_factory) if e[0] == price_events.STEAM_PAGE] == []


# --- «Тестовое событие» (spec 5.7) --------------------------------------------------------------------------------


def test_the_five_samples_of_steam(tracker, sender):
    ids = [sample_id for sample_id, _, _ in price_events.TEST_SAMPLES]
    assert {s.id for s in tracker.test_samples()} >= set(ids) and len(ids) == 5
    for sample_id in ids:
        assert run(tracker.send_test_event(sample_id)).delivered

    texts = [text for text, _ in sender.sent]
    assert len(sender.sent) == 5  # the three discounts of «скидки на несколько игр» are one message
    assert texts[0].split("\n") == [
        "Тестовое событие «Игра: скидка в Steam»: 🎮 Resident Evil Requiem: скидка −30 % в Steam — ₪279 → ₪195,30, до 3 ноября",
        "Самая низкая цена с тех пор, как игра в списке",
    ]
    assert "раздают бесплатно до 3 ноября (обычно ₪279)" in texts[1]
    assert "продаётся в бандле" in texts[2] and "появилась страница в Steam" in texts[3]
    for _, actions in sender.sent[:4]:
        assert [(a.label, a.url) for a in actions] == [("🛒 Открыть в Steam", "https://store.steampowered.com/app/3764200/")]
    many, actions = sender.sent[4]
    assert many.startswith("Тестовое событие «Игра: скидки на несколько игр»: 🎮 Скидки в Steam:\n")
    assert len(many.split("\n")) == 4
    assert [a.label for a in actions] == ["🛒 Steam: Resident Evil Requiem", "🛒 Steam: Hades II", "🛒 Steam: Elden Ring"]
    assert all(a.url for a in actions)


def test_the_folded_message_has_ten_links_at_most_and_cuts_long_names():
    from app.tracker.delivery_service import _unit_actions

    queue = [discount_pending(n, f"Игра {n}" if n > 1 else "Очень длинное название игры для кнопки", str(n)) for n in range(1, 13)]
    [unit] = delivery.fold(queue, episodes=False, discounts=True)
    actions = _unit_actions(unit)
    assert len(actions) == 10 and all(a.name == STEAM for a in actions)
    assert actions[0].label == "🛒 Steam: " + "Очень длинное название игры для кнопки"[:29] + "…"  # 30 characters
    assert actions[1].url == "https://store.steampowered.com/app/2/"
