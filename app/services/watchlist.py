"""Watchlist service (Phase 4): add/remove/list media items."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import ExternalId, MediaItem, UserWatchItem


def get_media_item_by_external_id(
    session: Session, source: str, external_id: str
) -> MediaItem | None:
    """Find a MediaItem by one of its stable external IDs."""
    ext = session.execute(
        select(ExternalId).where(
            (ExternalId.source == source) &
            (ExternalId.external_id == external_id)
        )
    ).scalar_one_or_none()
    if ext is None:
        return None
    return session.get(MediaItem, ext.media_item_id)


def add_watch_item(session: Session, user_id: int, media_item_id: str):
    """Add a watch item. Returns the new row, or None if already present."""
    existing = session.execute(
        select(UserWatchItem).where(
            (UserWatchItem.user_id == user_id) &
            (UserWatchItem.media_item_id == media_item_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return None  # already in watchlist
    item = UserWatchItem(user_id=user_id, media_item_id=media_item_id)
    session.add(item)
    session.commit()
    return item


def remove_watch_item(session: Session, user_id: int, media_item_id: str) -> bool:
    """Remove a watch item. Returns True if something was removed."""
    existing = session.execute(
        select(UserWatchItem).where(
            (UserWatchItem.user_id == user_id) &
            (UserWatchItem.media_item_id == media_item_id)
        )
    ).scalar_one_or_none()
    if existing is None:
        return False
    session.delete(existing)
    session.commit()
    return True


def list_watch_items(
    session: Session, user_id: int, page: int = 1, per_page: int = 20
):
    """List watch items with pagination. Returns (items, total_count)."""
    offset = (page - 1) * per_page
    rows = session.execute(
        select(UserWatchItem)
        .where(UserWatchItem.user_id == user_id)
        .order_by(UserWatchItem.added_at.desc())
        .offset(offset)
        .limit(per_page)
    ).scalars().all()
    total = session.execute(
        select(func.count(UserWatchItem.id)).where(
            UserWatchItem.user_id == user_id
        )
    ).scalar_one()
    return rows, total
