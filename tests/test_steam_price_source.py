"""Steam adapter for prices (spec 3.2–3.4 of part 6.2) on saved real answers of `GetItems` (`tests/fixtures/steam/`,
2026-10-31): each answer about a game, the price among the purchase options, the discount, the bundles and the currency
of every store country; a purchase option that cannot be read is a failure of its game only. The preorder answer is
built from a real one (KI-44)."""

import asyncio
import copy
import json
from datetime import datetime
from pathlib import Path

import pytest

from app.tracker import failures
from app.tracker.prices import (
    BUNDLES_ONLY,
    COMING_SOON,
    FREE,
    NOT_IN_COUNTRY,
    NOT_SOLD,
    PRICE,
    UNKNOWN_APP,
    Bundle,
    Price,
    PriceLook,
)
from app.tracker.sources.steam_prices import SOURCE_KEY, SteamPriceSource, UnreadAnswer, parse_items

FIXTURES = Path(__file__).parent / "fixtures" / "steam"

GTA, CYBERPUNK, ELDEN_RING, HADES_2, GHOSTLINE, RE_REQUIEM = "3240220", "1091500", "1245620", "1145350", "5180770", "3764200"
WITCHER_3, CS2, SPEC_OPS, FORZA_4, UNKNOWN = "292030", "730", "50300", "1293830", "999999999"
COUNTER_STRIKE, MULTIWINIA, TWO_WORLDS = "10", "1530", "1930"


def items(name):
    return json.loads((FIXTURES / f"getitems_{name}.json").read_text(encoding="utf-8"))["response"]["store_items"]


def looks(name, country="il"):
    """Every game of a saved answer, read."""
    found = items(name)
    return parse_items(found, [str(item["appid"] or item["id"]) for item in found], country)


def look(name, appid, country="il"):
    return looks(name, country)[appid]


def record(name, appid):
    """A copy of the record of a game in a saved answer, to change for a case Steam did not show that day."""
    return copy.deepcopy(next(item for item in items(name) if str(item["appid"] or item["id"]) == appid))


def read_one(item, appid, country="il"):
    return parse_items([item], [appid], country)[appid]


class FakeSteam:
    def __init__(self, answer=()):
        self.answer = list(answer)
        self.asked = []

    async def store_items(self, appids, country):
        self.asked.append((list(appids), country))
        return self.answer


# --- what Steam answered about a game ----------------------------------------------------------------------------------


def test_the_six_games_of_israel_have_prices_in_shekels_but_ghostline_comes_soon():
    found = looks("six_games_il")

    assert {appid: found[appid].answer for appid in found} == {
        GTA: PRICE, CYBERPUNK: PRICE, ELDEN_RING: PRICE, HADES_2: PRICE, GHOSTLINE: COMING_SOON, RE_REQUIEM: PRICE,
    }
    assert {found[appid].currency for appid in found if appid != GHOSTLINE} == {"₪{}"}
    assert found[GHOSTLINE] == PriceLook(GHOSTLINE, "il", COMING_SOON)


def test_a_free_game_has_no_price_even_with_a_purchase_option_of_one_game():
    assert look("answer_kinds_il", CS2) == PriceLook(CS2, "il", FREE)  # «прайм-статус» is no price
    assert look("ua", CS2, "ua") == PriceLook(CS2, "ua", FREE)


@pytest.mark.parametrize("appid", [SPEC_OPS, FORZA_4])
def test_a_game_taken_off_sale_is_not_sold(appid):
    assert look("delisted_il", appid) == PriceLook(appid, "il", NOT_SOLD)


def test_in_russia_a_game_is_not_sold_in_the_country():
    found = looks("ru", "ru")

    assert found[WITCHER_3] == PriceLook(WITCHER_3, "ru", NOT_IN_COUNTRY)
    assert found[GTA] == PriceLook(GTA, "ru", NOT_IN_COUNTRY)


@pytest.mark.parametrize("name, country", [("ua", "ua"), ("ru", "ru")])
def test_a_number_steam_does_not_know_is_an_unknown_app_matched_by_its_id(name, country):
    assert items(name)[2]["appid"] == 0  # Steam answers it under `id` only
    assert look(name, UNKNOWN, country) == PriceLook(UNKNOWN, country, UNKNOWN_APP)


def test_a_game_sold_only_in_bundles():
    found = look("packages_il", COUNTER_STRIKE)  # Counter-Strike: no purchase option of the game alone

    assert (found.answer, found.price, found.currency) == (BUNDLES_ONLY, None, "₪{}")
    assert found.bundles == (
        Bundle("package:7", "Counter-Strike: Condition Zero", 2, 3649),
        Bundle("bundle:236", "Counter-Strike Complete", 4, 4744),
        Bundle("bundle:235", "Counter-Strike 1 Anthology", 6, 5426),
        Bundle("bundle:232", "Valve Complete Pack", 20, 42554),
    )


def test_a_preorder_is_a_price_of_a_game_that_comes_soon():
    found = look("preorder_il_assembled", RE_REQUIEM)

    assert found.answer == PRICE
    assert found.price == Price(19530, 27900, 30, datetime(2026, 11, 3, 18, 0), preorder=True)


def test_the_source_is_steam():
    assert SOURCE_KEY == "steam"
    assert failures.source_name(SOURCE_KEY) == "Steam"


# --- the price, the discount, the bundles ------------------------------------------------------------------------------


def test_gta_costs_the_game_itself_not_the_shark_card_and_not_the_subscription():
    found = look("six_games_il", GTA)

    assert found.price == Price(5650, 11300, 50, datetime(2026, 11, 5, 18, 0))
    assert found.bundles == ()


def test_elden_ring_costs_the_game_itself_among_three_editions():
    assert look("six_games_il", ELDEN_RING).price == Price(24900)


def test_the_complete_edition_of_cyberpunk_is_no_bundle():
    found = look("six_games_il", CYBERPUNK)

    assert (found.price, found.bundles) == (Price(24900), ())


def test_resident_evil_requiem_has_a_discount_on_the_game_and_on_the_deluxe_and_costs_the_game():
    found = look("six_games_il", RE_REQUIEM)

    assert found.price == Price(19530, 27900, 30, datetime(2026, 11, 3, 18, 0))
    assert str(found.money(found.price.final)) == "₪195,30"
    assert str(found.money(found.price.original)) == "₪279"


def test_the_witcher_3_and_hades_2_have_bundles_with_the_count_of_games():
    witcher, hades = look("answer_kinds_il", WITCHER_3), look("six_games_il", HADES_2)

    assert (witcher.price, witcher.bundles) == (Price(17995), (Bundle("bundle:727", "The Witcher Trilogy", 3, 26175),))
    assert (hades.price, hades.bundles) == (Price(11095), (Bundle("bundle:61368", "Hades + Hades II", 2, 25000),))


def test_packages_with_two_games_are_bundles_too():
    multiwinia = look("packages_il", MULTIWINIA)
    two_worlds = look("packages_il", TWO_WORLDS)

    assert multiwinia.price == Price(4395)
    assert multiwinia.bundles[:2] == (
        Bundle("package:978", "Multiwinia + Darwinia", 2, 6295),
        Bundle("package:14002", "Introversion Classics Pack", 4, 11095),
    )
    assert two_worlds.price == Price(1678, 5595, 70, datetime(2026, 11, 1, 18, 0))
    assert Bundle("package:18163", "Two Worlds Collection", 3, 4248) in two_worlds.bundles


def test_poland_has_no_discount_where_steam_shows_none():
    found = look("pl", GTA, "pl")  # the same sale as −50 % in Germany, but `discount_pct` 0 and the same price

    assert found.price == Price(6450)
    assert look("de", GTA, "de").price == Price(1499, 2999, 50, datetime(2026, 11, 5, 18, 0))


def test_the_end_of_a_discount_is_the_earliest_of_its_active_discounts():
    item = record("six_games_il", RE_REQUIEM)
    discounts = item["purchase_options"][0]["active_discounts"]
    discounts.append(dict(discounts[0], discount_end_date=discounts[0]["discount_end_date"] - 86400))

    assert read_one(item, RE_REQUIEM).price.ends_at == datetime(2026, 11, 2, 18, 0)


def test_a_discount_without_active_discounts_has_no_known_end():
    item = record("six_games_il", RE_REQUIEM)
    del item["purchase_options"][0]["active_discounts"]

    assert read_one(item, RE_REQUIEM).price == Price(19530, 27900, 30)


def test_an_edition_cheaper_than_the_game_is_the_price_with_its_name():
    item = record("six_games_il", RE_REQUIEM)
    item["purchase_options"][1]["final_price_in_cents"] = "15000"

    assert read_one(item, RE_REQUIEM).price == Price(
        15000, 31900, 30, datetime(2026, 11, 3, 18, 0), edition="Resident Evil Requiem Deluxe Edition",
    )


def test_of_equal_prices_the_first_purchase_option_is_the_game():
    item = record("six_games_il", ELDEN_RING)
    item["purchase_options"][1]["final_price_in_cents"] = "24900"

    assert read_one(item, ELDEN_RING).price == Price(24900)


def test_a_free_game_with_a_bundle_writes_the_currency_of_the_bundle():
    item = record("six_games_il", HADES_2)
    item["is_free"] = True

    found = read_one(item, HADES_2)
    assert (found.answer, found.price, found.currency) == (FREE, None, "₪{}")
    assert len(found.bundles) == 1


# --- the currency of every store country -------------------------------------------------------------------------------


@pytest.mark.parametrize("name, country, appid, currency, written", [
    ("six_games_il", "il", HADES_2, "₪{}", "₪110,95"),
    ("ua", "ua", WITCHER_3, "{}₴", "1 349₴"),
    ("kz", "kz", HADES_2, "{}₸", "7 600₸"),
    ("pl", "pl", HADES_2, "{} zł", "117 zł"),
    ("de", "de", HADES_2, "{}€", "28,99€"),
    ("tr", "tr", HADES_2, "${}", "$14,99"),  # Turkey pays in dollars
])
def test_the_currency_is_how_steam_writes_the_price(name, country, appid, currency, written):
    found = look(name, appid, country)

    assert found.currency == currency
    assert str(found.money(found.price.final)) == written


# --- what cannot be read -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("field, value", [
    ("final_price_in_cents", None),
    ("final_price_in_cents", "110.95"),
    ("final_price_in_cents", -1),
    ("final_price_in_cents", True),
    ("formatted_final_price", None),
    ("formatted_final_price", "бесплатно"),
    ("included_game_count", None),
    ("included_game_count", "1"),
    ("included_game_count", -1),
    ("purchase_option_name", None),
])
def test_a_purchase_option_without_a_field_or_with_garbage_makes_the_game_unreadable_not_priceless(field, value):
    found = items("six_games_il")
    hades = next(item for item in found if item["appid"] == 1145350)
    if value is None:
        del hades["purchase_options"][1][field]  # the bundle: every purchase option counts, not only the price
    else:
        hades["purchase_options"][1][field] = value

    read = parse_items(found, [HADES_2, GTA, RE_REQUIEM], "il")

    assert isinstance(read[HADES_2], UnreadAnswer)
    assert field in str(read[HADES_2])
    assert read[GTA].answer == read[RE_REQUIEM].answer == PRICE
    assert failures.reason_of(read[HADES_2]) == failures.UNKNOWN


@pytest.mark.parametrize("change", [
    lambda option: option.pop("original_price_in_cents"),
    lambda option: option.update(discount_pct="30"),
    lambda option: option.update(active_discounts=[{"discount_end_date": "soon"}]),
    lambda option: option.update(active_discounts={"discount_end_date": 1793728800}),
    lambda option: option.update(discount_pct=130),
])
def test_a_discount_that_cannot_be_read_makes_the_game_unreadable(change):
    item = record("six_games_il", RE_REQUIEM)
    change(item["purchase_options"][0])

    assert isinstance(read_one(item, RE_REQUIEM), UnreadAnswer)


def test_another_success_or_no_record_is_a_failure_of_that_game():
    item = record("six_games_il", HADES_2)
    item["success"] = 2

    read = parse_items([item], [HADES_2, GTA], "il")

    assert "success" in str(read[HADES_2])
    assert "no record" in str(read[GTA])


# --- asking Steam ------------------------------------------------------------------------------------------------------


def test_a_steam_number_of_no_digits_is_an_unknown_app_without_asking():
    steam = FakeSteam(items("six_games_il"))

    found = asyncio.run(SteamPriceSource(steam).price_looks(["abc", "٣٤", HADES_2, HADES_2], "il"))

    assert steam.asked == [([HADES_2], "il")]
    assert found["abc"] == PriceLook("abc", "il", UNKNOWN_APP)
    assert found["٣٤"] == PriceLook("٣٤", "il", UNKNOWN_APP)
    assert found[HADES_2].price == Price(11095)


def test_with_no_number_of_digits_steam_is_not_asked():
    steam = FakeSteam()

    found = asyncio.run(SteamPriceSource(steam).price_looks(["abc"], "il"))

    assert (steam.asked, found) == ([], {"abc": PriceLook("abc", "il", UNKNOWN_APP)})
