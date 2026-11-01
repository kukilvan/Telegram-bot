"""Steam adapter for prices: what Steam answered about each game becomes its price look (`PriceLook`), source `steam`.

Parsing is pure (records of `GetItems` in, looks out) and is tested on saved real answers; the network client
(`SteamProvider.store_items`) is passed in. Spec 3.2–3.3 of part 6.2.

The purchase options are read strictly, unlike the dates of a service's answer (rule 9 reads those softly): the
prices stand on them, so a missing field or garbage makes the answer about that game unreadable (`UnreadAnswer`, a
failure of that game), never «no price» — a renamed field of Steam shows at once. The other games of the same answer
are read as usual.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from app.providers.steam import SteamProvider
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
    currency_of,
)
from app.tracker.sources.dates import response_moment_of_timestamp

SOURCE_KEY = "steam"

SOLD = 1  # `success` of a record: Steam knows the app in this country
NOT_HERE = 15  # Steam does not know the app here: not sold in the country, or no such app


class UnreadAnswer(ValueError):
    """Steam answered, but not so that the answer about a game can be read; the text names what (for the log). It has
    no status and no cause, so `failures.reason_of` tells the owner «неизвестная ошибка»."""


@dataclass(frozen=True)
class _Option:
    """One purchase option, read strictly."""

    record: dict[str, Any]
    name: str
    final: int
    formatted: str
    games: int
    subscription: bool

    @property
    def one_game(self) -> bool:
        return self.games == 1 and not self.subscription

    @property
    def bundle(self) -> bool:
        return self.games >= 2 and not self.subscription


class SteamPriceSource:
    """Asks Steam about the prices of games; the client comes from outside."""

    def __init__(self, steam: SteamProvider) -> None:
        self.steam = steam

    async def price_looks(self, appids: Sequence[str], country: str) -> dict[str, PriceLook | UnreadAnswer]:
        """What Steam answered about each of `appids` (at most 100, `MAX_ITEMS`) in the store of `country`. A number
        that is no number of digits is `unknown_app` without asking. A failure of the whole request is `SteamError`."""
        asked = list(dict.fromkeys(appid for appid in appids if _is_number(appid)))
        items = await self.steam.store_items(asked, country) if asked else []
        return parse_items(items, appids, country)


def parse_items(items: Iterable[dict[str, Any]], appids: Sequence[str], country: str) -> dict[str, PriceLook | UnreadAnswer]:
    """The look of each of `appids` by the records `items` of one answer of `GetItems` (matched by `appid`, else by
    `id`), or `UnreadAnswer` for a game whose record is missing or cannot be read."""
    by_number = {}
    for item in items:
        number = item.get("appid") or item.get("id")
        if number is not None:
            by_number.setdefault(str(number), item)
    looks: dict[str, PriceLook | UnreadAnswer] = {}
    for appid in appids:
        if not _is_number(appid):
            looks[appid] = PriceLook(appid, country, UNKNOWN_APP)
        elif appid not in by_number:
            looks[appid] = UnreadAnswer(f"Steam app {appid}: no record in the answer")
        else:
            try:
                looks[appid] = parse_item(by_number[appid], appid, country)
            except ValueError as exc:
                looks[appid] = UnreadAnswer(f"Steam app {appid}: {exc}")
    return looks


def parse_item(item: dict[str, Any], appid: str, country: str) -> PriceLook:
    """The look of one record of `GetItems` (spec 3.2); a ValueError when it cannot be read."""
    success = item.get("success")
    if success == NOT_HERE:
        answer = NOT_IN_COUNTRY if item.get("unvailable_for_country_restriction") is True else UNKNOWN_APP
        return PriceLook(appid, country, answer)
    if success != SOLD or isinstance(success, bool):
        raise ValueError(f"success is {success!r}")
    options = _options(item)
    bundles = tuple(_bundle(option) for option in options if option.bundle)
    one_game = [option for option in options if option.one_game]
    if item.get("is_free") is True:
        answer, price, written = FREE, None, None
    elif one_game:
        cheapest = min(one_game, key=lambda option: option.final)  # min keeps the first of equal ones
        edition = None if cheapest is one_game[0] else cheapest.name
        price = _price(cheapest, preorder=item.get("is_coming_soon") is True, edition=edition)
        answer, written = PRICE, cheapest.formatted
    else:
        answer = COMING_SOON if item.get("is_coming_soon") is True else BUNDLES_ONLY if bundles else NOT_SOLD
        price, written = None, None
    if written is None and bundles:
        written = next(option.formatted for option in options if option.bundle)
    currency = None if written is None else currency_of(written)
    return PriceLook(appid, country, answer, currency, price, bundles)


def _options(item: dict[str, Any]) -> list[_Option]:
    raw = item.get("purchase_options", [])
    if not isinstance(raw, list):
        raise ValueError(f"purchase_options is no list: {raw!r}")
    options = []
    for record in raw:
        if not isinstance(record, dict):
            raise ValueError(f"a purchase option is no record: {record!r}")
        options.append(_Option(
            record=record,
            name=record.get("purchase_option_name"),
            final=_cents(record, "final_price_in_cents"),
            formatted=_written(record, "formatted_final_price"),
            games=_whole(record, "included_game_count"),
            subscription="recurrence_info" in record,
        ))
    for option in options:
        if (option.one_game or option.bundle) and not isinstance(option.name, str):
            raise ValueError(f"purchase_option_name is {option.name!r}")
    return options


def _price(option: _Option, *, preorder: bool, edition: str | None) -> Price:
    """The price of the game by its purchase option: a discount only when Steam shows one (a percent and a higher
    price before it; Poland shows neither), its end the earliest of `active_discounts`."""
    record = option.record
    pct = _whole(record, "discount_pct") if "discount_pct" in record else 0
    if pct == 0:
        return Price(option.final, preorder=preorder, edition=edition)
    original = _cents(record, "original_price_in_cents")
    if original <= option.final:
        return Price(option.final, preorder=preorder, edition=edition)
    discounts = record.get("active_discounts", [])
    if not isinstance(discounts, list) or not all(isinstance(d, dict) for d in discounts):
        raise ValueError(f"active_discounts is no list of records: {discounts!r}")
    ends = [response_moment_of_timestamp(d.get("discount_end_date")) for d in discounts]
    if None in ends:
        raise ValueError(f"a discount_end_date is no Unix time: {discounts!r}")
    return Price(option.final, original, pct, min(ends, default=None), preorder, edition)


def _bundle(option: _Option) -> Bundle:
    record = option.record
    if "bundleid" in record:
        number = f"bundle:{_whole(record, 'bundleid')}"
    elif "packageid" in record:
        number = f"package:{_whole(record, 'packageid')}"
    else:
        raise ValueError(f"a bundle has neither bundleid nor packageid: {option.name!r}")
    return Bundle(number, option.name, option.games, option.final)


def _is_number(text: str) -> bool:
    """A Steam number or amount: ASCII digits only («٣» is a decimal digit too, but no number of Steam)."""
    return text.isascii() and text.isdecimal()


def _cents(record: dict[str, Any], field: str) -> int:
    """An amount in hundredths: Steam writes it as a text of digits (a whole number is taken too)."""
    value = record.get(field)
    if isinstance(value, str) and _is_number(value):
        return int(value)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    raise ValueError(f"{field} is {value!r}")


def _written(record: dict[str, Any], field: str) -> str:
    """A price as Steam writes it: a text with one number in it (`currency_of`)."""
    value = record.get(field)
    try:
        currency_of(value)
    except ValueError as exc:
        raise ValueError(f"{field}: {exc}") from exc
    return value


def _whole(record: dict[str, Any], field: str) -> int:
    value = record.get(field)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    raise ValueError(f"{field} is {value!r}")
