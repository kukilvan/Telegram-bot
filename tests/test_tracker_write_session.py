"""Ticket 29: the database guards a write, not a lock in memory.

`CoreContext.write_session()` opens its transaction at once for writing (`BEGIN IMMEDIATE`): a second writer, from
this process or from another, waits until the first has committed. So «check, then write» cannot be torn apart,
whoever else writes at that moment (the web application will be a second process on the same file).
"""

import ast
import asyncio
import pathlib
import threading
import time
from datetime import date, datetime, timezone

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text

from app.tracker.context import CoreContext
from app.tracker.core import Tracker
from app.tracker.db import MIGRATIONS_DIR, create_session_factory, create_tracker_engine, migrate
from app.tracker.models import DeliveryItem, Event, SettingRecord, SourceSnapshot, Title, TitleStatus
from app.tracker.sources.tmdb_movies import MovieSnapshot
from app.tracker.sources.tmdb_sequels import CollectionPart, SequelSnapshot
from test_tracker_migration_0008 import insert_event, insert_title

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


class FakeSender:
    async def send(self, message, actions=()):
        pass


class FakeMovieSource:
    source_key = "tmdb_movie"

    async def suggest(self, query):
        return []

    async def snapshot(self, external_id):
        return MovieSnapshot(external_id=external_id, name="Дюна", original_name="Dune", year=2021, genres=[])


class FakeSequelSource:
    source_key = "tmdb_sequels"

    async def snapshot(self, external_id):
        return SequelSnapshot(own_date=date(2021, 9, 15), parts=[CollectionPart("2", "Дюна 2", date(2024, 2, 27))])


def file_url(tmp_path) -> str:
    return f"sqlite:///{tmp_path / 'tracker.db'}"


def tracker_on(url: str) -> Tracker:
    """A core with its own engine on the file: two of them on one file are two writers like two processes."""
    return Tracker(
        create_session_factory(url), clock=lambda: NOW, sender=FakeSender(),
        sources={"movie": FakeMovieSource()}, sequel_sources={"movie": FakeSequelSource()},
    )


def context_on(url: str) -> CoreContext:
    return CoreContext(create_session_factory(url), lambda: NOW, FakeSender(), timezone.utc)


# --- the write session ------------------------------------------------------------------------


def test_a_second_writer_waits_for_the_open_write_session_and_then_passes(tmp_path):
    url = file_url(tmp_path)
    first, second = context_on(url), context_on(url)  # two engines on one file
    order: list[str] = []
    opened = threading.Event()

    def holder():
        with first.write_session() as session:
            opened.set()
            time.sleep(0.6)
            session.add(SettingRecord(key="a", value=1))
            session.commit()
            order.append("first committed")

    thread = threading.Thread(target=holder)
    thread.start()
    assert opened.wait(5)
    with second.write_session() as session:  # asked while the first is open: waits, then passes
        order.append("second opened")
        session.add(SettingRecord(key="b", value=2))
        session.commit()
    thread.join()

    assert order == ["first committed", "second opened"]
    with first.session_factory() as session:
        assert {r.key for r in session.scalars(select(SettingRecord))} == {"a", "b"}


def test_a_write_session_holds_the_database_from_its_first_statement(tmp_path):
    """Not at the first write: a «check, then write» inside it cannot be torn apart by another writer."""
    url = file_url(tmp_path)
    first, second = context_on(url), context_on(url)
    with first.write_session() as session:
        session.scalar(select(func.count()).select_from(SettingRecord))  # only a read so far
        with second.session_factory() as other:
            other.connection().exec_driver_sql("PRAGMA busy_timeout=50")
            with pytest.raises(Exception, match="locked"):
                other.connection().exec_driver_sql("BEGIN IMMEDIATE")


def test_an_ordinary_session_does_not_wait_for_a_writer_to_read(tmp_path):
    url = file_url(tmp_path)
    writer, reader = context_on(url), context_on(url)
    with writer.write_session():
        with reader.session_factory() as session:  # WAL: a reader is never blocked
            assert session.scalar(select(func.count()).select_from(Title)) == 0


def test_an_in_memory_database_still_works_for_write_sessions():
    ctx = CoreContext(create_session_factory("sqlite://"), lambda: NOW, FakeSender(), timezone.utc)
    with ctx.write_session() as session:
        session.add(SettingRecord(key="a", value=1))
        session.commit()
    with ctx.write_session() as session:
        assert session.get(SettingRecord, "a").value == 1


def test_a_rolled_back_write_session_leaves_the_database_free(tmp_path):
    url = file_url(tmp_path)
    first, second = context_on(url), context_on(url)
    with first.write_session() as session:
        session.add(SettingRecord(key="a", value=1))
        session.rollback()
    with second.write_session() as session:  # does not wait out the busy timeout
        started = time.monotonic()
        session.add(SettingRecord(key="b", value=2))
        session.commit()
    assert time.monotonic() - started < 1


# --- two «Посмотрел» at once --------------------------------------------------------------------


def test_two_watched_presses_at_once_from_two_cores_both_finish_and_the_sequels_are_snapshotted_once(tmp_path):
    url = file_url(tmp_path)
    one, two = tracker_on(url), tracker_on(url)  # the bot and the web application: two engines, no shared lock

    async def scenario():
        added = await one.add_title("movie", "1")
        results = await asyncio.gather(
            one.mark_watched(added.title_id), two.mark_watched(added.title_id)
        )
        return added.title_id, results

    title_id, results = asyncio.run(scenario())

    assert sorted(r.changed for r in results) == [False, True]
    with one.session_factory() as session:
        assert session.get(Title, title_id).status == TitleStatus.WATCHED
        sequel_snapshots = session.scalar(
            select(func.count()).select_from(SourceSnapshot)
            .where(SourceSnapshot.title_id == title_id, SourceSnapshot.source == "tmdb_sequels")
        )
        assert sequel_snapshots == 1


def test_two_adds_of_one_movie_from_two_cores_give_one_title(tmp_path):
    url = file_url(tmp_path)
    one, two = tracker_on(url), tracker_on(url)

    async def scenario():
        return await asyncio.gather(one.add_title("movie", "1"), two.add_title("movie", "1"))

    results = asyncio.run(scenario())

    assert sorted(r.created for r in results) == [False, True]
    assert results[0].title_id == results[1].title_id
    with one.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Title)) == 1


# --- the code ---------------------------------------------------------------------------------


def core_sources():
    return [path for path in (APP / "tracker").rglob("*.py") if "migrations" not in path.parts]


def test_there_is_no_write_lock_in_the_code():
    offenders = [str(p.relative_to(APP)) for p in core_sources() if "write_lock" in p.read_text(encoding="utf-8")]
    assert offenders == []


def test_every_write_goes_through_write_session():
    """A block that opens an ordinary session (`session_factory()`) only reads: it never commits."""
    offenders = []
    for path in core_sources():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.With):
                continue
            for item in node.items:
                call = item.context_expr
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "session_factory":
                    commits = [
                        n.lineno for n in ast.walk(node)
                        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "commit"
                    ]
                    offenders += [f"{path.relative_to(APP)}:{line}" for line in commits]
    assert offenders == []


# --- migrations -------------------------------------------------------------------------------


def alembic_config(url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", url)
    return config


def test_migrations_from_scratch_on_a_file_database(tmp_path):
    engine = create_tracker_engine(file_url(tmp_path))
    migrate(engine)
    with engine.connect() as connection:
        tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        assert {"titles", "events", "delivery_queue", "settings", "alembic_version"} <= tables
        assert connection.execute(text("PRAGMA foreign_key_check")).fetchall() == []


def test_migrations_run_from_the_command_line_way(tmp_path):
    """Without a connection handed over, as `alembic -c alembic_tracker.ini upgrade head` runs them."""
    url = file_url(tmp_path)
    command.upgrade(alembic_config(url), "head")
    engine = create_tracker_engine(url)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM alembic_version")).scalar() == 1
        assert "name" in {row[1] for row in connection.execute(text("PRAGMA table_info(titles)"))}


def test_an_older_database_with_data_is_migrated_when_opened_and_keeps_it(tmp_path):
    """The owner's file, as the previous version left it (revision 0007, with a title and a queued event)."""
    url = file_url(tmp_path)
    command.upgrade(alembic_config(url), "0007")
    engine = create_tracker_engine(url)
    with engine.begin() as connection:
        insert_title(connection, 1)
        insert_event(connection, 10, 1)
    engine.dispose()

    session_factory = create_session_factory(url)  # opening the database migrates it, through the new transactions

    with session_factory() as session:
        assert session.scalar(select(Title.name)) == "Дюна"
        assert session.scalar(select(func.count()).select_from(Event)) == 1
        assert session.scalar(select(func.count()).select_from(DeliveryItem)) == 1
        assert session.execute(text("PRAGMA foreign_key_check")).fetchall() == []
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == "0011"


def test_a_database_that_is_already_current_is_opened_again_without_change(tmp_path):
    url = file_url(tmp_path)
    ctx = context_on(url)
    with ctx.write_session() as session:
        session.add(SettingRecord(key="part_gap_weeks", value=8))
        session.commit()
    again = create_session_factory(url)
    with again() as session:
        assert session.get(SettingRecord, "part_gap_weeks").value == 8
