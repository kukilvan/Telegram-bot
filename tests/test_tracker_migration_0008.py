"""Migration 0008: events and the queue get foreign keys with cascade; orphans of deleted titles are cleaned first."""

import pathlib
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


def insert_title(connection, title_id, name="Дюна"):
    connection.execute(
        text(
            "INSERT INTO titles (id, kind, title, original_title, genres, status, tracking_enabled, added_at, "
            "status_changed_at) VALUES (:id, 'movie', :name, :name, '[]', 'want', 1, :now, :now)"
        ),
        {"id": title_id, "name": name, "now": NOW},
    )


def insert_event(connection, event_id, title_id, queued=True):
    connection.execute(
        text(
            "INSERT INTO events (id, type, title_id, payload, dedup_key, detected_at) "
            "VALUES (:id, 'x', :title, '{}', :key, :now)"
        ),
        {"id": event_id, "title": title_id, "key": f"k{event_id}", "now": NOW},
    )
    if queued:
        connection.execute(
            text(
                "INSERT INTO delivery_queue (event_id, status, attempts, created_at) "
                "VALUES (:id, 'pending', 0, :now)"
            ),
            {"id": event_id, "now": NOW},
        )


def count(engine, table):
    with engine.connect() as connection:
        return connection.scalar(text(f"SELECT count(*) FROM {table}"))


@pytest.fixture
def engine():
    return create_tracker_engine("sqlite://")


def test_an_empty_database_migrates_and_a_second_run_changes_nothing(engine):
    migrate(engine)
    migrate(engine)

    assert count(engine, "events") == 0
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0009"


def test_events_of_titles_that_no_longer_exist_go_with_their_queue_entries(engine):
    upgrade_to(engine, "0007")
    with engine.begin() as connection:
        insert_title(connection, 1)
        insert_event(connection, 10, 1)  # kept
        insert_event(connection, 11, 77)  # its title is gone
        insert_event(connection, 12, None)  # a test event: no title, kept

    migrate(engine)

    with engine.connect() as connection:
        assert [r[0] for r in connection.execute(text("SELECT id FROM events ORDER BY id"))] == [10, 12]
        assert [r[0] for r in connection.execute(text("SELECT event_id FROM delivery_queue ORDER BY id"))] == [10, 12]


def test_after_the_migration_deleting_a_title_or_an_event_cascades(engine):
    upgrade_to(engine, "0007")
    with engine.begin() as connection:
        insert_title(connection, 1)
        insert_event(connection, 10, 1)
        insert_event(connection, 12, None)
    migrate(engine)

    with engine.begin() as connection:
        connection.execute(text("DELETE FROM titles WHERE id = 1"))
    assert count(engine, "events") == 1 and count(engine, "delivery_queue") == 1

    with engine.begin() as connection:
        connection.execute(text("DELETE FROM events WHERE id = 12"))
    assert count(engine, "delivery_queue") == 0


def test_the_queue_keeps_its_uniqueness_and_index_and_a_row_keeps_its_values(engine):
    upgrade_to(engine, "0007")
    with engine.begin() as connection:
        insert_title(connection, 1)
        insert_event(connection, 10, 1)
    migrate(engine)

    with engine.connect() as connection:
        indexes = {r[1] for r in connection.execute(text("PRAGMA index_list(delivery_queue)"))}
        row = connection.execute(text("SELECT status, attempts, event_id FROM delivery_queue")).one()
    assert "ix_delivery_queue_status" in indexes
    assert tuple(row) == ("pending", 0, 10)
    with pytest.raises(Exception):
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO delivery_queue (event_id, status, attempts, created_at) VALUES (10, 'pending', 0, :n)"),
                {"n": NOW},
            )


def test_a_file_database_migrates_through_the_same_path(tmp_path: pathlib.Path):
    engine = create_tracker_engine(f"sqlite:///{tmp_path / 'tracker.db'}")
    upgrade_to(engine, "0007")
    with engine.begin() as connection:
        insert_title(connection, 1)
        insert_event(connection, 10, 1)
        insert_event(connection, 11, 5)

    migrate(engine)

    assert count(engine, "events") == 1


def test_downgrading_keeps_the_rows_and_drops_the_cascade(engine):
    upgrade_to(engine, "0007")
    with engine.begin() as connection:
        insert_title(connection, 1)
        insert_event(connection, 10, 1)
    migrate(engine)

    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0007")

    assert count(engine, "events") == 1 and count(engine, "delivery_queue") == 1
    migrate(engine)
    assert count(engine, "events") == 1 and count(engine, "delivery_queue") == 1
