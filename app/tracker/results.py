"""What the tracker core hands back to its callers. Plain data, no database. Re-exported by `core`."""

from dataclasses import dataclass
from datetime import datetime

from app.tracker.models import TitleKind, TitleStatus


@dataclass(frozen=True)
class AddResult:
    title_id: int
    created: bool  # False: the title was already in the list and is simply opened


@dataclass(frozen=True)
class WatchedResult:
    changed: bool  # False: the movie was already watched


@dataclass(frozen=True)
class DeleteResult:
    name: str  # the title that was removed, for the message to the owner


@dataclass(frozen=True)
class TitleSummary:
    """One row of the list."""

    id: int
    kind: TitleKind
    name: str
    year: int | None
    status: TitleStatus


@dataclass(frozen=True)
class WatchableSeason:
    """A season the owner can mark as watched: it has at least one released episode."""

    number: int
    watched: bool


@dataclass(frozen=True)
class TestEventResult:
    __test__ = False

    delivered: bool  # every event of the sample reached the owner
    delivered_at_once: bool = False  # ... at the moment it was queued (false when the rules made it wait)
    held_until: datetime | None = None  # aware UTC; set when the rules made the sample wait for this moment


@dataclass(frozen=True)
class SummaryResult:
    """«Сводка сейчас»: how many events were waiting and whether the summary went out."""

    events: int
    delivered: bool


@dataclass
class DeliveryReport:
    delivered: int = 0
    failed: int = 0


@dataclass
class PollReport:
    polled: int = 0
    failed: int = 0
    events: int = 0  # new events found (already queued for delivery)
    notices: int = 0  # «could not check» messages queued for the owner
