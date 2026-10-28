"""What the tracker core hands back to its callers. Plain data, no database. Re-exported by `core`."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.tracker.models import TitleKind, TitleStatus


@dataclass(frozen=True)
class AddResult:
    title_id: int
    created: bool  # False: the title was already in the list and is simply opened


@dataclass(frozen=True)
class ChangeResult:
    """What a press on a mark or a score did."""

    changed: bool  # False: the press changed nothing


@dataclass(frozen=True)
class DeleteResult:
    name: str  # the title that was removed, for the message to the owner


class ListOrder(StrEnum):
    """The order of the rows of the list."""

    ADDED = "added"  # the title added last first; the same moment: the larger number first
    NAME = "name"  # by name, case and «ё» ignored: digits, then Latin, then Cyrillic; the same name: the smaller number first


@dataclass(frozen=True)
class TitleSummary:
    """One row of the list."""

    id: int
    kind: TitleKind
    name: str
    year: int | None
    status: TitleStatus
    poster_path: str | None = None  # as the title stores it (a TMDb file name or a whole address); the web turns it into a picture


@dataclass(frozen=True)
class Overview:
    """What the web page says about the whole list: how many titles, and when a source last answered."""

    title_count: int  # every title in the list, the archive included
    last_check_at: datetime | None  # aware, on the owner's clock; None: no source was ever checked


@dataclass(frozen=True)
class WatchableSeason:
    """A season the owner can mark as watched: it has at least one released episode."""

    id: int  # the record of the season: what a mark is sent with (the number of an anime season may change)
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
