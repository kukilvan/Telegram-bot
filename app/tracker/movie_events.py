"""Movie events: what changed between two snapshots, how the message reads, how soon to look again.

Pure functions, no database and no network. Dates are whole days; `today` comes from the core's clock.

The four events: premiere date announced, premiere moved, released in cinemas, digital release. A date
counts as "released" once it is not later than `today`. A release is reported only when the previous
snapshot was taken before that day, so a movie added after its premiere never announces it as news.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from app.tracker.cards import format_date, format_short_date
from app.tracker.dedup import moved_key
from app.tracker.kinds import KINDS
from app.tracker.models import TitleKind
from app.tracker.sources.dates import parse_date

_ICON = KINDS[TitleKind.MOVIE].icon

DATE_ANNOUNCED = "movie_date_announced"
DATE_MOVED = "movie_date_moved"
RELEASED = "movie_released"
DIGITAL = "movie_digital"

SOON = timedelta(days=2)
NEAR = timedelta(days=14)
INTERVAL_SOON = timedelta(hours=1)
INTERVAL_NEAR = timedelta(hours=6)
INTERVAL_WAITING = timedelta(hours=24)
INTERVAL_QUIET = timedelta(days=7)
RETRY_AFTER_FAILURE = timedelta(minutes=30)


@dataclass(frozen=True)
class MovieDates:
    theatrical: date | None = None
    digital: date | None = None

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> "MovieDates":
        return cls(parse_date(state.get("theatrical_date")), parse_date(state.get("digital_date")))

    def to_state(self) -> dict[str, str | None]:
        return {
            "theatrical_date": self.theatrical.isoformat() if self.theatrical else None,
            "digital_date": self.digital.isoformat() if self.digital else None,
        }

    def keeping_known(self, previous: "MovieDates") -> "MovieDates":
        """A date the source stopped reporting is kept: a gap in the answer is not news, and when
        the date comes back it must not be announced a second time."""
        return MovieDates(self.theatrical or previous.theatrical, self.digital or previous.digital)


@dataclass(frozen=True)
class DetectedEvent:
    type: str
    dedup_key: str
    text: str
    data: dict[str, Any]
    earlier_key: str | None = None  # the key an earlier version gave this fact; see `EventQueue.queued_since`


def _released_by(value: date | None, day: date) -> bool:
    return value is not None and value <= day


def message_announced(name: str, premiere: date) -> str:
    return f"{_ICON} {name} — объявлена дата премьеры\nПремьера в кино: {format_date(premiere)}"


def message_moved(name: str, old: date, new: date) -> str:
    return f"{_ICON} {name} — премьера перенесена\n{format_short_date(old)} → {format_short_date(new)}"


def message_released(name: str) -> str:
    return f"{_ICON} {name} — вышел в кино"


def message_digital(name: str) -> str:
    return f"{_ICON} {name} — вышел цифровой релиз"


def detect_events(
    title_id: int, name: str, old: MovieDates, new: MovieDates, observed_at: datetime, today: date
) -> list[DetectedEvent]:
    """Events between the previous snapshot (taken at `observed_at`) and the new one (taken `today`).

    `new` must already keep the dates the source dropped (`MovieDates.keeping_known`).
    """
    prefix = f"movie:{title_id}"
    events: list[DetectedEvent] = []
    observed_on = observed_at.date()

    was_in_cinemas = _released_by(old.theatrical, observed_on)
    if new.theatrical is not None and not was_in_cinemas:
        if new.theatrical <= today:
            events.append(
                DetectedEvent(RELEASED, f"{prefix}:released", message_released(name), {"date": new.theatrical.isoformat()})
            )
        elif old.theatrical is None:
            events.append(
                DetectedEvent(
                    DATE_ANNOUNCED,
                    f"{prefix}:date_announced",
                    message_announced(name, new.theatrical),
                    {"date": new.theatrical.isoformat()},
                )
            )
        elif new.theatrical != old.theatrical:
            earlier_key = f"{prefix}:date_moved:{new.theatrical.isoformat()}"
            events.append(
                DetectedEvent(
                    DATE_MOVED,
                    # the new date alone would hide a move back to a date reported before (15 Dec → 22 Jan → 15 Dec →
                    # 22 Jan); the look it is seen from tells a move found again after a failed save (the same stored
                    # look, the same key) from a new move (a later look)
                    moved_key(earlier_key, observed_at),
                    message_moved(name, old.theatrical, new.theatrical),
                    {"old": old.theatrical.isoformat(), "new": new.theatrical.isoformat()},
                    earlier_key,
                )
            )

    if new.digital is not None and new.digital <= today and not _released_by(old.digital, observed_on):
        events.append(
            DetectedEvent(DIGITAL, f"{prefix}:digital", message_digital(name), {"date": new.digital.isoformat()})
        )
    return events


def check_interval(dates: MovieDates, today: date) -> timedelta:
    """How long to wait before looking at this movie again: often when a release is near."""
    upcoming = [d for d in (dates.theatrical, dates.digital) if d is not None and d >= today]
    if upcoming:
        distance = min(upcoming) - today
        if distance <= SOON:
            return INTERVAL_SOON
        if distance <= NEAR:
            return INTERVAL_NEAR
        return INTERVAL_WAITING
    if dates.theatrical is None or dates.digital is None:
        return INTERVAL_WAITING  # something is still to be announced
    return INTERVAL_QUIET  # both dates are behind us


def check_interval_for_state(state: dict[str, Any], today: date) -> timedelta:
    return check_interval(MovieDates.from_state(state), today)


_SAMPLE = "Дюна: Часть третья"

# (id, menu label, message text) of the sample events in «Тестовое событие»; the core turns them into menu entries
TEST_SAMPLES: list[tuple[str, str, str]] = [
    ("movie-announced", "Фильм: объявлена дата", message_announced(_SAMPLE, date(2026, 12, 16))),
    ("movie-moved", "Фильм: премьера перенесена", message_moved(_SAMPLE, date(2026, 12, 15), date(2027, 1, 22))),
    ("movie-released", "Фильм: вышел в кино", message_released(_SAMPLE)),
    ("movie-digital", "Фильм: цифровой релиз", message_digital(_SAMPLE)),
]
