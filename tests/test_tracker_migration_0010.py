"""Migration 0010: `titles.restored_at`, the moment of the last «Вернуть в список» (empty: never brought back)."""

from datetime import datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.tracker.db import MIGRATIONS_DIR, create_tracker_engine, migrate

NOW = datetime(2026, 10, 28, 12, 0)


def alembic_on(engine, step, revision):
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        step(config, revision)


def columns(engine):
    with engine.connect() as connection:
        return [row[1] for row in connection.execute(text("PRAGMA table_info(titles)"))]


@pytest.fixture
def engine():
    return create_tracker_engine("sqlite://")


def test_an_empty_database_migrates_and_a_second_run_changes_nothing(engine):
    migrate(engine)
    migrate(engine)

    assert "restored_at" in columns(engine)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0010"


def test_a_database_with_titles_gets_the_column_empty_and_keeps_everything(engine):
    alembic_on(engine, command.upgrade, "0009")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO titles (id, kind, name, original_name, genres, status, tracking_enabled, added_at, "
                "status_changed_at) VALUES (1, 'movie', 'Дюна', 'Dune', '[]', 'watched', 0, :now, :now)"
            ),
            {"now": NOW},
        )
        connection.execute(
            text("INSERT INTO external_ids (title_id, source, external_id, role) VALUES (1, 'tmdb_movie', '1', 'primary')")
        )

    migrate(engine)

    with engine.connect() as connection:
        assert tuple(connection.execute(text("SELECT id, name, status, restored_at FROM titles")).one()) == (
            1, "Дюна", "watched", None,
        )
        assert connection.scalar(text("SELECT count(*) FROM external_ids")) == 1


def test_downgrading_takes_the_column_away_and_keeps_the_titles(engine):
    migrate(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO titles (id, kind, name, original_name, genres, status, tracking_enabled, added_at, "
                "status_changed_at, restored_at) VALUES (1, 'movie', 'Дюна', 'Dune', '[]', 'want', 1, :now, :now, :now)"
            ),
            {"now": NOW},
        )
        connection.execute(
            text("INSERT INTO external_ids (title_id, source, external_id, role) VALUES (1, 'tmdb_movie', '1', 'primary')")
        )

    alembic_on(engine, command.downgrade, "0009")

    assert "restored_at" not in columns(engine)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT name FROM titles")) == "Дюна"
        assert connection.scalar(text("SELECT count(*) FROM external_ids")) == 1  # dropping a column rebuilds nothing
