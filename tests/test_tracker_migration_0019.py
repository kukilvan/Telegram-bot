"""Migration 0019: `inbox_items.answered_at` comes (KI-57), filled with `last_message_at` for the rows there are; down:
the column goes the way 0016 drops one."""

from datetime import datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.tracker.db import MIGRATIONS_DIR, create_tracker_engine, migrate

RECEIVED = datetime(2026, 11, 23, 9, 0)
LAST = datetime(2026, 11, 23, 9, 0, 1)


def alembic_on(engine, step, revision):
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        step(config, revision)


def columns(engine):
    with engine.connect() as connection:
        return {row[1] for row in connection.execute(text("PRAGMA table_info(inbox_items)"))}


def version(engine):
    with engine.connect() as connection:
        return connection.scalar(text("SELECT version_num FROM alembic_version"))


def insert_item(connection, number, state):
    connection.execute(
        text(
            "INSERT INTO inbox_items (id, state, text, bold, links, forwarded, query, offers, received_at, "
            "last_message_at) VALUES (:n, :state, 'Пост', '[]', '[]', 1, 'Пост', '[]', :received, :last)"
        ),
        {"n": number, "state": state, "received": RECEIVED, "last": LAST},
    )


@pytest.fixture
def engine():
    return create_tracker_engine("sqlite://")


def test_an_empty_database_gets_the_column_and_a_second_run_changes_nothing(engine):
    migrate(engine)
    migrate(engine)

    assert "answered_at" in columns(engine) and version(engine) == "0019"


def test_the_rows_there_are_get_their_last_message_as_answered(engine):
    alembic_on(engine, command.upgrade, "0018")
    with engine.begin() as connection:
        insert_item(connection, 1, "waiting")
        insert_item(connection, 2, "inbox")

    migrate(engine)

    with engine.connect() as connection:
        rows = connection.execute(text("SELECT id, answered_at FROM inbox_items ORDER BY id")).all()
    assert [(number, datetime.fromisoformat(str(at))) for number, at in rows] == [(1, LAST), (2, LAST)]


def test_down_drops_the_column_and_keeps_the_rows_and_up_brings_it_back(engine):
    migrate(engine)
    with engine.begin() as connection:
        insert_item(connection, 5, "waiting")

    alembic_on(engine, command.downgrade, "0018")
    assert "answered_at" not in columns(engine) and version(engine) == "0018"
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id FROM inbox_items")).all() == [(5,)]

    migrate(engine)
    assert "answered_at" in columns(engine) and version(engine) == "0019"
