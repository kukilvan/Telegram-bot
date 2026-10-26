"""Tracker core facade: the only door the bot (and later the web app) uses.

`Tracker` builds the parts of the core around one shared context and passes every call on to the part that owns it:
settings (`settings_store`), the list (`titles`), polling (`polling` and one poller per kind in `pollers/`), the
delivery queue (`queue`), delivery (`delivery_service`) and test events (`test_samples`). It holds no rules of its own.

Clock, sender and sources come from outside, so tests can replace all three. An event is marked delivered only after
the sender succeeded, and the dedup key guarantees one event per fact. Where new code goes: docs/coding-standards.md.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, time, timezone, tzinfo
from typing import Any

from sqlalchemy.orm import sessionmaker

from app.tracker import delivery
from app.tracker.cards import TitleCard
from app.tracker.context import Clock, CoreContext, Sender
from app.tracker.delivery_service import DeliveryService
from app.tracker.errors import TitleNotFound, UnknownEvent, UnknownKind, UnknownSeason, UnknownTitle
from app.tracker.models import TitleKind
from app.tracker.polling import Polling, Pollers
from app.tracker.queue import EventQueue
from app.tracker.results import (
    AddResult,
    DeleteResult,
    DeliveryReport,
    PollReport,
    SummaryResult,
    TestEventResult,
    TitleSummary,
    WatchableSeason,
    WatchedResult,
)
from app.tracker.settings_store import SettingsStore
from app.tracker.test_samples import DeliveryCheck, TestSample, TestSamples
from app.tracker.titles import Titles

__all__ = [
    "AddResult", "Clock", "DeleteResult", "DeliveryReport", "PollReport", "Sender", "SummaryResult", "TestEventResult",
    "TestSample", "TitleCard", "TitleNotFound", "TitleSummary", "Tracker", "UnknownEvent", "UnknownKind",
    "UnknownSeason", "UnknownTitle", "WatchableSeason", "WatchedResult",
]


@dataclass
class Tracker:
    session_factory: sessionmaker
    clock: Clock
    sender: Sender
    sources: Mapping[TitleKind, Any] = field(default_factory=dict)
    sequel_sources: Mapping[TitleKind, Any] = field(default_factory=dict)  # by kind: where an archived title's sequels come from
    default_tz: tzinfo = timezone.utc  # the time zone when the owner has set none (BOT_TIMEZONE); the set one is read from the database
    _settings: SettingsStore = field(init=False, repr=False)
    _queue: EventQueue = field(init=False, repr=False)
    _polling: Polling = field(init=False, repr=False)
    _titles: Titles = field(init=False, repr=False)
    _deliveries: DeliveryService = field(init=False, repr=False)
    _samples: TestSamples = field(init=False, repr=False)

    def __post_init__(self) -> None:
        # the core works with TitleKind keys; a caller may hand over plain text keys ("movie"), which become members here
        self.sources = {TitleKind(kind): source for kind, source in self.sources.items()}
        self.sequel_sources = {TitleKind(kind): source for kind, source in self.sequel_sources.items()}
        ctx = CoreContext(self.session_factory, self.clock, self.sender, self.default_tz)
        self._settings = SettingsStore(ctx)
        self._queue = EventQueue(ctx)
        pollers = Pollers(ctx, self._settings, self._queue, self.sources, self.sequel_sources)
        self._polling = Polling(ctx, self._queue, pollers)
        self._titles = Titles(ctx, self._settings, pollers)
        self._deliveries = DeliveryService(ctx, self._settings)
        self._samples = TestSamples(ctx, self._queue, self._deliveries, self._settings)

    # --- events ---------------------------------------------------------------------------------

    async def record_event(
        self,
        type: str,
        payload: dict[str, Any],
        dedup_key: str,
        title_id: int | None = None,
        at: datetime | None = None,
    ) -> int | None:
        """Store an event and queue it for delivery. Returns its id, or None if this fact is already known."""
        return await self._queue.record_event(type, payload, dedup_key, title_id, at)

    # --- settings -------------------------------------------------------------------------------

    async def part_gap_weeks(self) -> int:
        """Weeks of break between two episodes of a season after which the season is split into parts."""
        return await self._settings.part_gap_weeks()

    async def set_part_gap_weeks(self, weeks: int) -> None:
        """Change the break that splits a season into parts."""
        await self._settings.set_part_gap_weeks(weeks)

    async def delivery_rules(self) -> delivery.DeliveryRules:
        """The owner's time zone, working days, summary hour and quiet hours; what is not set is the default."""
        return await self._settings.delivery_rules()

    async def set_delivery_rules(
        self,
        *,
        tz_name: str | None = None,
        workdays: Sequence[int] | None = None,
        summary_at: time | str | None = None,
        quiet_from: time | str | None = None,
        quiet_until: time | str | None = None,
    ) -> None:
        """Change the given rules (the others stay). Nothing is stored when any value is wrong."""
        await self._settings.set_delivery_rules(
            tz_name=tz_name, workdays=workdays, summary_at=summary_at, quiet_from=quiet_from, quiet_until=quiet_until
        )

    # --- titles ---------------------------------------------------------------------------------

    async def search(self, kind: TitleKind, query: str) -> list[Any]:
        """Suggestions for `query` from the source of this kind. Raises KeyError for an unknown kind."""
        return await self._titles.search(kind, query)

    async def add_title(self, kind: TitleKind, external_id: str) -> AddResult:
        """Put a search result into the list with status «Хочу», or open the title that is already there."""
        return await self._titles.add_title(kind, external_id)

    async def watchable_seasons(self, title_id: int) -> list[WatchableSeason]:
        """Seasons that can be marked as watched, with their marks. A season with nothing released cannot."""
        return await self._titles.watchable_seasons(title_id)

    async def set_season_watched(self, title_id: int, number: int, watched: bool) -> None:
        """Mark a season as watched, or take the mark off. Marking twice changes nothing."""
        await self._titles.set_season_watched(title_id, number, watched)

    async def mark_watched(self, title_id: int) -> WatchedResult:
        """«Посмотрел»: the movie gets «Просмотрено» and moves to the archive, where only its sequels are watched."""
        return await self._titles.mark_watched(title_id)

    async def delete_title(self, title_id: int) -> DeleteResult:
        """Remove a title and everything that belongs to it, in one transaction: all of it or nothing."""
        return await self._titles.delete_title(title_id)

    async def follow_sequel_of(self, kind: str, sequel_id: str) -> AddResult:
        """«Следить» under a sequel announcement: the sequel joins the list as «Хочу». Pressing twice opens it."""
        return await self._titles.follow_sequel_of(kind, sequel_id)

    async def follow_sequel(self, event_id: int) -> AddResult:
        """The same for an old button, which holds only the number of the announcement."""
        return await self._titles.follow_sequel(event_id)

    async def list_titles(self) -> list[TitleSummary]:
        return await self._titles.list_titles()

    async def title_card(self, title_id: int) -> TitleCard | None:
        return await self._titles.title_card(title_id)

    # --- polling --------------------------------------------------------------------------------

    async def poll_due(self) -> PollReport:
        """Look at every title whose check time has come and queue the events found."""
        return await self._polling.poll_due()

    # --- delivery -------------------------------------------------------------------------------

    async def deliver_pending(
        self, *, now: datetime | None = None, only: frozenset[int] | None = None, force: bool = False
    ) -> DeliveryReport:
        """Send what the delivery rules let out at this moment. A failed send stays queued; the rest still go out."""
        return await self._deliveries.deliver_pending(now=now, only=only, force=force)

    async def summary_now(self) -> SummaryResult:
        """«Сводка сейчас»: everything waiting goes out in one summary at once, whatever the hour."""
        return await self._deliveries.summary_now()

    # --- test events ----------------------------------------------------------------------------

    def register_test_sample(self, sample: TestSample) -> None:
        self._samples.register(sample)

    def test_samples(self) -> list[TestSample]:
        return self._samples.samples()

    async def send_test_event(self, sample_id: str, at: datetime | None = None) -> TestEventResult:
        """Create a fresh sample of the given id and deliver it, at once or as if `at` were now."""
        return await self._samples.send_test_event(sample_id, at)

    async def delivery_check_moment(self, check: DeliveryCheck) -> datetime:
        """The next moment of the delivery check on the owner's clock, as an aware moment."""
        return await self._samples.delivery_check_moment(check)
