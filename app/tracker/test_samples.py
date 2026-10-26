"""«Тестовое событие»: samples of the messages the owner can ask for, and the check of the delivery rules.

A sample is delivered the way a real event would be, but only the sample itself is touched: what really waits in the
queue stays where it is.
"""

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any

from app.tracker import anime_events, failures, movie_events, sequel_events, series_events
from app.tracker.context import CoreContext, naive_utc
from app.tracker.delivery_service import DeliveryService
from app.tracker.queue import EventQueue
from app.tracker.results import TestEventResult
from app.tracker.settings_store import SettingsStore


@dataclass(frozen=True)
class TestSample:
    """One entry of the "Тестовое событие" menu. Later tickets register their own samples."""

    __test__ = False  # not a pytest test class

    id: str
    label: str
    build: Callable[[], dict[str, Any]]  # payload of the sample event; must contain "text"
    # several events instead of one (event type and payload each); the summary folds them like real ones
    events: Callable[[], list[tuple[str, dict[str, Any]]]] | None = None


@dataclass(frozen=True)
class DeliveryCheck:
    """A moment of the week for «Тестовое событие»: the owner sees how the rules treat an event queued then."""

    id: str
    label: str
    weekday: int  # Monday is 0
    at: time

    def next_moment(self, now_local: datetime) -> datetime:
        """The next such moment on the owner's clock (naive), today's included when it is still ahead."""
        ahead = (self.weekday - now_local.weekday()) % 7
        moment = datetime.combine(now_local.date() + timedelta(days=ahead), self.at)
        return moment if moment > now_local else moment + timedelta(days=7)


DELIVERY_CHECKS: tuple[DeliveryCheck, ...] = (
    DeliveryCheck("work-morning", "Вс, 10:00 — рабочий день до сводки", 6, time(10, 0)),
    DeliveryCheck("work-afternoon", "Вс, 16:00 — рабочий день после сводки", 6, time(16, 0)),
    DeliveryCheck("friday", "Пт, 12:00 — выходной", 4, time(12, 0)),
    DeliveryCheck("saturday", "Сб, 10:00 — выходной", 5, time(10, 0)),
    DeliveryCheck("night-before-day-off", "Чт, 22:00 — ночь перед выходным", 3, time(22, 0)),
    DeliveryCheck("night-before-workday", "Сб, 22:00 — ночь перед рабочим днём", 5, time(22, 0)),
    DeliveryCheck("quiet-ends", "Пт, 07:29 — за минуту до конца тихих часов", 4, time(7, 29)),
    DeliveryCheck("quiet-ended", "Пт, 07:30 — тихие часы кончились", 4, time(7, 30)),
)


def delivery_check_by_id(check_id: str) -> DeliveryCheck | None:
    return next((c for c in DELIVERY_CHECKS if c.id == check_id), None)


def _ping_payload() -> dict[str, Any]:
    return {"text": "если вы это видите, доставка работает."}


class TestSamples:
    __test__ = False

    def __init__(
        self, ctx: CoreContext, queue: EventQueue, deliveries: DeliveryService, settings: SettingsStore
    ) -> None:
        self.ctx = ctx
        self.queue = queue
        self.deliveries = deliveries
        self.settings = settings
        self._samples: dict[str, TestSample] = {}
        self._register_own_samples()

    def _register_own_samples(self) -> None:
        self.register(TestSample("ping", "Проверка связи", _ping_payload))
        sample_texts = (
            movie_events.TEST_SAMPLES
            + sequel_events.TEST_SAMPLES
            + series_events.TEST_SAMPLES
            + anime_events.TEST_SAMPLES
            + failures.TEST_SAMPLES
        )
        for sample_id, label, text in sample_texts:
            self.register(TestSample(sample_id, label, lambda text=text: {"text": text}))
        self.register(
            TestSample(
                failures.SAMPLE_MANY_ID,
                failures.SAMPLE_MANY_LABEL,
                lambda: failures.sample_failure_events()[0][1],
                failures.sample_failure_events,
            )
        )
        self.register(
            TestSample(
                series_events.SAMPLE_EPISODES_ID,
                series_events.SAMPLE_EPISODES_LABEL,
                lambda: series_events.sample_episode_events()[0][1],
                series_events.sample_episode_events,
            )
        )

    def register(self, sample: TestSample) -> None:
        self._samples[sample.id] = sample

    def samples(self) -> list[TestSample]:
        return list(self._samples.values())

    async def send_test_event(self, sample_id: str, at: datetime | None = None) -> TestEventResult:
        """Create a fresh sample of the given id and deliver it.

        Without `at` it goes out at once, whatever the hour: this checks that the channel works. With `at` (an aware
        moment) the sample is queued as if that moment were now and judged by the delivery rules of the owner. When
        the rules make it wait, the moment it would be released is played out too, so the owner sees the summary.
        Only the sample itself is touched: what really waits in the queue stays where it is."""
        sample = self._samples[sample_id]
        built = sample.events() if sample.events is not None else [("test", sample.build())]
        prefix = f"Тестовое событие «{sample.label}»: "
        events = [(event_type, {**payload, "text": prefix + payload["text"], "prefix": prefix}) for event_type, payload in built]
        run_id = uuid.uuid4().hex
        event_ids = await asyncio.to_thread(self._record_sample_events, sample.id, events, run_id, at)
        only = frozenset(event_ids)
        if at is None:
            await self.deliveries.deliver_pending(force=True, only=only)
            delivered = await self.deliveries.all_delivered(only)
            return TestEventResult(delivered=delivered, delivered_at_once=delivered)

        await self.deliveries.deliver_pending(now=at, only=only)
        if await self.deliveries.all_delivered(only):
            return TestEventResult(delivered=True, delivered_at_once=True)
        rules = await self.settings.delivery_rules()
        release, waited = rules.release(naive_utc(at))
        if not waited:  # the rules let it go at once, so the sender failed
            return TestEventResult(delivered=False)
        released_at = release.replace(tzinfo=timezone.utc)
        await self.deliveries.deliver_pending(now=released_at, only=only)
        return TestEventResult(delivered=await self.deliveries.all_delivered(only), held_until=released_at)

    def _record_sample_events(
        self, sample_id: str, events: list[tuple[str, dict[str, Any]]], run_id: str, at: datetime | None
    ) -> list[int]:
        return [
            self.queue.record(event_type, payload, f"test:{sample_id}:{run_id}:{number}", at=at)
            for number, (event_type, payload) in enumerate(events)
        ]

    async def delivery_check_moment(self, check: DeliveryCheck) -> datetime:
        """The next moment of the delivery check on the owner's clock, as an aware moment."""
        rules = await self.settings.delivery_rules()
        local = check.next_moment(rules.local(self.ctx.now()))
        return rules.utc(local).replace(tzinfo=timezone.utc)
