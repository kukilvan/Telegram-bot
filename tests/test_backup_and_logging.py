"""The database backup (when it is due, rotation, the copy before a migration, the scheduler job) and the log directory."""

import asyncio
import logging
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.bot.main import BACKUP_EVERY_HOURS, add_jobs
from app.tracker.db import (
    MIGRATIONS_DIR,
    TRACKER_DATABASE_URL,
    create_session_factory,
    create_tracker_engine,
    database_file,
)
from app.utils import backup
from app.utils.backup import backup_database, backup_if_due, create_backup
from app.utils.logging_config import setup_logging

DAILY = re.compile(r"^tracker_db_\d{8}_\d{6}\.db$")
NOW = datetime(2026, 10, 27, 12, 0, 0)  # the clock of the tests: they do not depend on today's date


def make_database(path: Path, name: str = "Дюна") -> str:
    """A small SQLite file at `path`; returns the address the bot would open it by."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE titles (id INTEGER PRIMARY KEY, name TEXT)")
    connection.execute("INSERT INTO titles (name) VALUES (?)", (name,))
    connection.commit()
    connection.close()
    return f"sqlite:///{path.as_posix()}"


def names_in(path: Path) -> list[str]:
    copy = sqlite3.connect(path)
    try:
        return [row[0] for row in copy.execute("SELECT name FROM titles")]
    finally:
        copy.close()


def daily_name(moment: datetime) -> str:
    return f"tracker_db_{moment:%Y%m%d_%H%M%S}.db"


def daily_files(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir() if DAILY.match(p.name)) if folder.exists() else []


def put_copy(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(b"old copy")
    return path


# --- where the database is -----------------------------------------------------------------------


def test_the_database_file_is_read_from_the_address_the_bot_opens_it_by():
    assert database_file("sqlite:///./data/tracker.db") == Path("./data/tracker.db")
    assert database_file(TRACKER_DATABASE_URL) == Path("./data/tracker.db")


def test_an_absolute_address_gives_an_absolute_file(tmp_path):
    assert database_file(f"sqlite:///{(tmp_path / 'x.db').as_posix()}") == tmp_path / "x.db"


@pytest.mark.parametrize("url", ["sqlite://", "sqlite:///:memory:"])
def test_an_in_memory_database_has_no_file(url):
    assert database_file(url) is None


# --- the copy ------------------------------------------------------------------------------------


def test_backup_copies_the_database_into_a_dated_file(tmp_path):
    url = make_database(tmp_path / "tracker.db")

    result = create_backup(url)

    assert result is not None and DAILY.match(result.name)
    assert names_in(result) == ["Дюна"]


def test_the_copy_is_named_by_the_clock_it_is_given(tmp_path):
    result = create_backup(make_database(tmp_path / "tracker.db"), NOW)

    assert result.name == "tracker_db_20261027_120000.db"


def test_the_backups_lie_in_a_folder_next_to_the_database_wherever_it_is(tmp_path):
    first = create_backup(make_database(tmp_path / "one" / "tracker.db", "Первая"))
    second = create_backup(make_database(tmp_path / "volume" / "other.db", "Вторая"))

    assert first.parent == tmp_path / "one" / "backups" and names_in(first) == ["Первая"]
    assert second.parent == tmp_path / "volume" / "backups" and names_in(second) == ["Вторая"]


def test_the_default_is_the_database_the_bot_opens_by_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    make_database(tmp_path / "data" / "tracker.db", "Из папки бота")

    result = create_backup()

    assert result.parent == Path("data") / "backups" and names_in(result) == ["Из папки бота"]


def test_backup_without_a_database_does_nothing(tmp_path):
    assert create_backup(f"sqlite:///{(tmp_path / 'missing.db').as_posix()}") is None
    assert not (tmp_path / "backups").exists()


def test_backup_of_an_in_memory_database_does_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert create_backup("sqlite://") is None
    assert not (tmp_path / "backups").exists()


def test_the_copy_by_hand_ignores_the_age_of_the_last_one(tmp_path):
    url = make_database(tmp_path / "tracker.db")
    put_copy(tmp_path / "backups", daily_name(NOW - timedelta(minutes=5)))

    result = create_backup(url, NOW)

    assert result is not None and result.name == daily_name(NOW)


def test_a_failed_copy_leaves_no_half_made_file_to_pass_for_a_fresh_copy(tmp_path):
    broken = tmp_path / "tracker.db"
    broken.write_bytes(b"this is not a database" * 500)

    with pytest.raises(sqlite3.DatabaseError):
        create_backup(f"sqlite:///{broken.as_posix()}", NOW)

    assert list((tmp_path / "backups").iterdir()) == []


# --- when a copy is due --------------------------------------------------------------------------


def test_without_copies_a_copy_is_made(tmp_path):
    url = make_database(tmp_path / "tracker.db")

    result = backup_if_due(url, NOW)

    assert result == tmp_path / "backups" / daily_name(NOW)
    assert names_in(result) == ["Дюна"]


def test_a_copy_of_23_hours_is_fresh_enough(tmp_path):
    url = make_database(tmp_path / "tracker.db")
    put_copy(tmp_path / "backups", daily_name(NOW - timedelta(hours=23)))

    assert backup_if_due(url, NOW) is None
    assert len(daily_files(tmp_path / "backups")) == 1


def test_a_copy_of_25_hours_is_stale(tmp_path):
    url = make_database(tmp_path / "tracker.db")
    put_copy(tmp_path / "backups", daily_name(NOW - timedelta(hours=25)))

    result = backup_if_due(url, NOW)

    assert result is not None and result.name == daily_name(NOW)
    assert len(daily_files(tmp_path / "backups")) == 2


def test_exactly_24_hours_is_not_yet_more_than_a_day(tmp_path):
    url = make_database(tmp_path / "tracker.db")
    put_copy(tmp_path / "backups", daily_name(NOW - timedelta(hours=24)))

    assert backup_if_due(url, NOW) is None


def test_the_age_is_read_from_the_name_not_from_the_file_date(tmp_path):
    url = make_database(tmp_path / "tracker.db")
    old = put_copy(tmp_path / "backups", daily_name(NOW - timedelta(days=3)))  # but the file itself was written just now

    assert old.stat().st_mtime > time.time() - 60
    assert backup_if_due(url, NOW) is not None


def test_only_the_newest_daily_copy_counts_and_other_files_do_not(tmp_path):
    url = make_database(tmp_path / "tracker.db")
    backups = tmp_path / "backups"
    put_copy(backups, daily_name(NOW - timedelta(days=9)))
    put_copy(backups, daily_name(NOW - timedelta(days=2)))
    put_copy(backups, daily_name(NOW - timedelta(minutes=5)).replace(".db", "_before-0008.db"))  # before a migration
    put_copy(backups, "tracker-before-0008.db")  # by hand

    assert backup_if_due(url, NOW) is not None  # the newest *daily* is two days old


def test_the_clock_defaults_to_the_current_time(tmp_path):
    result = backup_if_due(make_database(tmp_path / "tracker.db"))

    stamp = datetime.strptime(result.name, "tracker_db_%Y%m%d_%H%M%S.db")
    assert abs(stamp - datetime.now()) < timedelta(minutes=1)


def test_a_database_without_a_file_gives_no_copy(tmp_path):
    assert backup_if_due(f"sqlite:///{(tmp_path / 'gone.db').as_posix()}", NOW) is None
    assert backup_if_due("sqlite://", NOW) is None


# --- rotation ------------------------------------------------------------------------------------


def month_back(moment: datetime, months: int) -> datetime:
    index = moment.year * 12 + moment.month - 1 - months
    return moment.replace(year=index // 12, month=index % 12 + 1, day=1)


def test_rotation_keeps_the_14_newest_and_the_earliest_of_each_of_the_last_12_months(tmp_path):
    url = make_database(tmp_path / "tracker.db")
    backups = tmp_path / "backups"
    moments = set()
    for months in range(1, 15):  # 14 past months, three copies in each: the 5th, 15th and 25th
        for day in (5, 15, 25):
            moments.add(month_back(NOW, months).replace(day=day, hour=3))
    for day in range(1, 27):  # and one every day of this month up to yesterday
        moments.add(NOW.replace(day=day, hour=4))
    assert len(moments) > 40
    for moment in moments:
        put_copy(backups, daily_name(moment))
    kept_by_hand = [
        put_copy(backups, name)
        for name in ("tracker-before-0008.db", "my copy.db", "tracker_db_20250101_000000_before-0008.db")
    ]

    create_backup(url, NOW)  # one more copy, then the rotation

    everything = sorted(moments | {NOW})
    window = {(month_back(NOW, k).year, month_back(NOW, k).month) for k in range(12)}  # this month and 11 before it
    expected = {daily_name(m) for m in everything[-14:]}
    for month in window:
        expected.add(daily_name(next(m for m in everything if (m.year, m.month) == month)))
    assert set(daily_files(backups)) == expected
    assert len(expected) == 14 + 12  # none of the 12 earliest copies is among the 14 newest
    assert all(path.exists() for path in kept_by_hand)
    assert not any((backups / daily_name(m)).exists() for m in moments if (m.year, m.month) not in window)


def test_rotation_removes_nothing_when_there_are_few_copies(tmp_path):
    url = make_database(tmp_path / "tracker.db")
    backups = tmp_path / "backups"
    for days in (1, 2, 3):
        put_copy(backups, daily_name(NOW - timedelta(days=days)))

    create_backup(url, NOW)

    assert len(daily_files(backups)) == 4


def test_the_earliest_copy_of_a_month_survives_beyond_the_14_newest(tmp_path):
    url = make_database(tmp_path / "tracker.db")
    backups = tmp_path / "backups"
    for day in range(1, 21):
        put_copy(backups, daily_name(datetime(2026, 5, day, 12)))  # twenty copies of one old month

    create_backup(url, NOW)

    kept = daily_files(backups)
    expected = [daily_name(datetime(2026, 5, 1, 12))] + [daily_name(datetime(2026, 5, d, 12)) for d in range(8, 21)]
    assert kept == expected + [daily_name(NOW)]


def test_a_name_that_only_looks_like_a_daily_copy_is_never_removed(tmp_path):
    url = make_database(tmp_path / "tracker.db")
    backups = tmp_path / "backups"
    odd = [
        put_copy(backups, "tracker_db_20250101_000000.db.bak"),
        put_copy(backups, "tracker_db_20251301_000000.db"),  # no such month
        put_copy(backups, "tracker_db_2025.db"),
        put_copy(backups, "Tracker_db_20250101_000000.db"),
        put_copy(backups, "tracker_db_20250101_000000_before-0007.db"),
    ]

    create_backup(url, NOW)

    assert all(path.exists() for path in odd)


# --- the copy before a migration -----------------------------------------------------------------


def alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return config


def head_revision() -> str:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def migrated_file(path: Path, revision: str) -> str:
    """A database file of the tracker, migrated up to `revision` and closed."""
    url = f"sqlite:///{path.as_posix()}"
    engine = create_tracker_engine(url)
    with engine.begin() as connection:
        config = alembic_config()
        config.attributes["connection"] = connection
        command.upgrade(config, revision)
    engine.dispose()
    return url


def revision_of(file: Path) -> str:
    connection = sqlite3.connect(file)
    try:
        return connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    finally:
        connection.close()


def test_a_database_with_pending_migrations_is_copied_first_and_then_migrated(tmp_path):
    url = migrated_file(tmp_path / "tracker.db", "0007")

    create_session_factory(url, now=NOW)

    copy = tmp_path / "backups" / f"tracker_db_{NOW:%Y%m%d_%H%M%S}_before-0007.db"
    assert copy.exists()
    assert revision_of(copy) == "0007"  # the copy is the database as it was
    assert revision_of(tmp_path / "tracker.db") == head_revision()


def test_the_copy_before_a_migration_does_not_count_as_a_daily_one(tmp_path):
    url = migrated_file(tmp_path / "tracker.db", "0007")

    create_session_factory(url, now=NOW)

    assert daily_files(tmp_path / "backups") == []
    assert backup_if_due(url, NOW) is not None  # the daily copy is still due


def test_a_database_that_is_already_current_gets_no_copy_before_migration(tmp_path):
    url = migrated_file(tmp_path / "tracker.db", "head")

    create_session_factory(url, now=NOW)

    assert not (tmp_path / "backups").exists()


def test_a_new_database_gets_no_copy(tmp_path):
    url = f"sqlite:///{(tmp_path / 'fresh' / 'tracker.db').as_posix()}"

    create_session_factory(url, now=NOW)

    assert not (tmp_path / "fresh" / "backups").exists()
    assert revision_of(tmp_path / "fresh" / "tracker.db") == head_revision()


def test_an_in_memory_database_gets_no_copy(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    create_session_factory("sqlite://", now=NOW)

    assert not (tmp_path / "backups").exists()


def test_when_the_copy_fails_the_migration_does_not_run(tmp_path):
    url = migrated_file(tmp_path / "tracker.db", "0007")

    with patch("app.tracker.db.copy_database", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            create_session_factory(url, now=NOW)

    assert revision_of(tmp_path / "tracker.db") == "0007"


# --- the scheduler job ---------------------------------------------------------------------------


def test_the_job_copies_in_a_worker_thread_not_in_the_event_loop(tmp_path):
    threads = []
    real_copy = backup.create_backup

    def spying_copy(url, now=None):
        threads.append(threading.current_thread())
        return real_copy(url, now)

    async def job():
        loop_thread = threading.current_thread()
        with patch.object(backup, "create_backup", spying_copy):
            await backup_database(make_database(tmp_path / "tracker.db"))
        return loop_thread

    loop_thread = asyncio.run(job())

    assert len(threads) == 1 and threads[0] is not loop_thread


def test_the_bot_keeps_answering_while_the_copy_runs(tmp_path):
    ticks = []

    def slow_copy(url, now=None):
        time.sleep(0.3)
        return None

    async def ticker():
        for _ in range(5):
            await asyncio.sleep(0.01)
            ticks.append(1)

    async def job():
        with patch.object(backup, "create_backup", slow_copy):
            backing_up = asyncio.create_task(backup_database(make_database(tmp_path / "tracker.db")))
            await ticker()
            ticked_during_copy = not backing_up.done()
            await backing_up
        return ticked_during_copy

    assert asyncio.run(job()) is True
    assert len(ticks) == 5


def test_the_job_logs_what_it_made_or_that_there_was_nothing(tmp_path, caplog):
    with caplog.at_level(logging.INFO):
        asyncio.run(backup_database(make_database(tmp_path / "tracker.db")))
        asyncio.run(backup_database(f"sqlite:///{(tmp_path / 'gone.db').as_posix()}"))

    assert "Database backup created" in caplog.text
    assert "No database file found for backup" in caplog.text


def test_the_job_makes_no_copy_and_says_nothing_when_the_last_one_is_fresh(tmp_path, caplog):
    url = make_database(tmp_path / "tracker.db")
    put_copy(tmp_path / "backups", daily_name(datetime.now() - timedelta(hours=1)))

    with caplog.at_level(logging.INFO):
        asyncio.run(backup_database(url))

    assert len(daily_files(tmp_path / "backups")) == 1
    assert "Database backup created" not in caplog.text


def test_a_failed_copy_in_the_job_is_a_warning_not_a_crash(tmp_path, caplog):
    url = make_database(tmp_path / "tracker.db")

    with patch.object(backup, "create_backup", side_effect=OSError("disk full")):
        with caplog.at_level(logging.WARNING):
            asyncio.run(backup_database(url))  # does not raise

    assert any(r.levelno == logging.WARNING and "backup failed" in r.getMessage() for r in caplog.records)


def test_a_failed_rotation_is_a_warning_and_the_copy_stays(tmp_path, caplog):
    url = make_database(tmp_path / "tracker.db")

    with patch.object(backup, "rotate", side_effect=PermissionError("in use")):
        with caplog.at_level(logging.WARNING):
            asyncio.run(backup_database(url))

    assert len(daily_files(tmp_path / "backups")) == 1
    assert any(r.levelno == logging.WARNING and "rotation failed" in r.getMessage() for r in caplog.records)


def test_a_file_that_cannot_be_deleted_does_not_stop_the_rotation(tmp_path, caplog):
    url = make_database(tmp_path / "tracker.db")
    backups = tmp_path / "backups"
    for day in range(1, 21):
        put_copy(backups, daily_name(datetime(2026, 5, day, 12)))
    stuck = backups / daily_name(datetime(2026, 5, 2, 12))
    real_unlink = Path.unlink

    def unlink(path, *args, **kwargs):
        if path == stuck:
            raise PermissionError("in use")
        return real_unlink(path, *args, **kwargs)

    with patch.object(Path, "unlink", unlink), caplog.at_level(logging.WARNING):
        create_backup(url, NOW)

    assert stuck.exists() and not (backups / daily_name(datetime(2026, 5, 3, 12))).exists()
    assert "not deleted" in caplog.text


# --- the jobs of the bot -------------------------------------------------------------------------


class StubTracker:
    async def poll_due(self): ...

    async def deliver_pending(self): ...


async def not_a_real_backup():
    """Stands for `backup_database` in these tests: the job fires at the start and must not copy the real database."""


def scheduled_jobs():
    async def build():
        scheduler = AsyncIOScheduler()
        with patch("app.bot.main.backup_database", not_a_real_backup):
            add_jobs(scheduler, StubTracker())
        scheduler.start()
        try:
            return {job.func: job for job in scheduler.get_jobs()}
        finally:
            scheduler.shutdown(wait=False)

    return asyncio.run(build())


def test_the_backup_job_runs_every_hour(tmp_path):
    job = scheduled_jobs()[not_a_real_backup]

    assert BACKUP_EVERY_HOURS == 1
    assert job.trigger.interval == timedelta(hours=1)
    assert job.coalesce is True and job.max_instances == 1


def test_the_backup_job_runs_right_at_the_start_not_in_an_hour():
    runs = []

    async def spying_backup():
        runs.append(1)

    async def start_and_wait():
        scheduler = AsyncIOScheduler()
        with patch("app.bot.main.backup_database", spying_backup):
            add_jobs(scheduler, StubTracker())
        scheduler.start()
        try:
            await asyncio.sleep(0.3)
        finally:
            scheduler.shutdown(wait=False)

    asyncio.run(start_and_wait())

    assert runs == [1]


def test_there_is_no_job_at_three_in_the_morning():
    jobs = scheduled_jobs()

    assert not any(isinstance(job.trigger, CronTrigger) for job in jobs.values())
    assert len(jobs) == 3  # polling, delivery and the backup


def test_setup_logging_creates_the_log_file(tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    with patch("app.utils.logging_config.LOG_DIR", logs_dir):
        setup_logging(level="DEBUG")

    assert (logs_dir / "bot.log").exists()
