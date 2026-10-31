"""The platforms of the tracker and the countries of the stores: where a game comes out and whose region its dates are.

Pure: no database, no network. Everything that depends on a platform or a country lives in the two tables here and is
read from them (rule 6 of `docs/coding-standards.md`); the order of the rows is the order everywhere: the settings, the
card and the list of a message.
"""

from dataclasses import dataclass
from enum import StrEnum


class Platform(StrEnum):
    """The values live in the database and in the addresses; they never change."""

    PC = "pc"
    PS5 = "ps5"
    XBOX_SERIES = "xbox_series"
    SWITCH_2 = "switch_2"
    SWITCH = "switch"


@dataclass(frozen=True)
class OlderPlatform:
    """The console whose games a newer one runs (backward compatibility): where the date of the older version is read."""

    label: str
    igdb_id: int


@dataclass(frozen=True)
class PlatformInfo:
    settings_label: str  # in the settings
    label: str  # in the card and in the messages
    igdb_id: int
    older: OlderPlatform | None = None


# Windows only, as IGDB names it: Mac and Linux are not platforms of the tracker
PLATFORMS: dict[Platform, PlatformInfo] = {
    Platform.PC: PlatformInfo("ПК", "ПК", 6),
    Platform.PS5: PlatformInfo("PlayStation 5", "PS5", 167, OlderPlatform("PS4", 48)),
    Platform.XBOX_SERIES: PlatformInfo("Xbox Series X|S", "Xbox Series X|S", 169, OlderPlatform("Xbox One", 49)),
    Platform.SWITCH_2: PlatformInfo("Nintendo Switch 2", "Switch 2", 508, OlderPlatform("Switch", 130)),
    Platform.SWITCH: PlatformInfo("Nintendo Switch", "Switch", 130),
}
DEFAULT_PLATFORMS = (Platform.PC, Platform.PS5)

# The regions of IGDB, as its `release_region` numbers them
WORLD, EUROPE, NORTH_AMERICA = 8, 1, 2


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
