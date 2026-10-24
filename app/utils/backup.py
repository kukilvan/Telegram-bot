import logging
import sqlite3
from datetime import datetime
from pathlib import Path

DB_DIR = Path(__file__).parent.parent.parent / "data"
DB_FILE = DB_DIR / "tracker.db"
BACKUP_DIR = DB_DIR / "backups"


def create_backup() -> Path | None:
    """Copy the tracker database into a dated file with SQLite's online backup (safe while the bot writes in WAL mode).

    Returns the backup path, or None if the database does not exist."""
    if not DB_FILE.exists():
        return None

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = BACKUP_DIR / f"tracker_db_{timestamp}.db"

    source = sqlite3.connect(DB_FILE)
    try:
        target = sqlite3.connect(backup_file)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
    return backup_file


def backup_database() -> None:
    """Scheduler job: back up the database and log the result."""
    backup = create_backup()
    if backup:
        logging.info(f"Database backup created: {backup}")
    else:
        logging.warning("No database file found for backup")
