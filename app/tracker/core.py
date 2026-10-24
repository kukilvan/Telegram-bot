"""Tracker core facade: the only door the bot (and later the web app) uses.

Clock, sender and sources come from outside, so tests can replace all three. An event is marked
delivered only after the sender succeeded, and the dedup key guarantees one event per fact.
"""

import asyncio
import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.tracker.cards import TitleCard
from app.tracker.models import DeliveryItem, Event, ExternalId, SourceSnapshot, Title
from app.utils.secrets_mask import mask_secrets

Clock = Callable[[], datetime]  # returns an aware datetime

STATUS_WANT = "want"
PRIMARY_ROLE = "primary"


class Sender(Protocol):
    async def send(self, message: str) -> None:
        """Deliver one message to the owner; raise on failure."""


class TitleNotFound(Exception):
    """The source has nothing at the chosen id (for example a series id picked as a movie)."""


@dataclass(frozen=True)
class AddResult:
    title_id: int
    created: bool  # False: the title was already in the list and is simply opened


@dataclass(frozen=True)
class TitleSummary:
    """One row of the list."""

    id: int
    kind: str
    name: str
    year: int | None
    status: str


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


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


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

    # --- titles ---------------------------------------------------------------------------------

    async def search(self, kind: str, query: str) -> list[Any]:
        """Suggestions for `query` from the source of this kind. Raises KeyError for an unknown kind."""
        return await self.sources[kind].suggest(query)

    async def add_title(self, kind: str, external_id: str) -> AddResult:
        """Put a search result into the list with status «Хочу», or open the title that is already there."""
        source = self.sources[kind]
        existing = self._find_title_id(source.source_key, external_id)
        if existing is not None:
            return AddResult(existing, created=False)
        snapshot = await source.snapshot(external_id)
        if snapshot is None:
            raise TitleNotFound(f"{source.source_key}:{external_id}")
        return self._store_title(kind, source.source_key, snapshot)

    def _find_title_id(self, source_key: str, external_id: str) -> int | None:
        with self.session_factory() as session:
            return session.scalar(
                select(ExternalId.title_id).where(
                    ExternalId.source == source_key,
                    ExternalId.external_id == external_id,
                    ExternalId.role == PRIMARY_ROLE,
                )
            )

    def _store_title(self, kind: str, source_key: str, snapshot: Any) -> AddResult:
        now = _naive_utc(self.clock())
        with self.session_factory() as session:
            title = Title(
                kind=kind,
                title=snapshot.title,
                original_title=snapshot.original_title,
                year=snapshot.year,
                genres=list(snapshot.genres),
                poster_path=snapshot.poster_path,
                overview=snapshot.overview,
                status=STATUS_WANT,
                tracking_enabled=True,
                added_at=now,
                status_changed_at=now,
            )
            session.add(title)
            session.flush()
            session.add(
                ExternalId(title_id=title.id, source=source_key, external_id=snapshot.external_id, role=PRIMARY_ROLE)
            )
            session.add(SourceSnapshot(title_id=title.id, source=source_key, state=snapshot.state(), observed_at=now))
            try:
                session.commit()
            except IntegrityError:
                # the same movie was added by a second request while this one was waiting for the source
                session.rollback()
                existing = self._find_title_id(source_key, snapshot.external_id)
                if existing is None:
                    raise
                return AddResult(existing, created=False)
            return AddResult(title.id, created=True)

    def list_titles(self) -> list[TitleSummary]:
        with self.session_factory() as session:
            rows = session.scalars(select(Title).order_by(Title.id))
            return [TitleSummary(t.id, t.kind, t.title, t.year, t.status) for t in rows]

    def title_card(self, title_id: int) -> TitleCard | None:
        with self.session_factory() as session:
            title = session.get(Title, title_id)
            if title is None:
                return None
            snapshot = session.scalar(select(SourceSnapshot).where(SourceSnapshot.title_id == title_id))
            state = snapshot.state if snapshot else {}
            return TitleCard(
                id=title.id,
                kind=title.kind,
                title=title.title,
                original_title=title.original_title,
                year=title.year,
                genres=list(title.genres),
                status=title.status,
                theatrical_date=_parse_date(state.get("theatrical_date")),
                digital_date=_parse_date(state.get("digital_date")),
            )

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
