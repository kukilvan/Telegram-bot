"""The franchise built from the chain of Shikimori entries (pure): the entry, the walk along the chain, the snapshot.

It holds an entry as Shikimori describes it, the walk along `prequel` and `sequel`, the seasons, their parts and the
films, and the snapshot of it all.

Responses in, data out; tested on saved real responses. From the entry the owner picked, the chain is followed through
`prequel` and `sequel` relations (nothing else: side stories, spin-offs and crossovers stay out). Of the entries on the chain:

- TV and ONA entries are seasons, in the order of the chain; an entry that is a continuation of the same
  season by its name («Part 2», «Cour 2», «2nd Cour») joins the season before it as its next part;
- movies are the movies of the franchise, kept apart from the seasons;
- everything else (OVA, specials, recaps, PV, music) is ignored, but still passes the chain on.

Only the original name is read for «Part N»: a Russian name may say «Часть 2» where the Japanese one starts a
new season (Jujutsu Kaisen: Shimetsu Kaiyuu - Kouhen is season 4).

Shikimori knows when a season started, how many episodes are out and when the next one comes, but not the day
of every past episode. The episodes that are out get the day the entry started, the next one its own moment, and
an entry with nothing out yet gets its premiere day as a stub for episode 1. The exact schedule is AniList's job.
Each episode says where its moment comes from (`EpisodeTiming`): the next one's is exact, the premiere stub's and the
first episode's start day (`airedOn`) is the day only, and every other episode out has no moment of its own (unknown),
as has each episode of an entry known only by the day it ended (`releasedOn`). Shikimori may know the premiere only
by its month or year (`airedOn` without `day`, KI-81): an entry with nothing out then gets the approximate stub
(`month` or `year`, no moment, `Episode.rough`), and the episodes out of such an entry are all unknown.
"""

import logging
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timezone
from typing import Any

from app.tracker.models import EpisodeTiming
from app.tracker.release_dates import NOT_ANNOUNCED, ReleaseDate
from app.tracker.seasons import Episode, PartCut, Season
from app.tracker.sources.anilist_schedule import PartSchedule
from app.tracker.sources.dates import parse_response_date

SEASON_KINDS = frozenset({"tv", "ona"})  # Shikimori's own kinds of catalogue entry, not our TitleKind
MOVIE_KIND = "movie"  # Shikimori's word too: a film among the entries of the chain
CHAIN_RELATIONS = ("prequel", "sequel")
MIN_SEASON_MINUTES = 10  # a shorter tv/ona entry is a chibi short, not a season; unknown length passes
MAX_ENTRIES = 200  # a chain longer than this is a runaway graph, not a franchise
BATCH = 50  # Shikimori's page limit

# «Part 2», «Cour 2» and «2nd Cour»; the number is in the first group or in the second
_PART_MARK = re.compile(r"\b(?:part|cour)\s*(\d+)\b|\b(\d+)(?:st|nd|rd|th)\s+cour\b", re.IGNORECASE)

FetchEntries = Callable[[Sequence[str]], Awaitable[list[dict[str, Any]]]]


@dataclass(frozen=True)
class SourceIds:
    """One entry's ids in the three services. Shikimori numbers its entries as MyAnimeList does."""

    shikimori: str
    mal: str | None
    anilist: str | None = None

    def with_anilist(self, anilist: Mapping[str, str]) -> "SourceIds":
        return replace(self, anilist=anilist.get(self.shikimori))


@dataclass(frozen=True)
class Entry:
    """One Shikimori record, as much of it as the franchise needs."""

    id: str
    mal_id: str | None
    name: str
    russian: str | None
    kind: str
    status: str
    episodes: int | None  # announced total; None: unknown
    out: int  # episodes out
    next_at: datetime | None  # naive UTC
    aired_on: date | None  # the day Shikimori gives, the first of the period when it knows only the month or the year
    released_on: date | None
    duration: int | None
    franchise: str | None
    poster: str | None
    genres: tuple[str, ...]
    chain: tuple[tuple[str, str], ...]  # (relation, other entry id), prequel and sequel only
    english: str | None = None  # an offer of «Входящие» matches by it too
    aired: ReleaseDate = NOT_ANNOUNCED  # the premiere as precisely as Shikimori knows it: a day, a month or a year

    @property
    def display_name(self) -> str:
        return self.russian or self.name

    @property
    def size(self) -> int:
        """Episodes the entry has or announces; the next part counts from here."""
        return self.episodes or self.out

    def ids(self) -> SourceIds:
        return SourceIds(self.id, self.mal_id)  # AniList ids come later (`assign_anilist_ids`)


@dataclass(frozen=True)
class SeasonPart:
    """The entry behind one part of a season (a season of one entry has one part)."""

    season: int
    number: int
    first_episode: int  # counted through the whole season
    episode_count: int | None
    ids: SourceIds
    status: str = ""  # Shikimori's: «anons», «ongoing» or «released»


@dataclass(frozen=True)
class FranchiseMovie:
    name: str
    aired_on: date | None
    released: bool
    ids: SourceIds


@dataclass(frozen=True)
class AnimeSnapshot:
    """What the source knows about an anime franchise right now."""

    external_id: str  # Shikimori id of the franchise's first season: the same whichever entry the owner picked
    name: str
    original_name: str
    year: int | None
    genres: list[str] = field(default_factory=list)
    poster_path: str | None = None
    overview: str | None = None
    seasons: list[Season] = field(default_factory=list)
    parts: list[SeasonPart] = field(default_factory=list)
    movies: list[FranchiseMovie] = field(default_factory=list)
    franchise: str | None = None  # Shikimori's franchise key; unconnected chains can share it, so it is no identity
    # AniList's schedule of each part that is not over, by the part's Shikimori id; a part AniList did not answer for is missing
    schedules: dict[str, PartSchedule] = field(default_factory=dict)

    def state(self) -> dict[str, Any]:
        """Seasons, parts and movies live in their own tables; the snapshot row keeps only the franchise key.
        No «closed» status: Shikimori does not say that a franchise is over."""
        return {"franchise": self.franchise}


# --- parsing ------------------------------------------------------------------------------------


def _date(block: Any) -> date | None:
    return parse_response_date((block or {}).get("date"))


def _moment(value: Any) -> datetime | None:
    """Shikimori gives the next episode with an offset («...+03:00»); the tracker keeps naive UTC."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def parse_entry(raw: dict[str, Any]) -> Entry:
    chain = tuple(
        (rel["relationKind"], str(rel["anime"]["id"]))
        for rel in raw.get("related") or []
        if rel.get("relationKind") in CHAIN_RELATIONS and rel.get("anime")
    )
    mal_id = raw.get("malId")
    return Entry(
        id=str(raw["id"]),
        mal_id=str(mal_id) if mal_id else None,
        name=raw.get("name") or "",
        russian=raw.get("russian") or None,
        kind=raw.get("kind") or "",
        status=raw.get("status") or "",
        episodes=raw.get("episodes") or None,
        out=raw.get("episodesAired") or 0,
        next_at=_moment(raw.get("nextEpisodeAt")),
        aired_on=_date(raw.get("airedOn")),
        released_on=_date(raw.get("releasedOn")),
        duration=raw.get("duration") or None,
        franchise=raw.get("franchise") or None,
        poster=((raw.get("poster") or {}).get("originalUrl")) or None,
        genres=tuple(g["russian"] for g in raw.get("genres") or [] if g.get("kind") == "genre" and g.get("russian")),
        chain=chain,
        english=raw.get("english") or None,
        aired=ReleaseDate.from_shikimori(raw.get("airedOn")),
    )


# --- the chain ----------------------------------------------------------------------------------


async def collect_entries(fetch: FetchEntries, start_id: str) -> dict[str, Entry]:
    """Every entry reachable from `start_id` through prequel and sequel relations. A failing `fetch` raises."""
    entries: dict[str, Entry] = {}
    requested = {start_id}
    frontier = [start_id]
    while frontier:
        batch, frontier = frontier[:BATCH], frontier[BATCH:]
        found = [parse_entry(raw) for raw in await fetch(batch)]
        for entry in found:
            entries[entry.id] = entry
        for entry in found:
            for _, other in entry.chain:
                if other not in requested:
                    requested.add(other)
                    frontier.append(other)
        if len(requested) > MAX_ENTRIES:
            logging.warning("anime chain from %s is longer than %d entries; cut off", start_id, MAX_ENTRIES)
            break
    return entries


def chain_order(entries: Mapping[str, Entry]) -> list[Entry]:
    """The entries from the beginning of the chain to its end: no entry before its prequel, and among those
    free to go the one that aired earlier first (an entry without a date goes after the dated ones)."""
    before: dict[str, set[str]] = {id_: set() for id_ in entries}
    for entry in entries.values():
        for relation, other in entry.chain:
            if other not in entries:
                continue
            if relation == "sequel":
                before[other].add(entry.id)
            else:
                before[entry.id].add(other)

    def key(entry: Entry):
        return (entry.aired_on is None, entry.aired_on or date.max, int(entry.id) if entry.id.isdigit() else 0)

    ordered: list[Entry] = []
    done: set[str] = set()
    remaining = dict(entries)
    while remaining:
        ready = [e for e in remaining.values() if before[e.id] <= done]
        if not ready:  # a loop in the relations: let the earliest go, whatever it waits for
            ready = list(remaining.values())
        entry = min(ready, key=key)
        ordered.append(entry)
        done.add(entry.id)
        del remaining[entry.id]
    return ordered


def _is_season(entry: Entry) -> bool:
    return entry.kind in SEASON_KINDS and not (entry.duration is not None and entry.duration < MIN_SEASON_MINUTES)


def _continues_season(entry: Entry) -> bool:
    """«Part 2», «Cour 2», «2nd Cour»: the entry goes on with the season before it. Part 1 starts a season."""
    match = _PART_MARK.search(entry.name)
    if not match:
        return False
    return int(match.group(1) or match.group(2)) >= 2


def group_seasons(ordered: Sequence[Entry]) -> tuple[list[list[Entry]], list[Entry]]:
    """(seasons as lists of the entries that make them, movies), both in chain order."""
    seasons: list[list[Entry]] = []
    movies: list[Entry] = []
    for entry in ordered:
        if _is_season(entry):
            if seasons and _continues_season(entry):
                seasons[-1].append(entry)
            else:
                seasons.append([entry])
        elif entry.kind == MOVIE_KIND:
            movies.append(entry)
    return seasons, movies


def _day(value: date) -> datetime:
    return datetime.combine(value, time.min)


def part_episodes(entry: Entry, first_episode: int) -> list[Episode]:
    """Episodes of one entry in the season's numbering, as far as Shikimori tells (see the module note)."""
    aired = entry.out
    if entry.status == "released" and not aired and entry.episodes:
        aired = entry.episodes  # a finished entry whose counter was never filled in
    started = entry.aired_on or entry.released_on
    known_day = entry.aired_on is not None and entry.aired.exact  # the first of a month is no day of episode 1
    episodes = [
        Episode(
            first_episode + i,
            _day(started) if started else None,
            EpisodeTiming.DAY if i == 0 and known_day else EpisodeTiming.UNKNOWN,
        )
        for i in range(aired)
    ]
    if entry.next_at is not None:
        episodes.append(Episode(first_episode + aired, entry.next_at, EpisodeTiming.EXACT))
    elif not aired and known_day:  # premiere day as a stub for episode 1
        episodes.append(Episode(first_episode, _day(entry.aired_on), EpisodeTiming.DAY))
    elif not aired and entry.aired.announced:  # known by the month or the year: the approximate stub, no moment
        episodes.append(Episode(first_episode, None, entry.aired.timing, rough=entry.aired))
    return episodes


def build_season(number: int, entries: Sequence[Entry]) -> tuple[Season, list[SeasonPart]]:
    episodes: list[Episode] = []
    cuts: list[PartCut] = []
    first_episode = 1
    for entry in entries:
        cuts.append(PartCut(first_episode, entry.episodes, entry.id))
        listed = part_episodes(entry, first_episode)
        episodes.extend(listed)
        first_episode += max(entry.size, len(listed), 1)  # the next part never starts inside this one
    expected = sum(e.episodes for e in entries) if all(e.episodes for e in entries) else None
    season = Season(
        number=number,
        name=entries[0].display_name,
        expected=expected,
        episodes=tuple(episodes),
        cuts=tuple(cuts),
        source_id=entries[0].id,
    )
    parts = [
        SeasonPart(number, index + 1, cut.first_episode, cut.expected, entry.ids(), entry.status)
        for index, (cut, entry) in enumerate(zip(cuts, entries))
    ]
    return season, parts


def build_snapshot(entries: Mapping[str, Entry]) -> AnimeSnapshot | None:
    """The franchise of the collected entries; None when none of them is a season or a movie."""
    ordered = chain_order(entries)
    grouped, movie_entries = group_seasons(ordered)
    if not grouped and not movie_entries:
        return None

    seasons: list[Season] = []
    parts: list[SeasonPart] = []
    for number, group in enumerate(grouped, start=1):
        season, season_parts = build_season(number, group)
        seasons.append(season)
        parts.extend(season_parts)
    movies = [
        FranchiseMovie(name=m.display_name, aired_on=m.aired_on, released=m.status != "anons", ids=m.ids())
        for m in movie_entries
    ]

    head = grouped[0][0] if grouped else movie_entries[0]
    franchise = next((e.franchise for e in [head, *ordered] if e.franchise), None)
    return AnimeSnapshot(
        external_id=head.id,
        name=head.display_name,
        original_name=head.name,
        year=head.aired_on.year if head.aired_on else None,
        genres=list(head.genres),
        poster_path=head.poster,
        seasons=seasons,
        parts=parts,
        movies=movies,
        franchise=franchise,
    )


def assign_anilist_ids(snapshot: AnimeSnapshot, by_mal: Mapping[int, int]) -> AnimeSnapshot:
    """Put AniList ids on the parts and movies. AniList sometimes holds two Shikimori entries as one record:
    the id then goes to the first of them only, so an id is never stored twice."""
    taken: set[int] = set()
    chosen: dict[str, str] = {}
    for ids in [p.ids for p in snapshot.parts] + [m.ids for m in snapshot.movies]:
        anilist_id = by_mal.get(int(ids.mal)) if ids.mal and ids.mal.isdigit() else None
        if anilist_id is None or anilist_id in taken:
            continue
        taken.add(anilist_id)
        chosen[ids.shikimori] = str(anilist_id)
    return replace(
        snapshot,
        parts=[replace(p, ids=p.ids.with_anilist(chosen)) for p in snapshot.parts],
        movies=[replace(m, ids=m.ids.with_anilist(chosen)) for m in snapshot.movies],
    )
