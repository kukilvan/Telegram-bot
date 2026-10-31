"""The dates of a game: what a date of IGDB is, which record is ours, backward compatibility and a lost date.

Pure: no database, no network. The country of the stores comes as a parameter (rule 2 of `docs/coding-standards.md`):
whoever needs the dates reads it from the settings. Everything that depends on a platform is read from the table of
`platforms` (rule 6).

The snapshot of a game holds every record of IGDB for the platforms the tracker knows, of every region (spec 4.3 of
part 6.1); which of them is the date of the owner is decided here each time the dates are read, so a new country in the
settings shows its dates at once and gives no messages (spec 5.2).
"""

import calendar
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Any

from app.tracker.cards import format_date
from app.tracker.movie_events import INTERVAL_NEAR, INTERVAL_QUIET, INTERVAL_SOON, INTERVAL_WAITING, NEAR, SOON
from app.tracker.platforms import PLATFORMS, STORE_COUNTRIES, Platform
from app.tracker.sources.dates import parse_date, response_day_of_timestamp

# The kinds of a release record (`type` in the snapshot); other statuses of IGDB (alpha, beta, offline…) are not taken
FULL = "full"
EARLY = "early"
CANCELLED = "cancelled"
RELEASE_TYPES = (FULL, EARLY, CANCELLED)
DATED_TYPES = (FULL, EARLY)

_MONTHS = (
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
)
NOT_ANNOUNCED_LABEL = "дата не объявлена"

# `date_format` of IGDB: 0 a day, 1 a month, 2 a year, 3–6 the quarters 1–4, 7 «TBD»
_IGDB_DAY, _IGDB_MONTH, _IGDB_YEAR = 0, 1, 2
_IGDB_QUARTERS = range(3, 7)
_QUARTER_SHIFT = 2  # quarter = format − 2

_MONTH_TEXT = re.compile(r"(\d{4})-(\d{2})")
_QUARTER_TEXT = re.compile(r"(\d{4})-Q([1-4])")
_YEAR_TEXT = re.compile(r"\d{4}")
_DAY_TEXT = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class GameDate:
    """A year and one of: a day, a month, a quarter or nothing (only the year). No year at all — «not announced»."""

    year: int | None = None
    month: int | None = None
    day: int | None = None
    quarter: int | None = None

    @classmethod
    def parse(cls, text: str | None) -> "GameDate":
        """What the tracker stored: «2027-03-12», «2027-03», «2027-Q4», «2027» or None. Strict: garbage raises
        ValueError (rule 9); the day is read by `parse_date`."""
        if text is None:
            return NOT_ANNOUNCED
        if not isinstance(text, str):
            raise ValueError(f"not the text of a game date: {text!r}")
        if match := _QUARTER_TEXT.fullmatch(text):
            return cls(year=int(match[1]), quarter=int(match[2]))
        if match := _MONTH_TEXT.fullmatch(text):
            month = int(match[2])
            if not 1 <= month <= 12:
                raise ValueError(f"no such month: {text!r}")
            return cls(year=int(match[1]), month=month)
        if _YEAR_TEXT.fullmatch(text):
            return cls(year=int(text))
        if not _DAY_TEXT.fullmatch(text):
            raise ValueError(f"not the text of a game date: {text!r}")
        day = parse_date(text)
        return cls(year=day.year, month=day.month, day=day.day)

    @classmethod
    def from_igdb(cls, release: Mapping[str, Any]) -> "GameDate":
        """A record of `release_dates` as IGDB sent it. Soft: garbage is «not announced». `y` and `m` are read, and only
        when they are missing — from `date` (UTC): for a date without a day `date` is not the start of the period (a
        year is its 31 December, a quarter its last day), but its year and the month of a month are right."""
        form = release.get("date_format")
        day = response_day_of_timestamp(release.get("date"))
        if form == _IGDB_DAY:
            return cls(year=day.year, month=day.month, day=day.day) if day else NOT_ANNOUNCED
        year = _whole(release.get("y"), 1, 9999) or (day.year if day else None)
        if year is None:
            return NOT_ANNOUNCED
        if form == _IGDB_MONTH:
            month = _whole(release.get("m"), 1, 12) or (day.month if day else None)
            return cls(year=year, month=month) if month else NOT_ANNOUNCED
        if form == _IGDB_YEAR:
            return cls(year=year)
        if form in _IGDB_QUARTERS:
            return cls(year=year, quarter=form - _QUARTER_SHIFT)
        return NOT_ANNOUNCED  # 7 «TBD», nothing or a format IGDB has not had before

    @property
    def announced(self) -> bool:
        return self.year is not None

    @property
    def exact(self) -> bool:
        """Only a day is exact; a month, a quarter and a year are an approximate date: seen, but no messages."""
        return self.day is not None

    @property
    def text(self) -> str | None:
        """As the snapshot stores it."""
        if self.year is None:
            return None
        if self.day is not None:
            return date(self.year, self.month, self.day).isoformat()
        if self.month is not None:
            return f"{self.year:04d}-{self.month:02d}"
        if self.quarter is not None:
            return f"{self.year:04d}-Q{self.quarter}"
        return f"{self.year:04d}"

    @property
    def label(self) -> str:
        """«12 марта 2027», «март 2027», «4 квартал 2026», «2027», «дата не объявлена»."""
        if self.year is None:
            return NOT_ANNOUNCED_LABEL
        if self.day is not None:
            return format_date(date(self.year, self.month, self.day))
        if self.month is not None:
            return f"{_MONTHS[self.month - 1]} {self.year}"
        if self.quarter is not None:
            return f"{self.quarter} квартал {self.year}"
        return str(self.year)

    @property
    def start(self) -> date | None:
        """The first day of the period; None — not announced."""
        if self.year is None:
            return None
        if self.day is not None:
            return date(self.year, self.month, self.day)
        if self.month is not None:
            return date(self.year, self.month, 1)
        if self.quarter is not None:
            return date(self.year, 3 * self.quarter - 2, 1)
        return date(self.year, 1, 1)

    @property
    def end(self) -> date | None:
        """The last day of the period; None — not announced."""
        if self.year is None:
            return None
        if self.day is not None:
            return date(self.year, self.month, self.day)
        last_month = self.month or (3 * self.quarter if self.quarter else 12)
        return date(self.year, last_month, calendar.monthrange(self.year, last_month)[1])


NOT_ANNOUNCED = GameDate()


def _whole(value: Any, low: int, high: int) -> int | None:
    """A whole number from a service's answer within its bounds; anything else is None."""
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        return None
    return value


def _earliest_first(game_date: GameDate) -> tuple[bool, date]:
    """Sort key: the earlier start first, «not announced» last."""
    return (game_date.start is None, game_date.start or date.max)


@dataclass(frozen=True)
class Release:
    """One record of a date of IGDB in the snapshot: a platform and a region by their IGDB numbers, its kind, its date."""

    platform: int
    region: int
    type: str
    date: GameDate

    def state(self) -> dict[str, Any]:
        return {"platform": self.platform, "region": self.region, "type": self.type, "date": self.date.text}

    @classmethod
    def from_state(cls, data: Mapping[str, Any]) -> "Release":
        """Strict, like every text the tracker stored: an unknown kind or a broken record raises ValueError."""
        kind = data["type"]
        if kind not in RELEASE_TYPES:
            raise ValueError(f"unknown kind of a release: {kind!r}")
        return cls(platform=int(data["platform"]), region=int(data["region"]), type=kind, date=GameDate.parse(data["date"]))


@dataclass(frozen=True)
class GameState:
    """The part of a game that changes over time, as the snapshot stores it (`source_snapshots.state`, source `igdb`)."""

    steam_id: str | None = None
    ps_concept: str | None = None  # the number of the concept in PlayStation Store; None — a search is the link
    platforms: tuple[int, ...] = ()  # the IGDB platforms the tracker knows, ascending
    releases: tuple[Release, ...] = ()

    def state(self) -> dict[str, Any]:
        return {
            "steam_id": self.steam_id,
            "ps_concept": self.ps_concept,
            "platforms": list(self.platforms),
            "releases": [release.state() for release in self.releases],
        }

    @classmethod
    def from_state(cls, data: Mapping[str, Any]) -> "GameState":
        """Strict: what the tracker stored; garbage raises."""
        return cls(
            steam_id=data.get("steam_id"),
            ps_concept=data.get("ps_concept"),
            platforms=tuple(int(number) for number in data.get("platforms") or ()),
            releases=tuple(Release.from_state(release) for release in data.get("releases") or ()),
        )


def pick(releases: Iterable[Release], igdb_platform: int, kind: str, regions: Sequence[int]) -> GameDate | None:
    """The date of one IGDB platform and one kind for a country whose regions are `regions` (spec 5.2): the record of
    the first region that has one, else the earliest of the others («not announced» last). Two records of one region —
    the earlier start. None — the platform has no record of this kind."""
    found = [release for release in releases if release.platform == igdb_platform and release.type == kind]
    for region in regions:
        of_region = [release.date for release in found if release.region == region]
        if of_region:
            return min(of_region, key=_earliest_first)
    return min((release.date for release in found), key=_earliest_first) if found else None


@dataclass(frozen=True)
class PlatformDate:
    """A date of a platform of the tracker; `version_of` («PS4») when it is the date of the older platform's version."""

    date: GameDate
    version_of: str | None = None

    @property
    def label(self) -> str:
        """«27 марта 2015 (версия для PS4)»."""
        return f"{self.date.label} (версия для {self.version_of})" if self.version_of else self.date.label


@dataclass(frozen=True)
class PlatformDates:
    """The dates of a platform of the tracker: the full release and the early access (None — no record of the kind);
    `cancelled` — the platform is cancelled and the older one gives no date to play by."""

    full: PlatformDate | None = None
    early: PlatformDate | None = None
    cancelled: bool = False


def _igdb_numbers(platform: Platform) -> tuple[int, ...]:
    info = PLATFORMS[platform]
    return (info.igdb_id, info.older.igdb_id) if info.older else (info.igdb_id,)


def has_platform(game: GameState, platform: Platform) -> bool:
    """The game is on the platform: its IGDB number or the number of its older platform is in `platforms` or in the
    records (spec 5.3)."""
    present = set(game.platforms) | {release.platform for release in game.releases}
    return any(number in present for number in _igdb_numbers(platform))


def _better(own: GameDate | None, older: GameDate | None, older_label: str) -> PlatformDate | None:
    """The own date or the older platform's, whichever starts earlier; the own one on a tie. «Not announced» of
    either loses to a date."""
    if older is None:
        return PlatformDate(own) if own is not None else None
    if own is None:
        return PlatformDate(older, older_label)
    if not older.announced:
        return PlatformDate(own)
    if not own.announced or older.start < own.start:
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

    def dated(kind: str) -> PlatformDate | None:
        own = pick(game.releases, info.igdb_id, kind, regions)
        if info.older is None:
            return PlatformDate(own) if own is not None else None
        return _better(own, pick(game.releases, info.older.igdb_id, kind, regions), info.older.label)

    full, early = dated(FULL), dated(EARLY)
    own_cancelled = is_cancelled(game, info.igdb_id)
    return PlatformDates(full=full, early=early, cancelled=own_cancelled and full is None and early is None)


def is_cancelled(game: GameState, igdb_platform: int) -> bool:
    """An IGDB platform with records `cancelled` and none `full` or `early`."""
    kinds = {release.type for release in game.releases if release.platform == igdb_platform}
    return CANCELLED in kinds and not kinds & set(DATED_TYPES)


def carry_over(previous: GameState, current: GameState) -> GameState:
    """A date the source stopped sending is not wiped out (spec 5.4): when an IGDB platform has no record of a kind
    (`full`, `early`) in the new answer and had some in the previous snapshot, the previous records of that kind move
    into the new one — unless the platform has records `cancelled` now. A «TBD» record is a record: it replaces the
    previous ones. A platform gone from `platforms` comes back too when it still has records."""
    carried: list[Release] = []
    for release in previous.releases:
        if release.type not in DATED_TYPES:
            continue
        kinds_now = {item.type for item in current.releases if item.platform == release.platform}
        if release.type not in kinds_now and CANCELLED not in kinds_now:
            carried.append(release)
    if not carried:
        return current
    releases = current.releases + tuple(carried)
    with_records = {release.platform for release in releases}
    back = {number for number in previous.platforms if number in with_records}
    return replace(current, releases=releases, platforms=tuple(sorted(set(current.platforms) | back)))


def released_by(game_date: GameDate | None, day: date) -> bool:
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
