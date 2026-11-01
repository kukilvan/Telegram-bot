"""Steam prices, pure (spec 3.4, 3.5 and 4.5 of part 6.2): how an amount and a discount read, the currency taken from
how Steam writes a price, the price look there and back with a strict reading, and «самая низкая с добавления»."""

import json
from dataclasses import dataclass, replace
from datetime import datetime

import pytest

from app.tracker.prices import (
    ANSWERS,
    BUNDLES_ONLY,
    COMING_SOON,
    FREE,
    NOT_IN_COUNTRY,
    NOT_SOLD,
    PRICE,
    UNKNOWN_APP,
    Bundle,
    Lowest,
    Money,
    Price,
    PriceLook,
    currency_of,
    lowest,
    percent,
)

NBSP = " "
HADES = Bundle("bundle:61368", "Hades + Hades II", 2, 25000)
REQUIEM = Price(19530, 27900, 30, datetime(2026, 11, 3, 18, 0))


# --- money -------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("cents, currency, written", [
    (19530, "₪{}", "₪195,30"),
    (27900, "₪{}", "₪279"),
    (134900, "{}₴", f"1{NBSP}349₴"),
    (760000, "{}₸", f"7{NBSP}600₸"),
    (110000, "{} руб", f"1{NBSP}100 руб"),
    (11700, "{} zł", "117 zł"),
    (2899, "{}€", "28,99€"),
    (1499, "${}", "$14,99"),
    (2499, "£{}", "£24,99"),
    (99900, "₪{}", "₪999"),
    (123456789, "₪{}", f"₪1{NBSP}234{NBSP}567,89"),
    (5, "₪{}", "₪0,05"),
])
def test_an_amount_reads_in_groups_of_three_with_hundredths_after_a_comma(cents, currency, written):
    assert str(Money(cents, currency)) == written


def test_zero_is_free():
    assert str(Money(0, "₪{}")) == "бесплатно"


def test_a_discount_reads_with_the_minus_sign_and_a_no_break_space():
    assert percent(30) == f"−30{NBSP}%"


@pytest.mark.parametrize("written, currency", [
    ("₪179.95", "₪{}"),
    ("1 349,00₴", "{}₴"),
    ("7 600,00₸", "{}₸"),
    ("1100 руб", "{} руб"),
    ("117,00 zł", "{} zł"),
    ("28,99€", "{}€"),
    ("£24.99", "£{}"),
    ("$14.99", "${}"),
    (f"1{NBSP}349,00₴", "{}₴"),
])
def test_the_currency_is_the_price_of_steam_with_its_number_left_out(written, currency):
    assert currency_of(written) == currency


@pytest.mark.parametrize("written", ["бесплатно", "", None, 1499, "12 / 34 €", "{}12"])
def test_a_price_without_one_number_has_no_currency(written):
    with pytest.raises(ValueError):
        currency_of(written)


# --- the price look ----------------------------------------------------------------------------------------------------


LOOKS = [
    PriceLook("3764200", "il", PRICE, "₪{}", REQUIEM),
    PriceLook("1145350", "il", PRICE, "₪{}", Price(11095), (HADES,)),
    PriceLook("3764200", "il", PRICE, "₪{}", replace(REQUIEM, preorder=True, edition="Resident Evil Requiem Deluxe")),
    PriceLook("3764200", "il", PRICE, "₪{}", Price(19530, 27900, 30)),
    PriceLook("730", "ua", FREE),
    PriceLook("730", "ua", FREE, "{}₴", None, (HADES,)),
    PriceLook("5180770", "il", COMING_SOON),
    PriceLook("10", "il", BUNDLES_ONLY, "₪{}", None, (HADES, Bundle("package:7", "Counter-Strike: Condition Zero", 2, 3649))),
    PriceLook("50300", "il", NOT_SOLD),
    PriceLook("292030", "ru", NOT_IN_COUNTRY),
    PriceLook("999999999", "ua", UNKNOWN_APP),
    PriceLook("abc", "il", UNKNOWN_APP),
]


def test_every_answer_has_a_look_here():
    assert {look.answer for look in LOOKS} == set(ANSWERS)


@pytest.mark.parametrize("look", LOOKS, ids=lambda look: look.answer)
def test_a_look_goes_there_and_back_through_json(look):
    state = json.loads(json.dumps(look.state()))

    assert PriceLook.from_state(state) == look


def test_the_state_is_as_the_spec_writes_it():
    assert PriceLook("3764200", "il", PRICE, "₪{}", REQUIEM, (HADES,)).state() == {
        "appid": "3764200",
        "country": "il",
        "answer": "price",
        "currency": "₪{}",
        "price": {"final": 19530, "original": 27900, "pct": 30, "ends_at": "2026-11-03T18:00:00", "preorder": False,
                  "edition": None},
        "bundles": [{"id": "bundle:61368", "name": "Hades + Hades II", "games": 2, "final": 25000}],
    }


def test_the_empty_state_is_prices_not_looked_at_yet():
    assert PriceLook.from_state({}) is None


def spoiled(change):
    state = PriceLook("1145350", "il", PRICE, "₪{}", REQUIEM, (HADES,)).state()
    change(state)
    return state


@pytest.mark.parametrize("change", [
    lambda s: s.update(extra=1),
    lambda s: s.pop("bundles"),
    lambda s: s.update(appid=1145350),
    lambda s: s.update(appid=""),
    lambda s: s.update(country="IL"),
    lambda s: s.update(answer="sale"),
    lambda s: s.update(answer=FREE),  # a price with another answer
    lambda s: s.update(price=None),  # the answer `price` without one
    lambda s: s.update(currency=None),
    lambda s: s.update(currency="₪"),
    lambda s: s.update(bundles={}),
    lambda s: s["price"].update(final="19530"),
    lambda s: s["price"].update(final=True),
    lambda s: s["price"].update(final=-1),
    lambda s: s["price"].update(original=None),  # a percent without a discount
    lambda s: s["price"].update(original=19000),  # «before» lower than now
    lambda s: s["price"].update(pct=0),
    lambda s: s["price"].update(pct=101),
    lambda s: s["price"].update(ends_at="soon"),
    lambda s: s["price"].update(ends_at="2026-11-03T18:00:00+00:00"),
    lambda s: s["price"].update(ends_at=1793728800),
    lambda s: s["price"].update(preorder=0),
    lambda s: s["price"].update(edition=""),
    lambda s: s["price"].pop("edition"),
    lambda s: s["bundles"][0].update(id="61368"),
    lambda s: s["bundles"][0].update(games=1),
    lambda s: s["bundles"][0].update(name=None),
    lambda s: s["bundles"][0].update(colour="red"),
    lambda s: s["bundles"].append("Hades"),
])
def test_a_spoiled_state_is_a_mistake_not_a_look(change):
    with pytest.raises(ValueError):
        PriceLook.from_state(spoiled(change))


@pytest.mark.parametrize("state", [None, [], "price"])
def test_a_state_that_is_no_record_is_a_mistake(state):
    with pytest.raises(ValueError):
        PriceLook.from_state(state)


@pytest.mark.parametrize("look", [
    lambda: PriceLook("10", "il", BUNDLES_ONLY),
    lambda: PriceLook("50300", "il", NOT_SOLD, "₪{}", None, (HADES,)),
    lambda: PriceLook("292030", "ru", NOT_IN_COUNTRY, "{} руб", None, (HADES,)),
    lambda: PriceLook("5180770", "il", COMING_SOON, "₪{}"),
])
def test_a_look_that_contradicts_its_answer_cannot_be_made(look):
    with pytest.raises(ValueError):
        look()


def test_the_money_of_a_look_is_in_its_currency():
    look = PriceLook("3764200", "il", PRICE, "₪{}", REQUIEM)

    assert str(look.money(look.price.final)) == "₪195,30"
    assert look.price.discounted and not Price(11095).discounted
    with pytest.raises(ValueError):
        PriceLook("730", "ua", FREE).money(100)


# --- «самая низкая с добавления» ---------------------------------------------------------------------------------------


@dataclass
class Record:
    seen_at: datetime
    final: int
    appid: str = "3764200"
    country: str = "il"
    currency: str = "₪{}"


def test_the_lowest_is_of_the_same_number_country_and_currency():
    records = [
        Record(datetime(2026, 10, 1, 9), 27900),
        Record(datetime(2026, 10, 5, 9), 19530),
        Record(datetime(2026, 10, 9, 9), 27900),
        Record(datetime(2026, 10, 2, 9), 100, appid="1145350"),
        Record(datetime(2026, 10, 3, 9), 100, country="ua"),
        Record(datetime(2026, 10, 4, 9), 100, currency="${}"),
    ]

    assert lowest(records, "3764200", "il", "₪{}") == Lowest(Money(19530, "₪{}"), datetime(2026, 10, 5, 9))


def test_the_moment_is_of_the_latest_record_with_that_price():
    records = [
        Record(datetime(2026, 10, 5, 9), 19530),
        Record(datetime(2026, 10, 9, 9), 27900),
        Record(datetime(2026, 10, 20, 9), 19530),
        Record(datetime(2026, 10, 12, 9), 19530),
    ]

    assert lowest(records, "3764200", "il", "₪{}").seen_at == datetime(2026, 10, 20, 9)


def test_without_records_of_its_own_there_is_no_lowest():
    assert lowest([], "3764200", "il", "₪{}") is None
    assert lowest([Record(datetime(2026, 10, 1), 100, currency="${}")], "3764200", "il", "₪{}") is None
