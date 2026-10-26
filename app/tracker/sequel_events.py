"""Sequel announcements for an archived movie: what is new in its collection, how the message reads.

Pure functions, no database and no network. The first check after archiving only records what the
collection already holds, so sequels known at that moment are not announced as news. Nothing is added to
the list by this module: the owner presses «Следить» to add a sequel.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from app.tracker.cards import format_date
from app.tracker.kinds import KINDS
from app.tracker.models import TitleKind
from app.tracker.movie_events import DetectedEvent
from app.tracker.sources.dates import parse_date

SEQUEL_ANNOUNCED = "movie_sequel_announced"

_ICON = KINDS[TitleKind.MOVIE].icon

INTERVAL = timedelta(days=7)  # an archived movie is looked at once a week, and only for sequels


@dataclass(frozen=True)
class Part:
    id: str
    name: str
    date: date | None


@dataclass(frozen=True)
class Sequels:
    own_date: date | None = None
    parts: tuple[Part, ...] = ()

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> "Sequels":
        return cls(
            own_date=parse_date(state.get("own_date")),
            parts=tuple(Part(p["id"], p["title"], parse_date(p.get("date"))) for p in state.get("parts", [])),
        )

    def to_state(self) -> dict[str, Any]:
        return {
            "own_date": self.own_date.isoformat() if self.own_date else None,
            "parts": [  # the key "title" keeps its old name: snapshots already saved are read with it
                {"id": p.id, "title": p.name, "date": p.date.isoformat() if p.date else None} for p in self.parts
            ],
        }

    def keeping_known(self, previous: "Sequels") -> "Sequels":
        """A part the collection stopped listing is kept: a gap in the answer is not news, and when the
        part comes back it must not be announced a second time."""
        fresh = {p.id for p in self.parts}
        kept = tuple(p for p in previous.parts if p.id not in fresh)
        return Sequels(self.own_date or previous.own_date, self.parts + kept)

    def is_sequel(self, part: Part) -> bool:
        """A part is a sequel unless it is known to have come out before this movie."""
        return part.date is None or self.own_date is None or part.date > self.own_date


def message_sequel(name: str, sequel: str, premiere: date | None) -> str:
    return f"{_ICON} Анонсировано продолжение: {sequel}\nПродолжение фильма «{name}»\nПремьера: {format_date(premiere)}"


def detect_sequel_events(name: str, kind: TitleKind, old: Sequels, new: Sequels) -> list[DetectedEvent]:
    """Sequels in `new` that the previous snapshot did not hold. `new` must already keep the dropped parts."""
    known = {p.id for p in old.parts}
    return [
        DetectedEvent(
            SEQUEL_ANNOUNCED,
            f"movie:sequel:{part.id}",  # one announcement per sequel: not per archived movie of the franchise
            message_sequel(name, part.name, part.date),
            {
                "kind": kind.value,
                "sequel_id": part.id,
                "sequel_title": part.name,
                "date": part.date.isoformat() if part.date else None,
            },
        )
        for part in new.parts
        if part.id not in known and new.is_sequel(part)
    ]


# (id, menu label, message text) of the sample event in «Тестовое событие»
TEST_SAMPLES: list[tuple[str, str, str]] = [
    (
        "movie-sequel",
        "Фильм: анонсировано продолжение",
        message_sequel("Дюна: Часть третья", "Дюна: Часть четвёртая", date(2028, 12, 15)),
    ),
]
