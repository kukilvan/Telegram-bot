"""Migration 0009: the glossary names reach the database — `titles.name`, `titles.original_name`, `summary_at`."""

import json
from datetime import datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.tracker.db import MIGRATIONS_DIR, create_tracker_engine, migrate

NOW = datetime(2026, 10, 24, 12, 0)


def upgrade_to(engine, revision):
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, revision)


def downgrade_to(engine, revision):
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, revision)


def columns(engine, table):
    with engine.connect() as connection:
        return [row[1] for row in connection.execute(text(f"PRAGMA table_info({table})"))]


def settings(engine):
    with engine.connect() as connection:
        return {key: json.loads(str(value)) for key, value in connection.execute(text("SELECT key, value FROM settings"))}


def fill_old_database(engine):
    """A database as revision 0008 leaves it: a title with everything hanging off it, and the old setting key."""
    upgrade_to(engine, "0008")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO titles (id, kind, title, original_title, genres, status, tracking_enabled, added_at, "
                "status_changed_at) VALUES (1, 'movie', 'Дюна', 'Dune', '[]', 'want', 1, :now, :now)"
            ),
            {"now": NOW},
        )
        connection.execute(
            text("INSERT INTO external_ids (title_id, source, external_id, role) VALUES (1, 'tmdb_movie', '438631', 'primary')")
        )
        connection.execute(
            text("INSERT INTO events (id, type, title_id, payload, dedup_key, detected_at) VALUES (5, 'x', 1, '{}', 'k5', :now)"),
            {"now": NOW},
        )
        connection.execute(
            text("INSERT INTO delivery_queue (event_id, status, attempts, created_at) VALUES (5, 'pending', 0, :now)"),
            {"now": NOW},
        )
        connection.execute(text("INSERT INTO settings (key, value) VALUES ('digest_at', '\"09:30\"'), ('part_gap_weeks', '8')"))


@pytest.fixture
def engine():
    return create_tracker_engine("sqlite://")


def test_an_empty_database_migrates(engine):
    migrate(engine)
    migrate(engine)

    assert "name" in columns(engine, "titles") and "original_name" in columns(engine, "titles")
    assert "title" not in columns(engine, "titles") and "original_title" not in columns(engine, "titles")
    assert settings(engine) == {}


def test_titles_and_the_setting_move_over_with_nothing_lost(engine):
    fill_old_database(engine)

    migrate(engine)

    with engine.connect() as connection:
        row = connection.execute(text("SELECT id, name, original_name, kind, status FROM titles")).one()
        assert tuple(row) == (1, "Дюна", "Dune", "movie", "want")
        # the rows that hang off the title survive: renaming a column rebuilds nothing, so no cascade fires
        assert connection.scalar(text("SELECT count(*) FROM external_ids")) == 1
        assert connection.scalar(text("SELECT count(*) FROM events")) == 1
        assert connection.scalar(text("SELECT count(*) FROM delivery_queue")) == 1
    assert settings(engine) == {"summary_at": "09:30", "part_gap_weeks": 8}


def test_a_new_setting_already_there_wins_over_the_old_one(engine):
    fill_old_database(engine)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO settings (key, value) VALUES ('summary_at', '\"10:00\"')"))

    migrate(engine)

    assert settings(engine) == {"summary_at": "10:00", "part_gap_weeks": 8}


def test_the_database_keeps_its_cascade_after_the_migration(engine):
    fill_old_database(engine)
    migrate(engine)

    with engine.begin() as connection:
        connection.execute(text("DELETE FROM titles WHERE id = 1"))

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM external_ids")) == 0
        assert connection.scalar(text("SELECT count(*) FROM events")) == 0


def test_downgrading_gives_the_old_names_back(engine):
    fill_old_database(engine)
    migrate(engine)

    downgrade_to(engine, "0008")

    assert "title" in columns(engine, "titles") and "original_title" in columns(engine, "titles")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT title FROM titles")) == "Дюна"
    assert "digest_at" in settings(engine) and "summary_at" not in settings(engine)
