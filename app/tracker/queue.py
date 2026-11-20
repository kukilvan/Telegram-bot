"""Putting events into the delivery queue: the events the polls find, the test events, the «could not check» messages."""

import asyncio
from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.tracker import failures
from app.tracker.checks import still_checked
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
        due: DueTitle | None = None,
    ) -> int | None:
        """`due`: the check that found the event; it is queued only while the title is still checked by it
        (`checks.still_checked`), else nothing is queued and the dedup key is not spent (KI-22)."""
        now = naive_utc(at or self.ctx.clock())
        with self.ctx.write_session() as session:
            event_id = self.enqueue(session, type, payload, dedup_key, title_id, now, due)
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
        session,
        type: str,
        payload: dict[str, Any],
        dedup_key: str,
        title_id: int | None,
        now: datetime,
        due: DueTitle | None = None,
    ) -> int | None:
        """Add an event and its delivery-queue entry (status «pending») to a write session; the caller commits. None, with
        the session rolled back, if the fact is already known, its title is gone, or the title is no longer checked by
        `due`, the check that found it."""
        event = Event(type=type, title_id=title_id, payload=payload, dedup_key=dedup_key, detected_at=now)
        session.add(event)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            return None
        # the write session holds the database, so the title cannot be deleted between this check and the commit
        gone = title_id is not None and session.get(Title, title_id) is None
        if gone or (due is not None and not still_checked(session, due)):
            session.rollback()
            return None
        session.add(DeliveryItem(event_id=event.id, status=DeliveryStatus.PENDING, attempts=0, created_at=now))
        return event.id

    @staticmethod
    def withdraw(session, title_id: int, types: Collection[str] | None = None) -> None:
        """Take the title's entries that were not delivered yet out of the queue, in a write session; the caller commits.
        `types`: only the events of these types (the events of Steam of a game whose prices are no longer checked);
        None — all of them, the «could not check» messages too. The events stay: their dedup keys keep the same facts
        from coming again."""
        events_of_title = select(Event.id).where(Event.title_id == title_id)
        if types is not None:
            events_of_title = events_of_title.where(Event.type.in_(tuple(types)))
        session.execute(
            delete(DeliveryItem).where(DeliveryItem.status == DeliveryStatus.PENDING, DeliveryItem.event_id.in_(events_of_title))
        )

    def queue_failure_notices(self, broken: Sequence[tuple[DueTitle, Exception]]) -> int:
        """Queue the «could not check» events of one pass: one per title and source, none for a title no longer checked
        by the check that failed (KI-22), and none for a source of a title the owner was told about in the last 24
        hours (KI-45). Delivery folds the events of one source and reason into a message. The window is read from the
        events themselves, so a restart neither repeats a notice nor loses one."""
        now = self.ctx.now()
        stamp = now.strftime("%Y%m%dT%H%M%S")  # the moment of the pass; it opens the 24-hour window of its titles
        queued = 0
        seen: set[tuple[int, str]] = set()
        for due, exc in broken:
            source = failures.source_name(due.snapshot_source)
            if (due.id, source) in seen:  # two broken checks of one title and source are one failure
                continue
            seen.add((due.id, source))
            with self.ctx.write_session() as session:
                if not still_checked(session, due) or _told_lately(session, due.id, source, now):
                    continue
                title = session.get(Title, due.id)
                payload = failures.failure_payload(title.name, source, failures.reason_of(exc), stamp)
                event_id = self.enqueue(
                    session, failures.SOURCE_FAILED, payload, f"failure:{title.id}:{source}:{stamp}", title.id, now
                )
                if event_id is not None:
                    queued += 1
                    session.commit()
        return queued


def _told_lately(session, title_id: int, source: str, now: datetime) -> bool:
    """Whether a «could not check» event of this title and source was detected in the last 24 hours. Old events that
    name no source do not count."""
    payloads = session.scalars(
        select(Event.payload).where(
            Event.title_id == title_id,
            Event.type == failures.SOURCE_FAILED,
            Event.detected_at > now - failures.COOLDOWN,
        )
    )
    return any(isinstance(payload, dict) and payload.get("source") == source for payload in payloads)
