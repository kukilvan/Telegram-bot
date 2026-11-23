"""Migration 0017: `episodes.timing` (spec 11 of stage 9.1c). The old rows are filled by what their moment looks like:
a series `day`; an anime with no moment or with seconds `unknown`; at 00:00 UTC the lowest number of the season with that
moment `day`, the others `unknown`; any other anime moment `exact`. Down: the column goes. A copy of a database file goes
to `backups` before the migration runs."""

from datetime import datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.tracker.db import BACKUP_FOLDER, MIGRATIONS_DIR, create_session_factory, create_tracker_engine, migrate

NOW = datetime(2026, 11, 22, 12, 0)


def alembic_on(engine, step, revision):
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        step(config, revision)


def columns(engine):
    with engine.connect() as connection:
        return {row[1] for row in connection.execute(text("PRAGMA table_info(episodes)"))}


def version(engine):
    with engine.connect() as connection:
        return connection.scalar(text("SELECT version_num FROM alembic_version"))


def put_season(connection, title_id, kind, number, episodes):
    """A title of `kind` (once) with a season `number` and its episodes: episode number → moment (None: no date)."""
    connection.execute(
        text(
            "INSERT OR IGNORE INTO titles (id, kind, name, original_name, genres, status, tracking_enabled, added_at, "
            "status_changed_at) VALUES (:id, :kind, 'Тайтл', 'Title', '[]', 'want', 1, :now, :now)"
        ),
        {"id": title_id, "kind": kind, "now": NOW},
    )
    season_id = connection.execute(
        text("INSERT INTO seasons (title_id, number, name, watched) VALUES (:t, :n, 'Сезон', 0) RETURNING id"),
        {"t": title_id, "n": number},
    ).scalar()
    for episode, moment in episodes.items():
        connection.execute(
            text("INSERT INTO episodes (season_id, number, air_at) VALUES (:s, :n, :at)"),
            {"s": season_id, "n": episode, "at": moment},
        )
    return season_id


def timings(engine):
    """(title, season number, episode number) → timing."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT s.title_id, s.number, e.number, e.timing FROM episodes e JOIN seasons s ON s.id = e.season_id"
            )
        )
        return {(t, s, e): timing for t, s, e, timing in rows}


@pytest.fixture
def engine():
    return create_tracker_engine("sqlite://")


def test_an_empty_database_gets_the_column_and_a_second_run_changes_nothing(engine):
    migrate(engine)
    migrate(engine)

    assert "timing" in columns(engine) and version(engine) == "0018"


def test_the_old_rows_are_filled_by_the_table_of_the_spec(engine):
    alembic_on(engine, command.upgrade, "0016")
    with engine.begin() as connection:
        # One Piece-like: Shikimori's start day given to every episode out, then AniList's moment of the next one
        put_season(connection, 1, "anime", 1, {
            1: datetime(1999, 10, 20), 2: datetime(1999, 10, 20), 3: datetime(1999, 10, 20),
            1181: datetime(2026, 10, 25, 14, 16),
        })
        put_season(connection, 2, "anime", 1, {1: datetime(2027, 1, 9)})  # a lone 00:00: a premiere day
        put_season(connection, 2, "anime", 2, {5: datetime(2026, 11, 20, 14, 0)})  # a whole minute
        put_season(connection, 3, "anime", 1, {
            7: datetime(2026, 11, 22, 12, 42, 13),  # the moment of a check: seconds
            8: datetime(2026, 11, 22, 12, 42, 0, 5),  # ... microseconds
            9: None,
        })
        put_season(connection, 4, "series", 1, {1: datetime(2026, 11, 2), 2: datetime(2026, 11, 9), 3: None})
        put_season(connection, 5, "anime", 1, {2: datetime(2025, 1, 10), 3: datetime(2025, 1, 10)})  # lowest is not 1

    migrate(engine)

    assert timings(engine) == {
        (1, 1, 1): "day", (1, 1, 2): "unknown", (1, 1, 3): "unknown", (1, 1, 1181): "exact",
        (2, 1, 1): "day",
        (2, 2, 5): "exact",
        (3, 1, 7): "unknown", (3, 1, 8): "unknown", (3, 1, 9): "unknown",
        (4, 1, 1): "day", (4, 1, 2): "day", (4, 1, 3): "day",
        (5, 1, 2): "day", (5, 1, 3): "unknown",
    }


def test_down_drops_the_column_and_up_fills_it_again(engine):
    alembic_on(engine, command.upgrade, "0016")
    with engine.begin() as connection:
        put_season(connection, 1, "series", 1, {1: datetime(2026, 11, 2)})
    migrate(engine)

    alembic_on(engine, command.downgrade, "0016")
    assert "timing" not in columns(engine) and version(engine) == "0016"
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM episodes")) == 1

    migrate(engine)
    assert timings(engine) == {(1, 1, 1): "day"}


def test_a_database_file_is_copied_to_backups_before_the_migration(tmp_path):
    path = tmp_path / "tracker.db"
    engine = create_tracker_engine(f"sqlite:///{path}")
    alembic_on(engine, command.upgrade, "0016")
    engine.dispose()

    create_session_factory(f"sqlite:///{path}", now=NOW)

    copies = list((tmp_path / BACKUP_FOLDER).iterdir())
    assert len(copies) == 1 and "before-0016" in copies[0].name
