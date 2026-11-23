"""The rows of «Недавно» from the schedule (pure): what came out in its 7 days before adding or while in the archive,
and is not in the event log. KI-29, spec 2 of stage 9.1c.

The first check of a title, after adding and after «Вернуть в список», is a reference point and logs nothing, so the
log alone misses what came out just before it. The poller of each kind hands over what its schedule says came out in
the window (`Out`: an episode, or a film date); this module keeps what came out before the baseline and is not logged,
folds the episodes of one part of one season on one day, and writes the rows: «📺 Одни из нас — Сезон 2, серия 3» with
the grey line «вышла до добавления в список». Such a row has no hour and no buttons, and stands on the day of the
schedule (the one rule of `moment_words.episode_when`), not on the day it was found. Nothing is queued: the rows are made at
each read of the Feed.
"""

from collections.abc import Iterable, Mapping, Set
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, tzinfo
from enum import Enum, StrEnum
from typing import Any

from app.tracker import movie_events, series_events
from app.tracker.moment_words import episode_when
from app.tracker.feed_rows import BOTH, DIGITAL, RECENT_DAYS, THEATRICAL, FeedTitle, Piece, RecentRow, part_text
from app.tracker.kinds import KINDS
from app.tracker.models import EpisodeTiming
from app.tracker.seasons import Part, Season
from app.tracker.text import key as text_key

# the events that log an episode (anime use the same types) and a film date; the Feed reads them for the matching
EPISODE_TYPES = (series_events.SEASON_STARTED, series_events.EPISODE_OUT, series_events.SEASON_ENDED)


class FilmDate(StrEnum):
    """Which date of a film an `Out` is: its premiere in cinema or its digital release."""

    THEATRICAL = "theatrical"
    DIGITAL = "digital"


FILM_LABELS = {FilmDate.THEATRICAL: THEATRICAL, FilmDate.DIGITAL: DIGITAL}  # the words of a row (`feed_rows`)
FILM_TYPES = {movie_events.RELEASED: FilmDate.THEATRICAL, movie_events.DIGITAL: FilmDate.DIGITAL}
LOGGED_TYPES = (*EPISODE_TYPES, *FILM_TYPES)


class Reason(Enum):
    """Why the log does not have it: the title's baseline came after it. The grey line under the row says which."""

    BEFORE_ADDING = "до добавления в список"
    IN_ARCHIVE = "пока тайтл был в архиве"


@dataclass(frozen=True)
class Baseline:
    """When the checks of a title began from a reference point: its adding and its last return from the archive
    (naive UTC; None — never returned)."""

    added_at: datetime
    restored_at: datetime | None = None

    def reason(self, moment: datetime) -> Reason | None:
        """Why something out at `moment` is not in the log; None — it came out after the baseline (the log has it, or
        had it). Before adding wins over in the archive."""
        if moment <= self.added_at:
            return Reason.BEFORE_ADDING
        if self.restored_at is not None and moment <= self.restored_at:
            return Reason.IN_ARCHIVE
        return None


@dataclass(frozen=True)
class Out:
    """One episode or one film date that came out in the window of «Недавно», as the schedule of the title says."""

    title: FeedTitle
    day: date  # the day it stands on: the episode's day on the owner's clock (or the source's date), the film's date
    moment: datetime  # naive UTC, compared with the baseline: the episode's moment, the start of the film's day
    film: FilmDate | None = None  # which date of a film; None: an episode
    season: int = 0
    episode: int = 0
    part: Part | None = None  # the part of the season the episode belongs to (the card's parts)
    first: int = 0  # the first episode of its season: the premiere

    @property
    def logged_as(self) -> tuple[Any, ...]:
        """What an event of the log must name to be this: the title, and the season and episode or the film date."""
        return (self.title.id, self.film) if self.film is not None else (self.title.id, self.season, self.episode)


@dataclass(frozen=True)
class FeedParts:
    """What a poller hands the Feed for the titles of its kind: the pieces that come out from today on (`pieces`) and
    what the schedule says came out in the days of «Недавно» (`outs`)."""

    pieces: list[Piece] = field(default_factory=list)
    outs: list[Out] = field(default_factory=list)


def window(today: date) -> tuple[date, date]:
    """The first and the last day of «Недавно»: today − 6 and today."""
    return today - timedelta(days=RECENT_DAYS - 1), today


def season_outs(
    title: FeedTitle, seasons: Iterable[Season], gap: timedelta, tz: tzinfo | None, today: date, now: datetime
) -> list[Out]:
    """The episodes of a series or an anime out by `now` (naive UTC) whose day is in the window. An episode whose
    moment was found by a check (`unknown`) has no known day and is left out. `tz`: None for a kind whose source gives
    the day."""
    first_day, last_day = window(today)
    outs = []
    for season in seasons:
        if not season.episodes:
            continue
        first = min(e.number for e in season.episodes)
        for part in season.parts(gap):
            for episode in part.episodes:
                if episode.air_at is None or episode.timing == EpisodeTiming.UNKNOWN or episode.air_at > now:
                    continue
                day, _ = episode_when(episode, tz)
                if first_day <= day <= last_day:
                    outs.append(Out(title, day, episode.air_at, None, season.number, episode.number, part, first))
    return outs


def film_outs(title: FeedTitle, theatrical: date | None, digital: date | None, today: date) -> list[Out]:
    """The two dates of a film (the ones the card shows) that fall in the window."""
    first_day, last_day = window(today)
    return [
        Out(title, day, movie_events.day_start(day), film)
        for day, film in ((theatrical, FilmDate.THEATRICAL), (digital, FilmDate.DIGITAL))
        if day is not None and first_day <= day <= last_day
    ]


def logged(events: Iterable[tuple[int, str, Mapping[str, Any]]]) -> set[tuple[Any, ...]]:
    """What the log names, from its events of the window (title, type, payload): (title, season, episode) for an
    episode event, (title, film date) for a film one. The keys of `Out.logged_as`."""
    found: set[tuple[Any, ...]] = set()
    for title_id, type_, data in events:
        if type_ in FILM_TYPES:
            found.add((title_id, FILM_TYPES[type_]))
        elif type_ in EPISODE_TYPES and data.get("season") is not None and data.get("episode") is not None:
            found.add((title_id, data["season"], data["episode"]))
    return found


def _verb(members: list[Out]) -> str:
    """«вышла» (an episode, a premiere in cinema), «вышли» (several, or both film dates), «вышел» (a digital release)."""
    if len(members) > 1:
        return "вышли"
    return "вышел" if members[0].film == FilmDate.DIGITAL else "вышла"


def _what(members: list[Out]) -> str:
    first = members[0]
    if first.film is not None:
        return BOTH if len(members) > 1 else FILM_LABELS[first.film]
    return part_text(first.season, first.part, first.first, sorted(m.episode for m in members))


def _grey(reason: Reason, verb: str) -> str:
    return f"{verb} {reason.value}" if reason == Reason.BEFORE_ADDING else f"{verb}, {reason.value}"


def released_rows(
    outs: Iterable[Out], baselines: Mapping[int, Baseline], logged_keys: Set[tuple[Any, ...]]
) -> list[tuple[date, RecentRow]]:
    """The rows from the schedule, each with its day: what came out before the baseline of its title and is not in
    the log. The episodes of one part of one season of a title on one day with one reason are one row, and so are the
    two dates of a film. In a day: by name, then by title, then by season and first episode."""
    groups: dict[tuple[Any, ...], list[Out]] = {}
    for out in outs:
        baseline = baselines.get(out.title.id)
        reason = baseline.reason(out.moment) if baseline is not None else None
        if reason is None or out.logged_as in logged_keys:
            continue
        part = out.part.number if out.part is not None else 0
        groups.setdefault((out.title.id, out.day, reason, out.film is not None, out.season, part), []).append(out)
    rows = []
    for (_, day, reason, _, _, _), members in groups.items():
        members.sort(key=lambda m: (m.episode, m.film != FilmDate.THEATRICAL))
        first = members[0]
        headline = f"{KINDS[first.title.kind].icon} {first.title.name} — {_what(members)}"
        order = (text_key(first.title.name), first.title.id, first.season, first.episode)
        rows.append((day, order, RecentRow(first.title, headline, (_grey(reason, _verb(members)),), None)))
    rows.sort(key=lambda r: (r[0], r[1]))
    return [(day, row) for day, _, row in rows]
