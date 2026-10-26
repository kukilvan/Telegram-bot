"""TMDb adapter for sequels of an archived movie: the franchise collection the movie belongs to.

Parsing is pure (responses in, data out) and is tested on saved real responses. The network client
(`TMDbProvider`) is passed in, so the adapter never talks to the network itself.

Every check asks TMDb for the movie first and for its collection second: a movie that stood alone when
it was archived can join a collection later, once a sequel is announced.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.tracker.failures import TitleGone

SOURCE_KEY = "tmdb_sequels"  # distinct from the movie's own source: one title keeps one snapshot per source


@dataclass(frozen=True)
class CollectionPart:
    """Another movie of the same collection."""

    external_id: str
    name: str
    release_date: date | None


@dataclass(frozen=True)
class SequelSnapshot:
    """What the collection says right now: the movie's own premiere date and the other movies around it."""

    own_date: date | None
    parts: list[CollectionPart] = field(default_factory=list)

    def state(self) -> dict[str, Any]:
        """The part that changes over time, as JSON-ready data (stored as the source snapshot)."""
        return {
            "own_date": self.own_date.isoformat() if self.own_date else None,
            "parts": [
                {
                    "id": part.external_id,
                    "title": part.name,  # the stored key keeps its old name: snapshots already saved are read with it
                    "date": part.release_date.isoformat() if part.release_date else None,
                }
                for part in self.parts
            ],
        }


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def collection_id(movie: dict[str, Any]) -> int | None:
    belongs = movie.get("belongs_to_collection") or {}
    return belongs.get("id")


def parse_sequels(movie: dict[str, Any], collection: dict[str, Any] | None) -> SequelSnapshot:
    own_id = str(movie["id"])
    parts = [
        CollectionPart(
            external_id=str(raw["id"]),
            name=raw.get("title") or raw.get("original_title") or "",
            release_date=_parse_date(raw.get("release_date")),
        )
        for raw in (collection or {}).get("parts", [])
        if str(raw["id"]) != own_id
    ]
    return SequelSnapshot(own_date=_parse_date(movie.get("release_date")), parts=parts)


class TmdbSequelSource:
    """Sequel source of the tracker core, on top of a `TMDbProvider`-like client."""

    source_key = SOURCE_KEY

    def __init__(self, provider) -> None:
        self._provider = provider

    async def snapshot(self, external_id: str) -> SequelSnapshot | None:
        """None when TMDb has no movie at this id. A failure raises, so "TMDb is down" is not "no sequels"."""
        movie = await self._provider.get_movie_with_release_dates(int(external_id))
        if movie is None:
            return None
        belongs_to = collection_id(movie)
        if belongs_to is None:
            return parse_sequels(movie, None)
        collection = await self._provider.get_collection(belongs_to)
        if collection is None:
            raise TitleGone(f"TMDb has no collection {belongs_to} listed for movie {external_id}")
        return parse_sequels(movie, collection)
