"""IGDB adapter for games: search suggestions and the game snapshot, with the Russian texts of Steam when a game is added.

Parsing is pure (response in, data out) and is tested on saved real responses. The network clients (`IGDBProvider`,
`SteamProvider`) are passed in, so the adapter never talks to the network itself.

Only the games themselves count (spec 4.2 of part 6.1): a main game, a standalone expansion, a remake, a remaster, an
expanded game and a port, and a record that is no edition of another game (`version_parent`). DLC, bundles, mods,
updates, episodes and every edition are left out.
"""

import html
import re
from dataclasses import dataclass, field
from typing import Any

from app.tracker.errors import SourceNotConfigured
from app.tracker.games import CANCELLED, EARLY, FULL, GameDate, GameState, Release
from app.tracker.platforms import IGDB_LABELS
from app.tracker.sources.dates import response_day_of_timestamp
from app.tracker.sources.tmdb_movies import Suggestion

SOURCE_KEY = "igdb"
GAME = "game"  # the kind of a suggestion: `TitleKind.GAME` once the core knows games (ticket 04 of part 6.1)

# `game_type` of IGDB: 0 main game, 4 standalone expansion, 8 remake, 9 remaster, 10 expanded game, 11 port
GAME_TYPES = (0, 4, 8, 9, 10, 11)
_ONLY_GAMES = f"where game_type = ({','.join(map(str, GAME_TYPES))}) & version_parent = null"

SEARCH_QUERY = (
    'search "{query}"; '
    "fields name,game_type,version_parent,first_release_date,platforms,cover.image_id,"
    "alternative_names.name,alternative_names.comment; "
    f"{_ONLY_GAMES}; limit 10;"
)
GAME_QUERY = (
    "fields name,game_type,version_parent,parent_game,first_release_date,summary,genres.name,cover.image_id,platforms,"
    "alternative_names.name,alternative_names.comment,release_dates.date,release_dates.date_format,release_dates.y,"
    "release_dates.m,release_dates.platform,release_dates.release_region,release_dates.status,external_games.uid,"
    "external_games.external_game_source,external_games.url; "
    "where id = {id};"
)

# `status` of a release: nothing or 6 the full release, 3 early access, 5 cancelled; the others (alpha, beta, a
# preorder with early entry, offline…) are not taken
_RELEASE_TYPES = {None: FULL, 6: FULL, 3: EARLY, 5: CANCELLED}

STEAM_SOURCE = 1  # `external_game_source`: the number of the app in Steam
PS_STORE_SOURCE = 36  # «Playstation Store US»: the number of the concept

COVER_URL = "https://images.igdb.com/igdb/image/upload/t_cover_big/{}.jpg"

# Our own Russian for the genres of IGDB (KI-30: no mix of languages in the archive); an unknown one stays as it is
GENRES = {
    "Adventure": "Приключения",
    "Arcade": "Аркада",
    "Card & Board Game": "Карточная и настольная",
    "Fighting": "Файтинг",
    "Hack and slash/Beat 'em up": "Слэшер",
    "Indie": "Инди",
    "MOBA": "MOBA",
    "Music": "Музыка",
    "Pinball": "Пинбол",
    "Platform": "Платформер",
    "Point-and-click": "Квест",
    "Puzzle": "Головоломка",
    "Quiz/Trivia": "Викторина",
    "Racing": "Гонки",
    "Real Time Strategy (RTS)": "Стратегия в реальном времени",
    "Role-playing (RPG)": "Ролевая",
    "Shooter": "Шутер",
    "Simulator": "Симулятор",
    "Sport": "Спорт",
    "Strategy": "Стратегия",
    "Tactical": "Тактика",
    "Turn-based strategy (TBS)": "Пошаговая стратегия",
    "Visual Novel": "Визуальная новелла",
}

_RUSSIAN_LETTER = re.compile("[А-Яа-яЁё]")
_TAG = re.compile(r"<[^>]*>")
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True)
class GameSnapshot:
    """What IGDB (and Steam, when the game is added) knows about a game right now."""

    external_id: str
    name: str
    original_name: str
    year: int | None
    genres: list[str] = field(default_factory=list)
    poster_path: str | None = None  # the whole address of the cover
    overview: str | None = None
    game: GameState = field(default_factory=GameState)  # the dates and the numbers of the stores

    def state(self) -> dict[str, Any]:
        """The part that changes over time, as JSON-ready data (stored as the source snapshot)."""
        return self.game.state()


def clean_query(query: str) -> str:
    """`"` and `\\` do not change what IGDB finds, but break the text of the query."""
    return query.replace('"', "").replace("\\", "").strip()


def is_game(item: dict[str, Any]) -> bool:
    """One of the games themselves, not an edition of another one: checked again on the answer, the filter of the
    query may not have worked."""
    return item.get("game_type") in GAME_TYPES and item.get("version_parent") is None


def russian_name(item: dict[str, Any]) -> str | None:
    """The first alternative name IGDB marks as Russian («Russian title», «Russian Title»)."""
    for alternative in item.get("alternative_names") or []:
        if "russian" in str(alternative.get("comment") or "").casefold() and alternative.get("name"):
            return alternative["name"]
    return None


def cover_url(item: dict[str, Any]) -> str | None:
    image_id = (item.get("cover") or {}).get("image_id")
    return COVER_URL.format(image_id) if image_id else None


def platform_line(platforms: list[Any] | None) -> str | None:
    """«ПК, PS5, PS4, Xbox Series X|S, Xbox One, Switch 2, Switch»: the platforms the tracker knows, in that order; None
    when the game has none of them."""
    present = set(platforms or ())
    labels = [label for number, label in IGDB_LABELS.items() if number in present]
    return ", ".join(labels) or None


def _release_year(item: dict[str, Any]) -> int | None:
    day = response_day_of_timestamp(item.get("first_release_date"))
    return day.year if day else None


def parse_search(results: list[dict[str, Any]]) -> list[Suggestion]:
    return [
        Suggestion(
            kind=GAME,
            external_id=str(item["id"]),
            name=russian_name(item) or item.get("name") or "",
            original_name=item.get("name") or "",
            year=_release_year(item),
            poster_path=cover_url(item),
            details=platform_line(item.get("platforms")),
        )
        for item in results
        if is_game(item)
    ]


def _known(numbers: Any) -> tuple[int, ...]:
    return tuple(sorted({number for number in numbers or () if number in IGDB_LABELS}))


NO_REGION = 0  # a record without a region of IGDB: one of «the others» when the region of a country is chosen


def _region(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else NO_REGION


def _releases(raw: list[dict[str, Any]] | None) -> tuple[Release, ...]:
    return tuple(
        Release(
            platform=entry["platform"],
            region=_region(entry.get("release_region")),
            type=_RELEASE_TYPES[entry.get("status")],
            date=GameDate.from_igdb(entry),
        )
        for entry in raw or ()
        if entry.get("platform") in IGDB_LABELS and entry.get("status") in _RELEASE_TYPES
    )


def _store_id(external: list[dict[str, Any]] | None, source: int) -> str | None:
    for entry in external or ():
        if entry.get("external_game_source") == source:
            return str(entry.get("uid") or "").strip() or None
    return None


def parse_state(raw: dict[str, Any]) -> GameState:
    external = raw.get("external_games")
    concept = _store_id(external, PS_STORE_SOURCE)
    return GameState(
        steam_id=_store_id(external, STEAM_SOURCE),
        ps_concept=concept if concept and concept.isdigit() else None,  # anything else: the link is a search
        platforms=_known(raw.get("platforms")),
        releases=_releases(raw.get("release_dates")),
    )


def _russian(text: Any) -> bool:
    return isinstance(text, str) and bool(_RUSSIAN_LETTER.search(text))


def plain_text(description: str) -> str:
    """The description of Steam as text: no HTML tags, `&quot;` and the like opened, spaces squeezed."""
    return _SPACES.sub(" ", html.unescape(_TAG.sub(" ", description))).strip()


def parse_game(raw: dict[str, Any], steam: dict[str, Any] | None = None) -> GameSnapshot:
    """The snapshot of a game. `steam` — the details of its app in Steam (only when the game is added): its name counts
    when IGDB has no Russian one and it has Russian letters, its description when it has Russian letters (spec 4.4)."""
    steam = steam or {}
    steam_name, steam_description = steam.get("name"), steam.get("short_description")
    name = russian_name(raw) or (steam_name if _russian(steam_name) else None) or raw.get("name") or ""
    overview = plain_text(steam_description) if _russian(steam_description) else None
    return GameSnapshot(
        external_id=str(raw["id"]),
        name=name,
        original_name=raw.get("name") or "",
        year=_release_year(raw),
        genres=[GENRES.get(genre["name"], genre["name"]) for genre in raw.get("genres") or [] if genre.get("name")],
        poster_path=cover_url(raw),
        overview=overview or raw.get("summary") or None,
        game=parse_state(raw),
    )


class IgdbGameSource:
    """Game source of the tracker core, on top of an `IGDBProvider`-like client and, for adding, a `SteamProvider`-like
    one. Without the keys of IGDB every request raises `SourceNotConfigured` before the network."""

    source_key = SOURCE_KEY

    def __init__(self, provider, steam=None) -> None:
        self._provider = provider
        self._steam = steam

    def _check_keys(self) -> None:
        if not self._provider.enabled:
            raise SourceNotConfigured("IGDB_CLIENT_ID or IGDB_CLIENT_SECRET is empty")

    async def suggest(self, query: str) -> list[Suggestion]:
        """Goes at once, ahead of the paced requests of the polling; a query of nothing but quotes asks nothing."""
        self._check_keys()
        cleaned = clean_query(query)
        if not cleaned:
            return []
        return parse_search(await self._provider.games(SEARCH_QUERY.format(query=cleaned), at_once=True))

    async def _raw(self, external_id: str) -> dict[str, Any] | None:
        self._check_keys()
        found = await self._provider.games(GAME_QUERY.format(id=int(external_id)))
        return found[0] if found else None

    async def snapshot(self, external_id: str) -> GameSnapshot | None:
        """None when IGDB has no game at this id. The polling: the name and the description stay as they were added."""
        raw = await self._raw(external_id)
        return parse_game(raw) if raw else None

    async def snapshot_to_add(self, external_id: str) -> GameSnapshot | None:
        """The snapshot with the Russian name and description of Steam: asked only here, when the game is added, and
        only when IGDB knows its app in Steam. Steam failing is no failure: the game is added by what IGDB knows."""
        raw = await self._raw(external_id)
        if not raw:
            return None
        steam_id = parse_state(raw).steam_id
        details = await self._steam.app_details(steam_id) if steam_id and self._steam else None
        return parse_game(raw, details)
