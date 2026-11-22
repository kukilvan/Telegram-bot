"""Migration 0016: `titles.failure_notified_at` goes (KI-45), by `ALTER TABLE ... DROP COLUMN`, so the tables that
cascade from `titles` keep every row; down: the column comes back, empty."""

from datetime import datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.tracker.db import MIGRATIONS_DIR, create_tracker_engine, migrate

NOW = datetime(2026, 11, 20, 12, 0)
CHILDREN = ("external_ids", "source_snapshots", "seasons", "episodes", "events", "delivery_queue")


def alembic_on(engine, step, revision):
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        step(config, revision)


def columns(engine, table="titles"):
    with engine.connect() as connection:
        return {row[1] for row in connection.execute(text(f"PRAGMA table_info({table})"))}


def version(engine):
    with engine.connect() as connection:
        return connection.scalar(text("SELECT version_num FROM alembic_version"))


def counts(engine):
    with engine.connect() as connection:
        return {table: connection.scalar(text(f"SELECT count(*) FROM {table}")) for table in ("titles", *CHILDREN)}


def insert_title(connection, number):
    """A title told about a failure, with the children a real one has, each of which cascades from it."""
    connection.execute(
        text(
            "INSERT INTO titles (id, kind, name, original_name, genres, status, tracking_enabled, added_at, "
            "status_changed_at, failure_notified_at) VALUES (:n, 'series', 'Сериал', 'Show', '[]', 'want', 1, :now, :now, :now)"
        ),
        {"n": number, "now": NOW},
    )
    connection.execute(
        text("INSERT INTO external_ids (title_id, source, external_id, role) VALUES (:n, 'tmdb_tv', :e, 'primary')"),
        {"n": number, "e": str(1000 + number)},
    )
    connection.execute(
        text("INSERT INTO source_snapshots (title_id, source, state, observed_at) VALUES (:n, 'tmdb_tv', '{}', :now)"),
        {"n": number, "now": NOW},
    )
    season_id = connection.execute(
        text("INSERT INTO seasons (title_id, number, name, watched) VALUES (:n, 1, 'Сезон 1', 0) RETURNING id"), {"n": number}
    ).scalar()
    connection.execute(
        text("INSERT INTO episodes (season_id, number, air_at) VALUES (:s, 1, :now)"), {"s": season_id, "now": NOW}
    )
    event_id = connection.execute(
        text(
            "INSERT INTO events (title_id, type, payload, dedup_key, detected_at) "
            "VALUES (:n, 'source_failure', '{}', :k, :now) RETURNING id"
        ),
        {"n": number, "k": f"failure:{number}:x", "now": NOW},
    ).scalar()
    connection.execute(
        text("INSERT INTO delivery_queue (event_id, status, attempts, created_at) VALUES (:e, 'pending', 0, :now)"),
        {"e": event_id, "now": NOW},
    )


@pytest.fixture
def engine():
    return create_tracker_engine("sqlite://")


def test_an_empty_database_has_no_column_and_a_second_run_changes_nothing(engine):
    migrate(engine)
    migrate(engine)

    assert "failure_notified_at" not in columns(engine) and version(engine) == "0017"


def test_the_column_goes_and_the_titles_and_their_children_keep_every_row(engine):
    alembic_on(engine, command.upgrade, "0015")
    with engine.begin() as connection:
        insert_title(connection, 1)
        insert_title(connection, 2)
    before = counts(engine)

    migrate(engine)

    assert "failure_notified_at" not in columns(engine)
    assert {"restored_at", "score", "name"} <= columns(engine)
    assert counts(engine) == before == {"titles": 2, **{table: 2 for table in CHILDREN}}
    with engine.connect() as connection:
        assert connection.scalar(text("PRAGMA foreign_key_check")) is None


def test_down_brings_the_column_back_empty_and_up_takes_it_away_again(engine):
    migrate(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO titles (id, kind, name, original_name, genres, status, tracking_enabled, added_at, "
                "status_changed_at) VALUES (7, 'movie', 'Фильм', 'Movie', '[]', 'want', 1, :now, :now)"
            ),
            {"now": NOW},
        )

    alembic_on(engine, command.downgrade, "0015")
    assert "failure_notified_at" in columns(engine) and version(engine) == "0015"
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id, failure_notified_at FROM titles")).all() == [(7, None)]

    migrate(engine)
    assert "failure_notified_at" not in columns(engine)
