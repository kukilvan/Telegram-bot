"""Tracker core facade: the only door the bot (and later the web app) uses.

Clock, sender and sources come from outside, so tests can replace all three. An event is marked
delivered only after the sender succeeded, and the dedup key guarantees one event per fact.
"""

import asyncio
import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.tracker import movie_events
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


@dataclass
class PollReport:
    polled: int = 0
    failed: int = 0
    events: int = 0  # new events found (already queued for delivery)


@dataclass(frozen=True)
class _DueTitle:
    id: int
    kind: str
    name: str
    external_id: str


def _ping_payload() -> dict[str, Any]:
    return {"text": "если вы это видите, доставка работает."}


def format_event(event: Event) -> str:
    """Text of the message the owner receives for an event."""
    if event.type == "test":
        return f"🧪 {event.payload['text']}"
    return event.payload.get("text", event.type)


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
    _poll_lock: asyncio.Lock = field(init=False, default_factory=asyncio.Lock)
    _write_lock: asyncio.Lock = field(init=False, default_factory=asyncio.Lock)  # one «add» writes at a time

    def __post_init__(self) -> None:
        self.register_test_event_kind(TestEventKind("ping", "Проверка связи", _ping_payload))
        for kind_id, label, text in movie_events.TEST_SAMPLES:
            self.register_test_event_kind(TestEventKind(kind_id, label, lambda text=text: {"text": text}))

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
        existing = await asyncio.to_thread(self._find_title_id, source.source_key, external_id)
        if existing is not None:
            return AddResult(existing, created=False)
        snapshot = await source.snapshot(external_id)
        if snapshot is None:
            raise TitleNotFound(f"{source.source_key}:{external_id}")
        async with self._write_lock:
            return await asyncio.to_thread(self._store_title, kind, source.source_key, snapshot)

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
            state = snapshot.state()
            session.add(
                SourceSnapshot(
                    title_id=title.id,
                    source=source_key,
                    state=state,
                    observed_at=now,
                    # the snapshot taken now is the baseline; the first poll compares against it
                    next_check_at=now + movie_events.check_interval_for_state(state, now.date()),
                )
            )
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

    # --- polling --------------------------------------------------------------------------------

    async def poll_due(self) -> PollReport:
        """Look at every title whose check time has come and queue the events found.

        A failing source postpones only its own title; the others are still polled. Database work runs
        in a worker thread, so a slow disk never freezes the bot.
        """
        report = PollReport()
        async with self._poll_lock:
            for due in await asyncio.to_thread(self._due_titles):
                await self._poll_one(due, report)
        return report

    def _due_titles(self) -> list[_DueTitle]:
        now = _naive_utc(self.clock())
        with self.session_factory() as session:
            rows = session.execute(
                select(Title.id, Title.kind, Title.title, ExternalId.external_id)
                .join(SourceSnapshot, SourceSnapshot.title_id == Title.id)
                .join(
                    ExternalId,
                    (ExternalId.title_id == Title.id) & (ExternalId.role == PRIMARY_ROLE),
                )
                .where(
                    Title.tracking_enabled.is_(True),
                    (SourceSnapshot.next_check_at.is_(None)) | (SourceSnapshot.next_check_at <= now),
                )
                .order_by(Title.id)
            )
            return [_DueTitle(*row) for row in rows]

    async def _poll_one(self, due: _DueTitle, report: PollReport) -> None:
        try:
            source = self.sources[due.kind]
            snapshot = await source.snapshot(due.external_id)
            if snapshot is None:
                raise LookupError(f"{due.kind}:{due.external_id} is no longer known to the source")
            found = await asyncio.to_thread(self._apply_snapshot, due, snapshot)
        except Exception as exc:  # one broken title or source must not stop the pass
            logging.warning("polling title %s failed: %s", due.id, mask_secrets(repr(exc)))
            report.failed += 1
            try:
                await asyncio.to_thread(self._postpone, due.id, movie_events.RETRY_AFTER_FAILURE)
            except Exception as postpone_exc:  # even a failed postponement leaves the other titles to the pass
                logging.warning("postponing title %s failed: %s", due.id, mask_secrets(repr(postpone_exc)))
            return
        report.polled += 1
        report.events += found

    def _apply_snapshot(self, due: _DueTitle, snapshot: Any) -> int:
        """Compare the fresh snapshot with the stored one, queue events, store the new state."""
        now = _naive_utc(self.clock())
        today = now.date()
        with self.session_factory() as session:
            stored = self._stored_snapshot(session, due.id)
            old = movie_events.MovieDates.from_state(stored.state)
            new = movie_events.MovieDates.from_state(snapshot.state()).keeping_known(old)
            observed_on = stored.observed_at.date()
        found = 0
        # events first: if storing the state fails, the next poll finds the same facts and the dedup key drops them
        for event in movie_events.detect_events(due.id, due.name, old, new, observed_on, today):
            payload = {"text": event.text, **event.data}
            if self.record_event(event.type, payload, event.dedup_key, title_id=due.id) is not None:
                found += 1
        with self.session_factory() as session:
            stored = self._stored_snapshot(session, due.id)
            stored.state = new.to_state()
            stored.observed_at = now
            stored.next_check_at = now + movie_events.check_interval(new, today)
            session.commit()
        return found

    @staticmethod
    def _stored_snapshot(session, title_id: int) -> SourceSnapshot:
        return session.scalars(select(SourceSnapshot).where(SourceSnapshot.title_id == title_id)).one()

    def _postpone(self, title_id: int, delay: timedelta) -> None:
        now = _naive_utc(self.clock())
        with self.session_factory() as session:
            stored = self._stored_snapshot(session, title_id)
            stored.next_check_at = now + delay
            session.commit()

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
        event_id = await asyncio.to_thread(
            self.record_event, "test", payload, f"test:{kind.id}:{uuid.uuid4().hex}"
        )
        await self.deliver_pending()
        return TestEventResult(delivered=await asyncio.to_thread(self._is_delivered, event_id))

    def _is_delivered(self, event_id: int) -> bool:
        with self.session_factory() as session:
            item = session.scalar(select(DeliveryItem).where(DeliveryItem.event_id == event_id))
            return item is not None and item.status == "delivered"

    # --- delivery -------------------------------------------------------------------------------

    async def deliver_pending(self) -> DeliveryReport:
        """Send everything waiting in the queue. A failed send stays queued; the rest still go out."""
        report = DeliveryReport()
        async with self._delivery_lock:
            pending = await asyncio.to_thread(self._pending_items)
            for item_id, event in pending:
                if await self._deliver_one(item_id, format_event(event)):
                    report.delivered += 1
                else:
                    report.failed += 1
        return report

    def _pending_items(self) -> list[tuple[int, Event]]:
        with self.session_factory() as session:
            return list(
                session.execute(
                    select(DeliveryItem.id, Event)
                    .join(Event, Event.id == DeliveryItem.event_id)
                    .where(DeliveryItem.status == "pending")
                    .order_by(DeliveryItem.id)
                )
            )

    async def _deliver_one(self, item_id: int, message: str) -> bool:
        error: Exception | None = None
        try:
            await self.sender.send(message)
        except Exception as exc:  # the sender is a network client: any failure means "try again later"
            error = exc
            logging.warning("delivery of queue item %s failed: %s", item_id, mask_secrets(repr(exc)))

        await asyncio.to_thread(self._record_attempt, item_id, error)
        return error is None

    def _record_attempt(self, item_id: int, error: Exception | None) -> None:
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
