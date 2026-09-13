"""SQLAlchemy models. Phase 2 schema."""

import uuid as _uuid_mod
from typing import Optional

from datetime import date, datetime, timezone as _dt_timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class User(Base):
    """Telegram user profile."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_user_id: Mapped[int]  # int, unique
    username: Mapped[Optional[str]]
    timezone: Mapped[str] = mapped_column(default="Asia/Jerusalem")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.now(tz=_dt_timezone.utc)
    )


class MediaItem(Base):
    """Core entity: a movie, TV series, anime, or game."""

    __tablename__ = "media_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_mod.uuid4)
    media_type: Mapped[str]  # movie | tv | anime | game
    canonical_title_en: Mapped[Optional[str]]
    title_ru: Mapped[Optional[str]]
    year: Mapped[Optional[int]]
    description: Mapped[Optional[str]] = mapped_column(Text)
    poster_url: Mapped[Optional[str]]
    backdrop_url: Mapped[Optional[str]]


class ExternalId(Base):
    """Stable external IDs per media_item (not identified by title)."""

    __tablename__ = "external_ids"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    media_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("media_items.id"), index=True
    )
    source: Mapped[str]  # tmdb | imdb | anilist | igdb | steam | psn | kinopub
    external_id: Mapped[str]


class MediaAlias(Base):
    """All known names for a media_item (original, English, Russian, AKA)."""

    __tablename__ = "media_aliases"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    media_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("media_items.id"), index=True
    )
    alias_text: Mapped[str]
    alias_type: Mapped[str]  # original | english | russian | aka | localized


class UserWatchItem(Base):
    """User's watchlist entry."""

    __tablename__ = "user_watch_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    media_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("media_items.id"), index=True
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.now(tz=_dt_timezone.utc)
    )


class UserNote(Base):
    """Free-form user note per media_item."""

    __tablename__ = "user_notes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    media_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("media_items.id"), index=True
    )
    note_text: Mapped[Optional[str]]


class Tag(Base):
    """Tag definition."""

    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str]  # e.g. "с женой", "RPG", "ужасы"


class WatchItemTag(Base):
    """Join table: which tags apply to which watch items."""

    __tablename__ = "watch_item_tags"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    media_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("media_items.id"), index=True
    )
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"))


class NotificationRule(Base):
    """Per watch item, what events the user cares about."""

    __tablename__ = "notification_rules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    media_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("media_items.id"), index=True
    )
    event_type: Mapped[str]  # e.g. DIGITAL_RELEASED, RUSSIAN_AUDIO_AVAILABLE
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class SourceState(Base):
    """Current state per source per media_item."""

    __tablename__ = "source_states"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    media_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("media_items.id"), index=True
    )
    source_name: Mapped[str]  # tmdb | anilist | igdb | steam | psn | kinopub
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.now(tz=_dt_timezone.utc)
    )
    state_data: Mapped[Optional[str]]  # JSON blob of normalized state


class ReleaseEvent(Base):
    """Domain events detected by state comparison."""

    __tablename__ = "release_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    media_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("media_items.id"), index=True
    )
    event_type: Mapped[str]  # DIGITAL_RELEASED, RUSSIAN_AUDIO_AVAILABLE, etc.
    old_state: Mapped[Optional[str]]  # JSON
    new_state: Mapped[Optional[str]]  # JSON
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.now(tz=_dt_timezone.utc)
    )


class SentNotification(Base):
    """Deduplication: which notifications have been sent."""

    __tablename__ = "sent_notifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_fingerprint: Mapped[str]  # stable hash for dedup
    media_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("media_items.id"), index=True
    )
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.now(tz=_dt_timezone.utc)
    )



