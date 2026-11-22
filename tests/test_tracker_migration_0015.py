"""Migration 0015: `issued_ids`, the last number given to a title, seeded with the biggest number there is; down: the table
goes. A database of the owner's shape (a title with its children) keeps every row."""

from datetime import datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.tracker.db import MIGRATIONS_DIR, create_tracker_engine, migrate

NOW = datetime(2026, 11, 20, 12, 0)


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


def issued(engine):
    with engine.connect() as connection:
        return connection.execute(text("SELECT name, last_id FROM issued_ids")).all()


def insert_titles(connection, *numbers):
    """Each title with the children a real one has: an external id, a snapshot, a season, an event, a queue entry."""
    for number in numbers:
        connection.execute(
            text(
                "INSERT INTO titles (id, kind, name, original_name, genres, status, tracking_enabled, added_at, "
                "status_changed_at) VALUES (:n, 'movie', 'Фильм', 'Movie', '[]', 'want', 1, :now, :now)"
            ),
            {"n": number, "now": NOW},
        )
        connection.execute(
            text("INSERT INTO external_ids (title_id, source, external_id, role) VALUES (:n, 'tmdb_movie', :e, 'primary')"),
            {"n": number, "e": str(1000 + number)},
        )
        connection.execute(
            text("INSERT INTO source_snapshots (title_id, source, state, observed_at) VALUES (:n, 'tmdb_movie', '{}', :now)"),
            {"n": number, "now": NOW},
        )
        connection.execute(
            text(
                "INSERT INTO events (title_id, type, payload, dedup_key, detected_at) "
                "VALUES (:n, 'movie_released', '{}', :k, :now)"
            ),
            {"n": number, "k": f"k{number}", "now": NOW},
        )


@pytest.fixture
def engine():
    return create_tracker_engine("sqlite://")


def test_an_empty_database_gets_the_table_seeded_with_zero_and_a_second_run_changes_nothing(engine):
    migrate(engine)
    migrate(engine)

    assert "issued_ids" in tables(engine) and version(engine) == "0017"
    assert issued(engine) == [("titles", 0)]


def test_the_seed_is_the_biggest_number_of_the_titles_there_are(engine):
    alembic_on(engine, command.upgrade, "0014")
    with engine.begin() as connection:
        insert_titles(connection, 1, 2, 5)  # 3 and 4 were deleted long ago

    migrate(engine)

    assert issued(engine) == [("titles", 5)]


def test_a_database_of_the_owners_shape_keeps_every_row(engine):
    alembic_on(engine, command.upgrade, "0014")
    with engine.begin() as connection:
        insert_titles(connection, 1, 2)

    migrate(engine)

    with engine.connect() as connection:
        counts = {
            table: connection.scalar(text(f"SELECT count(*) FROM {table}"))
            for table in ("titles", "external_ids", "source_snapshots", "events")
        }
    assert counts == {"titles": 2, "external_ids": 2, "source_snapshots": 2, "events": 2}


def test_down_takes_the_table_away_and_up_brings_it_back_seeded_again(engine):
    migrate(engine)
    with engine.begin() as connection:
        insert_titles(connection, 7)

    alembic_on(engine, command.downgrade, "0014")
    assert "issued_ids" not in tables(engine) and version(engine) == "0014"
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM titles")) == 1

    migrate(engine)
    assert issued(engine) == [("titles", 7)]
