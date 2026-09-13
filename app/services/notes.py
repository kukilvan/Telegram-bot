"""Notes service (Phase 4): free-form user notes per media item."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import UserNote


def create_or_update_note(
    session: Session, user_id: int, media_item_id: str, note_text: str | None
) -> UserNote:
    """Create or update a note. Returns the stored row."""
    existing = session.execute(
        select(UserNote).where(
            (UserNote.user_id == user_id) &
            (UserNote.media_item_id == media_item_id)
        )
    ).scalar_one_or_none()
    if existing is None:
        note = UserNote(
            user_id=user_id, media_item_id=media_item_id, note_text=note_text
        )
        session.add(note)
    else:
        existing.note_text = note_text
        note = existing
    session.commit()
    return note


def get_note(session: Session, user_id: int, media_item_id: str):
    """Return the note for (user, item), or None."""
    return session.execute(
        select(UserNote).where(
            (UserNote.user_id == user_id) &
            (UserNote.media_item_id == media_item_id)
        )
    ).scalar_one_or_none()


def list_notes(session: Session, user_id: int):
    """List all notes for the user. Returns [(media_item_id, note_text), ...]."""
    rows = session.execute(
        select(UserNote).where(UserNote.user_id == user_id)
    ).scalars().all()
    return [(n.media_item_id, n.note_text) for n in rows]


def delete_note(session: Session, user_id: int, media_item_id: str) -> bool:
    """Delete a note. Returns True if something was removed."""
    existing = session.execute(
        select(UserNote).where(
            (UserNote.user_id == user_id) &
            (UserNote.media_item_id == media_item_id)
        )
    ).scalar_one_or_none()
    if existing is None:
        return False
    session.delete(existing)
    session.commit()
    return True
