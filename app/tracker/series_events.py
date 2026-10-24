"""Series events: what changed between two looks at a series, how the message reads, how soon to look again.

Pure functions, no database and no network. Moments are naive UTC, like everywhere in the tracker.

The six events: season date announced, season started, episode out, season ended, next episode moved,
series closed or cancelled. An episode is reported as out only when its moment fell between the previous
look (`observed_at`) and now, so a series added in the middle of a season never announces old episodes as
news. The first episode of a season is reported as «сезон начался» and the last one as «сезон закончился»
instead of a second «вышла серия» message about the same fact.

TMDb gives the day of an episode, not the hour, so an episode counts as out from 00:00 UTC of its day.

An anime goes through the same code with its own `Flavor`: its icon, its key prefix and the owner's time zone, so
that its messages give the hour of an episode (TMDb knows only the day, and a series keeps the plain form).

Every dedup key holds the season (and the episode where there is one): the end of season 2 is not the end
of season 1, even when both have the same number of episodes.

A season that airs in parts (a break longer than the owner's threshold between two episodes, see `seasons`)
has its start and end told per part: «началась часть 2 сезона 3», «закончилась часть 1 сезона 3». The keys of
such a season carry the part (`s3:p1:ended`); a season without a break keeps the keys and texts it always had.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from typing import Any

from app.tracker.cards import NOT_ANNOUNCED, format_date, format_day_month, format_short_date, format_when, local_moment
from app.tracker.movie_events import (
    INTERVAL_NEAR,
    INTERVAL_QUIET,
    INTERVAL_SOON,
    INTERVAL_WAITING,
    NEAR,
    SOON,
    DetectedEvent,
)
from app.tracker.seasons import DEFAULT_PART_GAP, RELEASED as SEASON_RELEASED, Episode, Part, Season

ICON = "📺"

DATE_ANNOUNCED = "series_date_announced"
SEASON_STARTED = "series_season_started"
EPISODE_OUT = "series_episode_out"
SEASON_ENDED = "series_season_ended"
DATE_MOVED = "series_date_moved"
CLOSED = "series_closed"

# TMDb's status of the show, as the state keeps it, and what the owner is told
ENDED_STATUS = "Ended"
CANCELED_STATUS = "Canceled"
_CLOSED_STATUSES = (ENDED_STATUS, CANCELED_STATUS)


@dataclass(frozen=True)
class Flavor:
    """What differs between the kinds of title that share these events: the icon, the prefix of the dedup keys and
    whether the hour is told (and in which time zone)."""

    icon: str = ICON
    key_prefix: str = "series"
    tz: tzinfo | None = None  # None: the source knows only the day, so no hour is shown

    def day(self, moment: datetime) -> date:
        return local_moment(moment, self.tz).date()


SERIES = Flavor()


def is_closed(show_status: str | None) -> bool:
    """The source says the series will get no more seasons."""
    return show_status in _CLOSED_STATUSES


@dataclass(frozen=True)
class ShowState:
    """What is known about a series at one look: its seasons and the status the source gives the show."""

    seasons: tuple[Season, ...] = ()
    status: str | None = None  # None: not known yet (a look taken before series were polled)

    @classmethod
    def of(cls, seasons: Iterable[Season], state: dict[str, Any]) -> "ShowState":
        return cls(tuple(sorted(seasons, key=lambda s: s.number)), state.get("show_status"))

    def keeping_known(self, previous: "ShowState") -> "ShowState":
        """Gaps in the answer are not news. A source that returns no seasons, a season with no episodes or
        an episode without a date has failed to say something, not said that it is gone; what was known stays.
        A season missing from a non-empty answer is kept too, so a blip cannot announce it twice."""
        before = {s.number: s for s in previous.seasons}
        merged = {}
        for season in self.seasons:
            old = before.get(season.number)
            merged[season.number] = _keep_season(season, old) if old else season
        for number, old in before.items():
            merged.setdefault(number, old)
        return ShowState(tuple(sorted(merged.values(), key=lambda s: s.number)), self.status or previous.status)

    def to_state(self) -> dict[str, Any]:
        return {"show_status": self.status}


def _keep_season(new: Season, old: Season) -> Season:
    cuts = new.cuts or old.cuts  # the parts of an anime season are given, not worked out: they must not be lost
    if not new.episodes:
        return Season(new.number, new.name, new.expected or old.expected, old.episodes, cuts)
    known = {e.number: e.air_at for e in old.episodes}
    episodes = tuple(Episode(e.number, e.air_at or known.get(e.number)) for e in new.episodes)
    return Season(new.number, new.name, new.expected or old.expected, episodes, cuts)


def _episode(season: Season, number: int) -> Episode | None:
    return next((e for e in season.episodes if e.number == number), None)


def _total_text(season: Season | Part) -> str:
    total = season.total()
    return str(total) if total else "?"


def _next_line(season: Season | Part, now: datetime, flavor: Flavor = SERIES) -> str:
    coming = season.next_air_at(now)
    return f"следующая: {format_when(coming, flavor.tz) if coming else NOT_ANNOUNCED}"


def message_announced(name: str, season: int, premiere: datetime, part: int | None = None, flavor: Flavor = SERIES) -> str:
    what = f"сезона {season}" if part is None else f"части {part} сезона {season}"
    return f"{flavor.icon} {name} — объявлена дата {what}\nПремьера: {format_date(flavor.day(premiere))}"


def message_started(name: str, season: Season, episode: int, next_line: str | None, flavor: Flavor = SERIES) -> str:
    tail = f" · {next_line}" if next_line else ""
    return f"{flavor.icon} {name} — начался сезон {season.number}\nВышла серия {episode} из {_total_text(season)}{tail}"


def message_episode(name: str, season: Season, episode: int, next_line: str | None, flavor: Flavor = SERIES) -> str:
    tail = f" · {next_line}" if next_line else ""
    return f"{flavor.icon} {name} — вышла серия {episode} из {_total_text(season)}\nСезон {season.number}{tail}"


def message_ended(name: str, season: Season, episode: int, flavor: Flavor = SERIES) -> str:
    return f"{flavor.icon} {name} — сезон {season.number} закончился\nВышла последняя серия — {episode} из {_total_text(season)}"


def message_part_started(name: str, part: Part, episode: int, next_line: str | None, flavor: Flavor = SERIES) -> str:
    tail = f" · {next_line}" if next_line else ""
    return f"{flavor.icon} {name} — началась часть {part.number} сезона {part.season}\nВышла серия {episode}{tail}"


def message_part_episode(
    name: str, part: Part, episode: int, now: datetime, next_line: str | None, flavor: Flavor = SERIES
) -> str:
    tail = f" · {next_line}" if next_line else ""
    return (
        f"{flavor.icon} {name} — вышла серия {episode}\n"
        f"Сезон {part.season}, часть {part.number}: вышло {part.released_through(episode, now)} из {_total_text(part)}{tail}"
    )


def message_part_ended(name: str, part: Part, episode: int, following: Part | None, flavor: Flavor = SERIES) -> str:
    head = f"{flavor.icon} {name} — закончилась часть {part.number} сезона {part.season}\n"
    if following is None:
        return f"{head}Вышла последняя серия — {episode}"
    start = following.first_air_at()
    when = f"с {format_day_month(flavor.day(start))}" if start else NOT_ANNOUNCED
    return f"{head}Вышла последняя серия части — {episode}; часть {following.number} — {when}"


def message_moved(
    name: str,
    season: int,
    episode: int,
    old: datetime,
    new: datetime,
    premiere: bool,
    part: int | None = None,
    flavor: Flavor = SERIES,
) -> str:
    days = f"{format_short_date(flavor.day(old))} → {format_short_date(flavor.day(new))}"
    if premiere and part:
        return f"{flavor.icon} {name} — премьера части {part} сезона {season} перенесена\n{days}"
    if premiere:
        return f"{flavor.icon} {name} — премьера сезона {season} перенесена\n{days}"
    return (
        f"{flavor.icon} {name} — дата серии {episode} сдвинулась\n"
        f"Сезон {season} · {format_when(old, flavor.tz)} → {format_when(new, flavor.tz)}"
    )


def message_closed(name: str, status: str | None, last_season: int | None, flavor: Flavor = SERIES) -> str:
    verb = "отменён" if status == CANCELED_STATUS else "закрыт"
    tail = f"\nПоследний сезон — {last_season}" if last_season else ""
    return f"{flavor.icon} {name} — сериал {verb}{tail}"


def _newly_out(old: Season | None, new: Season, observed_at: datetime, now: datetime) -> list[int]:
    """Numbers of the episodes whose moment came after the previous look.

    An episode the source lists for the first time with a date already behind the previous look is a
    backfill of history, not an event."""
    out = []
    for episode in new.episodes:
        if episode.air_at is None or episode.air_at > now:
            continue
        before = _episode(old, episode.number) if old else None
        if before is not None:
            was_out = before.air_at is not None and before.air_at <= observed_at
        else:
            was_out = episode.air_at <= observed_at
        if not was_out:
            out.append(episode.number)
    return sorted(out)


def _old_first_air(old: Season, numbers: frozenset[int]) -> datetime | None:
    dated = [e.air_at for e in old.episodes if e.number in numbers and e.air_at is not None]
    return min(dated) if dated else None


def _ended_unseen(
    old: Season | None,
    old_part: Part | None,
    part: Part,
    parts: tuple[Part, ...],
    came: list[int],
    observed_at: datetime,
    now: datetime,
) -> bool:
    """A part that is complete only because the season was cut just now.

    The source dated the rest of the season after the last episode of this part was already out, so no episode
    comes out to say that the part has ended; the cut itself is the news."""
    if old is None or part.number >= len(parts) or part.status(now) != SEASON_RELEASED:
        return False
    if old_part is not None and old_part.status(observed_at) == SEASON_RELEASED:
        return False
    if any(episode in part.numbers for episode in came):
        return False  # an episode of the part came out now: the ordinary end of a part reports it
    out_before = {e.number for e in old.episodes if e.air_at is not None and e.air_at <= observed_at}
    return part.numbers <= out_before


def _season_events(
    prefix: str,
    name: str,
    old: Season | None,
    new: Season,
    observed_at: datetime,
    now: datetime,
    gap: timedelta,
    flavor: Flavor,
):
    events: list[DetectedEvent] = []
    number = new.number
    came = _newly_out(old, new, observed_at, now)
    season_key = f"{prefix}:s{number}"
    parts = new.parts(gap)
    old_parts = {p.number: p for p in old.parts(gap)} if old else {}
    unseen_ends = {
        p.number for p in parts if _ended_unseen(old, old_parts.get(p.number), p, parts, came, observed_at, now)
    }

    if not came and new.released(now) == 0:
        premiere = new.first_air_at()
        if premiere is not None:
            old_premiere = old.first_air_at() if old else None
            if old_premiere is None:
                events.append(
                    DetectedEvent(
                        DATE_ANNOUNCED,
                        f"{season_key}:date_announced",
                        message_announced(name, number, premiere, None, flavor),
                        {"season": number, "date": premiere.date().isoformat()},
                    )
                )

    if old is not None and old.released(observed_at) > 0:
        # the season was already running at the previous look: the date of a later part turning up now is news
        for part in parts[1:]:
            premiere = part.first_air_at()
            if part.number - 1 in unseen_ends:
                continue  # the end of the part before already tells when this one starts
            if part.released(now) == 0 and premiere is not None and _old_first_air(old, part.numbers) is None:
                events.append(
                    DetectedEvent(
                        DATE_ANNOUNCED,
                        f"{season_key}:p{part.number}:date_announced",
                        message_announced(name, number, premiere, part.number, flavor),
                        {"season": number, "part": part.number, "date": premiere.date().isoformat()},
                    )
                )

    moved = _moved(old, new, observed_at, now)
    if moved is not None:
        episode, old_at, new_at = moved
        part = next(p for p in parts if episode in p.numbers)
        premiere = episode == min(part.numbers) and part.released(now) == 0
        events.append(
            DetectedEvent(
                DATE_MOVED,
                f"{season_key}:e{episode}:moved:{_moment_key(new_at)}",  # the new date is part of the key
                message_moved(
                    name, number, episode, old_at, new_at, premiere, part.number if part.split else None, flavor
                ),
                {"season": number, "episode": episode, "old": old_at.date().isoformat(), "new": new_at.date().isoformat()},
            )
        )

    for part in parts:
        events.extend(
            _part_events(season_key, name, new, part, parts, old_parts.get(part.number), came, observed_at, now, flavor)
        )
        if part.number in unseen_ends:
            last = max(part.numbers)
            events.append(
                DetectedEvent(
                    SEASON_ENDED,
                    f"{season_key}:p{part.number}:ended",
                    message_part_ended(name, part, last, parts[part.number], flavor),
                    {"season": number, "episode": last, "part": part.number},
                )
            )
    return events


def _part_events(
    season_key: str,
    name: str,
    season: Season,
    part: Part,
    parts: tuple[Part, ...],
    old_part: Part | None,
    came: list[int],
    observed_at: datetime,
    now: datetime,
    flavor: Flavor,
):
    """Started, episode out and ended for one part (for the whole season when it has no break)."""
    events: list[DetectedEvent] = []
    mine = [episode for episode in came if episode in part.numbers]
    key = f"{season_key}:p{part.number}" if part.split else season_key
    was_over = old_part is not None and old_part.status(observed_at) == SEASON_RELEASED
    part_over = part.status(now) == SEASON_RELEASED
    first_number = min(part.numbers, default=None)
    nothing_out_before = old_part is None or old_part.released(observed_at) == 0
    following = parts[part.number] if part.number < len(parts) else None
    for episode in mine:
        latest = episode == mine[-1]  # only the latest of a batch says when the next one comes
        data = {"season": season.number, "episode": episode}
        if part.split:
            data["part"] = part.number
        opens = episode == first_number and nothing_out_before
        closes = latest and part_over and not was_over
        next_line = _next_line(part, now, flavor) if latest and not closes else None
        if opens:
            text = (
                message_part_started(name, part, episode, next_line, flavor)
                if part.split
                else message_started(name, season, episode, next_line, flavor)
            )
            events.append(DetectedEvent(SEASON_STARTED, f"{key}:started", text, data))
        if closes:
            text = (
                message_part_ended(name, part, episode, following, flavor)
                if part.split
                else message_ended(name, season, episode, flavor)
            )
            events.append(DetectedEvent(SEASON_ENDED, f"{key}:ended", text, data))
        elif not opens:
            text = (
                message_part_episode(name, part, episode, now, next_line, flavor)
                if part.split
                else message_episode(name, season, episode, next_line, flavor)
            )
            events.append(DetectedEvent(EPISODE_OUT, f"{season_key}:e{episode}:out", text, data))
    return events


def _moment_key(moment: datetime) -> str:
    """The day for a source that knows only the day (midnight), the day and the minute for one that knows the hour,
    so that a second move of an episode within the same day is a new fact."""
    if moment.time() == datetime.min.time():
        return moment.date().isoformat()
    return moment.strftime("%Y-%m-%dT%H%M")


def _only_the_hour_learned(before: datetime, after: datetime) -> bool:
    """A day-only date (midnight) that a finer source has now given an hour on the same day: nothing was moved."""
    return before.time() == datetime.min.time() and before.date() == after.date()


def _moved(
    old: Season | None, new: Season, observed_at: datetime, now: datetime
) -> tuple[int, datetime, datetime] | None:
    """The next dated episode of the previous look that is still ahead, when its date changed.

    An episode that has come out meanwhile is skipped: it is reported as out, and the move of the one after
    it is still news."""
    if old is None:
        return None
    for before in sorted((e for e in old.episodes if e.air_at is not None and e.air_at > observed_at), key=lambda e: e.number):
        current = _episode(new, before.number)
        if current is None or current.air_at is None or current.air_at <= now:
            continue
        if current.air_at == before.air_at or _only_the_hour_learned(before.air_at, current.air_at):
            return None
        return before.number, before.air_at, current.air_at
    return None


def detect_events(
    title_id: int,
    name: str,
    old: ShowState,
    new: ShowState,
    observed_at: datetime,
    now: datetime,
    gap: timedelta = DEFAULT_PART_GAP,
    flavor: Flavor = SERIES,
) -> list[DetectedEvent]:
    """Events between the previous look (taken at `observed_at`) and the new one (taken at `now`).

    `new` must already keep what the source dropped (`ShowState.keeping_known`). `gap` is the owner's break
    between two episodes after which a season counts as two parts; `flavor` says whose events these are.
    """
    prefix = f"{flavor.key_prefix}:{title_id}"
    before = {s.number: s for s in old.seasons}
    events: list[DetectedEvent] = []
    for season in new.seasons:
        events.extend(_season_events(prefix, name, before.get(season.number), season, observed_at, now, gap, flavor))

    if new.status in _CLOSED_STATUSES and old.status is not None and old.status not in _CLOSED_STATUSES:
        last = max((s.number for s in new.seasons), default=None)
        events.append(
            DetectedEvent(
                CLOSED,
                f"{prefix}:closed:{new.status.lower()}:s{last}",
                message_closed(name, new.status, last, flavor),
                {"status": new.status, "season": last},
            )
        )
    return events


def check_interval(show: ShowState, now: datetime) -> timedelta:
    """How long to wait before looking at this series again: often when an episode is near."""
    coming = [t for t in (s.next_air_at(now) for s in show.seasons) if t is not None]
    if coming:
        distance = min(coming) - now
        if distance <= SOON:
            return INTERVAL_SOON
        if distance <= NEAR:
            return INTERVAL_NEAR
        return INTERVAL_WAITING
    if show.status in _CLOSED_STATUSES:
        return INTERVAL_QUIET  # nothing more is expected
    return INTERVAL_WAITING  # a next episode or season may still be announced


_SAMPLE = "Укрытие"
_SAMPLE_SEASON = Season(2, "Сезон 2", 10)
_SAMPLE_DATE = datetime(2027, 7, 8)
# season 3 in two parts of eight episodes: part 1 in autumn, part 2 after the break
_SAMPLE_PARTS = Season(
    3,
    "Сезон 3",
    16,
    tuple(Episode(n, datetime(2026, 9, 7) + timedelta(weeks=n - 1)) for n in range(1, 9))
    + tuple(Episode(n, datetime(2027, 3, 29) + timedelta(weeks=n - 9)) for n in range(9, 17)),
).parts()

# (id, menu label, message text) of the sample events in «Тестовое событие»; the core turns them into menu entries
TEST_SAMPLES: list[tuple[str, str, str]] = [
    ("series-announced", "Сериал: объявлена дата сезона", message_announced(_SAMPLE, 4, _SAMPLE_DATE)),
    ("series-started", "Сериал: сезон начался", message_started(_SAMPLE, _SAMPLE_SEASON, 1, "следующая: пн, 12 окт")),
    ("series-episode", "Сериал: вышла серия", message_episode(_SAMPLE, _SAMPLE_SEASON, 6, "следующая: пн, 12 окт")),
    ("series-ended", "Сериал: сезон закончился", message_ended(_SAMPLE, _SAMPLE_SEASON, 10)),
    (
        "series-moved",
        "Сериал: дата серии сдвинулась",
        message_moved(_SAMPLE, 2, 7, datetime(2026, 10, 12), datetime(2026, 10, 19), premiere=False),
    ),
    (
        "series-part-announced",
        "Сериал: объявлена дата части",
        message_announced(_SAMPLE, 3, datetime(2027, 3, 29), part=2),
    ),
    (
        "series-part-started",
        "Сериал: началась часть сезона",
        message_part_started(_SAMPLE, _SAMPLE_PARTS[1], 9, "следующая: пн, 5 апр"),
    ),
    (
        "series-part-ended",
        "Сериал: закончилась часть сезона",
        message_part_ended(_SAMPLE, _SAMPLE_PARTS[0], 8, _SAMPLE_PARTS[1]),
    ),
    ("series-closed", "Сериал: закрыт", message_closed(_SAMPLE, ENDED_STATUS, 4)),
    ("series-canceled", "Сериал: отменён", message_closed(_SAMPLE, CANCELED_STATUS, 4)),
]

SAMPLE_EPISODES_ID = "series-two-episodes"
SAMPLE_EPISODES_LABEL = "Сериал: две серии подряд"


def sample_episode_events() -> list[tuple[str, dict[str, Any]]]:
    """Two episodes of one season as real «вышла серия» events (type and payload): a summary folds them into one line."""
    return [
        (EPISODE_OUT, {"text": message_episode(_SAMPLE, _SAMPLE_SEASON, 5, None), "season": 2, "episode": 5}),
        (
            EPISODE_OUT,
            {"text": message_episode(_SAMPLE, _SAMPLE_SEASON, 6, "следующая: пн, 12 окт"), "season": 2, "episode": 6},
        ),
    ]
