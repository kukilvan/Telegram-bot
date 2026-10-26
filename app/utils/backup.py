"""Backup of the tracker database. By hand, from the bot's folder: `python -m app.utils.backup`."""

import asyncio
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from app.tracker.db import TRACKER_DATABASE_URL, database_file

BACKUP_FOLDER = "backups"  # next to the database file


def create_backup(url: str = TRACKER_DATABASE_URL) -> Path | None:
    """Copy the database the bot opens by this address into a dated file with SQLite's online backup (safe while
    the bot writes in WAL mode). The copy goes to `backups` next to the database file.

    Returns the backup path, or None if the database has no file (in memory, or not created yet)."""
    db_file = database_file(url)
    if db_file is None or not db_file.exists():
        return None

    backup_dir = db_file.parent / BACKUP_FOLDER
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"tracker_db_{timestamp}.db"

    source = sqlite3.connect(db_file)
    try:
        target = sqlite3.connect(backup_file)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
    return backup_file


async def backup_database(url: str = TRACKER_DATABASE_URL) -> None:
    """Scheduler job: back up the database in a worker thread (the bot keeps answering) and log the result."""
    backup = await asyncio.to_thread(create_backup, url)
    if backup:
        logging.info("Database backup created: %s", backup)
    else:
        logging.warning("No database file found for backup")


if __name__ == "__main__":
    print(create_backup() or "Нет файла базы, копировать нечего.")
