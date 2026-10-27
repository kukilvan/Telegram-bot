"""Backup of the tracker database: a copy when the last one is over a day old, and rotation of the old ones.

By hand, from the bot's folder: `python -m app.utils.backup` (copies at once, whatever the last copy's age).
The copy before a migration is made by `app/tracker/db.py` (`tracker_db_<time>_before-<revision>.db`); rotation never
touches it, nor any file whose name is not exactly that of a daily copy.
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from app.tracker.db import (
    BACKUP_FOLDER,
    BACKUP_STAMP_FORMAT,
    TRACKER_DATABASE_URL,
    backup_name,
    copy_database,
    database_file,
)

DAILY_NAME = re.compile(r"^tracker_db_(\d{8}_\d{6})\.db$")  # exactly: no suffix, nothing before or after
DUE_AFTER = timedelta(hours=24)  # a new copy once the newest daily one is older than this
KEPT_NEWEST = 14  # daily copies kept: the newest
KEPT_MONTHS = 12  # and the earliest daily copy of each of this many calendar months, counting the current one


def daily_backups(folder: Path) -> list[tuple[datetime, Path]]:
    """The daily copies in the folder, oldest first, with the time written in their names (the file date is not
    used: copying the folder changes it). Names that only look like a daily copy are not in the list."""
    found = []
    if folder.is_dir():
        for path in folder.iterdir():
            match = DAILY_NAME.match(path.name)
            if match is None:
                continue
            try:
                found.append((datetime.strptime(match.group(1), BACKUP_STAMP_FORMAT), path))
            except ValueError:  # no such date
                continue
    return sorted(found)


def rotate(folder: Path, now: datetime) -> None:
    """Delete the daily copies that are neither among the 14 newest nor the earliest of one of the last 12 calendar
    months (up to the month of `now`). Other files in the folder are left alone."""
    copies = daily_backups(folder)
    keep = {path for _, path in copies[-KEPT_NEWEST:]}
    this_month = now.year * 12 + now.month
    earliest: dict[int, Path] = {}
    for moment, path in copies:  # oldest first: the first one met in a month is its earliest
        earliest.setdefault(moment.year * 12 + moment.month, path)
    keep.update(path for month, path in earliest.items() if this_month - KEPT_MONTHS < month <= this_month)
    for _, path in copies:
        if path not in keep:
            try:
                path.unlink()
            except OSError as exc:  # in use, say: it goes at the next rotation
                logging.warning("Old backup not deleted: %s (%r)", path, exc)


def create_backup(url: str = TRACKER_DATABASE_URL, now: datetime | None = None) -> Path | None:
    """Copy the database the bot opens by this address into a dated file with SQLite's online backup (safe while
    the bot writes in WAL mode), then rotate the old copies. The copy goes to `backups` next to the database file and
    is named by `now` (local time; the current time by default). A failed rotation is a warning: the copy is made.

    Returns the backup path, or None if the database has no file (in memory, or not created yet)."""
    db_file = database_file(url)
    if db_file is None or not db_file.exists():
        return None

    now = now or datetime.now()
    backup_dir = db_file.parent / BACKUP_FOLDER
    backup_file = backup_dir / backup_name(now)
    copy_database(db_file, backup_file)
    try:
        rotate(backup_dir, now)
    except Exception as exc:
        logging.warning("Backup rotation failed, old copies stay: %r", exc)
    return backup_file


def backup_if_due(url: str = TRACKER_DATABASE_URL, now: datetime | None = None) -> Path | None:
    """`create_backup`, but only if the newest daily copy is more than 24 hours old (by the time in its name) or there
    is none. Returns the new copy's path, or None if nothing was made."""
    db_file = database_file(url)
    if db_file is None or not db_file.exists():
        return None
    now = now or datetime.now()
    copies = daily_backups(db_file.parent / BACKUP_FOLDER)
    if copies and now - copies[-1][0] <= DUE_AFTER:
        return None
    return create_backup(url, now)


async def backup_database(url: str = TRACKER_DATABASE_URL) -> None:
    """Scheduler job: back up the database if a copy is due, in a worker thread (the bot keeps answering), and log
    the result. A failure is a warning in the log: the bot goes on, the next try is at the next run."""
    try:
        backup = await asyncio.to_thread(backup_if_due, url)
    except Exception as exc:
        logging.warning("Database backup failed: %r", exc)
        return
    if backup:
        logging.info("Database backup created: %s", backup)
    else:
        file = database_file(url)
        if file is None or not file.exists():
            logging.warning("No database file found for backup")


if __name__ == "__main__":
    print(create_backup() or "Нет файла базы, копировать нечего.")
