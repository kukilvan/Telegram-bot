"""Steam prices of a game: what one price check saw (`PriceLook`), an amount of money (`Money`) and «самая низкая с добавления».

Pure: no database, no network, no clock (spec 3.4, 3.5 and 4.5 of part 6.2). The look is the state of the snapshot of
source `steam`; it is read back strictly (rule 9): garbage there is a bug, so it raises. Money is kept in hundredths
with the currency as Steam writes a price («₪{}», «{}₴», «{} руб»): Steam gives no currency code.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

from app.tracker.cards import format_day_month
from app.tracker.sources.dates import parse_moment

# What Steam answered about a game: the `answer` of a look (spec 3.2), in the order the adapter tries them
NOT_IN_COUNTRY = "not_in_country"
UNKNOWN_APP = "unknown_app"
FREE = "free"
PRICE = "price"
COMING_SOON = "coming_soon"
BUNDLES_ONLY = "bundles_only"
NOT_SOLD = "not_sold"
ANSWERS = (NOT_IN_COUNTRY, UNKNOWN_APP, FREE, PRICE, COMING_SOON, BUNDLES_ONLY, NOT_SOLD)
_NO_BUNDLES = (NOT_IN_COUNTRY, UNKNOWN_APP, NOT_SOLD)  # Steam gives no purchase options with these

NBSP = " "
MINUS = "−"
FREE_TEXT = "бесплатно"
SLOT = "{}"  # where the amount stands in a currency
FREE_PCT = 100  # a discount of 100 % is a giveaway: «раздают бесплатно»

_NUMBER_INSIDE = re.compile(r"[\d\s.,]*")
_COUNTRY = re.compile(r"[a-z]{2}")
_BUNDLE_ID = re.compile(r"(bundle|package):\d+")


def currency_of(formatted: Any) -> str:
    """The currency of a price as Steam writes it: the number in it becomes `{}` — «₪179.95» → «₪{}», «1 349,00₴» →
    «{}₴», «117,00 zł» → «{} zł». The number runs from the first digit to the last, with spaces, dots and commas
    inside; a text without a digit, or with anything else between the digits, is a ValueError."""
    if not isinstance(formatted, str):
        raise ValueError(f"a price written by Steam is no text: {formatted!r}")
    digits = [i for i, char in enumerate(formatted) if char.isdigit()]
    if not digits:
        raise ValueError(f"a price written by Steam has no digit: {formatted!r}")
    first, last = digits[0], digits[-1] + 1
    if not _NUMBER_INSIDE.fullmatch(formatted[first:last]) or SLOT in formatted:
        raise ValueError(f"a price written by Steam has no one number in it: {formatted!r}")
    return formatted[:first] + SLOT + formatted[last:]


@dataclass(frozen=True)
class Money:
    """An amount in hundredths and its currency (`currency_of`). Reads as the owner reads it: «₪195,30», «1 349₴»,
    «1 100 руб» (groups of three digits from 1 000, a no-break space between them), «,00» left out, zero «бесплатно»."""

    cents: int
    currency: str

    def __str__(self) -> str:
        if self.cents == 0:
            return FREE_TEXT
        whole, part = divmod(self.cents, 100)
        amount = f"{whole:,}".replace(",", NBSP) + (f",{part:02d}" if part else "")
        return self.currency.replace(SLOT, amount)


def percent(pct: int) -> str:
    """A discount as the owner reads it: «−30 %» (the minus sign U+2212, a no-break space before «%»)."""
    return f"{MINUS}{pct}{NBSP}%"


def until(ends_on: date | None, *, comma: bool = False) -> str:
    """« до 3 ноября» (with `comma`, after the amounts: «, до 3 ноября»): the last day of a discount on the owner's
    clock; empty when Steam does not say."""
    if ends_on is None:
        return ""
    return f"{',' if comma else ''} до {format_day_month(ends_on)}"


def edition_note(edition: str | None) -> str:
    """« («Resident Evil Requiem Deluxe Edition»)» after a price that is an edition's; empty for the game itself."""
    return f" («{edition}»)" if edition else ""


@dataclass(frozen=True)
class Price:
    """The price of a game: the cheapest purchase option with one game (spec 3.3). `original` is the price before the
    discount and None without one; `ends_at` the end of the discount (naive UTC), None when Steam does not say;
    `edition` the name of the edition when its price is the game's price."""

    final: int
    original: int | None = None
    pct: int = 0
    ends_at: datetime | None = None
    preorder: bool = False
    edition: str | None = None

    def __post_init__(self) -> None:
        _count(self.final, "price.final")
        if self.original is None:
            if self.pct != 0 or self.ends_at is not None:
                raise ValueError(f"a price without a discount has its percent or its end: {self}")
        elif not (_count(self.original, "price.original") > self.final and 0 < _count(self.pct, "price.pct") <= 100):
            raise ValueError(f"a discount is no lower price with a percent: {self}")
        if self.ends_at is not None and (not isinstance(self.ends_at, datetime) or self.ends_at.tzinfo is not None):
            raise ValueError(f"the end of a discount is no naive moment: {self.ends_at!r}")
        if not isinstance(self.preorder, bool):
            raise ValueError(f"price.preorder is no yes or no: {self.preorder!r}")
        if self.edition is not None:
            _text(self.edition, "price.edition")

    @property
    def discounted(self) -> bool:
        return self.original is not None


@dataclass(frozen=True)
class Bundle:
    """A purchase option with two games or more, not a subscription (`CONTEXT.md`, «Бандл»): `bundle:<bundleid>` or
    `package:<packageid>`, its name, how many games and its price as it is."""

    id: str
    name: str
    games: int
    final: int

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not _BUNDLE_ID.fullmatch(self.id):
            raise ValueError(f"no number of a bundle: {self.id!r}")
        if not isinstance(self.name, str):
            raise ValueError(f"the name of a bundle is no text: {self.name!r}")
        if _count(self.games, "bundle.games") < 2:
            raise ValueError(f"a bundle of fewer than two games: {self.games}")
        _count(self.final, "bundle.final")


_LOOK_KEYS = {"appid", "country", "answer", "currency", "price", "bundles"}
_PRICE_KEYS = {"final", "original", "pct", "ends_at", "preorder", "edition"}
_BUNDLE_KEYS = {"id", "name", "games", "final"}


@dataclass(frozen=True)
class PriceLook:
    """What one price check saw of a game (spec 3.5): the Steam number it asked about, the store country of that
    moment, what Steam answered, the currency (None when there is nothing to write), the price (only with the answer
    `price`) and the bundles in the order of Steam."""

    appid: str
    country: str
    answer: str
    currency: str | None = None
    price: Price | None = None
    bundles: tuple[Bundle, ...] = ()

    def __post_init__(self) -> None:
        _text(self.appid, "appid")
        if not isinstance(self.country, str) or not _COUNTRY.fullmatch(self.country):
            raise ValueError(f"no store country: {self.country!r}")
        if self.answer not in ANSWERS:
            raise ValueError(f"no answer of Steam: {self.answer!r}")
        if (self.price is not None) != (self.answer == PRICE):
            raise ValueError(f"a price goes with the answer {PRICE!r} only: {self.answer!r}, {self.price}")
        if (self.answer in _NO_BUNDLES and self.bundles) or (self.answer == BUNDLES_ONLY and not self.bundles):
            raise ValueError(f"the answer {self.answer!r} with {len(self.bundles)} bundles")
        if (self.currency is not None) != (self.price is not None or bool(self.bundles)):
            raise ValueError(f"a currency goes with a price or a bundle only: {self.currency!r}")
        if self.currency is not None and (not isinstance(self.currency, str) or self.currency.count(SLOT) != 1):
            raise ValueError(f"no currency: {self.currency!r}")

    def is_of(self, appid: str, country: str) -> bool:
        """The look asked about this Steam number in this store country: a look of another one says nothing of now."""
        return (self.appid, self.country) == (appid, country)

    def money(self, cents: int) -> Money:
        """An amount of this look in its currency (a look with a price or a bundle has one)."""
        if self.currency is None:
            raise ValueError(f"a look with the answer {self.answer!r} has no currency")
        return Money(cents, self.currency)

    def state(self) -> dict[str, Any]:
        """The state of the snapshot of source `steam`; `from_state` reads it back."""
        price = self.price
        return {
            "appid": self.appid,
            "country": self.country,
            "answer": self.answer,
            "currency": self.currency,
            "price": None if price is None else {
                "final": price.final,
                "original": price.original,
                "pct": price.pct,
                "ends_at": None if price.ends_at is None else price.ends_at.isoformat(),
                "preorder": price.preorder,
                "edition": price.edition,
            },
            "bundles": [
                {"id": bundle.id, "name": bundle.name, "games": bundle.games, "final": bundle.final}
                for bundle in self.bundles
            ],
        }

    @classmethod
    def from_state(cls, state: Any) -> "PriceLook | None":
        """The look a snapshot keeps; None for the empty state `{}` (prices not looked at yet). Strict: a missing,
        extra or wrong field is a ValueError."""
        if state == {}:
            return None
        _fields(state, _LOOK_KEYS, "price look")
        raw_price, raw_bundles = state["price"], state["bundles"]
        if not isinstance(raw_bundles, list):
            raise ValueError(f"the bundles of a price look are no list: {raw_bundles!r}")
        price = None
        if raw_price is not None:
            _fields(raw_price, _PRICE_KEYS, "price")
            ends_at = raw_price["ends_at"]
            if ends_at is not None and not isinstance(ends_at, str):
                raise ValueError(f"the end of a discount is no text: {ends_at!r}")
            price = Price(
                final=raw_price["final"],
                original=raw_price["original"],
                pct=raw_price["pct"],
                ends_at=parse_moment(ends_at),
                preorder=raw_price["preorder"],
                edition=raw_price["edition"],
            )
        bundles = []
        for raw in raw_bundles:
            _fields(raw, _BUNDLE_KEYS, "bundle")
            bundles.append(Bundle(id=raw["id"], name=raw["name"], games=raw["games"], final=raw["final"]))
        return cls(
            appid=state["appid"],
            country=state["country"],
            answer=state["answer"],
            currency=state["currency"],
            price=price,
            bundles=tuple(bundles),
        )


class PricedRecord(Protocol):
    """What «самая низкая» reads of a record of the price history (`PriceRecord` of the database, ticket 03)."""

    seen_at: datetime
    appid: str
    country: str
    currency: str
    final: int


@dataclass(frozen=True)
class Lowest:
    """«Самая низкая с добавления»: the amount and the moment (naive UTC) of the latest record with it."""

    money: Money
    seen_at: datetime


def comparable(records: Iterable[PricedRecord], appid: str, country: str, currency: str) -> list[PricedRecord]:
    """The records of the price history that compare with a price of this Steam number, store country and currency
    (spec 4.5): the records of another one do not count."""
    return [r for r in records if (r.appid, r.country, r.currency) == (appid, country, currency)]


def lowest(records: Iterable[PricedRecord], appid: str, country: str, currency: str) -> Lowest | None:
    """The lowest price among the `comparable` records; the moment is of the latest record with that price. No such
    records — None."""
    same = comparable(records, appid, country, currency)
    if not same:
        return None
    cheapest = min(r.final for r in same)
    seen_at = max(r.seen_at for r in same if r.final == cheapest)
    return Lowest(Money(cheapest, currency), seen_at)


def _fields(raw: Any, keys: set[str], what: str) -> None:
    if not isinstance(raw, dict) or set(raw) != keys:
        raise ValueError(f"a {what} with other fields: {raw!r}")


def _count(value: Any, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{what} is no whole number of 0 or more: {value!r}")
    return value


def _text(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{what} is no text: {value!r}")
    return value
