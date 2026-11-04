"""What the owner reads of the Steam prices of a game (spec 6 of part 6.2, ticket 05): every line of table 6.1 for the
web and for the bot, «самая низкая» of three kinds, the bundles, the caption, the mark of the list.

Pure: `price_rows` and the cards, no database; the owner's clock is Asia/Jerusalem, now is 9 November 2026, 12:00 UTC.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.tracker import price_rows
from app.tracker.cards import SteamView
from app.tracker.prices import (
    BUNDLES_ONLY, COMING_SOON, FREE, NOT_IN_COUNTRY, NOT_SOLD, PRICE, UNKNOWN_APP, Bundle, Price, PriceLook,
)

TZ = ZoneInfo("Asia/Jerusalem")  # UTC+2 in November
NOW = datetime(2026, 11, 9, 12, 0)  # naive UTC, as stored
CHECKED = datetime(2026, 11, 9, 12, 5)  # 14:05 on the owner's clock
ILS = "₪{}"
APPID = "1145350"
ENDS = datetime(2026, 11, 12, 18, 0)  # 20:00 on 12 November in Israel


@dataclass
class Record:
    seen_at: datetime
    appid: str
    country: str
    currency: str
    final: int


def look(answer=PRICE, price=None, bundles=(), currency=ILS, appid=APPID, country="il"):
    if answer == PRICE and price is None:
        price = Price(11095)
    if price is None and not bundles:
        currency = None
    return PriceLook(appid, country, answer, currency if (price or bundles) else None, price, tuple(bundles))


def view(a_look, steam_id=APPID, country="il", records=(), now=NOW, observed_at=CHECKED):
    return price_rows.steam_view(country, steam_id, a_look, observed_at if a_look is not None else None, list(records), now, TZ)


def lines(a_view: SteamView):
    return a_view.line, a_view.bot_line


# --- the line of the price: every row of table 6.1 ------------------------------------------------------------------


def test_a_game_without_a_steam_number_says_the_page_is_not_there_yet():
    got = view(None, steam_id=None)
    assert lines(got) == ("Страницы в Steam пока нет — придёт сообщение, когда появится", "страницы пока нет")
    assert got.caption == "Цены для страны «Израиль»"  # nothing was checked: no «проверено»


def test_an_empty_snapshot_says_the_price_was_not_looked_at_yet():
    got = view(None)
    assert lines(got) == ("Цену ещё не проверяли — она появится через минуту-другую", "ещё не проверяли")
    assert got.caption == "Цены для страны «Израиль»"


@pytest.mark.parametrize(
    ("price", "web", "bot"),
    [
        (Price(11095), "Цена: ₪110,95", "₪110,95"),
        (Price(19530, 27900, 30, ENDS), "Скидка −30 %: ₪279 → ₪195,30, до 12 ноября", "₪195,30 (−30 % до 12 ноября)"),
        (Price(19530, 27900, 30), "Скидка −30 %: ₪279 → ₪195,30", "₪195,30 (−30 %)"),
        (Price(0, 27900, 100, ENDS), "Раздают бесплатно до 12 ноября (обычно ₪279)", "бесплатно до 12 ноября (обычно ₪279)"),
        (Price(0, 27900, 100), "Раздают бесплатно (обычно ₪279)", "бесплатно (обычно ₪279)"),
        (Price(19900, preorder=True), "Предзаказ: ₪199", "предзаказ ₪199"),
        (
            Price(17910, 19900, 10, ENDS, preorder=True),
            "Предзаказ со скидкой −10 %: ₪199 → ₪179,10, до 12 ноября", "₪179,10 (предзаказ, −10 % до 12 ноября)",
        ),
        (
            Price(24900, edition="ELDEN RING Shadow of the Erdtree Edition"),
            "Цена: ₪249 («ELDEN RING Shadow of the Erdtree Edition»)", "₪249",  # the bot leaves the edition out
        ),
        (Price(0), "Цена: бесплатно", "бесплатно"),
    ],
)
def test_the_price_lines_of_a_game_for_the_web_and_for_the_bot(price, web, bot):
    assert lines(view(look(price=price))) == (web, bot)


@pytest.mark.parametrize(
    ("answer", "web", "bot"),
    [
        (FREE, "Бесплатная игра", "бесплатная игра"),
        (COMING_SOON, "Ещё не продаётся — скоро выйдет", "ещё не продаётся (скоро выйдет)"),
        (NOT_SOLD, "Сейчас в Steam не продаётся", "не продаётся"),
        (NOT_IN_COUNTRY, "В Steam в вашей стране не продаётся", "в вашей стране не продаётся"),
        (
            UNKNOWN_APP, "Steam не знает игру с номером из IGDB — ссылка «Открыть в Steam» может не работать",
            "номер из IGDB неверный",
        ),
    ],
)
def test_the_answers_of_steam_with_no_price(answer, web, bot):
    got = view(look(answer))
    assert lines(got) == (web, bot) and got.lowest == "" and got.bundles == ()


def test_a_game_sold_only_in_bundles_says_so_and_lists_them():
    got = view(look(BUNDLES_ONLY, bundles=[Bundle("bundle:1", "Hades + Hades II", 2, 25000)]))
    assert lines(got) == ("Отдельно не продаётся — только в бандлах", "только в бандлах")
    assert got.bundles == ("«Hades + Hades II» (2 игры) — ₪250",)


def test_a_discount_whose_end_has_come_is_the_old_full_price_until_the_next_check():
    over = look(price=Price(19530, 27900, 30, NOW - timedelta(minutes=1)))
    assert lines(view(over)) == ("Цена: ₪279", "₪279")
    assert price_rows.mark(over, NOW) == ""
    # the same moment: the end has come
    assert price_rows.mark(look(price=Price(19530, 27900, 30, NOW)), NOW) == ""
    assert price_rows.mark(look(price=Price(19530, 27900, 30, NOW + timedelta(minutes=1))), NOW) == "−30 %"


def test_the_end_of_a_discount_is_the_day_on_the_owners_clock():
    late = datetime(2026, 11, 12, 23, 30)  # 01:30 on the 13th in Israel
    assert view(look(price=Price(19530, 27900, 30, late))).line.endswith("до 13 ноября")


# --- the mark of the list ---------------------------------------------------------------------------------------------


def test_the_mark_is_the_percent_of_a_discount_going_and_nothing_else():
    assert price_rows.mark(look(price=Price(19530, 27900, 30, ENDS)), NOW) == "−30 %"
    assert price_rows.mark(look(price=Price(19530, 27900, 30)), NOW) == "−30 %"  # no end: going
    assert price_rows.mark(look(price=Price(0, 27900, 100, ENDS)), NOW) == "−100 %"
    assert price_rows.mark(look(price=Price(11095)), NOW) == ""
    assert price_rows.mark(look(FREE), NOW) == ""
    assert price_rows.mark(None, NOW) == ""


def test_a_look_of_another_number_or_country_is_no_look():
    state = look(price=Price(11095)).state()
    assert price_rows.current_look(state, APPID, "il") is not None
    assert price_rows.current_look(state, "1", "il") is None
    assert price_rows.current_look(state, APPID, "de") is None
    assert price_rows.current_look({}, APPID, "il") is None


# --- «самая низкая» ---------------------------------------------------------------------------------------------------


def record(final, seen_at, **own):
    return Record(seen_at, own.get("appid", APPID), own.get("country", "il"), own.get("currency", ILS), final)


def test_the_lowest_below_the_price_now_has_its_amount_and_day():
    history = [record(7767, datetime(2026, 9, 16, 10, 0)), record(11095, NOW)]
    got = view(look(price=Price(11095)), records=history)
    assert got.lowest == "Самая низкая с добавления: ₪77,67 (16 сентября 2026)"


def test_the_lowest_is_the_latest_record_with_the_lowest_price():
    history = [record(7767, datetime(2026, 9, 1, 10, 0)), record(9000, datetime(2026, 9, 5, 10, 0)),
               record(7767, datetime(2026, 10, 3, 22, 30))]  # 00:30 on the 4th in Israel
    assert view(look(price=Price(11095)), records=history).lowest == "Самая низкая с добавления: ₪77,67 (4 октября 2026)"


def test_the_price_now_is_the_lowest_during_a_discount_when_the_history_has_a_dearer_record():
    history = [record(27900, datetime(2026, 9, 1)), record(19530, NOW)]
    got = view(look(price=Price(19530, 27900, 30, ENDS)), records=history)
    assert got.lowest == "Сейчас — самая низкая цена с добавления"


@pytest.mark.parametrize(
    ("price", "history"),
    [
        (Price(19530, 27900, 30, ENDS), [record(19530, NOW)]),  # the only record: nothing dearer to be lower than
        (Price(11095), [record(11095, NOW)]),  # no discount: nothing to boast of
        (Price(11095), [record(7767, NOW, currency="{} zł")]),  # another currency does not count
        (Price(11095), [record(7767, NOW, country="de")]),
        (Price(11095), [record(7767, NOW, appid="1")]),
        (Price(11095), [record(30000, NOW)]),  # dearer: not the lowest
        (Price(11095), []),
    ],
)
def test_no_line_of_the_lowest(price, history):
    assert view(look(price=price), records=history).lowest == ""


def test_the_lowest_of_a_price_without_one_is_the_price_before_the_ended_discount():
    over = look(price=Price(19530, 27900, 30, NOW - timedelta(hours=1)))
    history = [record(27900, datetime(2026, 9, 1)), record(19530, datetime(2026, 11, 3))]
    assert view(over, records=history).lowest == "Самая низкая с добавления: ₪195,30 (3 ноября 2026)"


def test_only_a_price_has_the_lowest():
    assert view(look(FREE), records=[record(100, NOW)]).lowest == ""


# --- the bundles ------------------------------------------------------------------------------------------------------


def bundle(number, games=2, final=25000):
    return Bundle(f"bundle:{number}", f"Pack {number}", games, final)


def test_the_card_lists_five_bundles_and_counts_the_rest():
    many = [bundle(n, games=n + 1) for n in range(1, 9)]  # 2 … 9 games
    got = view(look(bundles=many))
    assert len(got.bundles) == 5 and got.more_bundles == "и ещё 3"
    assert got.bundles[0] == "«Pack 1» (2 игры) — ₪250" and got.bundles[4] == "«Pack 5» (6 игр) — ₪250"


def test_five_bundles_or_fewer_have_no_rest():
    got = view(look(bundles=[bundle(n) for n in range(1, 6)]))
    assert len(got.bundles) == 5 and got.more_bundles == ""
    assert view(look()).bundles == ()


@pytest.mark.parametrize(("games", "text"), [(2, "2 игры"), (5, "5 игр"), (21, "21 игра"), (11, "11 игр"), (22, "22 игры")])
def test_the_games_of_a_bundle_are_declined(games, text):
    assert view(look(bundles=[bundle(1, games)])).bundles == (f"«Pack 1» ({text}) — ₪250",)


def test_bundles_come_with_any_answer_that_has_them():
    got = view(look(price=Price(11095), bundles=[bundle(1)]))
    assert got.line == "Цена: ₪110,95" and got.bundles == ("«Pack 1» (2 игры) — ₪250",)


# --- the caption ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("observed", "text"),
    [
        (datetime(2026, 11, 9, 12, 5), "в 14:05"),
        (datetime(2026, 11, 8, 21, 10), "вчера в 23:10"),
        (datetime(2026, 10, 26, 7, 5), "26 окт в 09:05"),
    ],
)
def test_the_caption_names_the_country_and_when_the_prices_were_checked(observed, text):
    got = view(look(), observed_at=observed)
    assert got.caption == f"Цены для страны «Израиль» · проверено {text}"


def test_the_country_of_the_caption_is_the_one_of_the_stores():
    assert view(look(country="de"), country="de").caption.startswith("Цены для страны «Германия»")
