"""Tables of the tracker database. Timestamps are naive UTC and are always set by the core at insert time."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class TrackerBase(DeclarativeBase):
    """Base of the tracker schema; kept apart from the legacy `Base` so the two databases never mix."""


class Event(TrackerBase):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(64))
    # Plain column for now: the titles table arrives with the next tickets, which add the foreign key
    title_id: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON)
    dedup_key: Mapped[str] = mapped_column(String(255), unique=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime)


class DeliveryItem(TrackerBase):
    __tablename__ = "delivery_queue"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), unique=True)
    status: Mapped[str] = mapped_column(String(16), index=True)  # pending | delivered
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime)
