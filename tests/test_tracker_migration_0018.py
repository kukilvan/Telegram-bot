"""Migration 0018 (spec 4.6 and 12 of stage 9.1d, KI-81): the Shikimori snapshot of every anime title is due at the
moment of the migration, so the first polling pass reads the premieres again; nothing else changes. Down: nothing to
undo. A copy of a database file goes to `backups` before the migration runs."""

from datetime import datetime, timedelta, timezone

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.tracker.db import BACKUP_FOLDER, MIGRATIONS_DIR, create_session_factory, create_tracker_engine, migrate

NOW = datetime(2026, 11, 23, 12, 0)
LATER = datetime(2026, 11, 24, 9, 0)


def alembic_on(engine, step, revision):
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        step(config, revision)


def version(engine):
    with engine.connect() as connection:
        return connection.scalar(text("SELECT version_num FROM alembic_version"))


def put_title(connection, title_id, kind, snapshots):
    """A title of `kind` with its snapshots: source → the time of its next check."""
    connection.execute(
        text(
            "INSERT INTO titles (id, kind, name, original_name, genres, status, tracking_enabled, added_at, "
            "status_changed_at) VALUES (:id, :kind, 'Тайтл', 'Title', '[]', 'want', 1, :now, :now)"
        ),
        {"id": title_id, "kind": kind, "now": NOW},
    )
    for source, next_check_at in snapshots.items():
        connection.execute(
            text(
                "INSERT INTO source_snapshots (title_id, source, state, observed_at, next_check_at) "
                "VALUES (:t, :s, '{}', :now, :next)"
            ),
            {"t": title_id, "s": source, "now": NOW, "next": next_check_at},
        )


def checks(engine):
    """(title, source) → the time of the next check, as stored."""
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT title_id, source, next_check_at FROM source_snapshots"))
        return {(t, s): at for t, s, at in rows}


@pytest.fixture
def engine():
    return create_tracker_engine("sqlite://")


def test_the_shikimori_snapshots_of_anime_are_due_and_the_rest_is_untouched(engine):
    alembic_on(engine, command.upgrade, "0017")
    with engine.begin() as connection:
        put_title(connection, 1, "anime", {"shikimori": LATER})
        put_title(connection, 2, "anime", {"shikimori": None})
        put_title(connection, 3, "series", {"tmdb_tv": LATER})
        put_title(connection, 4, "movie", {"tmdb_movie": LATER, "tmdb_sequels": LATER})
        put_title(connection, 5, "game", {"igdb": LATER, "steam_prices": LATER})
    before = checks(engine)
    start = datetime.now(timezone.utc).replace(tzinfo=None)

    migrate(engine)

    after = checks(engine)
    assert version(engine) == "0019"
    for key in ((1, "shikimori"), (2, "shikimori")):
        due = datetime.fromisoformat(str(after[key]))
        assert start - timedelta(seconds=1) <= due <= datetime.now(timezone.utc).replace(tzinfo=None)
    assert {k: v for k, v in after.items() if k[1] != "shikimori"} == {
        k: v for k, v in before.items() if k[1] != "shikimori"
    }


def test_an_empty_database_migrates_and_a_second_run_changes_nothing(engine):
    migrate(engine)
    migrate(engine)

    assert version(engine) == "0019"


def test_down_leaves_the_checks_as_they_are(engine):
    alembic_on(engine, command.upgrade, "0017")
    with engine.begin() as connection:
        put_title(connection, 1, "anime", {"shikimori": LATER})
    migrate(engine)
    migrated = checks(engine)

    alembic_on(engine, command.downgrade, "0017")

    assert version(engine) == "0017" and checks(engine) == migrated


def test_a_database_file_is_copied_to_backups_before_the_migration(tmp_path):
    path = tmp_path / "tracker.db"
    engine = create_tracker_engine(f"sqlite:///{path}")
    alembic_on(engine, command.upgrade, "0017")
    engine.dispose()

    create_session_factory(f"sqlite:///{path}", now=NOW)

    copies = list((tmp_path / BACKUP_FOLDER).iterdir())
    assert len(copies) == 1 and "before-0017" in copies[0].name
