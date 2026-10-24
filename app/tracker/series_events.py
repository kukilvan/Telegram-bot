"""Series events: what changed between two looks at a series, how the message reads, how soon to look again.

Pure functions, no database and no network. Moments are naive UTC, like everywhere in the tracker.

The six events: season date announced, season started, episode out, season ended, next episode moved,
series closed or cancelled. An episode is reported as out only when its moment fell between the previous
look (`observed_at`) and now, so a series added in the middle of a season never announces old episodes as
news. The first episode of a season is reported as «сезон начался» and the last one as «сезон закончился»
instead of a second «вышла серия» message about the same fact.

TMDb gives the day of an episode, not the hour, so an episode counts as out from 00:00 UTC of its day.

Every dedup key holds the season (and the episode where there is one): the end of season 2 is not the end
of season 1, even when both have the same number of episodes.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.tracker.cards import NOT_ANNOUNCED, format_date, format_short_date, format_weekday_date
from app.tracker.movie_events import (
    INTERVAL_NEAR,
    INTERVAL_QUIET,
    INTERVAL_SOON,
    INTERVAL_WAITING,
    NEAR,
    SOON,
    DetectedEvent,
)
from app.tracker.seasons import RELEASED as SEASON_RELEASED, Episode, Season

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
    if not new.episodes:
        return Season(new.number, new.name, new.expected or old.expected, old.episodes)
    known = {e.number: e.air_at for e in old.episodes}
    episodes = tuple(Episode(e.number, e.air_at or known.get(e.number)) for e in new.episodes)
    return Season(new.number, new.name, new.expected or old.expected, episodes)


def _episode(season: Season, number: int) -> Episode | None:
    return next((e for e in season.episodes if e.number == number), None)


def _total_text(season: Season) -> str:
    total = season.total()
    return str(total) if total else "?"


def _next_line(season: Season, now: datetime) -> str:
    coming = season.next_air_at(now)
    return f"следующая: {format_weekday_date(coming.date()) if coming else NOT_ANNOUNCED}"


def message_announced(name: str, season: int, premiere: datetime) -> str:
    return f"{ICON} {name} — объявлена дата сезона {season}\nПремьера: {format_date(premiere.date())}"


def message_started(name: str, season: Season, episode: int, next_line: str | None) -> str:
    tail = f" · {next_line}" if next_line else ""
    return f"{ICON} {name} — начался сезон {season.number}\nВышла серия {episode} из {_total_text(season)}{tail}"


def message_episode(name: str, season: Season, episode: int, next_line: str | None) -> str:
    tail = f" · {next_line}" if next_line else ""
    return f"{ICON} {name} — вышла серия {episode} из {_total_text(season)}\nСезон {season.number}{tail}"


def message_ended(name: str, season: Season, episode: int) -> str:
    return f"{ICON} {name} — сезон {season.number} закончился\nВышла последняя серия — {episode} из {_total_text(season)}"


def message_moved(name: str, season: int, episode: int, old: datetime, new: datetime, premiere: bool) -> str:
    if premiere:
        return f"{ICON} {name} — премьера сезона {season} перенесена\n{format_short_date(old.date())} → {format_short_date(new.date())}"
    return (
        f"{ICON} {name} — дата серии {episode} сдвинулась\n"
        f"Сезон {season} · {format_weekday_date(old.date())} → {format_weekday_date(new.date())}"
    )


def message_closed(name: str, status: str | None, last_season: int | None) -> str:
    verb = "отменён" if status == CANCELED_STATUS else "закрыт"
    tail = f"\nПоследний сезон — {last_season}" if last_season else ""
    return f"{ICON} {name} — сериал {verb}{tail}"


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


def _season_events(prefix: str, name: str, old: Season | None, new: Season, observed_at: datetime, now: datetime):
    events: list[DetectedEvent] = []
    number = new.number
    came = _newly_out(old, new, observed_at, now)
    season_key = f"{prefix}:s{number}"

    if not came and new.released(now) == 0:
        premiere = new.first_air_at()
        if premiere is not None:
            old_premiere = old.first_air_at() if old else None
            if old_premiere is None:
                events.append(
                    DetectedEvent(
                        DATE_ANNOUNCED,
                        f"{season_key}:date_announced",
                        message_announced(name, number, premiere),
                        {"season": number, "date": premiere.date().isoformat()},
                    )
                )

    moved = _moved(old, new, observed_at, now)
    if moved is not None:
        episode, old_at, new_at = moved
        premiere = episode == min(e.number for e in new.episodes) and new.released(now) == 0
        events.append(
            DetectedEvent(
                DATE_MOVED,
                f"{season_key}:e{episode}:moved:{new_at.date().isoformat()}",  # the new date is part of the key
                message_moved(name, number, episode, old_at, new_at, premiere),
                {"season": number, "episode": episode, "old": old_at.date().isoformat(), "new": new_at.date().isoformat()},
            )
        )

    was_over = old is not None and old.status(observed_at) == SEASON_RELEASED
    season_over = new.status(now) == SEASON_RELEASED
    first_number = min((e.number for e in new.episodes), default=None)
    nothing_out_before = old is None or old.released(observed_at) == 0
    for episode in came:
        latest = episode == came[-1]  # only the latest of a batch says when the next one comes
        data = {"season": number, "episode": episode}
        opens = episode == first_number and nothing_out_before
        closes = latest and season_over and not was_over
        next_line = _next_line(new, now) if latest and not closes else None
        if opens:
            events.append(
                DetectedEvent(SEASON_STARTED, f"{season_key}:started", message_started(name, new, episode, next_line), data)
            )
        if closes:
            events.append(DetectedEvent(SEASON_ENDED, f"{season_key}:ended", message_ended(name, new, episode), data))
        elif not opens:
            events.append(
                DetectedEvent(
                    EPISODE_OUT, f"{season_key}:e{episode}:out", message_episode(name, new, episode, next_line), data
                )
            )
    return events


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
        return (before.number, before.air_at, current.air_at) if current.air_at != before.air_at else None
    return None


def detect_events(title_id: int, name: str, old: ShowState, new: ShowState, observed_at: datetime, now: datetime) -> list[DetectedEvent]:
    """Events between the previous look (taken at `observed_at`) and the new one (taken at `now`).

    `new` must already keep what the source dropped (`ShowState.keeping_known`).
    """
    prefix = f"series:{title_id}"
    before = {s.number: s for s in old.seasons}
    events: list[DetectedEvent] = []
    for season in new.seasons:
        events.extend(_season_events(prefix, name, before.get(season.number), season, observed_at, now))

    if new.status in _CLOSED_STATUSES and old.status is not None and old.status not in _CLOSED_STATUSES:
        last = max((s.number for s in new.seasons), default=None)
        events.append(
            DetectedEvent(
                CLOSED,
                f"{prefix}:closed:{new.status.lower()}:s{last}",
                message_closed(name, new.status, last),
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
    ("series-closed", "Сериал: закрыт", message_closed(_SAMPLE, ENDED_STATUS, 4)),
    ("series-canceled", "Сериал: отменён", message_closed(_SAMPLE, CANCELED_STATUS, 4)),
]
