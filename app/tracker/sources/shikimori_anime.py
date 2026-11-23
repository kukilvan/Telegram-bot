"""Shikimori adapter for anime: search suggestions and the source of the tracker core.

The source gives the whole franchise of the entry the owner picked: Shikimori's entries put together by
`shikimori_chain`, with AniList's ids and schedules added. The network clients (`ShikimoriClient`, `AniListProvider`)
are passed in, so the adapter never talks to the network itself. A suggestion is one franchise: adding it takes its chain.
"""

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import date, datetime, timezone
from typing import Any, Protocol

from app.tracker.models import TitleKind
from app.tracker.sources.anilist_schedule import parse_schedules
from app.tracker.sources.shikimori_chain import (
    SEASON_KINDS,
    AnimeSnapshot,
    Entry,
    assign_anilist_ids,
    build_snapshot,
    collect_entries,
    parse_entry,
)
from app.tracker.sources.tmdb_movies import Suggestion

SOURCE_KEY = "shikimori"
KIND = TitleKind.ANIME

RELEASED_STATUS = "released"  # Shikimori's word for an entry that has been out in full
NOT_FOR_SUGGESTIONS = frozenset({"pv", "cm", "music"})


class AniListIds(Protocol):
    async def get_anilist_ids(self, mal_ids: Sequence[int]) -> Mapping[int, int]:
        """AniList ids by MAL id; a MAL id AniList does not know is simply missing."""

    async def get_schedules(self, anilist_ids: Sequence[int], now: datetime) -> list[dict[str, Any]]:
        """Raw AniList records (status, episode count, next airing episode, airings of the 8 days before `now`, an
        aware moment) of the given entries."""


def parse_search(results: list[dict[str, Any]]) -> list[Suggestion]:
    """One suggestion per franchise, in the order the search found them. The entry shown is the earliest
    season among the hits (the franchise's name), or else the earliest hit; its id is what gets added."""
    groups: dict[str, list[Entry]] = {}
    for raw in results:
        entry = parse_entry(raw)
        if entry.kind in NOT_FOR_SUGGESTIONS:
            continue
        groups.setdefault(entry.franchise or f"single:{entry.id}", []).append(entry)

    def earliest(entries: list[Entry]) -> Entry:
        return min(entries, key=lambda e: (e.aired_on is None, e.aired_on or date.max))

    return [suggestion(earliest([e for e in entries if e.kind in SEASON_KINDS] or entries)) for entries in groups.values()]


def suggestion(entry: Entry) -> Suggestion:
    """The suggestion of an entry: adding it takes its whole chain."""
    return Suggestion(
        kind=KIND,
        external_id=entry.id,
        name=entry.display_name,
        original_name=entry.name,
        year=entry.aired_on.year if entry.aired_on else None,
        poster_path=entry.poster,
        released=entry.aired_on,
        other_names=tuple(name for name in (entry.russian, entry.english) if name),
    )


class ShikimoriAnimeSource:
    """Anime source of the tracker core, on top of a `ShikimoriClient`-like client and an AniList client."""

    source_key = SOURCE_KEY

    def __init__(
        self,
        shikimori,
        anilist: AniListIds | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._shikimori = shikimori
        self._anilist = anilist
        self._clock = clock  # the core's clock (aware): the airings of the last 8 days are counted back from it

    async def suggest(self, query: str) -> list[Suggestion]:
        return parse_search(await self._shikimori.search_anime(query, strict=True))

    async def suggest_by_id(self, external_id: str) -> Suggestion | None:
        """The entry of a Shikimori link as a suggestion (adding it takes its chain); None when Shikimori has none."""
        found = [parse_entry(raw) for raw in await self._shikimori.fetch_entries([external_id])]
        return next((suggestion(entry) for entry in found if entry.id == external_id), None)

    async def snapshot(self, external_id: str) -> AnimeSnapshot | None:
        """The franchise around the entry with this Shikimori id; None when Shikimori has no such entry.

        A failing Shikimori request fails the whole snapshot: a franchise stored without part of its chain
        would later look as if a season had been announced out of nowhere. A failing AniList only leaves
        the AniList ids empty (the next poll fills them in) and leaves the schedules out: the core then goes by what
        Shikimori says and by what it stored."""
        entries = await collect_entries(self._shikimori.fetch_entries, external_id)
        if external_id not in entries:
            return None
        snapshot = build_snapshot(entries)
        if snapshot is None:
            return None
        return await self._with_schedules(await self._with_anilist_ids(snapshot))

    async def _with_schedules(self, snapshot: AnimeSnapshot) -> AnimeSnapshot:
        """AniList's schedule of every part that is not over. A part that is over has nothing left to schedule."""
        if self._anilist is None:
            return snapshot
        asked = {p.ids.anilist: p.ids.shikimori for p in snapshot.parts if p.ids.anilist and p.status != RELEASED_STATUS}
        if not asked:
            return snapshot
        try:
            media = await self._anilist.get_schedules([int(anilist_id) for anilist_id in asked], self._clock())
        except Exception as exc:  # the schedule is a refinement: Shikimori's figures and the stored ones stand without it
            logging.warning("AniList schedules for anime %s not found: %r", snapshot.external_id, exc)
            return snapshot
        found = parse_schedules(media)
        return replace(snapshot, schedules={asked[i]: schedule for i, schedule in found.items() if i in asked})

    async def _with_anilist_ids(self, snapshot: AnimeSnapshot) -> AnimeSnapshot:
        if self._anilist is None:
            return snapshot
        entries = [*(p.ids for p in snapshot.parts), *(m.ids for m in snapshot.movies)]
        mal_ids = [int(i.mal) for i in entries if i.mal and i.mal.isdigit()]
        try:
            found = await self._anilist.get_anilist_ids(mal_ids)
        except Exception as exc:  # AniList is not needed to know the seasons
            logging.warning("AniList ids for anime %s not found: %r", snapshot.external_id, exc)
            return snapshot
        return assign_anilist_ids(snapshot, found)
