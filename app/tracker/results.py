"""What the tracker core hands back to its callers. Plain data, no database. Re-exported by `core`."""

from collections.abc import Collection
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
    SCORE = "score"  # by the shown score, the exact one, the highest first; no score last; the same: the later change of status, then the larger number
    ARCHIVED = "archived"  # the latest change of status first (for the archive, the day it went there); the same: the larger number first


@dataclass(frozen=True)
class TitleSummary:
    """One row of the list."""

    id: int
    kind: TitleKind
    name: str
    year: int | None
    status: TitleStatus
    poster_path: str | None = None  # as the title stores it (a TMDb file name or a whole address); the web turns it into a picture
    score: int | None = None  # what the owner reads: the own score, else the average of the seasons to the nearest step; None: none shown
    score_by_seasons: bool = False  # `score` is the average of the seasons


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


@dataclass(frozen=True)
class ZoneOption:
    """One choice of the time zone list: the name that is stored and the text the owner reads."""

    name: str  # «Asia/Jerusalem»
    label: str  # «Asia/Jerusalem (UTC+2)»: with today's offset


@dataclass(frozen=True)
class Choice:
    """One choice of a setting: the value that is stored (and sent by the form) and the text the owner reads."""

    value: str
    label: str


@dataclass(frozen=True)
class SettingsChange:
    """What the settings form sent, as it came: the core reads the texts, so the web has no part in the rules. A new
    setting is one more field here, one more check in `settings_store` and one more field on the page."""

    tz_name: str  # «»: the zone of the launch file
    workdays: Collection[int]
    summary_at: str
    quiet_from: str
    quiet_until: str
    part_gap_weeks: str
    my_platforms: Collection[str]  # the values of `Platform`
    store_country: str  # the code of the country


@dataclass(frozen=True)
class SettingsView:
    """What the settings page shows: the stored values (the defaults where nothing is stored), the choices and the
    line «Сейчас»."""

    tz_name: str | None  # the zone chosen in the settings; None: none chosen, the one of the launch file (`.env`) works
    default_tz_name: str  # the zone of the launch file
    zones: tuple[ZoneOption, ...]  # the choices, by name; a stored zone outside the usual list is one of them
    default_label: str  # «Как в файле настроек запуска: Asia/Jerusalem (UTC+2)»: the first line of the list
    workdays: frozenset[int]  # weekday numbers, Monday is 0
    summary_at: str  # «15:00»
    quiet_from: str  # «21:00»
    quiet_until: str  # «07:30»
    part_gap_weeks: int
    saved: SettingsChange  # all of the above and the rest, as the form sends them: the page fills itself from it
    platforms: tuple[Choice, ...]  # «Мои платформы»: the boxes, in the order of the table
    countries: tuple[Choice, ...]  # «Страна магазинов»: the list, by label
    now_line: str  # what the stored rules would do with an event at this minute
