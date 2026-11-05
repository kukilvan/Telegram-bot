"""IGDB adapter of the follow-up check: one request a game for its expansions and the games of its series, parsed into a `FollowUpsSnapshot`.

Parsing is pure and soft (an answer of a service: garbage is «no such field») and is tested on saved real answers; the
network client (`IGDBProvider.games`, paced like every IGDB request) is passed in. Spec 3.1–3.2 of stage 6.3.

The series is IGDB's `collections` (not its franchises, full of editions, bundles and crossovers), with the game's own
`remakes` and `remasters`; of them only the games themselves count (`igdb_games.is_game`). The expansions are
`expansions` (type 2) and `standalone_expansions` (type 4): small DLC (`dlcs`) is left out.
"""

from collections.abc import Iterable
from typing import Any

from app.tracker.errors import SourceNotConfigured
from app.tracker.failures import TitleGone
from app.tracker.follow_ups import Candidate, FollowUpsSnapshot
from app.tracker.sources.dates import response_day_of_timestamp
from app.tracker.sources.igdb_games import is_game, known_platforms, read_releases, russian_name

SOURCE_KEY = "igdb_follow_ups"

STANDALONE_TYPE = 4  # `game_type` of a standalone expansion

# `<F>` of spec 3.1: what is read of every candidate
CANDIDATE_FIELDS = (
    "id", "name", "game_type", "version_parent", "first_release_date", "platforms", "alternative_names.name",
    "alternative_names.comment", "release_dates.date", "release_dates.date_format", "release_dates.y", "release_dates.m",
    "release_dates.platform", "release_dates.release_region", "release_dates.status",
)


def _fields(prefix: str) -> str:
    return ",".join(f"{prefix}.{name}" for name in CANDIDATE_FIELDS)


FOLLOW_UPS_QUERY = (
    "fields name,game_type,first_release_date,"
    f"{_fields('expansions')},{_fields('standalone_expansions')},{_fields('remakes')},{_fields('remasters')},"
    f"collections.name,{_fields('collections.games')}; "
    "where id = {id};"
)


def _records(value: Any) -> list[dict[str, Any]]:
    """A list of records of an answer: anything that is not a record with an int id is left out."""
    if not isinstance(value, list):
        return []
    return [
        item for item in value
        if isinstance(item, dict) and isinstance(item.get("id"), int) and not isinstance(item.get("id"), bool)
    ]


def _candidate(item: dict[str, Any]) -> Candidate:
    name = item.get("name")
    return Candidate(
        id=str(item["id"]),
        name=russian_name(item) or (name if isinstance(name, str) else "") or str(item["id"]),
        first=response_day_of_timestamp(item.get("first_release_date")),
        platforms=known_platforms(item.get("platforms") if isinstance(item.get("platforms"), list) else ()),
        releases=read_releases(_records_of_dates(item.get("release_dates"))),
        standalone=item.get("game_type") == STANDALONE_TYPE,
    )


def _records_of_dates(value: Any) -> list[dict[str, Any]]:
    return [entry for entry in value if isinstance(entry, dict)] if isinstance(value, list) else []


def _once(items: Iterable[dict[str, Any]], skip: set[int]) -> list[dict[str, Any]]:
    """Each record once by its id, in the order of the answer, without the ids of `skip`."""
    seen = set(skip)
    kept = []
    for item in items:
        if item["id"] not in seen:
            seen.add(item["id"])
            kept.append(item)
    return kept


def parse_follow_ups(raw: dict[str, Any]) -> FollowUpsSnapshot:
    """The snapshot of the answer about one game (spec 3.2)."""
    expansions = _once(
        (
            item for item in _records(raw.get("expansions")) + _records(raw.get("standalone_expansions"))
            if item.get("version_parent") is None
        ),
        {raw.get("id")},
    )
    collections = _records(raw.get("collections"))
    series = _records(raw.get("remakes")) + _records(raw.get("remasters"))
    for collection in collections:
        series += _records(collection.get("games"))
    games = _once(
        (item for item in series if is_game(item)), {raw.get("id")} | {item["id"] for item in expansions}
    )
    return FollowUpsSnapshot(
        own_date=response_day_of_timestamp(raw.get("first_release_date")),
        collections=tuple(c["name"] for c in collections if isinstance(c.get("name"), str) and c["name"]),
        expansions=tuple(_candidate(item) for item in expansions),
        games=tuple(_candidate(item) for item in games),
    )


class IgdbFollowUpSource:
    """The source of the follow-up check, on top of an `IGDBProvider`-like client: without the keys of IGDB a request
    raises `SourceNotConfigured` before the network; a failure of IGDB (`IgdbError`) passes through."""

    source_key = SOURCE_KEY

    def __init__(self, provider) -> None:
        self._provider = provider

    async def follow_ups(self, external_id: str) -> FollowUpsSnapshot:
        """What IGDB says now about the game `external_id`; `TitleGone` when IGDB no longer knows it."""
        if not self._provider.enabled:
            raise SourceNotConfigured("IGDB_CLIENT_ID or IGDB_CLIENT_SECRET is empty")
        found = await self._provider.games(FOLLOW_UPS_QUERY.format(id=int(external_id)))
        if not found:
            raise TitleGone(f"IGDB has no game {external_id}")
        return parse_follow_ups(found[0])
