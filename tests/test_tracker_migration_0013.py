"""Migration 0013: `price_history`, the records of the Steam prices of the games; down: the price snapshots go too."""

from datetime import datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.tracker.db import MIGRATIONS_DIR, create_tracker_engine, migrate

NOW = datetime(2026, 11, 1, 12, 0)


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


def insert_game(connection):
    """Hades II with its IGDB snapshot and its PC row, as 0012 left a game."""
    connection.execute(
        text(
            "INSERT INTO titles (id, kind, name, original_name, genres, status, tracking_enabled, added_at, "
            "status_changed_at) VALUES (1, 'game', 'Hades II', 'Hades II', '[]', 'want', 1, :now, :now)"
        ),
        {"now": NOW},
    )
    connection.execute(
        text("INSERT INTO external_ids (title_id, source, external_id, role) VALUES (1, 'igdb', '228525', 'primary')")
    )
    connection.execute(
        text("INSERT INTO source_snapshots (title_id, source, state, observed_at) VALUES (1, 'igdb', '{}', :now)"),
        {"now": NOW},
    )
    connection.execute(text("INSERT INTO game_platforms (title_id, platform, playing) VALUES (1, 'pc', 1)"))


def insert_prices(connection):
    """The price snapshot of the game and two records of its history."""
    connection.execute(
        text("INSERT INTO source_snapshots (title_id, source, state, observed_at) VALUES (1, 'steam', '{}', :now)"),
        {"now": NOW},
    )
    connection.execute(
        text(
            "INSERT INTO price_history (title_id, seen_at, appid, country, currency, final, original, pct) VALUES "
            "(1, :now, '1145350', 'il', '₪{}', 27900, NULL, 0), (1, :now, '1145350', 'il', '₪{}', 19530, 27900, 30)"
        ),
        {"now": NOW},
    )


def snapshot_sources(engine):
    with engine.connect() as connection:
        return sorted(connection.scalars(text("SELECT source FROM source_snapshots")))


@pytest.fixture
def engine():
    return create_tracker_engine("sqlite://")


def test_an_empty_database_migrates_and_a_second_run_changes_nothing(engine):
    migrate(engine)
    migrate(engine)

    assert "price_history" in tables(engine) and version(engine) == "0014"


def test_a_database_with_a_game_gets_the_table_and_keeps_the_game(engine):
    alembic_on(engine, command.upgrade, "0012")
    with engine.begin() as connection:
        insert_game(connection)

    migrate(engine)

    with engine.begin() as connection:
        insert_prices(connection)
        assert connection.execute(text("SELECT id, kind, name FROM titles")).all() == [(1, "game", "Hades II")]
        assert connection.scalar(text("SELECT count(*) FROM price_history")) == 2
    assert snapshot_sources(engine) == ["igdb", "steam"]


def test_the_history_goes_with_its_title(engine):
    migrate(engine)
    with engine.begin() as connection:
        insert_game(connection)
        insert_prices(connection)

    with engine.begin() as connection:
        connection.execute(text("DELETE FROM titles WHERE id = 1"))

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM price_history")) == 0
    assert snapshot_sources(engine) == []


def test_downgrading_takes_the_price_snapshots_and_the_table_away_and_keeps_the_game(engine):
    migrate(engine)
    with engine.begin() as connection:
        insert_game(connection)
        insert_prices(connection)

    alembic_on(engine, command.downgrade, "0012")

    assert "price_history" not in tables(engine) and version(engine) == "0012"
    assert snapshot_sources(engine) == ["igdb"]
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id, kind FROM titles")).all() == [(1, "game")]
        assert connection.execute(text("SELECT platform, playing FROM game_platforms")).all() == [("pc", 1)]


def test_after_downgrading_the_database_migrates_up_again(engine):
    migrate(engine)
    with engine.begin() as connection:
        insert_game(connection)
        insert_prices(connection)
    alembic_on(engine, command.downgrade, "0012")

    migrate(engine)

    assert "price_history" in tables(engine) and version(engine) == "0014"
    assert snapshot_sources(engine) == ["igdb"]
