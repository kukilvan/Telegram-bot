"""Tables of the tracker database. Timestamps are naive UTC and are always set by the core at insert time."""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


STATUS_WANT = "want"  # «Хочу»
STATUS_WATCHED = "watched"  # «Просмотрено»: the movie is in the archive


class TrackerBase(DeclarativeBase):
    """Base of the tracker schema; kept apart from the legacy `Base` so the two databases never mix."""


class Title(TrackerBase):
    """One entry of the owner's list (a movie for now; series, anime and games come with later tickets)."""

    __tablename__ = "titles"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)  # movie | series | anime | game
    title: Mapped[str] = mapped_column(String(500))  # Russian name when the source knows it
    original_title: Mapped[str] = mapped_column(String(500))
    year: Mapped[int | None] = mapped_column(Integer)
    genres: Mapped[list] = mapped_column(JSON)
    poster_path: Mapped[str | None] = mapped_column(String(255))
    overview: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), index=True)  # STATUS_WANT | STATUS_WATCHED
    tracking_enabled: Mapped[bool] = mapped_column(Boolean)
    added_at: Mapped[datetime] = mapped_column(DateTime)
    status_changed_at: Mapped[datetime] = mapped_column(DateTime)


class ExternalId(TrackerBase):
    """A title's id in an outside source. The source name carries the kind ("tmdb_movie"), because TMDb
    numbers movies and series in one id space."""

    __tablename__ = "external_ids"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_external_ids_source_id"),
        UniqueConstraint("title_id", "source", "role", name="uq_external_ids_title_source_role"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title_id: Mapped[int] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16))  # primary | ...


class SourceSnapshot(TrackerBase):
    """Last normalized state of a title as one source reported it."""

    __tablename__ = "source_snapshots"
    __table_args__ = (UniqueConstraint("title_id", "source", name="uq_source_snapshots_title_source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    title_id: Mapped[int] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(32))
    state: Mapped[dict] = mapped_column(JSON)
    observed_at: Mapped[datetime] = mapped_column(DateTime)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)  # None: due now


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
