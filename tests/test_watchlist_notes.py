"""Tests for watchlist + notes services (in-memory SQLite via StaticPool, no network)."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import MediaItem, User


def _make_session():
    """Fresh in-memory engine + schema; one shared connection (StaticPool)."""
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return factory()


def test_add_remove_watch_item():
    from app.services.watchlist import (
        add_watch_item,
        list_watch_items,
        remove_watch_item,
    )

    s = _make_session()
    user = User(telegram_user_id=454501218)
    s.add(user)
    s.commit()
    item = MediaItem(media_type="movie", canonical_title_en="Dune")
    s.add(item)
    s.flush()  # generate UUID primary key before FK reference
    s.commit()

    added = add_watch_item(s, user.id, item.id)
    assert added is not None
    dup = add_watch_item(s, user.id, item.id)
    assert dup is None  # duplicate add returns None
    items, total = list_watch_items(s, user.id)
    assert total == 1 and len(items) == 1

    ok = remove_watch_item(s, user.id, item.id)
    assert ok is True
    ok2 = remove_watch_item(s, user.id, item.id)
    assert ok2 is False
    s.close()


def test_notes_crud():
    from app.services.notes import (
        create_or_update_note,
        delete_note,
        get_note,
        list_notes,
    )

    s = _make_session()
    user = User(telegram_user_id=454501218)
    s.add(user)
    s.commit()
    item = MediaItem(media_type="movie", canonical_title_en="Dune")
    s.add(item)
    s.flush()  # generate UUID primary key before FK reference
    s.commit()

    create_or_update_note(s, user.id, item.id, "Моя заметка")
    assert get_note(s, user.id, item.id).note_text == "Моя заметка"
    create_or_update_note(s, user.id, item.id, "Обновлено")
    assert get_note(s, user.id, item.id).note_text == "Обновлено"
    rows = list_notes(s, user.id)
    assert len(rows) == 1 and rows[0][1] == "Обновлено"
    ok = delete_note(s, user.id, item.id)
    assert ok is True
    s.close()


if __name__ == "__main__":
    # Run directly without pytest (pytest not yet installed in .venv).
    test_add_remove_watch_item()
    test_notes_crud()
    print("watchlist + notes tests passed")
