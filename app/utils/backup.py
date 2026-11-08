"""Backups of the tracker database: the daily copy when the last one is over a day old, the manual copy, the reading of
the folder as a list of copies, and the rotation of the old ones.

By hand, from the bot's folder: `python -m app.utils.backup` (copies at once, whatever the last copy's age).
The copy before a migration is made by `app/tracker/db.py` (`tracker_db_<time>_before-<revision>.db`) and the copy before
a restore by the restore script; rotation never touches them, nor any file whose name is not exactly that of the copy
whose rotation it is (the daily and the manual copies each have their own).
"""

import asyncio
import contextlib
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import NamedTuple

from app.tracker.db import (
    BACKUP_FOLDER,
    BACKUP_STAMP_FORMAT,
    TRACKER_DATABASE_URL,
    backup_name,
    copy_database,
    database_file,
)

COPY_NAME = re.compile(r"^tracker_db_(\d{8}_\d{6})(?:_(manual|before-.+))?\.db$")  # a valid time, one of the suffixes
DAILY, MANUAL, OTHER = "daily", "manual", "other"  # the kinds of a copy; the others are those made before an update or a restore
KIND_ORDER = {DAILY: 0, MANUAL: 1, OTHER: 2}  # on equal times in a name: the daily copy first
MANUAL_SUFFIX = "manual"
BEFORE_RESTORE_SUFFIX = "before-restore"  # the copy of the base the restore replaces (`app/utils/restore.py`)
KEPT_MANUAL = 10  # manual copies kept: the newest
DUE_AFTER = timedelta(hours=24)  # a new copy once the newest daily one is older than this
KEPT_NEWEST = 14  # daily copies kept: the newest
KEPT_MONTHS = 12  # and the earliest daily copy of each of this many calendar months, counting the current one


class Copy(NamedTuple):
    moment: datetime  # the time written in the name (the container's clock)
    path: Path
    kind: str  # DAILY, MANUAL or OTHER


def copies(folder: Path) -> list[Copy]:
    """The copies in the folder, newest first, by the time written in their names (the file date is not used: copying
    the folder changes it); on equal times the daily copy comes before the manual one and that before the others. A name
    that only looks like a copy (no such date, another suffix) is not in the list. A folder that does not exist has none;
    one that cannot be read raises `OSError`."""
    found = []
    if folder.is_dir():
        for path in folder.iterdir():
            match = COPY_NAME.match(path.name)
            if match is None:
                continue
            try:
                moment = datetime.strptime(match.group(1), BACKUP_STAMP_FORMAT)
            except ValueError:  # no such date
                continue
            suffix = match.group(2)
            kind = DAILY if suffix is None else MANUAL if suffix == MANUAL_SUFFIX else OTHER
            found.append(Copy(moment, path, kind))
    found.sort(key=lambda copy: (KIND_ORDER[copy.kind], copy.path.name))
    return sorted(found, key=lambda copy: copy.moment, reverse=True)  # stable: equal times keep the order above


def _of_kind(folder: Path, kind: str) -> list[tuple[datetime, Path]]:
    return sorted((copy.moment, copy.path) for copy in copies(folder) if copy.kind == kind)


def daily_backups(folder: Path) -> list[tuple[datetime, Path]]:
    """The daily copies in the folder, oldest first, with the time written in their names. Names that only look like a
    daily copy (and the manual copies) are not in the list."""
    return _of_kind(folder, DAILY)


def rotate(folder: Path, now: datetime) -> None:
    """Delete the daily copies that are neither among the 14 newest nor the earliest of one of the last 12 calendar
    months (up to the month of `now`). Other files in the folder are left alone."""
    daily = daily_backups(folder)
    keep = {path for _, path in daily[-KEPT_NEWEST:]}
    this_month = now.year * 12 + now.month
    earliest: dict[int, Path] = {}
    for moment, path in daily:  # oldest first: the first one met in a month is its earliest
        earliest.setdefault(moment.year * 12 + moment.month, path)
    keep.update(path for month, path in earliest.items() if this_month - KEPT_MONTHS < month <= this_month)
    for _, path in daily:
        if path not in keep:
            try:
                path.unlink()
            except OSError as exc:  # in use, say: it goes at the next rotation
                logging.warning("Old backup not deleted: %s (%r)", path, exc)


def rotate_manual(folder: Path) -> None:
    """Delete the manual copies but the 10 newest. Daily copies and the others are left alone; the daily rotation does not
    see the manual copies either."""
    for _, path in _of_kind(folder, MANUAL)[:-KEPT_MANUAL]:
        try:
            path.unlink()
        except OSError as exc:  # in use, say: it goes at the next rotation
            logging.warning("Old manual backup not deleted: %s (%r)", path, exc)


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


def create_manual_backup(url: str = TRACKER_DATABASE_URL, now: datetime | None = None) -> Copy | None:
    """The manual copy `tracker_db_<time>_manual.db` (SQLite's online backup, as the daily one), then the rotation of the
    manual copies. It does not move the daily schedule. A copy of the same second is `FileExistsError`: nothing is made.
    A failed rotation is a warning: the copy is made.

    Returns the copy, or None if the database has no file (in memory, or not created yet)."""
    db_file = database_file(url)
    if db_file is None or not db_file.exists():
        return None
    now = now or datetime.now()
    backup_dir = db_file.parent / BACKUP_FOLDER
    target = backup_dir / backup_name(now, MANUAL_SUFFIX)
    if target.exists():
        raise FileExistsError(target)
    copy_database(db_file, target)
    try:
        rotate_manual(backup_dir)
    except Exception as exc:
        logging.warning("Manual backup rotation failed, old copies stay: %r", exc)
    return Copy(datetime.strptime(now.strftime(BACKUP_STAMP_FORMAT), BACKUP_STAMP_FORMAT), target, MANUAL)


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


async def backup_database(
    url: str = TRACKER_DATABASE_URL,
    *,
    lock: asyncio.Lock | None = None,
    on_failure: Callable[[Exception], Awaitable[None]] | None = None,
) -> None:
    """Scheduler job: back up the database if a copy is due, in a worker thread (the bot keeps answering), and log
    the result. A failure is a warning in the log: the bot goes on, the next try is at the next run. With a `lock` the
    copy waits for its turn (one copy at a time); `on_failure` is told of a failed copy once the lock is free."""
    failure = None
    async with lock or contextlib.nullcontext():
        try:
            backup = await asyncio.to_thread(backup_if_due, url)
        except Exception as exc:
            logging.warning("Database backup failed: %r", exc)
            failure = exc
        else:
            if backup:
                logging.info("Database backup created: %s", backup)
            else:
                file = database_file(url)
                if file is None or not file.exists():
                    logging.warning("No database file found for backup")
    if failure is not None and on_failure is not None:
        try:
            await on_failure(failure)
        except Exception as exc:  # the report is no reason to stop the job
            logging.warning("The report of the failed backup was not made: %r", exc)


if __name__ == "__main__":
    print(create_backup() or "Нет файла базы, копировать нечего.")
