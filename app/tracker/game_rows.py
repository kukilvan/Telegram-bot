"""What the owner reads of a game: the lines of its platforms on the card, the date outside the country, the links to the stores, the pieces of the feed.

Pure: no database, no network. The dates are the ones of `games` for the country of the stores, which comes as a
parameter with «Мои платформы» and the marks «играю здесь» (rule 2 of `docs/coding-standards.md`); everything that
depends on a platform or a country is read from the tables of `platforms` (rule 6).
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import date
from urllib.parse import quote

from app.tracker.cards import PlatformRow, StoreLink
from app.tracker.feed_rows import FeedTitle, Piece
from app.tracker.game_events import older_tells, platforms_text
from app.tracker.games import (
    FULL, NOT_ANNOUNCED_LABEL, GameDate, GameState, PlatformDates, has_platform, igdb_numbers, platform_dates, released_by,
)
from app.tracker.platforms import NO_REGION, PLATFORMS, REGION_WORDS, STORE_COUNTRIES, Platform, steam_url

CANCELLED_LABEL = "отменена"
NO_PLATFORMS = "Платформы пока не объявлены"
NONE_OF_MINE = "Игры нет на ваших платформах — выбрать платформы можно в Настройках"

PLAYSTATION_URL = "https://store.playstation.com/{locale}/{path}"

RELEASE = "Выход"
EARLY_ACCESS = "Ранний доступ"


# --- the card -------------------------------------------------------------------------------------------------------


def _line(platform: Platform, dates: PlatformDates, today: date) -> str:
    """«PS5 — 27 марта 2015 (версия для PS4)», «ПК — дата не объявлена, ранний доступ с 6 мая 2024», «PS5 — отменена»."""
    if dates.cancelled:
        return f"{PLATFORMS[platform].label} — {CANCELLED_LABEL}"
    full = dates.full.label if dates.full is not None else NOT_ANNOUNCED_LABEL
    line = f"{PLATFORMS[platform].label} — {full}"
    early = dates.early
    if early is not None and early.date.announced and not released_by(dates.full.date if dates.full else None, today):
        line += f", ранний доступ с {early.label}"
    return line


def platform_rows(
    game: GameState, mine: Collection[Platform], playing: Mapping[str, bool], country: str, today: date
) -> tuple[PlatformRow, ...]:
    """The platforms of «Мои платформы» the game is on, in the order of the table, with the mark «играю здесь». A
    platform without a stored row yet (IGDB added it after the last check) counts as marked, as the events count it."""
    rows = []
    for platform in Platform:
        dates = platform_dates(game, platform, country) if platform in mine else None
        if dates is not None:
            rows.append(PlatformRow(platform.value, _line(platform, dates, today), playing.get(platform.value, True)))
    return tuple(rows)


def outside_date(game: GameState, mine: Collection[Platform], country: str) -> str:
    """«в Японии — 12 марта 2027»: the earliest announced full release in a region outside the country's (KI-35), which
    is no release for the owner but worth a line. Over the platforms of «Мои платформы» the game is on and that are not
    cancelled (a record of the platform's own IGDB number or of its older one); a platform counts only when that date
    ends earlier than its own date for the country, or it has none. Empty: no such line."""
    regions = STORE_COUNTRIES[country].regions
    found: list[tuple[GameDate, int]] = []
    for platform in Platform:
        dates = platform_dates(game, platform, country) if platform in mine else None
        if dates is None or dates.cancelled:
            continue
        numbers = igdb_numbers(platform)
        outside = [
            release for release in game.releases
            if release.platform in numbers and release.type == FULL and release.region not in regions
            and release.date.announced
        ]
        if not outside:
            continue
        earliest = min(outside, key=lambda release: release.date.start)
        own = dates.full.date if dates.full is not None else None
        if own is None or not own.announced or earliest.date.end < own.end:
            found.append((earliest.date, earliest.region))
    if not found:
        return ""
    day, region = min(found, key=lambda item: item[0].start)
    return f"{REGION_WORDS.get(region, REGION_WORDS[NO_REGION])} — {day.label}"


def platform_note(game: GameState, rows: Collection[PlatformRow]) -> str:
    """Why the card lists no platform: the game is on none of the tracker, or on none of the owner's. Empty: it lists some."""
    if rows:
        return ""
    if not any(has_platform(game, platform) for platform in Platform):
        return NO_PLATFORMS
    return NONE_OF_MINE


@dataclass(frozen=True)
class PlayStationLink:
    """Where a game is in PlayStation Store for the country of the stores: the page of its concept (None — the game
    has no number there) and the search by its original name, the address the store sends from a concept it lacks to."""

    locale: str
    concept: str | None
    search_url: str

    @property
    def concept_url(self) -> str | None:
        return PLAYSTATION_URL.format(locale=self.locale, path=f"concept/{self.concept}") if self.concept else None

    @property
    def url(self) -> str:
        """The page of the concept, else the search."""
        return self.concept_url or self.search_url


def playstation_link(
    game: GameState, mine: Collection[Platform], country: str, original_name: str
) -> PlayStationLink | None:
    """The link of the game in PlayStation Store: when PS5 is one of the owner's, the game is on PS5 or PS4 and the
    country has the store. None: no link."""
    locale = STORE_COUNTRIES[country].playstation_locale
    if not locale or Platform.PS5 not in mine or not has_platform(game, Platform.PS5):
        return None
    search = PLAYSTATION_URL.format(locale=locale, path=f"search/{quote(original_name, safe='')}")
    return PlayStationLink(locale, game.ps_concept or None, search)


def store_links(game: GameState, mine: Collection[Platform], country: str, original_name: str) -> tuple[StoreLink, ...]:
    """Steam, when the game has its number and ПК is one of the owner's; PlayStation Store (`playstation_link`): the
    page of the concept, else a search by the original name. The link of a concept is `checked` for the web: it leads
    through the check of the page (KI-37)."""
    links = []
    if game.steam_id and Platform.PC in mine:
        links.append(StoreLink("Открыть в Steam", "Steam", steam_url(game.steam_id)))
    if (found := playstation_link(game, mine, country, original_name)) is not None:
        links.append(StoreLink("Открыть в PlayStation Store", "PS Store", found.url, checked=found.concept is not None))
    return tuple(links)


# --- the feed -------------------------------------------------------------------------------------------------------


def feed_pieces(
    title: FeedTitle, game: GameState, told: Collection[Platform], country: str, today: date
) -> list[Piece]:
    """What comes out of a game from today on, on the platforms the owner is told about (`game_events.reported`) and
    that are not cancelled: the full release on an exact day, the early access on an exact day while the full release
    is not out, the full release on an approximate date (only for «Позже»). Platforms of one day (or one approximate
    date) and one type are one piece: «Выход на ПК и PS5»; a date of the older platform: «Выход на PS4 (идёт на PS5)»."""
    grouped: dict[tuple[int, date, str], list[tuple[Platform, str]]] = {}
    for platform in Platform:
        dates = platform_dates(game, platform, country) if platform in told else None
        if dates is None or dates.cancelled:
            continue
        found = []
        full = dates.full
        if full is not None and full.date.announced and full.date.end >= today:
            found.append((0, full, full.date.end, "" if full.date.exact else full.date.label))
        early = dates.early
        if early is not None and early.date.exact and early.date.start >= today:
            # a full release on that day or before it leaves the early access nothing to open
            full_day = full.date.start if full is not None and full.date.exact else None
            if full_day is None or full_day > early.date.start:
                found.append((1, early, early.date.start, ""))
        for order, dated, day, when in found:
            if dated.via and older_tells(platform, told):
                continue  # the older platform is in the piece itself
            grouped.setdefault((order, day, when), []).append((platform, dated.via or ""))
    return [
        Piece(title, day, None, (order,), f"{EARLY_ACCESS if order else RELEASE} на {platforms_text(entries)}", when)
        for (order, day, when), entries in grouped.items()
    ]
