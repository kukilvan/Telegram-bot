"""Tracker core facade: the only door the bot (and later the web app) uses.

Clock, sender and sources come from outside, so tests can replace all three. An event is marked
delivered only after the sender succeeded, and the dedup key guarantees one event per fact.
"""

import asyncio
import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.tracker.models import DeliveryItem, Event
from app.utils.secrets_mask import mask_secrets

Clock = Callable[[], datetime]  # returns an aware datetime


class Sender(Protocol):
    async def send(self, message: str) -> None:
        """Deliver one message to the owner; raise on failure."""


@dataclass(frozen=True)
class TestEventKind:
    """One entry of the "Тестовое событие" menu. Later tickets register their own kinds."""

    __test__ = False  # not a pytest test class

    id: str
    label: str
    build: Callable[[], dict[str, Any]]  # payload of the sample event; must contain "text"


@dataclass(frozen=True)
class TestEventResult:
    __test__ = False

    delivered: bool


@dataclass
class DeliveryReport:
    delivered: int = 0
    failed: int = 0


def _ping_payload() -> dict[str, Any]:
    return {"text": "если вы это видите, доставка работает."}


def format_event(event: Event) -> str:
    """Text of the message the owner receives for an event."""
    if event.type == "test":
        return f"🧪 {event.payload['text']}"
    return f"🔔 {event.payload.get('text', event.type)}"


def _naive_utc(moment: datetime) -> datetime:
    return moment.astimezone(timezone.utc).replace(tzinfo=None)


@dataclass
class Tracker:
    session_factory: sessionmaker
    clock: Clock
    sender: Sender
    sources: Mapping[str, Any] = field(default_factory=dict)
    _kinds: dict[str, TestEventKind] = field(init=False, default_factory=dict)
    _delivery_lock: asyncio.Lock = field(init=False, default_factory=asyncio.Lock)

    def __post_init__(self) -> None:
        self.register_test_event_kind(TestEventKind("ping", "Проверка связи", _ping_payload))

    # --- events ---------------------------------------------------------------------------------

    def record_event(
        self, type: str, payload: dict[str, Any], dedup_key: str, title_id: int | None = None
    ) -> int | None:
        """Store an event and queue it for delivery. Returns its id, or None if this fact is already known."""
        now = _naive_utc(self.clock())
        with self.session_factory() as session:
            event = Event(type=type, title_id=title_id, payload=payload, dedup_key=dedup_key, detected_at=now)
            session.add(event)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                return None
            session.add(DeliveryItem(event_id=event.id, status="pending", attempts=0, created_at=now))
            session.commit()
            return event.id

    # --- test events ----------------------------------------------------------------------------

    def register_test_event_kind(self, kind: TestEventKind) -> None:
        self._kinds[kind.id] = kind

    def test_event_kinds(self) -> list[TestEventKind]:
        return list(self._kinds.values())

    async def send_test_event(self, kind_id: str) -> TestEventResult:
        """Create a fresh sample event of the given kind and try to deliver it right away."""
        kind = self._kinds[kind_id]
        payload = kind.build()
        payload = {**payload, "text": f"Тестовое событие «{kind.label}»: {payload['text']}"}
        event_id = self.record_event("test", payload, dedup_key=f"test:{kind.id}:{uuid.uuid4().hex}")
        await self.deliver_pending()
        return TestEventResult(delivered=self._is_delivered(event_id))

    def _is_delivered(self, event_id: int) -> bool:
        with self.session_factory() as session:
            item = session.scalar(select(DeliveryItem).where(DeliveryItem.event_id == event_id))
            return item is not None and item.status == "delivered"

    # --- delivery -------------------------------------------------------------------------------

    async def deliver_pending(self) -> DeliveryReport:
        """Send everything waiting in the queue. A failed send stays queued; the rest still go out."""
        report = DeliveryReport()
        async with self._delivery_lock:
            with self.session_factory() as session:
                pending = list(
                    session.execute(
                        select(DeliveryItem.id, Event)
                        .join(Event, Event.id == DeliveryItem.event_id)
                        .where(DeliveryItem.status == "pending")
                        .order_by(DeliveryItem.id)
                    )
                )
            for item_id, event in pending:
                if await self._deliver_one(item_id, format_event(event)):
                    report.delivered += 1
                else:
                    report.failed += 1
        return report

    async def _deliver_one(self, item_id: int, message: str) -> bool:
        error: Exception | None = None
        try:
            await self.sender.send(message)
        except Exception as exc:  # the sender is a network client: any failure means "try again later"
            error = exc
            logging.warning("delivery of queue item %s failed: %s", item_id, mask_secrets(repr(exc)))

        with self.session_factory() as session:
            item = session.get(DeliveryItem, item_id)
            item.attempts += 1
            if error is None:
                item.status = "delivered"
                item.last_error = None
                item.delivered_at = _naive_utc(self.clock())
            else:
                item.last_error = mask_secrets(repr(error))[:500]
            session.commit()
        return error is None
