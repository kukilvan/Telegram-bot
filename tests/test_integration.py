"""Integration tests for main bot flows: watchlist, notes, events, backup, logging.

Phase 15: Tests, backups, logging
Run: .venv\\Scripts\\python.exe -m pytest tests/test_integration.py -v
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.database.models import (
    ExternalId,
    MediaItem,
    NotificationRule,
    SourceState,
    User,
    UserNote,
    UserWatchItem,
)
from app.services.watchlist import add_watch_item, remove_watch_item, list_watch_items, get_media_item_by_external_id
from app.services.notes import create_or_update_note, get_note, list_notes, delete_note
from app.services.notifications import has_been_sent, mark_sent, get_enabled_rules, set_rule
from app.domain.events import compare_states, DIGITAL_DATE_ANNOUNCED
from app.utils.backup import create_backup
from app.utils.logging_config import setup_logging


@pytest.fixture
def db_path(tmp_path):
    """Create a temporary SQLite database for each test."""
    db_file = tmp_path / "test_bot.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return db_file, Session


@pytest.fixture
def session(db_path):
    """Provide a database session for testing."""
    _, Session = db_path
    s = Session()
    yield s
    s.close()


@pytest.fixture
def user(session):
    """Create a test user."""
    user = User(telegram_user_id=123456, username="testuser", timezone="Asia/Jerusalem")
    session.add(user)
    session.commit()
    return user


@pytest.fixture
def media_item(session):
    """Create a test media item."""
    item = MediaItem(
        id="test-media-1",
        media_type="movie",
        canonical_title_en="Test Movie",
        title_ru="Тестовый фильм",
        year=2024,
        description="Test description",
    )
    session.add(item)
    session.commit()
    
    ext_id = ExternalId(media_item_id=item.id, source="tmdb", external_id="12345")
    session.add(ext_id)
    session.commit()
    
    return item


# ==================== Watchlist Tests ====================

def test_add_and_remove_watch_item(session, user, media_item):
    """Test adding and removing items from watchlist."""
    result = add_watch_item(session, user.id, media_item.id)
    assert result is not None
    assert result.media_item_id == media_item.id
    
    watchlist, total = list_watch_items(session, user.id)
    assert len(watchlist) == 1
    assert watchlist[0].media_item_id == media_item.id
    
    result = remove_watch_item(session, user.id, media_item.id)
    assert result is True
    
    watchlist, total = list_watch_items(session, user.id)
    assert len(watchlist) == 0


def test_get_media_item_by_external_id(session, media_item):
    """Test retrieving media item by external ID."""
    item = get_media_item_by_external_id(session, "tmdb", "12345")
    assert item is not None
    assert item.id == media_item.id
    
    item = get_media_item_by_external_id(session, "tmdb", "nonexistent")
    assert item is None


# ==================== Notes Tests ====================

def test_notes_crud(session, user, media_item):
    """Test notes CRUD operations."""
    note = create_or_update_note(session, user.id, media_item.id, "Test note content")
    assert note is not None
    assert note.note_text == "Test note content"
    
    retrieved = get_note(session, user.id, media_item.id)
    assert retrieved is not None
    assert retrieved.note_text == "Test note content"
    
    notes = list_notes(session, user.id)
    assert len(notes) == 1
    
    updated = create_or_update_note(session, user.id, media_item.id, "Updated note")
    assert updated.note_text == "Updated note"
    
    deleted = delete_note(session, user.id, media_item.id)
    assert deleted is True
    
    retrieved = get_note(session, user.id, media_item.id)
    assert retrieved is None


# ==================== Event Detection Tests ====================

def test_compare_states_detects_digital_date():
    """Test that compare_states detects new digital release date."""
    old_state = {"digital_release": None}
    new_state = {"digital_release": "2024-12-25"}
    
    events = compare_states(old_state, new_state)
    event_types = [e.event_type for e in events]
    assert DIGITAL_DATE_ANNOUNCED in event_types


def test_compare_states_no_event_on_no_change():
    """Test that no event is fired when state doesn't change."""
    old_state = {"digital_release": "2024-12-25"}
    new_state = {"digital_release": "2024-12-25"}
    
    events = compare_states(old_state, new_state)
    assert len(events) == 0


# ==================== Notification Tests ====================

def test_dedup_mark_sent(session):
    """Test notification deduplication."""
    fp = "test-fingerprint-123"
    media_id = "test-media-1"
    
    result = mark_sent(session, fp, media_id)
    assert result is True
    
    result = mark_sent(session, fp, media_id)
    assert result is False
    
    assert has_been_sent(session, fp) is True


# ==================== Backup Tests ====================

def test_backup_creates_file(session, db_path):
    """Test that backup creates a dated file."""
    db_file, _ = db_path
    
    with patch("app.utils.backup.DB_FILE", db_file):
        backup = create_backup()
    
    assert backup is not None
    assert backup.exists()
    assert "bot_db_" in str(backup)
    assert backup.suffix == ".db"


# ==================== Logging Tests ====================

def test_setup_logging_creates_directory(tmp_path):
    """Test that setup logging creates logs directory."""
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    with patch("app.utils.logging_config.LOG_DIR", logs_dir):
        setup_logging(level="DEBUG")
    
    assert logs_dir.exists()
    assert (logs_dir / "bot.log").exists()
