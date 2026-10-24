"""Seasons of a series: what the source says about them and how far each one has got.

Pure functions, no database and no network. Moments are naive UTC, like everywhere in the tracker.

An episode is out only once its moment has come; the status of a season is never stored, because it
changes with the clock alone. A season with no released episode is announced, however many stub episodes
the source lists for it. Season 0 (specials) is not a season and never gets here.
"""

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import datetime

ANNOUNCED = "announced"  # no episode is out yet
AIRING = "airing"  # some episodes are out and more are to come (or the total is unknown)
RELEASED = "released"  # every episode is out


@dataclass(frozen=True)
class Episode:
    number: int
    air_at: datetime | None  # None: the source has no date yet


@dataclass(frozen=True)
class Season:
    number: int  # 1 and up
    name: str
    expected: int | None  # episode count the source announces; None: unknown
    episodes: tuple[Episode, ...] = ()

    def released(self, now: datetime) -> int:
        return sum(1 for e in self.episodes if e.air_at is not None and e.air_at <= now)

    def total(self) -> int | None:
        """Episodes in the season; None when the source does not say. A listed episode alone proves nothing
        about the total: a weekly show lists only what is scheduled so far."""
        if not self.expected:
            return None
        return max(self.expected, len(self.episodes))

    def next_air_at(self, now: datetime) -> datetime | None:
        coming = [e.air_at for e in self.episodes if e.air_at is not None and e.air_at > now]
        return min(coming) if coming else None

    def first_air_at(self) -> datetime | None:
        dated = [e.air_at for e in self.episodes if e.air_at is not None]
        return min(dated) if dated else None

    def status(self, now: datetime) -> str:
        released = self.released(now)
        if released == 0:
            return ANNOUNCED
        total = self.total()
        return RELEASED if total is not None and released >= total else AIRING


@dataclass(frozen=True)
class SeasonProgress:
    """The line of the current season: «сезон 2: вышло 5 из 8, следующая — пн, 12 окт»."""

    number: int
    released: int
    total: int | None  # None is shown as «?»
    status: str
    next_air_at: datetime | None


@dataclass(frozen=True)
class SeasonAnnouncement:
    """A season with no released episode: «сезон 4 анонсирован»."""

    number: int
    first_air_at: datetime | None  # None: no date yet


@dataclass(frozen=True)
class SeasonsView:
    current: SeasonProgress | None  # the season on air, or the last one that has aired
    announced: SeasonAnnouncement | None  # the nearest announced season after it
    watched: tuple[int, ...] = ()


def summarize(seasons: Iterable[Season], watched: Collection[int], now: datetime) -> SeasonsView:
    ordered = sorted((s for s in seasons if s.number >= 1), key=lambda s: s.number)
    aired = [s for s in ordered if s.released(now) > 0]
    current = aired[-1] if aired else None
    after = [s for s in ordered if s.released(now) == 0 and (current is None or s.number > current.number)]
    return SeasonsView(
        current=SeasonProgress(
            current.number, current.released(now), current.total(), current.status(now), current.next_air_at(now)
        )
        if current
        else None,
        announced=SeasonAnnouncement(after[0].number, after[0].first_air_at()) if after else None,
        watched=tuple(sorted(n for n in watched if n >= 1)),
    )
