"""Putting events into the delivery queue: the events the polls find, the test events, the «could not check» messages."""

import asyncio
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
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
        with self.ctx.write_session() as session:
            event_id = self.enqueue(session, type, payload, dedup_key, title_id, now)
            if event_id is not None:
                session.commit()
            return event_id

    def queued_since(self, dedup_key: str, since: datetime) -> bool:
        """Whether an event with this key was queued at or after `since`.

        A «date moved» key used to hold only the new date. A move such an old key queued after the previous look is the
        move being found again (the state was not saved), and is not sent twice; one queued before that look is a
        past move, and a new move to the same date is news."""
        with self.ctx.session_factory() as session:
            return session.scalar(
                select(Event.id).where(Event.dedup_key == dedup_key, Event.detected_at >= since).limit(1)
            ) is not None

    @staticmethod
    def enqueue(
        session, type: str, payload: dict[str, Any], dedup_key: str, title_id: int | None, now: datetime
    ) -> int | None:
        """Add an event and its delivery-queue entry (status «pending») to a write session; the caller commits. None, with
        the session rolled back, if the fact is already known or its title is gone."""
        event = Event(type=type, title_id=title_id, payload=payload, dedup_key=dedup_key, detected_at=now)
        session.add(event)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            return None
        # the write session holds the database, so the title cannot be deleted between this check and the commit
        if title_id is not None and session.get(Title, title_id) is None:
            session.rollback()
            return None
        session.add(DeliveryItem(event_id=event.id, status=DeliveryStatus.PENDING, attempts=0, created_at=now))
        return event.id

    @staticmethod
    def withdraw(session, title_id: int) -> None:
        """Take the title's entries that were not delivered yet out of the queue (the «could not check» messages too), in
        a write session; the caller commits. The events stay: their dedup keys keep the same facts from coming again."""
        events_of_title = select(Event.id).where(Event.title_id == title_id)
        session.execute(
            delete(DeliveryItem).where(DeliveryItem.status == DeliveryStatus.PENDING, DeliveryItem.event_id.in_(events_of_title))
        )

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
            with self.ctx.write_session() as session:
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
