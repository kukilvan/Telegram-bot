"""What the owner reads of the Steam prices of a game: the block of the card, the line of the bot and the mark of the list.

Pure: no database, no network, no clock (spec 6 of part 6.2). The caller says what the snapshot of prices holds, the
records of the price history, the moment now and the owner's time zone. A look counts only when it asks about the game's
Steam number and the store country of now; a discount whose end has come, with no new check yet, is over (spec 6.1).
"""

from collections.abc import Collection
from datetime import date, datetime, timezone, tzinfo
from typing import Any

from app.tracker.cards import SteamView, format_date, format_past_moment, games_word, local_moment
from app.tracker.platforms import STORE_COUNTRIES
from app.tracker.prices import (
    BUNDLES_ONLY, COMING_SOON, FREE, FREE_PCT, NOT_IN_COUNTRY, NOT_SOLD, UNKNOWN_APP, Money, Price, PriceLook,
    PricedRecord, comparable, edition_note, lowest, percent, until,
)

BUNDLES_SHOWN = 5  # the card lists the first ones; the rest is «и ещё 3»

NO_PAGE = ("Страницы в Steam пока нет — придёт сообщение, когда появится", "страницы пока нет")
NOT_CHECKED = ("Цену ещё не проверяли — она появится через минуту-другую", "ещё не проверяли")
# the answers of Steam with no price to write: the line of the web and the one of the bot (table 6.1)
_NO_PRICE = {
    FREE: ("Бесплатная игра", "бесплатная игра"),
    COMING_SOON: ("Ещё не продаётся — скоро выйдет", "ещё не продаётся (скоро выйдет)"),
    BUNDLES_ONLY: ("Отдельно не продаётся — только в бандлах", "только в бандлах"),
    NOT_SOLD: ("Сейчас в Steam не продаётся", "не продаётся"),
    NOT_IN_COUNTRY: ("В Steam в вашей стране не продаётся", "в вашей стране не продаётся"),
    UNKNOWN_APP: (
        "Steam не знает игру с номером из IGDB — ссылка «Открыть в Steam» может не работать",
        "номер из IGDB неверный",
    ),
}


def current_look(state: Any, steam_id: str, country: str) -> PriceLook | None:
    """The look a snapshot of prices keeps, when it asked about this Steam number in this country; None — nothing was
    looked at yet, or the look is of another number or country (changed since, the next check comes within a minute)."""
    look = PriceLook.from_state(state)
    return look if look is not None and look.is_of(steam_id, country) else None


def shown_price(price: Price, now: datetime) -> Price:
    """The price as it reads now (`now`: naive UTC): a discount whose end has come is over, the price is the one before it."""
    if price.discounted and price.ends_at is not None and price.ends_at <= now:
        return Price(final=price.original or 0, preorder=price.preorder, edition=price.edition)
    return price


def mark(look: PriceLook | None, now: datetime) -> str:
    """The mark of the row of the list: «−30 %» while a discount goes («−100 %» of a giveaway); empty — none."""
    if look is None or look.price is None:
        return ""
    price = shown_price(look.price, now)
    return percent(price.pct) if price.discounted else ""


def _web_line(price: Price, currency: str, ends_on: date | None) -> str:
    final = Money(price.final, currency)
    edition = edition_note(price.edition)
    if not price.discounted:
        return f"{'Предзаказ' if price.preorder else 'Цена'}: {final}{edition}"
    original = Money(price.original or 0, currency)
    if price.pct == FREE_PCT:
        return f"Раздают бесплатно{until(ends_on)} (обычно {original}){edition}"
    head = "Предзаказ со скидкой" if price.preorder else "Скидка"
    return f"{head} {percent(price.pct)}: {original} → {final}{until(ends_on, comma=True)}{edition}"


def _bot_line(price: Price, currency: str, ends_on: date | None) -> str:
    final = Money(price.final, currency)
    if not price.discounted:
        return f"предзаказ {final}" if price.preorder else str(final)
    if price.pct == FREE_PCT:
        return f"бесплатно{until(ends_on)} (обычно {Money(price.original or 0, currency)})"
    inside = (["предзаказ"] if price.preorder else []) + [f"{percent(price.pct)}{until(ends_on)}"]
    return f"{final} ({', '.join(inside)})"


def _lowest_line(records: Collection[PricedRecord], look: PriceLook, price: Price, tz: tzinfo) -> str:
    """«Самая низкая с добавления» (spec 6.1): lower than the price now — its amount and day; the price now is the
    lowest, in a discount, and the history has a dearer record — «Сейчас — самая низкая…»; else nothing."""
    if look.currency is None:
        return ""
    found = lowest(records, look.appid, look.country, look.currency)
    if found is None:
        return ""
    if found.money.cents < price.final:
        return f"Самая низкая с добавления: {found.money} ({format_date(local_moment(found.seen_at, tz).date())})"
    same = comparable(records, look.appid, look.country, look.currency)
    if price.discounted and found.money.cents == price.final and any(r.final > price.final for r in same):
        return "Сейчас — самая низкая цена с добавления"
    return ""


def _bundle_lines(look: PriceLook) -> tuple[tuple[str, ...], str]:
    lines = tuple(
        f"«{bundle.name}» ({games_word(bundle.games)}) — {look.money(bundle.final)}" for bundle in look.bundles[:BUNDLES_SHOWN]
    )
    rest = len(look.bundles) - BUNDLES_SHOWN
    return lines, f"и ещё {rest}" if rest > 0 else ""


def steam_view(
    country: str,
    steam_id: str | None,
    look: PriceLook | None,
    observed_at: datetime | None,
    records: Collection[PricedRecord],
    now: datetime,
    tz: tzinfo,
) -> SteamView:
    """The block of Steam of a game for the card. `steam_id` None: the game has no page yet; `look` None: no price was
    looked at yet (`current_look`); `observed_at` (naive UTC) is when it was. `records`: the price history of the game."""
    caption = f"Цены для страны «{STORE_COUNTRIES[country].label}»"
    if steam_id is None:
        return SteamView(caption, *NO_PAGE)
    if look is None:
        return SteamView(caption, *NOT_CHECKED)
    if observed_at is not None:
        owner_now = now.replace(tzinfo=timezone.utc).astimezone(tz)
        caption += f" · проверено {format_past_moment(observed_at.replace(tzinfo=timezone.utc), owner_now)}"
    bundles, more = _bundle_lines(look)
    price = look.price
    if price is None:
        web, bot = _NO_PRICE.get(look.answer, NOT_CHECKED)
        return SteamView(caption, web, bot, "", bundles, more)
    price = shown_price(price, now)
    ends_on = local_moment(price.ends_at, tz).date() if price.ends_at is not None else None
    currency = look.currency or ""
    return SteamView(
        caption, _web_line(price, currency, ends_on), _bot_line(price, currency, ends_on),
        _lowest_line(records, look, price, tz), bundles, more,
    )
