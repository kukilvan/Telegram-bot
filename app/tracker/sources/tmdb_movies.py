"""TMDb adapter for movies: search suggestions and the movie snapshot.

Parsing is pure (response in, data out) and is tested on saved real responses. The network client
(`TMDbProvider`) is passed in, so the adapter never talks to the network itself.

Dates come from the nested per-region `release_dates` (integer types: 3 theatrical, 4 digital). A date is
the earliest one over all regions, because the owner's region is not fixed yet; limited release (2) and
premiere (1) are not counted as the theatrical date.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any

THEATRICAL = 3
DIGITAL = 4

SOURCE_KEY = "tmdb_movie"  # TMDb shares one id space between movies and series, so ids are namespaced by kind


@dataclass(frozen=True)
class Suggestion:
    """One search result the owner can pick."""

    kind: str
    external_id: str
    title: str
    original_title: str
    year: int | None


@dataclass(frozen=True)
class MovieSnapshot:
    """What the source knows about a movie right now."""

    external_id: str
    title: str
    original_title: str
    year: int | None
    genres: list[str] = field(default_factory=list)
    poster_path: str | None = None
    overview: str | None = None
    theatrical_date: date | None = None
    digital_date: date | None = None

    def state(self) -> dict[str, str | None]:
        """The part that changes over time, as JSON-ready data (stored as the source snapshot)."""
        return {
            "theatrical_date": self.theatrical_date.isoformat() if self.theatrical_date else None,
            "digital_date": self.digital_date.isoformat() if self.digital_date else None,
        }


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _year(value: str | None) -> int | None:
    parsed = _parse_date(value)
    return parsed.year if parsed else None


def parse_search(results: list[dict[str, Any]]) -> list[Suggestion]:
    return [
        Suggestion(
            kind="movie",
            external_id=str(item["id"]),
            title=item.get("title") or item.get("original_title") or "",
            original_title=item.get("original_title") or item.get("title") or "",
            year=_year(item.get("release_date")),
        )
        for item in results
    ]


def _earliest(release_dates: dict[str, Any], release_type: int) -> date | None:
    found = [
        parsed
        for region in (release_dates or {}).get("results", [])
        for entry in region.get("release_dates", [])
        if entry.get("type") == release_type and (parsed := _parse_date(entry.get("release_date")))
    ]
    return min(found) if found else None


def parse_movie(raw: dict[str, Any]) -> MovieSnapshot:
    release_dates = raw.get("release_dates") or {}
    return MovieSnapshot(
        external_id=str(raw["id"]),
        title=raw.get("title") or raw.get("original_title") or "",
        original_title=raw.get("original_title") or raw.get("title") or "",
        year=_year(raw.get("release_date")),
        genres=[genre["name"] for genre in raw.get("genres") or []],
        poster_path=raw.get("poster_path"),
        overview=raw.get("overview") or None,
        theatrical_date=_earliest(release_dates, THEATRICAL),
        digital_date=_earliest(release_dates, DIGITAL),
    )


class TmdbMovieSource:
    """Movie source of the tracker core, on top of a `TMDbProvider`-like client."""

    source_key = SOURCE_KEY

    def __init__(self, provider) -> None:
        self._provider = provider

    async def suggest(self, query: str) -> list[Suggestion]:
        return parse_search(await self._provider.search_movie(query, strict=True))

    async def snapshot(self, external_id: str) -> MovieSnapshot | None:
        """None when TMDb has no movie at this id (the id may belong to a series)."""
        raw = await self._provider.get_movie_with_release_dates(int(external_id))
        return parse_movie(raw) if raw else None
