"""Migration 0014: `inbox_items`, the inbox items, with numbers that never come back; down: the table goes."""

from datetime import datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.tracker.db import MIGRATIONS_DIR, create_tracker_engine, migrate

NOW = datetime(2026, 11, 6, 12, 0)


def alembic_on(engine, step, revision):
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        step(config, revision)


def tables(engine):
    with engine.connect() as connection:
        return {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))}


def version(engine):
    with engine.connect() as connection:
        return connection.scalar(text("SELECT version_num FROM alembic_version"))


def insert_item(connection):
    connection.execute(
        text(
            "INSERT INTO inbox_items (state, forwarded, received_at, last_message_at) VALUES ('waiting', 0, :now, :now)"
        ),
        {"now": NOW},
    )
    return connection.scalar(text("SELECT max(id) FROM inbox_items"))


@pytest.fixture
def engine():
    return create_tracker_engine("sqlite://")


def test_an_empty_database_migrates_and_a_second_run_changes_nothing(engine):
    migrate(engine)
    migrate(engine)

    assert "inbox_items" in tables(engine) and version(engine) == "0014"
    with engine.connect() as connection:
        indexes = {row[1] for row in connection.execute(text("PRAGMA index_list('inbox_items')"))}
    assert "ix_inbox_items_state" in indexes


def test_the_defaults_of_a_new_row(engine):
    migrate(engine)
    with engine.begin() as connection:
        item = insert_item(connection)
        row = connection.execute(
            text("SELECT text, bold, links, query, offers, reason, kind, moved_at FROM inbox_items WHERE id = :id"),
            {"id": item},
        ).one()

    assert tuple(row) == ("", "[]", "[]", "", "[]", None, None, None)


def test_the_number_of_a_deleted_last_item_never_comes_back(engine):
    migrate(engine)
    with engine.begin() as connection:
        first = insert_item(connection)
        connection.execute(text("DELETE FROM inbox_items"))
        second = insert_item(connection)

    assert second == first + 1


def test_down_takes_the_table_away_and_up_brings_it_back(engine):
    migrate(engine)
    with engine.begin() as connection:
        insert_item(connection)

    alembic_on(engine, command.downgrade, "0013")
    assert "inbox_items" not in tables(engine) and version(engine) == "0013"

    alembic_on(engine, command.upgrade, "head")
    assert "inbox_items" in tables(engine) and version(engine) == "0014"
