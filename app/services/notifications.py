"""Notification dedup + rules service (Phase 5)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import NotificationRule, SentNotification


def has_been_sent(session: Session, event_fingerprint: str) -> bool:
    """Return True if this exact event was already sent (dedup check)."""
    row = session.execute(
        select(SentNotification).where(
            SentNotification.event_fingerprint == event_fingerprint
        )
    ).scalar_one_or_none()
    return row is not None


def mark_sent(session: Session, fingerprint: str, media_item_id: str) -> bool:
    """Record a notification as sent. Returns True if newly recorded."""
    existing = session.execute(
        select(SentNotification).where(
            SentNotification.event_fingerprint == fingerprint
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False  # already sent (dedup)
    row = SentNotification(event_fingerprint=fingerprint, media_item_id=media_item_id)
    session.add(row)
    session.commit()
    return True


def get_enabled_rules(session: Session, user_id: int, media_item_id: str):
    """Return enabled notification rules for (user, item)."""
    rows = session.execute(
        select(NotificationRule).where(
            (NotificationRule.user_id == user_id) &
            (NotificationRule.media_item_id == media_item_id) &
            (NotificationRule.enabled.is_(True))
        )
    ).scalars().all()
    return rows


def set_rule(session: Session, user_id: int, media_item_id: str, event_type: str, enabled: bool):
    """Create or update a notification rule. Returns the row."""
    existing = session.execute(
        select(NotificationRule).where(
            (NotificationRule.user_id == user_id) &
            (NotificationRule.media_item_id == media_item_id) &
            (NotificationRule.event_type == event_type)
        )
    ).scalar_one_or_none()
    if existing is None:
        row = NotificationRule(
            user_id=user_id,
            media_item_id=media_item_id,
            event_type=event_type,
            enabled=enabled,
        )
        session.add(row)
    else:
        existing.enabled = enabled
        row = existing
    session.commit()
    return row
