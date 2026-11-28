"""The platforms of the tracker and the countries of the stores: where a game comes out, whose region its dates are, and the words of the other regions.

Pure: no database, no network. Everything that depends on a platform or a country lives in the two tables here and is
read from them (rule 6 of `docs/coding-standards.md`); the order of the rows is the order everywhere: the settings, the
card and the list of a message.
"""

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import quote


class Platform(StrEnum):
    """The values live in the database and in the addresses; they never change."""

    PC = "pc"
    PS5 = "ps5"
    XBOX_SERIES = "xbox_series"
    SWITCH_2 = "switch_2"
    SWITCH = "switch"
    META_QUEST = "meta_quest"


@dataclass(frozen=True)
class OlderPlatform:
    """The console whose games a newer one runs (backward compatibility): where the date of the older version is read."""

    label: str
    igdb_id: int


@dataclass(frozen=True)
class PlatformInfo:
    """A platform of the tracker: its own IGDB numbers (one or more, ADR 0018: the earliest date among them is the
    platform's own date, with no text) and at most one older platform."""

    settings_label: str  # in the settings
    label: str  # in the card and in the messages
    igdb_ids: tuple[int, ...]
    older: OlderPlatform | None = None


# ПК: Windows (6) as IGDB names it — Mac and Linux are not platforms of the tracker — and SteamVR (163), where IGDB puts
# the PC version of a VR game. Meta Quest: Quest 3 (471, Quest 3S included), Quest 2 (386) and the first Quest (384) —
# one app in the Meta store. Not taken: 162 «Oculus VR», 385 Rift, 161 Windows Mixed Reality, 387 Go, the PlayStation VR
# headsets (spec 1.2 of stage 6.5)
PLATFORMS: dict[Platform, PlatformInfo] = {
    Platform.PC: PlatformInfo("ПК", "ПК", (6, 163)),
    Platform.PS5: PlatformInfo("PlayStation 5", "PS5", (167,), OlderPlatform("PS4", 48)),
    Platform.XBOX_SERIES: PlatformInfo("Xbox Series X|S", "Xbox Series X|S", (169,), OlderPlatform("Xbox One", 49)),
    Platform.SWITCH_2: PlatformInfo("Nintendo Switch 2", "Switch 2", (508,), OlderPlatform("Switch", 130)),
    Platform.SWITCH: PlatformInfo("Nintendo Switch", "Switch", (130,)),
    Platform.META_QUEST: PlatformInfo("Meta Quest", "Meta Quest", (471, 386, 384)),
}
DEFAULT_PLATFORMS = (Platform.PC, Platform.PS5)


def _igdb_labels() -> dict[int, str]:
    labels: dict[int, str] = {}
    for info in PLATFORMS.values():
        for number in info.igdb_ids:
            labels.setdefault(number, info.label)
        if info.older:
            labels.setdefault(info.older.igdb_id, info.older.label)
    return labels


# Every IGDB number the tracker knows, its own and the older ones, in the order of the table with each older one right
# after its newer (the line of platforms of a suggestion: «ПК, PS5, PS4, …, Meta Quest», each label once)
IGDB_LABELS: dict[int, str] = _igdb_labels()

# The regions of IGDB, as its `release_region` numbers them
WORLD, EUROPE, NORTH_AMERICA = 8, 1, 2
NO_REGION = 0  # a record without a region (or one IGDB has not had before)

# «в Японии»: where a date outside the regions of the country is, as the card says it (spec 1.1 of stage 9.1b). The
# regions every country has (world, Europe, North America) never need a word
REGION_WORDS: dict[int, str] = {
    3: "в Австралии", 4: "в Новой Зеландии", 5: "в Японии", 6: "в Китае", 7: "в Азии", 9: "в Корее", 10: "в Бразилии",
    NO_REGION: "в другой стране",
}


@dataclass(frozen=True)
class StoreCountry:
    label: str
    playstation_locale: str | None  # «en-il»: the store of the country in the address of PlayStation Store; None: no store
    regions: tuple[int, ...]  # whose date of a game is the date of the country, the first that has one


_EUROPEAN = (WORLD, EUROPE, NORTH_AMERICA)
# By label, as the list of the settings reads; `ru-ru` and `kk-kz` lead to another store, so Russia and Kazakhstan have none
STORE_COUNTRIES: dict[str, StoreCountry] = {
    "gb": StoreCountry("Великобритания", "en-gb", _EUROPEAN),
    "de": StoreCountry("Германия", "de-de", _EUROPEAN),
    "il": StoreCountry("Израиль", "en-il", _EUROPEAN),
    "kz": StoreCountry("Казахстан", None, _EUROPEAN),
    "pl": StoreCountry("Польша", "pl-pl", _EUROPEAN),
    "ru": StoreCountry("Россия", None, _EUROPEAN),
    "us": StoreCountry("США", "en-us", (WORLD, NORTH_AMERICA, EUROPE)),
    "tr": StoreCountry("Турция", "en-tr", _EUROPEAN),
    "ua": StoreCountry("Украина", "ru-ua", _EUROPEAN),
}
DEFAULT_COUNTRY = "il"


def steam_url(steam_id: str) -> str:
    """The page of a game in the Steam store (the same in every country): the link of the card and the button under
    the messages of Steam."""
    return f"https://store.steampowered.com/app/{steam_id}/"


def meta_store_url(meta_store_id: str | None, original_name: str) -> str:
    """The page of a game in the Meta store by its number; no number — the store's search by the original name (the
    store is in English). The same in every country, and never asked by the tracker (spec 6.2 of stage 6.5)."""
    if meta_store_id:
        return f"https://www.meta.com/experiences/{meta_store_id}/"
    return f"https://www.meta.com/experiences/search/?q={quote(original_name, safe='')}"
