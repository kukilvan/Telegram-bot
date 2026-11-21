"""Steam adapter for languages: what Steam answered about each game becomes what it says about Russian (`russian.Support` or «no data»).

Parsing is pure (records of `GetItems` in, supports out) and is tested on saved real answers; the network client
(`SteamProvider.store_items` with `languages=True`) is passed in. Spec 5.5 of stage 9.1b.

The languages are asked in the store of the United States (`STORE_COUNTRY`) whatever the country of the stores: a game
not sold in a country answers `success: 15` there with no languages (in Russia even Cyberpunk 2077). Russian is
`elanguage` 8: its text is `supported` or `subtitles`, its voice `full_audio`. A list without Russian says «no
Russian» (both no); a missing or empty list, or `success: 15`, says nothing (None). The list is read strictly, as the
prices: a list that is not records with yes/no flags makes the answer about that game unreadable (`UnreadAnswer`, a
failure of that game), never «no Russian»; the other games of the same answer are read as usual.
"""

from collections.abc import Iterable, Sequence
from typing import Any

from app.providers.steam import SteamProvider
from app.tracker.russian import Support
from app.tracker.sources.steam_prices import NOT_HERE, SOLD, UnreadAnswer

STORE_COUNTRY = "US"  # the store the languages are asked in, whatever the country of the stores
RUSSIAN = 8  # `elanguage` of Steam
_FLAGS = ("supported", "full_audio", "subtitles")


class SteamLanguageSource:
    """Asks Steam about the languages of games; the client comes from outside."""

    def __init__(self, steam: SteamProvider) -> None:
        self.steam = steam

    async def russian(self, appids: Sequence[str]) -> dict[str, Support | None | UnreadAnswer]:
        """What Steam says about Russian in each of `appids` (at most 100, `MAX_ITEMS`), asked in `STORE_COUNTRY`. A
        number that is no number of digits says nothing without asking. A failure of the whole request is `SteamError`."""
        asked = list(dict.fromkeys(appid for appid in appids if _is_number(appid)))
        items = await self.steam.store_items(asked, STORE_COUNTRY, languages=True) if asked else []
        return parse_items(items, appids)


def parse_items(items: Iterable[dict[str, Any]], appids: Sequence[str]) -> dict[str, Support | None | UnreadAnswer]:
    """What each of `appids` says by the records `items` of one answer of `GetItems` (matched by `appid`, else by `id`),
    or `UnreadAnswer` for a game whose record is missing or cannot be read."""
    by_number: dict[str, dict[str, Any]] = {}
    for item in items:
        number = item.get("appid") or item.get("id")
        if number is not None:
            by_number.setdefault(str(number), item)
    found: dict[str, Support | None | UnreadAnswer] = {}
    for appid in appids:
        if not _is_number(appid):
            found[appid] = None
        elif appid not in by_number:
            found[appid] = UnreadAnswer(f"Steam app {appid}: no record in the answer")
        else:
            try:
                found[appid] = parse_item(by_number[appid])
            except ValueError as exc:
                found[appid] = UnreadAnswer(f"Steam app {appid}: {exc}")
    return found


def parse_item(item: dict[str, Any]) -> Support | None:
    """What one record of `GetItems` says about Russian; a ValueError when it cannot be read."""
    success = item.get("success")
    if success == NOT_HERE and not isinstance(success, bool):
        return None
    if success != SOLD or isinstance(success, bool):
        raise ValueError(f"success is {success!r}")
    languages = item.get("supported_languages")
    if languages is None:
        return None
    if not isinstance(languages, list):
        raise ValueError(f"supported_languages is no list: {languages!r}")
    for record in languages:
        if not isinstance(record, dict) or not _whole(record.get("elanguage")):
            raise ValueError(f"a supported language is no record with elanguage: {record!r}")
        if not all(isinstance(record.get(flag), bool) for flag in _FLAGS):
            raise ValueError(f"a supported language has no yes/no flags: {record!r}")
    if not languages:
        return None
    russian = [record for record in languages if record["elanguage"] == RUSSIAN]
    if not russian:
        return Support(False, False)
    return Support(
        text=any(record["supported"] or record["subtitles"] for record in russian),
        voice=any(record["full_audio"] for record in russian),
    )


def _whole(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_number(text: str) -> bool:
    """A Steam number: ASCII digits only."""
    return text.isascii() and text.isdecimal()
