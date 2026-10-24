"""The database backup and the log directory."""

import sqlite3
from unittest.mock import patch

from app.utils.backup import create_backup
from app.utils.logging_config import setup_logging


def test_backup_copies_the_database_into_a_dated_file(tmp_path):
    db_file = tmp_path / "tracker.db"
    connection = sqlite3.connect(db_file)
    connection.execute("CREATE TABLE titles (id INTEGER PRIMARY KEY, name TEXT)")
    connection.execute("INSERT INTO titles (name) VALUES ('Дюна')")
    connection.commit()
    connection.close()

    with patch("app.utils.backup.DB_FILE", db_file), patch("app.utils.backup.BACKUP_DIR", tmp_path / "backups"):
        backup = create_backup()

    assert backup is not None and backup.suffix == ".db" and "tracker_db_" in backup.name
    copy = sqlite3.connect(backup)
    try:
        assert copy.execute("SELECT name FROM titles").fetchall() == [("Дюна",)]
    finally:
        copy.close()


def test_backup_without_a_database_does_nothing(tmp_path):
    with patch("app.utils.backup.DB_FILE", tmp_path / "missing.db"), patch("app.utils.backup.BACKUP_DIR", tmp_path / "b"):
        assert create_backup() is None
    assert not (tmp_path / "b").exists()


def test_setup_logging_creates_the_log_file(tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    with patch("app.utils.logging_config.LOG_DIR", logs_dir):
        setup_logging(level="DEBUG")

    assert (logs_dir / "bot.log").exists()
