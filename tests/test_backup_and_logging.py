"""The database backup (the file the bot opens, copied off the event loop) and the log directory."""

import asyncio
import sqlite3
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from app.tracker.db import TRACKER_DATABASE_URL, database_file
from app.utils import backup
from app.utils.backup import backup_database, create_backup
from app.utils.logging_config import setup_logging


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

    assert result is not None and result.suffix == ".db" and "tracker_db_" in result.name
    assert names_in(result) == ["Дюна"]


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


# --- the scheduler job ---------------------------------------------------------------------------


def test_the_job_copies_in_a_worker_thread_not_in_the_event_loop(tmp_path):
    threads = []
    real_copy = backup.create_backup

    def spying_copy(url):
        threads.append(threading.current_thread())
        return real_copy(url)

    async def job():
        loop_thread = threading.current_thread()
        with patch.object(backup, "create_backup", spying_copy):
            await backup_database(make_database(tmp_path / "tracker.db"))
        return loop_thread

    loop_thread = asyncio.run(job())

    assert len(threads) == 1 and threads[0] is not loop_thread


def test_the_bot_keeps_answering_while_the_copy_runs(tmp_path):
    ticks = []

    def slow_copy(url):
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
    import logging

    with caplog.at_level(logging.INFO):
        asyncio.run(backup_database(make_database(tmp_path / "tracker.db")))
        asyncio.run(backup_database(f"sqlite:///{(tmp_path / 'gone.db').as_posix()}"))

    assert "Database backup created" in caplog.text
    assert "No database file found for backup" in caplog.text


def test_setup_logging_creates_the_log_file(tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    with patch("app.utils.logging_config.LOG_DIR", logs_dir):
        setup_logging(level="DEBUG")

    assert (logs_dir / "bot.log").exists()
