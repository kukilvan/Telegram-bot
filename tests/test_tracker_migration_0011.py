"""Migration 0011: `titles.score` and `seasons.score`, the owner's scores (empty: not scored)."""

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


def columns(engine, table):
    with engine.connect() as connection:
        return [row[1] for row in connection.execute(text(f"PRAGMA table_info({table})"))]


def fill(connection, **extra):
    """A series with one watched season; `extra` adds the score columns once they are there."""
    title_score = ", score" if extra else ""
    connection.execute(
        text(
            "INSERT INTO titles (id, kind, name, original_name, genres, status, tracking_enabled, added_at, "
            f"status_changed_at{title_score}) VALUES (1, 'series', 'Тьма', 'Dark', '[]', 'watched', 0, :now, :now"
            f"{', :title' if extra else ''})"
        ),
        {"now": NOW, **extra},
    )
    connection.execute(
        text("INSERT INTO external_ids (title_id, source, external_id, role) VALUES (1, 'tmdb_series', '1', 'primary')")
    )
    connection.execute(
        text(
            f"INSERT INTO seasons (id, title_id, number, name, episode_count, watched{title_score}) "
            f"VALUES (7, 1, 1, 'Сезон 1', 10, 1{', :season' if extra else ''})"
        ),
        extra,
    )


@pytest.fixture
def engine():
    return create_tracker_engine("sqlite://")


def test_an_empty_database_migrates_and_a_second_run_changes_nothing(engine):
    migrate(engine)
    migrate(engine)

    assert "score" in columns(engine, "titles") and "score" in columns(engine, "seasons")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0012"


def test_a_database_after_0010_gets_both_columns_empty_and_keeps_everything(engine):
    alembic_on(engine, command.upgrade, "0010")
    with engine.begin() as connection:
        fill(connection)

    migrate(engine)

    with engine.connect() as connection:
        assert tuple(connection.execute(text("SELECT id, name, status, score FROM titles")).one()) == (
            1, "Тьма", "watched", None,
        )
        assert tuple(connection.execute(text("SELECT id, number, watched, score FROM seasons")).one()) == (7, 1, 1, None)
        assert connection.scalar(text("SELECT count(*) FROM external_ids")) == 1


def test_downgrading_takes_both_columns_away_and_keeps_the_titles_and_seasons(engine):
    migrate(engine)
    with engine.begin() as connection:
        fill(connection, title=28, season=27)

    alembic_on(engine, command.downgrade, "0010")

    assert "score" not in columns(engine, "titles") and "score" not in columns(engine, "seasons")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT name FROM titles")) == "Тьма"
        assert tuple(connection.execute(text("SELECT id, watched FROM seasons")).one()) == (7, 1)
