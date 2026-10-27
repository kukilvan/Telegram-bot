"""Seasons of a series: what the source says about them and how far each one has got.

Pure functions, no database and no network. Moments are naive UTC, like everywhere in the tracker.

An episode is out only once its moment has come; the status of a season is never stored, because it
changes with the clock alone. A season with no released episode is announced, however many stub episodes
the source lists for it. Season 0 (specials) is not a season and never gets here.

A season that airs in portions with a long break is split into parts: a gap between neighbouring episodes
that is longer than the threshold (`DEFAULT_PART_GAP` unless the owner changed it) starts a new part. A gap of
exactly the threshold does not. Parts are always worked out from the episode dates, never stored; a season
without such a gap is one part and nothing says «part» about it.

An anime season is the exception: its parts are separate entries of the source (`PartCut`), so they are given,
not worked out, and the threshold does not apply to it (a season of one entry is one part, whatever its dates).
"""

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

ANNOUNCED = "announced"  # no episode is out yet
AIRING = "airing"  # some episodes are out and more are to come (or the total is unknown)
RELEASED = "released"  # every episode is out

DEFAULT_PART_GAP = timedelta(weeks=6)


@dataclass(frozen=True)
class Episode:
    number: int
    air_at: datetime | None  # None: the source has no date yet


class _EpisodeRun:
    """What a season and a part of it have in common: a run of episodes and the count the source announces."""

    episodes: tuple[Episode, ...]
    expected: int | None  # episode count the source announces; None: unknown

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
class PartCut:
    """Where an anime season's part starts: the number of its first episode (counted through the whole season)
    and how many episodes the source announces for it (None: unknown)."""

    first_episode: int
    expected: int | None
    source_id: str | None = None  # the source's id of the entry behind the part; None: not known


@dataclass(frozen=True)
class Season(_EpisodeRun):
    number: int  # 1 and up; for an anime only the order of showing, the season is known by `source_id`
    name: str
    expected: int | None  # episode count the source announces; None: unknown
    episodes: tuple[Episode, ...] = ()
    cuts: tuple[PartCut, ...] = ()  # given parts, one per source entry; empty: parts follow the gaps
    source_id: str | None = None  # the source's id of the entry the season starts with; None: known by its number

    def parts(self, gap: timedelta = DEFAULT_PART_GAP) -> tuple["Part", ...]:
        """The season cut at every break longer than `gap`; always at least one part.

        An episode with no date yet stays with the part before it: a break is measured between dated episodes only."""
        if self.cuts:
            return self._given_parts()
        groups: list[list[Episode]] = [[]]
        previous: datetime | None = None
        for episode in sorted(self.episodes, key=lambda e: e.number):
            if episode.air_at is not None:
                if previous is not None and episode.air_at - previous > gap:
                    groups.append([])
                previous = episode.air_at
            groups[-1].append(episode)
        split = len(groups) > 1
        parts = []
        before = 0  # episodes in the parts already built
        for index, group in enumerate(groups):
            if index < len(groups) - 1:
                expected = len(group)  # a part that is followed by another one is complete as listed
            elif not split:
                expected = self.expected
            else:
                # the last part holds whatever the season announces beyond the earlier parts
                expected = self.expected - before if self.expected and self.expected > before else None
            parts.append(Part(self.number, index + 1, tuple(group), expected, split))
            before += len(group)
        return tuple(parts)

    def _given_parts(self) -> tuple["Part", ...]:
        ordered = sorted(self.cuts, key=lambda c: c.first_episode)
        parts = []
        for index, cut in enumerate(ordered):
            end = ordered[index + 1].first_episode if index + 1 < len(ordered) else None
            group = tuple(
                e for e in sorted(self.episodes, key=lambda e: e.number)
                if e.number >= cut.first_episode and (end is None or e.number < end)
            )
            parts.append(Part(self.number, index + 1, group, cut.expected, split=len(ordered) > 1))
        return tuple(parts)


@dataclass(frozen=True)
class Part(_EpisodeRun):
    """One portion of a season. `split` is False when the season has no break: then the part is the whole season."""

    season: int
    number: int  # 1 and up within the season
    episodes: tuple[Episode, ...]
    expected: int | None  # episodes of this part; None: unknown
    split: bool

    @property
    def numbers(self) -> frozenset[int]:
        return frozenset(e.number for e in self.episodes)

    def released_through(self, episode: int, now: datetime) -> int:
        """Episodes of the part that are out and not later than the given one."""
        return sum(1 for e in self.episodes if e.number <= episode and e.air_at is not None and e.air_at <= now)


@dataclass(frozen=True)
class SeasonProgress:
    """The line of the current season, or of its current part: «сезон 2: вышло 5 из 8, следующая — пн, 12 окт»."""

    number: int
    released: int
    total: int | None  # None is shown as «?»
    status: str
    next_air_at: datetime | None
    part: int | None = None  # None: the season has no parts
    next_part: int | None = None  # the part after this one, once this one is complete
    next_part_at: datetime | None = None


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


def _progress(season: Season, gap: timedelta, now: datetime) -> SeasonProgress:
    parts = season.parts(gap)
    current = [p for p in parts if p.released(now) > 0][-1]
    following = parts[current.number] if current.number < len(parts) else None
    return SeasonProgress(
        season.number,
        current.released(now),
        current.total(),
        current.status(now),
        current.next_air_at(now),
        part=current.number if current.split else None,
        next_part=following.number if following else None,
        next_part_at=following.first_air_at() if following else None,
    )


def summarize(
    seasons: Iterable[Season], watched: Collection[int], now: datetime, gap: timedelta = DEFAULT_PART_GAP
) -> SeasonsView:
    ordered = sorted((s for s in seasons if s.number >= 1), key=lambda s: s.number)
    aired = [s for s in ordered if s.released(now) > 0]
    current = aired[-1] if aired else None
    after = [s for s in ordered if s.released(now) == 0 and (current is None or s.number > current.number)]
    return SeasonsView(
        current=_progress(current, gap, now) if current else None,
        announced=SeasonAnnouncement(after[0].number, after[0].first_air_at()) if after else None,
        watched=tuple(sorted(n for n in watched if n >= 1)),
    )
