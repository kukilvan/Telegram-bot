"""Anime events: the episodes the two sources agree on, and the films of a franchise.

Pure functions, no database and no network. Moments are naive UTC, like everywhere in the tracker.

An anime goes through the same events as a series (`series_events`, with its own `Flavor`: the 🎌 icon, the `anime:`
key prefix and the owner's time zone, so a message gives the hour of an episode). What is different is where the
episodes come from. Shikimori says which seasons and parts exist and, roughly, how far each has got; AniList gives the
exact schedule of one entry. `assemble` puts them together:

- a part AniList has a schedule for takes its episodes from AniList: those already out are known by their number (and,
  when they aired in the last 8 days, by the moment they aired: exact), the next one by its moment (exact);
- a part AniList is expected to know but says nothing about this time (the service is down, the answer is empty or has
  a gap) keeps what was stored; Shikimori adds only the episodes that were not there. A source that fails to answer is
  never taken for a source that says «nothing is out», and the two cannot make the date flip back and forth;
- every other part (not known to AniList, or one AniList says has nothing out and no date) follows Shikimori, which is
  how a new season or part is noticed even when AniList has no data for it yet.

Every episode keeps where its moment comes from (`EpisodeTiming`). A date once recorded for an episode that is out stays
as it was, with its timing. An episode that is out now and was not stored before keeps the fresh moment when a source
named it exactly; otherwise it gets the moment of this look, as unknown: it came out after the previous look as far as
anyone can tell, and that is what makes it news (the first episode of a new season included), though not when (an
episode AniList says aired in the last 8 days is the exception: it has its own moment). At
adding there is nothing stored, and what is out is history. So is an entry the title never had when its day by
Shikimori is not later than the previous look: the chain grew behind the owner's back, nothing came out. An episode
not stored before whose exact airing is behind the previous look is not history but late news (`Assembled.late`, KI-83).
An approximate premiere (`Episode.rough`) has no moment, so the loops over the episodes out pass it by.

A season is known by the entry it starts with, not by its number: the source numbers the entries of the chain in order,
and when it adds, removes or regroups an entry the numbers move. `relayout` puts what is stored behind its entries in
the numbering of the fresh answer before anything is compared.

The events about the films of a franchise (announced, released) are decided here too; their samples and those of the
episodes for «Тестовое событие» are `anime_samples`.
"""

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, tzinfo
from typing import Any

from app.tracker.moment_words import NOT_ANNOUNCED, format_date
from app.tracker.kinds import KINDS
from app.tracker.models import EpisodeTiming, TitleKind
from app.tracker.movie_events import DetectedEvent, day_start
from app.tracker.seasons import Episode, PartCut, Season
from app.tracker.series_messages import Flavor
from app.tracker.sources.anilist_schedule import PartSchedule
from app.tracker.sources.shikimori_anime import RELEASED_STATUS
from app.tracker.sources.shikimori_chain import SeasonPart

_ICON = KINDS[TitleKind.ANIME].icon
KEY_PREFIX = TitleKind.ANIME.value  # the keys already stored start with the kind's value

MOVIE_ANNOUNCED = "anime_movie_announced"
MOVIE_RELEASED = "anime_movie_released"


def flavor(tz: tzinfo | None) -> Flavor:
    return Flavor(icon=_ICON, key_prefix=KEY_PREFIX, tz=tz)


# --- putting the two sources together --------------------------------------------------------------


def _scheduled(part: SeasonPart, schedule: PartSchedule, shikimori: Mapping[int, Episode], now: datetime) -> list[Episode]:
    """The episodes of a part as AniList's schedule tells them, in the season's numbering."""
    first = part.first_episode
    episodes = [
        _out(first + index, schedule.aired.get(index + 1), shikimori.get(first + index), now)
        for index in range(schedule.released)  # the airings are numbered inside the entry, from 1
    ]
    if schedule.next_episode:
        number = first + schedule.next_episode - 1
        if schedule.next_at is not None:
            episodes.append(Episode(number, schedule.next_at, EpisodeTiming.EXACT))
        else:  # AniList knows the number, not the moment: Shikimori's, with its timing
            episodes.append(shikimori.get(number, Episode(number, None)))
    return episodes


def _out(number: int, aired: datetime | None, shikimori: Episode | None, now: datetime) -> Episode:
    """An episode AniList counts as out, its moment taken in this order: its airing from AniList (exact), Shikimori's
    when that one is out (with its timing), else the moment of this look (unknown)."""
    if aired is not None and aired <= now:
        return Episode(number, aired, EpisodeTiming.EXACT)
    if shikimori is not None and shikimori.air_at is not None and shikimori.air_at <= now:
        return shikimori
    return Episode(number, now, EpisodeTiming.UNKNOWN)


def _usable(part: SeasonPart, schedule: PartSchedule) -> bool:
    """AniList numbers the episodes of an entry from 1. A count beyond what the part announces means it numbers on
    through the season, and then its figures do not mean what they are taken for."""
    if not part.episode_count or schedule.released is None:
        return True
    return schedule.released <= part.episode_count and (schedule.next_episode or 0) <= part.episode_count


def _inside(number: int, low: int, high: int | None) -> bool:
    """Whether an episode (in the season's numbering) belongs to the part that starts at `low`, the next one at `high`."""
    return number >= low and (high is None or number < high)


# --- what is stored, behind the entries it came from ---------------------------------------------


@dataclass(frozen=True)
class Relayout:
    """The stored seasons in the numbering of a fresh answer, and what the database has to do to match them."""

    seasons: tuple[Season, ...]  # in the fresh numbering; no season for an entry the title never had
    renumber: Mapping[int, int]  # number of a stored season -> its number now
    dissolved: Mapping[int, str | None]  # number of a stored season that starts no season now -> the entry it started with
    had: frozenset[str]  # the entries the title already had


def relayout(stored: Sequence[Season], parts: Sequence[SeasonPart]) -> Relayout:
    """Lay the stored seasons over a fresh chain.

    Every stored episode belongs to the entry (part) it was stored for, from that part's `first_episode` to the next
    one's, and is numbered inside the entry. It goes where its entry stands in the fresh answer, under the same number
    inside the entry; the episodes of an entry the answer no longer has are dropped. A stored season is the one that
    starts with an entry which starts a season in the fresh answer (it gets that season's number); a season whose
    first entry starts none any more is dissolved, its episodes having gone with their entries. A season stored with
    no parts (old data) is taken as it is, by its number.

    The announced counts and the parts of an old season stay as they were stored (what was known at the previous look),
    only moved to the fresh numbering.

    An answer with no entry at all says nothing about the seasons (a franchise left with its films, a source that came
    back empty): it is not taken for «every season is gone», nothing is moved or dissolved."""
    if not parts:
        had = {c.source_id for s in stored for c in s.cuts if c.source_id}
        return Relayout(tuple(stored), {s.number: s.number for s in stored}, {}, frozenset(had))
    placed = {p.ids.shikimori: p for p in parts}
    starts = {p.ids.shikimori: p.season for p in parts if p.number == 1}
    entries: dict[int, list[SeasonPart]] = {}
    for p in sorted(parts, key=lambda p: (p.season, p.number)):
        entries.setdefault(p.season, []).append(p)

    renumber: dict[int, int] = {}
    dissolved: dict[int, str | None] = {}
    had: set[str] = set()
    episodes: dict[int, dict[int, Episode]] = {}  # fresh season number -> episodes by number
    held: dict[int, dict[str, int | None]] = {}  # fresh season number -> stored entries there -> announced count
    names: dict[int, str] = {}  # fresh season number -> name of the stored season that is that season
    brought: dict[int, str] = {}  # ... or, failing that, of the first stored season that brought episodes there
    legacy: dict[int, Season] = {}

    for season in sorted(stored, key=lambda s: s.number):
        if not season.source_id or not season.cuts:
            renumber[season.number] = season.number
            legacy[season.number] = season
            continue
        number = starts.get(season.source_id)
        if number is None:
            dissolved[season.number] = season.source_id
        else:
            renumber[season.number] = number
            names[number] = season.name
        cuts = sorted(season.cuts, key=lambda c: c.first_episode)
        for index, cut in enumerate(cuts):
            if cut.source_id:
                had.add(cut.source_id)
            part = placed.get(cut.source_id)
            if part is None:
                continue
            end = cuts[index + 1].first_episode if index + 1 < len(cuts) else None
            held.setdefault(part.season, {})[cut.source_id] = cut.expected
            brought.setdefault(part.season, season.name)
            target = episodes.setdefault(part.season, {})
            for episode in season.episodes:
                if _inside(episode.number, cut.first_episode, end):
                    moved = part.first_episode + episode.number - cut.first_episode
                    target[moved] = replace(episode, number=moved)

    result: dict[int, Season] = {}
    for number in sorted(held):
        cuts = tuple(
            PartCut(p.first_episode, held[number][p.ids.shikimori], p.ids.shikimori)
            for p in entries[number]
            if p.ids.shikimori in held[number]
        )
        expected = sum(c.expected for c in cuts) if all(c.expected for c in cuts) else None
        result[number] = Season(
            number,
            names.get(number, brought[number]),
            expected,
            tuple(episodes[number][n] for n in sorted(episodes[number])),
            cuts,
            source_id=entries[number][0].ids.shikimori,
        )
    for number, season in legacy.items():
        result.setdefault(number, season)
    return Relayout(tuple(result[n] for n in sorted(result)), renumber, dissolved, frozenset(had))


# --- the seasons as they are known now -----------------------------------------------------------


def assemble(
    seasons: Sequence[Season],
    parts: Sequence[SeasonPart],
    schedules: Mapping[str, PartSchedule],
    previous: Sequence[Season] | None,
    now: datetime,
    anilist_known: Collection[str] = (),
    new_entries: Collection[str] = (),
    observed_at: datetime | None = None,
) -> "Assembled":
    """The seasons as they are known now, and the episodes found out late (`Assembled`). `parts` are the source entries
    behind the seasons (season, number, first_episode, status, ids), `schedules` AniList's answers by the Shikimori id of the part, `previous` the seasons
    stored at the last look, laid over the fresh chain (None at adding), `anilist_known` the Shikimori ids of the parts
    AniList has an id for, `new_entries` the Shikimori ids of the parts the title never had and `observed_at` the
    moment of the previous look: an episode of a new entry that was out by then is history."""
    before = {season.number: season for season in previous or ()}
    by_season: dict[int, list[SeasonPart]] = {}
    for part in sorted(parts, key=lambda p: (p.season, p.number)):
        by_season.setdefault(part.season, []).append(part)

    result = []
    late: list[tuple[int, int]] = []
    for season in seasons:
        old = {e.number: e for e in before[season.number].episodes} if season.number in before else {}
        shikimori = {e.number: e for e in season.episodes}
        final = dict(shikimori)
        entries = by_season.get(season.number, [])
        history = [  # the episodes of the entries the title never had: what was out at the previous look is not news
            (part.first_episode, entries[index + 1].first_episode if index + 1 < len(entries) else None)
            for index, part in enumerate(entries)
            if part.ids.shikimori in new_entries
        ]
        for index, part in enumerate(entries):
            if part.status == RELEASED_STATUS:
                continue
            low = part.first_episode
            high = entries[index + 1].first_episode if index + 1 < len(entries) else None
            sid = part.ids.shikimori
            schedule = schedules.get(sid)
            if schedule is not None and not _usable(part, schedule):
                schedule = None  # numbered on through the season: not the part's own numbering, so not to be trusted
            if schedule is not None and schedule.released is not None:
                built = _scheduled(part, schedule, shikimori, now)
                if built:
                    for number in [n for n in final if _inside(n, low, high)]:
                        del final[number]
                    final.update({e.number: e for e in built})
                # nothing out and no date: AniList has nothing to say about the schedule, Shikimori's days stand
            elif previous is not None and (sid in anilist_known or part.ids.anilist):
                final.update({n: e for n, e in old.items() if _inside(n, low, high)})  # expected, not heard: what was stored stays
        if previous is not None:
            for number, episode in list(final.items()):
                stored = old.get(number)
                if episode.air_at is None or episode.air_at > now:
                    continue
                if stored is not None and stored.air_at is not None and stored.air_at <= now:
                    final[number] = stored  # the first recorded moment of an episode that is out stays
                elif stored is None or stored.air_at is None:
                    if observed_at is not None and episode.air_at <= observed_at and any(
                        _inside(number, low, high) for low, high in history
                    ):
                        continue  # out before the previous look, in an entry the title never had: its own day stays
                    if episode.timing != EpisodeTiming.EXACT:  # found out now: a moment a source named stays
                        final[number] = Episode(number, now, EpisodeTiming.UNKNOWN)
                    elif observed_at is not None and episode.air_at <= observed_at:
                        late.append((season.number, number))  # aired before the previous look, seen only now (KI-83)
            for number, stored in old.items():
                if number not in final and stored.air_at is not None and stored.air_at <= now:
                    final[number] = stored  # a source that forgets an episode has not un-aired it
        result.append(replace(season, episodes=tuple(final[n] for n in sorted(final))))
    return Assembled(tuple(result), frozenset(late))


@dataclass(frozen=True)
class Assembled:
    """What `assemble` gives: the seasons as they are known now, and `late` — (season, episode) of every episode that
    was not stored (or stored with no moment), is out now with an exact moment not later than the previous look, and
    is not in an entry the title never had (KI-83, spec 5 of 9.1d). Such an episode aired while nobody saw it (a drop of
    several episodes, a lagging counter): its moment is behind the previous look, yet it is news. Empty at adding."""

    seasons: tuple[Season, ...]
    late: frozenset[tuple[int, int]] = frozenset()


# --- the films of a franchise ----------------------------------------------------------------------


def message_movie_announced(name: str, film: str, premiere: date | None) -> str:
    when = f"премьера: {format_date(premiere)}" if premiere else f"дата {NOT_ANNOUNCED}"
    return f"{_ICON} {name} — анонсирован фильм франшизы\n«{film}» · {when}"


def message_movie_released(name: str, film: str) -> str:
    return f"{_ICON} {name} — вышел фильм франшизы\n«{film}»"


def detect_movie_events(
    title_id: int, name: str, stored: Mapping[str, bool], movies: Iterable[Any], observed_on: date
) -> list[DetectedEvent]:
    """Films that appeared in the chain or came out since the previous look. `stored` maps the Shikimori id of each
    known film to «is out». A film already out that shows up in the chain with a day behind the previous look is
    history (the chain grew, the film did not just come out)."""
    events = []
    for film in movies:
        sid = film.ids.shikimori
        was = stored.get(sid)
        key = f"{KEY_PREFIX}:{title_id}:movie:{sid}"
        data = {"film": film.name, "shikimori_id": sid}
        if film.released and was is not True:
            if was is None and film.aired_on is not None and film.aired_on <= observed_on:
                continue
            happened_at = day_start(film.aired_on) if film.aired_on is not None else None
            events.append(
                DetectedEvent(
                    MOVIE_RELEASED, f"{key}:released", message_movie_released(name, film.name), data, happened_at=happened_at
                )
            )
        elif not film.released and was is None:
            events.append(
                DetectedEvent(
                    MOVIE_ANNOUNCED, f"{key}:announced", message_movie_announced(name, film.name, film.aired_on), data
                )
            )
    return events
