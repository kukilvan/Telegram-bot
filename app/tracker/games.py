"""The dates of a game: the release records of IGDB, which one is ours, backward compatibility and a lost date.

Pure: no database, no network. The country of the stores comes as a parameter (rule 2 of `docs/coding-standards.md`):
whoever needs the dates reads it from the settings. Everything that depends on a platform is read from the table of
`platforms` (rule 6).

The snapshot of a game holds every record of IGDB for the platforms the tracker knows, of every region (spec 4.3 of
part 6.1); which of them is the date of the owner is decided here each time the dates are read, so a new country in the
settings shows its dates at once and gives no messages (spec 5.2). Only the records of the regions of the country are its
dates: a day only in Japan is none (KI-35, spec 1.1 of stage 9.1b). A platform with several own IGDB numbers (ПК with
SteamVR, Meta Quest) takes the date that ends earliest among them (spec 2 of stage 6.5, ADR 0018); the snapshot remembers
which numbers the tracker knew when it was taken (`known`), so a number added later gives no events on the first poll
(spec 5 of stage 6.5). `GameState` also says whether the game is an expansion
and of which game (spec 3.3 of stage 6.3), and what IGDB says about Russian in it (`russian`, spec 5.5 of stage 9.1b).
"""

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Any

from app.tracker.movie_events import INTERVAL_NEAR, INTERVAL_QUIET, INTERVAL_SOON, INTERVAL_WAITING, NEAR, SOON
from app.tracker.platforms import IGDB_LABELS, PLATFORMS, STORE_COUNTRIES, Platform
from app.tracker.release_dates import ReleaseDate
from app.tracker.russian import NOT_ASKED, IgdbRussian, Support, igdb_from_state, igdb_state

# The types of a release record (`type` in the snapshot); other statuses of IGDB (alpha, beta, offline…) are not taken
FULL = "full"
EARLY = "early"
CANCELLED = "cancelled"
RELEASE_TYPES = (FULL, EARLY, CANCELLED)
DATED_TYPES = (FULL, EARLY)


def _earliest_first(game_date: ReleaseDate) -> tuple[bool, date]:
    """Sort key: the earlier start first, «not announced» last."""
    return (game_date.start is None, game_date.start or date.max)


@dataclass(frozen=True)
class Release:
    """One record of a date of IGDB in the snapshot: a platform and a region by their IGDB numbers, its type, its date."""

    platform: int
    region: int
    type: str
    date: ReleaseDate

    def state(self) -> dict[str, Any]:
        return {"platform": self.platform, "region": self.region, "type": self.type, "date": self.date.text}

    @classmethod
    def from_state(cls, data: Mapping[str, Any]) -> "Release":
        """Strict, like every text the tracker stored: an unknown type or a broken record raises ValueError."""
        release_type = data["type"]
        if release_type not in RELEASE_TYPES:
            raise ValueError(f"unknown type of a release: {release_type!r}")
        return cls(
            platform=int(data["platform"]), region=int(data["region"]), type=release_type, date=ReleaseDate.parse(data["date"])
        )


# The IGDB numbers the tracker knows now (`GameState.known` of a new snapshot), and the ones a snapshot without the key
# knew: the table before stage 6.5 (spec 5)
KNOWN_NOW: tuple[int, ...] = tuple(sorted(IGDB_LABELS))
KNOWN_BEFORE_6_5: tuple[int, ...] = (6, 48, 49, 130, 167, 169, 508)


# What an expansion is (`GameState.expansion`): one that needs its game (IGDB type 2) or one played alone (type 4)
EXPANSION = "expansion"
STANDALONE = "standalone"
EXPANSION_KINDS = (EXPANSION, STANDALONE)


def expansion_of(data: Any) -> str | None:
    """Only the key `expansion` of a stored own snapshot, strictly: not a mapping or an unknown kind raises ValueError
    (the follow-up check reads no more of it, so a spoiled date there does not stop the check)."""
    if not isinstance(data, Mapping):
        raise ValueError(f"not the state of a game: {data!r}")
    expansion = data.get("expansion")
    if expansion is not None and expansion not in EXPANSION_KINDS:
        raise ValueError(f"unknown kind of an expansion: {expansion!r}")
    return expansion


@dataclass(frozen=True)
class Parent:
    """The game an expansion belongs to: its IGDB id and its IGDB name."""

    id: str
    name: str

    def state(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name}

    @classmethod
    def from_state(cls, data: Any) -> "Parent":
        """Strict: a parent without a text `id` or `name` raises ValueError."""
        if not isinstance(data, Mapping) or not isinstance(data.get("id"), str) or not isinstance(data.get("name"), str):
            raise ValueError(f"not a parent game: {data!r}")
        return cls(data["id"], data["name"])


@dataclass(frozen=True)
class GameState:
    """The part of a game that changes over time, as the snapshot stores it (`source_snapshots.state`, source `igdb`).
    `expansion` and `parent` are set together, only for an expansion (spec 3.3 of stage 6.3), and stored only then.
    `russian` — what IGDB says about Russian (`russian.Support`), None — IGDB has no languages, `NOT_ASKED` — a
    snapshot from before stage 9.1b (no key). `known` — the IGDB numbers the tracker knew when the snapshot was taken
    (its `platforms` and `releases` hold only them); a snapshot without the key is from before stage 6.5."""

    steam_id: str | None = None
    ps_concept: str | None = None  # the number of the concept in PlayStation Store; None — a search is the link
    meta_store_id: str | None = None  # the number of the app in the Meta store; None — a search is the link
    platforms: tuple[int, ...] = ()  # the IGDB platforms the tracker knows, ascending
    releases: tuple[Release, ...] = ()
    expansion: str | None = None  # `EXPANSION`, `STANDALONE` or None: not an expansion
    parent: Parent | None = None
    russian: IgdbRussian = NOT_ASKED
    known: tuple[int, ...] = KNOWN_NOW  # ascending

    def state(self) -> dict[str, Any]:
        state = {"steam_id": self.steam_id, "ps_concept": self.ps_concept, "meta_store_id": self.meta_store_id}
        state["platforms"] = list(self.platforms)
        state["releases"] = [release.state() for release in self.releases]
        state["known"] = list(self.known)
        if self.expansion is not None:
            state["expansion"] = self.expansion
            state["parent"] = self.parent.state() if self.parent is not None else None
        state.update(igdb_state(self.russian))
        return state

    @classmethod
    def from_state(cls, data: Mapping[str, Any]) -> "GameState":
        """Strict: what the tracker stored; garbage raises. An unknown `expansion`, or a `parent` without `id` or `name`
        (or one without the other), or a `russian` that is no support raises ValueError."""
        expansion = expansion_of(data)
        raw_parent = data.get("parent")
        if (expansion is None) != (raw_parent is None):
            raise ValueError(f"an expansion and its parent go together: {expansion!r}, {raw_parent!r}")
        return cls(
            steam_id=data.get("steam_id"),
            ps_concept=data.get("ps_concept"),
            meta_store_id=data.get("meta_store_id"),
            platforms=tuple(int(number) for number in data.get("platforms") or ()),
            releases=tuple(Release.from_state(release) for release in data.get("releases") or ()),
            expansion=expansion,
            parent=Parent.from_state(raw_parent) if raw_parent is not None else None,
            russian=igdb_from_state(data),
            known=tuple(sorted(int(number) for number in data["known"])) if "known" in data else KNOWN_BEFORE_6_5,
        )

    def seen_as(self, known: Iterable[int]) -> "GameState":
        """The snapshot as a snapshot that knew only `known` would hold it: the platforms and the records of the other
        numbers left out (the first poll after a number was added, spec 5 of stage 6.5)."""
        numbers = set(known)
        return replace(
            self,
            platforms=tuple(number for number in self.platforms if number in numbers),
            releases=tuple(release for release in self.releases if release.platform in numbers),
            known=tuple(sorted(numbers)),
        )


def pick(releases: Iterable[Release], igdb_platform: int, release_type: str, regions: Sequence[int]) -> ReleaseDate | None:
    """The date of one IGDB platform and one type for a country whose regions are `regions` (spec 1.1 of stage 9.1b):
    the record of the first region that has one. A record of another region (Japan, Australia…) is no date of the
    country (KI-35). Two records of one region — the earlier start. None — the platform has no such record of this type."""
    found = [release for release in releases if release.platform == igdb_platform and release.type == release_type]
    for region in regions:
        of_region = [release.date for release in found if release.region == region]
        if of_region:
            return min(of_region, key=_earliest_first)
    return None


@dataclass(frozen=True)
class PlatformDate:
    """A date of a platform of the tracker; `via` («PS4») when it is the date of the older platform's version."""

    date: ReleaseDate
    via: str | None = None

    @property
    def label(self) -> str:
        """«27 марта 2015 (версия для PS4)»."""
        return f"{self.date.label} (версия для {self.via})" if self.via else self.date.label


@dataclass(frozen=True)
class PlatformDates:
    """The dates of a platform of the tracker: the full release and the early access (None — no record of the type);
    `cancelled` — the platform is cancelled and the older one gives no date to play by."""

    full: PlatformDate | None = None
    early: PlatformDate | None = None
    cancelled: bool = False


def igdb_numbers(platform: Platform) -> tuple[int, ...]:
    """The IGDB numbers of a platform of the tracker: its own ones and its older one's."""
    info = PLATFORMS[platform]
    return info.igdb_ids + (info.older.igdb_id,) if info.older else info.igdb_ids


def has_platform(game: GameState, platform: Platform) -> bool:
    """The game is on the platform: one of its own IGDB numbers or the number of its older platform is in `platforms`
    or in the records (spec 5.3)."""
    present = set(game.platforms) | {release.platform for release in game.releases}
    return any(number in present for number in igdb_numbers(platform))


def _soonest_end(game_date: ReleaseDate) -> tuple[bool, date, int]:
    """Sort key among the own numbers of a platform: the earlier end first; equal ends — the narrower one (the later
    start: «31 декабря 2026» before «2026»); «not announced» last."""
    if not game_date.announced:
        return (True, date.max, 0)
    return (False, game_date.end, -game_date.start.toordinal())


def own_date(
    releases: Iterable[Release], numbers: Sequence[int], release_type: str, regions: Sequence[int]
) -> ReleaseDate | None:
    """The own date of a platform of one type (spec 2 of stage 6.5): the date of each own number as `pick` reads it,
    then the one that ends earliest; None — no own number has a record of this type."""
    releases = tuple(releases)
    found = [dated for number in numbers if (dated := pick(releases, number, release_type, regions)) is not None]
    return min(found, key=_soonest_end) if found else None


def _better(own: ReleaseDate | None, older: ReleaseDate | None, older_label: str) -> PlatformDate | None:
    """The own date or the older platform's, whichever ends earlier («the game can surely be played by this day»: a
    year is no earlier than a day of it); the own one on a tie. «Not announced» of either loses to a date."""
    if older is None:
        return PlatformDate(own) if own is not None else None
    if own is None:
        return PlatformDate(older, older_label)
    if not older.announced:
        return PlatformDate(own)
    if not own.announced or older.end < own.end:
        return PlatformDate(older, older_label)
    return PlatformDate(own)


def platform_dates(game: GameState, platform: Platform, country: str) -> PlatformDates | None:
    """The dates of a platform of the tracker for the country of the stores `country` (a code of `STORE_COUNTRIES`);
    None — the game is not on the platform. Backward compatibility: a newer console runs the games of its older one,
    so the older date counts when it is earlier (spec 5.3)."""
    if not has_platform(game, platform):
        return None
    info = PLATFORMS[platform]
    regions = STORE_COUNTRIES[country].regions

    def dated(release_type: str) -> PlatformDate | None:
        own = own_date(game.releases, info.igdb_ids, release_type, regions)
        if info.older is None:
            return PlatformDate(own) if own is not None else None
        return _better(own, pick(game.releases, info.older.igdb_id, release_type, regions), info.older.label)

    full, early = dated(FULL), dated(EARLY)
    own_cancelled = is_cancelled(game, info.igdb_ids)
    return PlatformDates(full=full, early=early, cancelled=own_cancelled and full is None and early is None)


def is_cancelled(game: GameState, igdb_platforms: Collection[int]) -> bool:
    """IGDB numbers (the own ones of a platform) with records `cancelled` and, all together, none `full` or `early`."""
    types = {release.type for release in game.releases if release.platform in igdb_platforms}
    return CANCELLED in types and not types & set(DATED_TYPES)


def carry_over(previous: GameState, current: GameState) -> GameState:
    """A date the source stopped sending is not wiped out (spec 5.4): when an IGDB platform has no record of a type
    (`full`, `early`) in the new answer and had some in the previous snapshot, the previous records of that type move
    into the new one — unless the platform has records `cancelled` now. A «TBD» record is a record: it replaces the
    previous ones. A platform gone from `platforms` comes back too when it still has records. Russian that IGDB stopped
    sending stays as it was (spec 5.1 of stage 9.1b)."""
    if not isinstance(current.russian, Support) and isinstance(previous.russian, Support):
        current = replace(current, russian=previous.russian)
    carried: list[Release] = []
    for release in previous.releases:
        if release.type not in DATED_TYPES:
            continue
        types_now = {item.type for item in current.releases if item.platform == release.platform}
        if release.type not in types_now and CANCELLED not in types_now:
            carried.append(release)
    if not carried:
        return current
    releases = current.releases + tuple(carried)
    with_records = {release.platform for release in releases}
    back = {number for number in previous.platforms if number in with_records}
    return replace(current, releases=releases, platforms=tuple(sorted(set(current.platforms) | back)))


def released_by(game_date: ReleaseDate | None, day: date) -> bool:
    """An exact date not later than `day`: out by then. An approximate date is never out."""
    return game_date is not None and game_date.exact and game_date.start <= day


def check_interval(game: GameState, country: str, today: date) -> timedelta:
    """How long to wait before looking at the game again (spec 6.6), by the dates of all its platforms of the tracker,
    marked or not, for the country of the stores; the intervals of a film. A full release or an early access on an
    exact day within 2 days — an hour, within 14 — 6 hours; a later exact day, an approximate date or «not announced»
    on a platform that is not cancelled — a day; every such platform out (or all cancelled) — a week."""
    upcoming: list[date] = []
    waiting = False
    for platform in Platform:
        dates = platform_dates(game, platform, country)
        if dates is None or dates.cancelled:
            continue
        for dated in (dates.full, dates.early):
            if dated is not None and dated.date.exact and dated.date.start >= today:
                upcoming.append(dated.date.start)
        if not released_by(dates.full.date if dates.full else None, today):
            waiting = True
    if upcoming:
        distance = min(upcoming) - today
        if distance <= SOON:
            return INTERVAL_SOON
        if distance <= NEAR:
            return INTERVAL_NEAR
        return INTERVAL_WAITING
    return INTERVAL_WAITING if waiting else INTERVAL_QUIET
