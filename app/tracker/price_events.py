"""The events of Steam (pure): a discount and a bundle from two price looks, the page in Steam, texts, keys, folding.

A discount and a bundle are found by comparing two price looks of a game, the page in Steam by the IGDB check; the
samples of «Тестовое событие» are here too (spec 5 of part 6.2).

Pure: no database, no network, no clock. The caller says when the check is (`now`), the owner's time zone, the lowest
price before this check and the moment of the previous look; the reference point (`game_prices.is_baseline`) is the
caller's too: then there is nothing to compare. A discount is told when it starts, when the next sale starts (the end
of the previous one has come) or when it gets deeper; an extension, a smaller percent, the end of a discount or a
change of the price without one are silent. The game's price is the cheapest option with one game (`prices.Price`), so
a discount on a bundle or on an edition dearer than the game is not one. Several discounts that go out at once in
messages of their own become one message («🎮 Скидки в Steam:», `folded_messages`); a summary and «Недавно» keep a
line each.
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, tzinfo
from typing import Any

from app.tracker.cards import format_day_month, local_moment
from app.tracker.dedup import moved_key
from app.tracker.kinds import KINDS
from app.tracker.models import TitleKind
from app.tracker.movie_events import DetectedEvent
from app.tracker.prices import Bundle, Lowest, Money, Price, PriceLook, percent

_ICON = KINDS[TitleKind.GAME].icon

DISCOUNT = "game_discount"
BUNDLE = "game_bundle"
STEAM_PAGE = "game_steam_page"
TYPES = (DISCOUNT, BUNDLE, STEAM_PAGE)  # the one list of the types of the events of Steam

LOWEST_LINE = "Самая низкая цена с тех пор, как игра в списке"
FOLDED_HEADER = f"{_ICON} Скидки в Steam:"
_FREE_PCT = 100


def store_url(steam_id: str) -> str:
    """The page of the game in the Steam store."""
    return f"https://store.steampowered.com/app/{steam_id}/"


def games_word(count: int) -> str:
    """«2 игры», «5 игр», «21 игра»: the number of games of a bundle (as `cards.titles_word`)."""
    if count % 10 == 1 and count % 100 != 11:
        return f"{count} игра"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return f"{count} игры"
    return f"{count} игр"


# --- texts ----------------------------------------------------------------------------------------------------------


def _until(ends_on: date | None) -> str:
    return f" до {format_day_month(ends_on)}" if ends_on is not None else ""


def _edition(edition: str | None) -> str:
    return f" («{edition}»)" if edition else ""


def discount_text(name: str, price: Price, currency: str, ends_on: date | None, lowest: bool) -> str:
    """«🎮 Resident Evil Requiem: скидка −30 % в Steam — ₪279 → ₪195,30, до 3 ноября» (spec 5.2); 100 % — «в Steam
    раздают бесплатно до 3 ноября (обычно ₪279)»; a preorder says so after the percent, an edition ends the line in
    brackets, the lowest price is the second line. `ends_on` is the last day on the owner's clock, None — unknown."""
    original = Money(price.original or 0, currency)
    if price.pct == _FREE_PCT:
        head = f"{_ICON} {name}: в Steam раздают бесплатно{_until(ends_on)} (обычно {original})"
    else:
        preorder = " на предзаказ" if price.preorder else ""
        until = f", до {format_day_month(ends_on)}" if ends_on is not None else ""
        head = (
            f"{_ICON} {name}: скидка {percent(price.pct)}{preorder} в Steam — "
            f"{original} → {Money(price.final, currency)}{until}"
        )
    head += _edition(price.edition)
    return f"{head}\n{LOWEST_LINE}" if lowest else head


def discount_line(name: str, price: Price, currency: str, ends_on: date | None, lowest: bool) -> str:
    """The line of a discount in the folded message (spec 5.4): «Hades II — −20 %, ₪110,95 → ₪88,76, до 5 ноября,
    самая низкая с добавления»; «Elden Ring — раздают бесплатно до 5 ноября»."""
    if price.pct == _FREE_PCT:
        line = f"{name} — раздают бесплатно{_until(ends_on)}"
    else:
        preorder = " на предзаказ" if price.preorder else ""
        until = f", до {format_day_month(ends_on)}" if ends_on is not None else ""
        line = f"{name} — {percent(price.pct)}{preorder}, {Money(price.original or 0, currency)} → {Money(price.final, currency)}{until}"
    line += _edition(price.edition)
    return f"{line}, самая низкая с добавления" if lowest else line


def bundle_text(name: str, bundle: Bundle, currency: str) -> str:
    """«🎮 Hades II продаётся в бандле «Hades + Hades II» (2 игры) — ₪250»."""
    return f"{_ICON} {name} продаётся в бандле «{bundle.name}» ({games_word(bundle.games)}) — {Money(bundle.final, currency)}"


def steam_page_text(name: str) -> str:
    return f"{_ICON} {name}: появилась страница в Steam"


def discount_payload(
    name: str, steam_id: str, price: Price, currency: str, ends_on: date | None, lowest: bool
) -> dict[str, Any]:
    """The payload of a discount with its text and its line of the folded message (spec 5.3), without `expires_at`."""
    return {
        "text": discount_text(name, price, currency, ends_on, lowest), "name": name, "steam_id": steam_id,
        "pct": price.pct, "final": price.final, "original": price.original, "currency": currency,
        "ends_at": price.ends_at.isoformat() if price.ends_at is not None else None, "lowest": lowest,
        "edition": price.edition, "preorder": price.preorder, "line": discount_line(name, price, currency, ends_on, lowest),
    }


def bundle_payload(name: str, steam_id: str, bundle: Bundle, currency: str) -> dict[str, Any]:
    return {
        "text": bundle_text(name, bundle, currency), "name": name, "steam_id": steam_id, "bundle": bundle.name,
        "games": bundle.games, "final": bundle.final, "currency": currency,
    }


# --- detection ------------------------------------------------------------------------------------------------------


def _new_discount(old: PriceLook, new: Price, now: datetime) -> bool:
    before = old.price
    if before is None or not before.discounted:
        return True  # it started (or the game came out with a discount)
    if before.ends_at is not None and before.ends_at <= now:
        return True  # the previous sale is over: this is the next one
    return new.pct > before.pct  # deeper in the same sale; the same or smaller, or another end, is silent


def detect_events(
    title_id: int,
    name: str,
    old: PriceLook,
    new: PriceLook,
    now: datetime,
    tz: tzinfo | None,
    lowest: Lowest | None,
    previous_look: datetime,
) -> list[DetectedEvent]:
    """The events between the previous look (taken at `previous_look`) and the new one (taken `now`) of a game that is
    not at its reference point. `lowest` is «самая низкая» by the history before this check; the discount is the
    lowest when it costs no more than it (and there is a record of the same currency)."""
    events: list[DetectedEvent] = []
    price = new.price
    if price is not None and price.discounted and new.currency is not None and _new_discount(old, price, now):
        ends_on = local_moment(price.ends_at, tz).date() if price.ends_at is not None else None
        is_lowest = lowest is not None and lowest.money.currency == new.currency and price.final <= lowest.money.cents
        key = f"game:{title_id}:discount:{price.pct}"
        key = f"{key}:{price.ends_at.isoformat()}" if price.ends_at is not None else moved_key(f"{key}:none", previous_look)
        payload = discount_payload(name, new.appid, price, new.currency, ends_on, is_lowest)
        # the message is old once the discount is over (spec 5.6)
        data = {**payload, "expires_at": payload["ends_at"]}
        events.append(DetectedEvent(DISCOUNT, key, data.pop("text"), data))
    known = {bundle.id for bundle in old.bundles}
    for bundle in new.bundles:
        if bundle.id in known or new.currency is None:
            continue
        data = bundle_payload(name, new.appid, bundle, new.currency)
        events.append(DetectedEvent(BUNDLE, f"game:{title_id}:bundle:{bundle.id}", data.pop("text"), data))
    return events


def steam_page_event(title_id: int, name: str, steam_id: str) -> DetectedEvent:
    """«Появилась страница в Steam»: IGDB gave the Steam number of a game whose prices are checked now (spec 5.1); the
    caller decides that the previous IGDB look had none. Once a game."""
    return DetectedEvent(
        STEAM_PAGE, f"game:{title_id}:steam_page", steam_page_text(name), {"name": name, "steam_id": steam_id}
    )


# --- folding --------------------------------------------------------------------------------------------------------


def foldable(event_type: str, data: Mapping[str, Any]) -> bool:
    """A discount that folds with the others of its sending (it has its line); a sample of the old format does not."""
    return event_type == DISCOUNT and "line" in data and "steam_id" in data


def folded_messages(members: Sequence[Mapping[str, Any]], limit: int) -> list[tuple[str, list[int]]]:
    """The folded message of the discounts (their payloads, in queue order) and the members each part holds: a text
    longer than `limit` is split by lines, each part with the header; a sample keeps the words it starts with."""
    header = members[0].get("prefix", "") + FOLDED_HEADER
    parts: list[tuple[str, list[int]]] = []
    lines: list[str] = []
    held: list[int] = []
    size = len(header)
    for number, data in enumerate(members):
        line = data["line"]
        if held and size + len(line) + 1 > limit:
            parts.append(("\n".join([header, *lines]), held))
            lines, held, size = [], [], len(header)
        lines.append(line)
        held.append(number)
        size += len(line) + 1
    parts.append(("\n".join([header, *lines]), held))
    return parts


# --- «Тестовое событие» (spec 5.7) ----------------------------------------------------------------------------------

_SAMPLE_GAME = ("Resident Evil Requiem", "3764200")  # the buttons of the samples open the page of a real game
_SAMPLE_CURRENCY = "₪{}"
_SAMPLE_END = date(2026, 11, 3)


def _sample_discount(name: str, steam_id: str, price: Price, lowest: bool) -> tuple[str, dict[str, Any]]:
    """A discount as a real event would have it, without `expires_at`: a sample never gets old."""
    return DISCOUNT, discount_payload(name, steam_id, price, _SAMPLE_CURRENCY, _SAMPLE_END, lowest)


def _sample_bundle() -> tuple[str, dict[str, Any]]:
    bundle = Bundle("bundle:1", "Resident Evil Requiem + Village", 2, 25000)
    return BUNDLE, bundle_payload(*_SAMPLE_GAME, bundle, _SAMPLE_CURRENCY)


def _sample_page() -> tuple[str, dict[str, Any]]:
    name, steam_id = _SAMPLE_GAME
    return STEAM_PAGE, {"text": steam_page_text(name), "name": name, "steam_id": steam_id}


def _sample_many() -> list[tuple[str, dict[str, Any]]]:
    return [
        _sample_discount(*_SAMPLE_GAME, Price(19530, 27900, 30), False),
        _sample_discount("Hades II", "1145350", Price(8876, 11095, 20), True),
        _sample_discount("Elden Ring", "1245620", Price(0, 19900, 100), False),
    ]


# (id, menu label, the events of the sample: type and payload each) — the samples are events of Steam, not «test», so
# that their buttons open Steam as the real ones do
TEST_SAMPLES: list[tuple[str, str, Any]] = [
    ("steam-discount", "Игра: скидка в Steam", lambda: [_sample_discount(*_SAMPLE_GAME, Price(19530, 27900, 30), True)]),
    ("steam-free", "Игра: раздают бесплатно в Steam", lambda: [_sample_discount(*_SAMPLE_GAME, Price(0, 27900, 100), False)]),
    ("steam-bundle", "Игра: бандл в Steam", lambda: [_sample_bundle()]),
    ("steam-page", "Игра: страница в Steam", lambda: [_sample_page()]),
    ("steam-many", "Игра: скидки на несколько игр", _sample_many),
]


def steam_ids(members: Iterable[Mapping[str, Any]]) -> list[tuple[str, str]]:
    """(name, Steam number) of the games of folded discounts, in the order of their lines, each game once."""
    seen: dict[str, str] = {}
    for data in members:
        seen.setdefault(data["steam_id"], data["name"])
    return [(name, steam_id) for steam_id, name in seen.items()]
