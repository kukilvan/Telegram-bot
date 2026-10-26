"""Putting events into the delivery queue: the events the polls find, the test events, the «could not check» messages."""

import asyncio
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.tracker import failures
from app.tracker.context import CoreContext, naive_utc
from app.tracker.models import DeliveryItem, DeliveryStatus, Event, Title
from app.tracker.pollers.base import DueTitle


class EventQueue:
    def __init__(self, ctx: CoreContext) -> None:
        self.ctx = ctx

    async def record_event(
        self,
        type: str,
        payload: dict[str, Any],
        dedup_key: str,
        title_id: int | None = None,
        at: datetime | None = None,
    ) -> int | None:
        """Store an event and queue it for delivery. Returns its id, or None if this fact is already known.
        `at` stands in for the moment of detection (a test event with a substituted time). An event of a title that is
        no longer in the list (deleted while the poll was under way) is dropped."""
        return await asyncio.to_thread(self.record, type, payload, dedup_key, title_id, at)

    def record(
        self,
        type: str,
        payload: dict[str, Any],
        dedup_key: str,
        title_id: int | None = None,
        at: datetime | None = None,
    ) -> int | None:
        now = naive_utc(at or self.ctx.clock())
        with self.ctx.session_factory() as session:
            event_id = self.enqueue(session, type, payload, dedup_key, title_id, now)
            if event_id is not None:
                session.commit()
            return event_id

    @staticmethod
    def enqueue(
        session, type: str, payload: dict[str, Any], dedup_key: str, title_id: int | None, now: datetime
    ) -> int | None:
        """Add an event and its delivery-queue entry (status «pending») to the session; the caller commits. None, with
        the session rolled back, if the fact is already known or its title is gone."""
        event = Event(type=type, title_id=title_id, payload=payload, dedup_key=dedup_key, detected_at=now)
        session.add(event)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            return None
        # the flush holds the write lock, so the title cannot be deleted between this check and the commit
        if title_id is not None and session.get(Title, title_id) is None:
            session.rollback()
            return None
        session.add(DeliveryItem(event_id=event.id, status=DeliveryStatus.PENDING, attempts=0, created_at=now))
        return event.id

    def queue_failure_notices(self, broken: Sequence[tuple[DueTitle, Exception]]) -> int:
        """Queue the «could not check» events of one pass: one per title, and none for a title the owner was told about
        in the last 24 hours. Delivery folds the events of one source and reason into a message. The event and the time
        it was queued are stored together, so a restart neither repeats a notice nor loses one."""
        now = self.ctx.now()
        stamp = now.strftime("%Y%m%dT%H%M%S")  # the moment of the pass; it opens the 24-hour window of its titles
        queued = 0
        seen: set[int] = set()
        for due, exc in broken:
            if due.id in seen:  # two broken sources of one title are one failure
                continue
            seen.add(due.id)
            with self.ctx.session_factory() as session:
                title = session.get(Title, due.id)
                if title is None or (
                    title.failure_notified_at is not None and now - title.failure_notified_at < failures.COOLDOWN
                ):
                    continue
                payload = failures.failure_payload(
                    title.name, failures.source_name(due.snapshot_source), failures.reason_of(exc), stamp
                )
                title.failure_notified_at = now
                event_id = self.enqueue(
                    session, failures.SOURCE_FAILED, payload, f"failure:{title.id}:{stamp}", title.id, now
                )
                if event_id is not None:
                    queued += 1
                session.commit()
        return queued
