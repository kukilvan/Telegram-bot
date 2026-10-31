"""Migration 0012: `game_platforms`, the platforms of a game with the mark «играю здесь»; down: the games go with it."""

from datetime import datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.tracker.db import MIGRATIONS_DIR, create_tracker_engine, migrate

NOW = datetime(2026, 10, 31, 12, 0)


def alembic_on(engine, step, revision):
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        step(config, revision)


def tables(engine):
    with engine.connect() as connection:
        return {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))}


def count(engine, table):
    with engine.connect() as connection:
        return connection.scalar(text(f"SELECT count(*) FROM {table}"))


def insert_title(connection, title_id, kind, name, source):
    connection.execute(
        text(
            "INSERT INTO titles (id, kind, name, original_name, genres, status, tracking_enabled, added_at, "
            "status_changed_at) VALUES (:id, :kind, :name, :name, '[]', 'want', 1, :now, :now)"
        ),
        {"id": title_id, "kind": kind, "name": name, "now": NOW},
    )
    connection.execute(
        text("INSERT INTO external_ids (title_id, source, external_id, role) VALUES (:id, :source, :id, 'primary')"),
        {"id": title_id, "source": source},
    )
    connection.execute(
        text(
            "INSERT INTO source_snapshots (title_id, source, state, observed_at) VALUES (:id, :source, '{}', :now)"
        ),
        {"id": title_id, "source": source, "now": NOW},
    )
    connection.execute(
        text(
            "INSERT INTO events (id, type, title_id, payload, dedup_key, detected_at) "
            "VALUES (:id, 'x', :id, '{}', :key, :now)"
        ),
        {"id": title_id, "key": f"x:{title_id}", "now": NOW},
    )
    connection.execute(
        text(
            "INSERT INTO delivery_queue (event_id, status, attempts, created_at) VALUES (:id, 'pending', 0, :now)"
        ),
        {"id": title_id, "now": NOW},
    )


def fill(connection):
    """A movie and a game, each with its id, snapshot and a queued event; the game has two platforms."""
    insert_title(connection, 1, "movie", "Дюна", "tmdb_movie")
    insert_title(connection, 2, "game", "Hades II", "igdb")
    connection.execute(
        text("INSERT INTO game_platforms (title_id, platform, playing) VALUES (2, 'pc', 1), (2, 'ps5', 0)")
    )


@pytest.fixture
def engine():
    return create_tracker_engine("sqlite://")


def test_an_empty_database_migrates_and_a_second_run_changes_nothing(engine):
    migrate(engine)
    migrate(engine)

    assert "game_platforms" in tables(engine)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0012"


def test_a_database_after_0011_gets_the_table_and_keeps_its_titles(engine):
    alembic_on(engine, command.upgrade, "0011")
    with engine.begin() as connection:
        insert_title(connection, 1, "movie", "Дюна", "tmdb_movie")

    migrate(engine)

    assert count(engine, "game_platforms") == 0
    with engine.connect() as connection:
        assert tuple(connection.execute(text("SELECT id, kind, name FROM titles")).one()) == (1, "movie", "Дюна")
    assert count(engine, "source_snapshots") == count(engine, "delivery_queue") == 1


def test_a_platform_is_stored_once_per_game_and_goes_with_its_game(engine):
    migrate(engine)
    with engine.begin() as connection:
        fill(connection)

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text("INSERT INTO game_platforms (title_id, platform, playing) VALUES (2, 'pc', 0)"))
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM titles WHERE id = 2"))

    assert count(engine, "game_platforms") == 0


def test_downgrading_takes_the_games_and_the_table_away_and_keeps_the_movie(engine):
    migrate(engine)
    with engine.begin() as connection:
        fill(connection)

    alembic_on(engine, command.downgrade, "0011")

    assert "game_platforms" not in tables(engine)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id, kind FROM titles")).all() == [(1, "movie")]
        assert connection.execute(text("SELECT title_id FROM external_ids")).all() == [(1,)]
        assert connection.execute(text("SELECT title_id FROM source_snapshots")).all() == [(1,)]
        assert connection.execute(text("SELECT title_id FROM events")).all() == [(1,)]
        assert connection.execute(text("SELECT event_id FROM delivery_queue")).all() == [(1,)]
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0011"


def test_after_downgrading_the_database_migrates_up_again(engine):
    migrate(engine)
    with engine.begin() as connection:
        fill(connection)
    alembic_on(engine, command.downgrade, "0011")

    migrate(engine)

    assert "game_platforms" in tables(engine) and count(engine, "titles") == 1
