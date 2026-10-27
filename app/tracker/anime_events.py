"""Anime events: the episodes the two sources agree on, and the films of a franchise.

Pure functions, no database and no network. Moments are naive UTC, like everywhere in the tracker.

An anime goes through the same events as a series (`series_events`, with its own `Flavor`: the 🎌 icon, the `anime:`
key prefix and the owner's time zone, so a message gives the hour of an episode). What is different is where the
episodes come from. Shikimori says which seasons and parts exist and, roughly, how far each has got; AniList gives the
exact schedule of one entry. `assemble` puts them together:

- a part AniList has a schedule for takes its episodes from AniList: those already out are known by their number, the
  next one by its moment;
- a part AniList is expected to know but says nothing about this time (the service is down, the answer is empty or has
  a gap) keeps what was stored; Shikimori adds only the episodes that were not there. A source that fails to answer is
  never taken for a source that says «nothing is out», and the two cannot make the date flip back and forth;
- every other part (not known to AniList, or one AniList says has nothing out and no date) follows Shikimori, which is
  how a new season or part is noticed even when AniList has no data for it yet.

A date once recorded for an episode that is out stays as it was. An episode that is out now and was not stored before
gets the moment of this look: it came out after the previous look as far as anyone can tell, and that is what makes it
news (the first episode of a new season included). At adding there is nothing stored, and what is out is history. So is
an entry the title never had when its day by Shikimori is not later than the previous look: the chain grew behind the
owner's back, nothing came out.

A season is known by the entry it starts with, not by its number: the source numbers the entries of the chain in order,
and when it adds, removes or regroups an entry the numbers move. `relayout` puts what is stored behind its entries in
the numbering of the fresh answer before anything is compared.

The events about the films of a franchise (announced, released) are decided here too.
"""

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Any

from app.tracker import series_events
from app.tracker.cards import NOT_ANNOUNCED, format_date
from app.tracker.kinds import KINDS
from app.tracker.models import TitleKind
from app.tracker.movie_events import DetectedEvent
from app.tracker.seasons import Episode, PartCut, Season
from app.tracker.series_events import Flavor
from app.tracker.sources.anilist_schedule import PartSchedule
from app.tracker.sources.shikimori_anime import RELEASED_STATUS, SeasonPart

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
    episodes = []
    for index in range(schedule.released):
        number = first + index
        known = shikimori.get(number)
        episodes.append(Episode(number, known.air_at if known and known.air_at and known.air_at <= now else now))
    if schedule.next_episode:
        number = first + schedule.next_episode - 1
        at = schedule.next_at
        if at is None and number in shikimori:
            at = shikimori[number].air_at  # AniList knows the number, not the moment
        episodes.append(Episode(number, at))
    return episodes


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
                    target[moved] = Episode(moved, episode.air_at)

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
) -> tuple[Season, ...]:
    """The seasons as they are known now. `parts` are the source entries behind the seasons (season, number,
    first_episode, status, ids), `schedules` AniList's answers by the Shikimori id of the part, `previous` the seasons
    stored at the last look, laid over the fresh chain (None at adding), `anilist_known` the Shikimori ids of the parts
    AniList has an id for, `new_entries` the Shikimori ids of the parts the title never had and `observed_at` the
    moment of the previous look: an episode of a new entry that was out by then is history."""
    before = {season.number: season for season in previous or ()}
    by_season: dict[int, list[SeasonPart]] = {}
    for part in sorted(parts, key=lambda p: (p.season, p.number)):
        by_season.setdefault(part.season, []).append(part)

    result = []
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
                    final[number] = Episode(number, now)  # found out now
            for number, stored in old.items():
                if number not in final and stored.air_at is not None and stored.air_at <= now:
                    final[number] = stored  # a source that forgets an episode has not un-aired it
        result.append(replace(season, episodes=tuple(final[n] for n in sorted(final))))
    return tuple(result)


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
            events.append(DetectedEvent(MOVIE_RELEASED, f"{key}:released", message_movie_released(name, film.name), data))
        elif not film.released and was is None:
            events.append(
                DetectedEvent(
                    MOVIE_ANNOUNCED, f"{key}:announced", message_movie_announced(name, film.name, film.aired_on), data
                )
            )
    return events


# --- samples for «Тестовое событие» ------------------------------------------------------------------

_SAMPLE = "Магическая битва (Jujutsu Kaisen)"
_SAMPLE_TZ = timezone(timedelta(hours=3))  # a sample shows how an hour reads, not the owner's zone
_FLAVOR = flavor(_SAMPLE_TZ)
_SAMPLE_SEASON = Season(4, "Сезон 4", 12)
_NEXT = "следующая: пн, 12 окт в 18:00"
# season 3 in two parts of twelve episodes: part 1 in autumn, part 2 after the break
_PARTS = Season(
    3,
    "Сезон 3",
    24,
    tuple(Episode(n, datetime(2026, 10, 5, 9, 0) + timedelta(weeks=n - 1)) for n in range(1, 13))
    + tuple(Episode(n, datetime(2027, 4, 5, 9, 0) + timedelta(weeks=n - 13)) for n in range(13, 25)),
).parts(timedelta(weeks=6))

TEST_SAMPLES: list[tuple[str, str, str]] = [
    (
        "anime-announced",
        "Аниме: объявлена дата сезона",
        series_events.message_announced(_SAMPLE, 4, datetime(2027, 1, 10, 15, 0), flavor=_FLAVOR),
    ),
    (
        "anime-started",
        "Аниме: сезон начался",
        series_events.message_started(_SAMPLE, _SAMPLE_SEASON, 1, _NEXT, _FLAVOR),
    ),
    (
        "anime-episode",
        "Аниме: вышла серия",
        series_events.message_episode(_SAMPLE, _SAMPLE_SEASON, 6, _NEXT, _FLAVOR),
    ),
    (
        "anime-ended",
        "Аниме: сезон закончился",
        series_events.message_ended(_SAMPLE, _SAMPLE_SEASON, 12, _FLAVOR),
    ),
    (
        "anime-moved",
        "Аниме: дата серии сдвинулась",
        series_events.message_moved(
            _SAMPLE, 4, 7, datetime(2026, 10, 12, 15, 0), datetime(2026, 10, 19, 15, 0), premiere=False, flavor=_FLAVOR
        ),
    ),
    (
        "anime-part-episode",
        "Аниме: вышла серия части",
        series_events.message_part_episode(_SAMPLE, _PARTS[0], 6, datetime(2026, 11, 10), _NEXT, _FLAVOR),
    ),
    (
        "anime-part-announced",
        "Аниме: объявлена дата части",
        series_events.message_announced(_SAMPLE, 3, datetime(2027, 4, 5, 6, 0), part=2, flavor=_FLAVOR),
    ),
    (
        "anime-part-started",
        "Аниме: началась часть сезона",
        series_events.message_part_started(_SAMPLE, _PARTS[1], 13, "следующая: пн, 12 апр в 12:00", _FLAVOR),
    ),
    (
        "anime-part-ended",
        "Аниме: закончилась часть сезона",
        series_events.message_part_ended(_SAMPLE, _PARTS[0], 12, _PARTS[1], _FLAVOR),
    ),
    (
        "anime-movie-announced",
        "Аниме: анонсирован фильм франшизы",
        message_movie_announced(_SAMPLE, "Магическая битва: Фильм", date(2027, 2, 5)),
    ),
    (
        "anime-movie-released",
        "Аниме: вышел фильм франшизы",
        message_movie_released(_SAMPLE, "Магическая битва: Фильм"),
    ),
]
