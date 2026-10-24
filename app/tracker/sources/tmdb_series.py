"""TMDb adapter for series: search suggestions and the series snapshot with its seasons.

Parsing is pure (responses in, data out) and is tested on saved real responses. The network client
(`TMDbProvider`) is passed in, so the adapter never talks to the network itself.

`/tv/{id}` lists the seasons (number, name, episode count) but not their episodes, so every season is
asked for separately (`/tv/{id}/season/{n}`). TMDb gives an episode's air day, not its hour: the episode
counts as out from the start of that day (UTC). Season 0 holds specials and is not a season.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any

from app.tracker.seasons import Episode, Season
from app.tracker.sources.tmdb_movies import Suggestion

SOURCE_KEY = "tmdb_tv"  # TMDb shares one id space between movies and series, so ids are namespaced by kind
KIND = "series"

__all__ = ["Suggestion", "SeriesSnapshot", "TmdbSeriesSource", "parse_search", "parse_show", "SOURCE_KEY"]


@dataclass(frozen=True)
class SeriesSnapshot:
    """What the source knows about a series right now."""

    external_id: str
    title: str
    original_title: str
    year: int | None
    genres: list[str] = field(default_factory=list)
    poster_path: str | None = None
    overview: str | None = None
    seasons: list[Season] = field(default_factory=list)

    def state(self) -> dict[str, Any]:
        """The seasons and episodes live in their own tables, so the snapshot row has nothing to add."""
        return {}


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
            kind=KIND,
            external_id=str(item["id"]),
            title=item.get("name") or item.get("original_name") or "",
            original_title=item.get("original_name") or item.get("name") or "",
            year=_year(item.get("first_air_date")),
        )
        for item in results
    ]


def _parse_season(summary: dict[str, Any], detail: dict[str, Any] | None) -> Season:
    episodes = []
    for raw in (detail or {}).get("episodes") or []:
        aired = _parse_date(raw.get("air_date"))
        episodes.append(
            Episode(number=int(raw["episode_number"]), air_at=datetime.combine(aired, time.min) if aired else None)
        )
    number = int(summary["season_number"])
    return Season(
        number=number,
        name=summary.get("name") or f"Сезон {number}",
        expected=summary.get("episode_count") or None,  # 0 means "not announced yet"
        episodes=tuple(sorted(episodes, key=lambda e: e.number)),
    )


def parse_show(raw: dict[str, Any], season_details: dict[int, dict[str, Any] | None]) -> SeriesSnapshot:
    """`season_details` maps a season number to its `/tv/{id}/season/{n}` response (None: TMDb has no such season)."""
    seasons = [
        _parse_season(summary, season_details.get(int(summary["season_number"])))
        for summary in raw.get("seasons") or []
        if summary.get("season_number") is not None and int(summary["season_number"]) >= 1
    ]
    return SeriesSnapshot(
        external_id=str(raw["id"]),
        title=raw.get("name") or raw.get("original_name") or "",
        original_title=raw.get("original_name") or raw.get("name") or "",
        year=_year(raw.get("first_air_date")),
        genres=[genre["name"] for genre in raw.get("genres") or []],
        poster_path=raw.get("poster_path"),
        overview=raw.get("overview") or None,
        seasons=sorted(seasons, key=lambda s: s.number),
    )


class TmdbSeriesSource:
    """Series source of the tracker core, on top of a `TMDbProvider`-like client."""

    source_key = SOURCE_KEY

    def __init__(self, provider) -> None:
        self._provider = provider

    async def suggest(self, query: str) -> list[Suggestion]:
        return parse_search(await self._provider.search_tv(query, strict=True))

    async def snapshot(self, external_id: str) -> SeriesSnapshot | None:
        """None when TMDb has no series at this id (the id may belong to a movie).

        A failing season request fails the whole snapshot: a series stored without one of its seasons
        would later look as if that season had been announced out of nowhere.
        """
        tv_id = int(external_id)
        raw = await self._provider.get_tv_show(tv_id)
        if raw is None:
            return None
        details = {}
        for summary in raw.get("seasons") or []:
            number = summary.get("season_number")
            if number is not None and int(number) >= 1:
                details[int(number)] = await self._provider.get_tv_season(tv_id, int(number))
        return parse_show(raw, details)
