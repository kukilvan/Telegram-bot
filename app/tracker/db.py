"""Tracker database: engine (WAL), session factory and Alembic migrations.

The schema is created only by Alembic (`app/tracker/migrations`), never by `create_all`.
"""

import hashlib
import logging
import pathlib
import re
import sqlite3
import threading
from datetime import datetime

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

TRACKER_DATABASE_URL = "sqlite:///./data/tracker.db"  # separate file: the legacy data/bot.db is not touched

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent / "migrations"

BACKUP_FOLDER = "backups"  # next to the database file
BACKUP_STAMP_FORMAT = "%Y%m%d_%H%M%S"  # the time in the name of a backup


def database_file(url: str = TRACKER_DATABASE_URL) -> pathlib.Path | None:
    """The file the database at this address lives in, as the engine opens it (a relative address counts from the
    current folder). None for an in-memory database. The backup finds the database through this."""
    database = make_url(url).database
    return None if database in (None, "", ":memory:") else pathlib.Path(database)


WRITE_OPTION = "tracker_write"  # execution option of a connection: its transaction opens at once for writing


def create_tracker_engine(url: str = TRACKER_DATABASE_URL) -> Engine:
    """SQLite engine in WAL mode with foreign keys on. `sqlite://` gives a private in-memory database.

    The driver (pysqlite) does not begin transactions itself; the engine writes the beginning (`begin` event, the way
    SQLAlchemy documents it for SQLite): `BEGIN` for an ordinary transaction, `BEGIN IMMEDIATE` for a connection with
    the option `WRITE_OPTION`. A writer that begins that way holds the database: another writer, of this process or of
    another, waits up to `busy_timeout` instead of failing in the middle of «check, then write».
    """
    file = database_file(url)
    if file is not None:
        file.parent.mkdir(parents=True, exist_ok=True)
    kwargs = {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}} if file is None else {}
    engine = create_engine(url, **kwargs)
    # An in-memory database is one connection shared by all threads, so its transactions cannot wait for each other in
    # SQLite: they take turns in this lock, from the beginning of a transaction to the end of its commit or rollback.
    turns = threading.Lock() if file is None else None
    owner: list[int] = []  # the thread that holds `turns`

    @event.listens_for(engine, "connect")
    def _configure(dbapi_connection, _record):
        dbapi_connection.isolation_level = None  # the beginning of a transaction is written by `_begin`
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")  # no-op for in-memory databases
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    def _release():
        if owner and owner[0] == threading.get_ident():  # a transaction ends in the thread that began it
            owner.clear()
            turns.release()

    @event.listens_for(engine, "begin")
    def _begin(connection):
        if turns is not None:
            turns.acquire()
            owner[:] = [threading.get_ident()]
        try:
            writing = connection.get_execution_options().get(WRITE_OPTION)
            connection.exec_driver_sql("BEGIN IMMEDIATE" if writing else "BEGIN")
        except BaseException:
            if turns is not None:
                _release()
            raise

    if turns is not None:
        # the `commit` and `rollback` events fire before the driver's commit; the turn passes on only after it
        dialect = engine.dialect
        driver_commit, driver_rollback = dialect.do_commit, dialect.do_rollback

        def do_commit(dbapi_connection):
            try:
                driver_commit(dbapi_connection)
            finally:
                _release()

        def do_rollback(dbapi_connection):
            try:
                driver_rollback(dbapi_connection)
            finally:
                _release()

        dialect.do_commit, dialect.do_rollback = do_commit, do_rollback

    return engine


def _alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return config


def migrate(engine: Engine) -> None:
    """Bring the database up to the latest revision (safe to call on every start)."""
    config = _alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def backup_name(now: datetime, suffix: str = "") -> str:
    """The name of a backup made at `now`: `tracker_db_<time>.db`, or `tracker_db_<time>_<suffix>.db`."""
    return f"tracker_db_{now.strftime(BACKUP_STAMP_FORMAT)}{'_' + suffix if suffix else ''}.db"


def copy_database(source: pathlib.Path, target: pathlib.Path) -> None:
    """Copy a database file with SQLite's online backup (safe while the bot writes in WAL mode). The backups of
    `app/utils/backup.py` and the copy before a migration both go through this."""
    target.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(source)
    try:
        target_connection = sqlite3.connect(target)
        try:
            source_connection.backup(target_connection)
        except BaseException:
            target_connection.close()
            target.unlink(missing_ok=True)  # a half-made file would pass for the newest copy
            raise
        finally:
            target_connection.close()
    finally:
        source_connection.close()


def _revision_of(file: pathlib.Path) -> str | None:
    """The migration revision the database file is at; None if it has none (an empty file)."""
    connection = sqlite3.connect(file)
    try:
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    except sqlite3.OperationalError:  # no `alembic_version` table
        return None
    finally:
        connection.close()
    return row[0] if row else None


def _dump_hash(file: pathlib.Path) -> str:
    """SHA-256 of the text dump of a database (the schema and every row), read as a stream. A plain connection, not a
    read-only one: that would leave the `-wal` and `-shm` files of a WAL copy behind; reading changes nothing."""
    connection = sqlite3.connect(file)
    try:
        dump = hashlib.sha256()
        for line in connection.iterdump():
            dump.update(line.encode("utf-8"))
            dump.update(b"\n")
        return dump.hexdigest()
    finally:
        connection.close()


def _newest_copy_before(folder: pathlib.Path, revision: str) -> pathlib.Path | None:
    """The newest `tracker_db_<time>_before-<revision>.db` in the folder, by the time in its name."""
    name = re.compile(rf"^tracker_db_(\d{{8}}_\d{{6}})_before-{re.escape(revision)}\.db$")
    found = []
    if folder.is_dir():
        for path in folder.iterdir():
            match = name.match(path.name)
            if match is None:
                continue
            try:
                found.append((datetime.strptime(match.group(1), BACKUP_STAMP_FORMAT), path))
            except ValueError:  # no such date
                continue
    return max(found)[1] if found else None


def _same_content(file: pathlib.Path, copy: pathlib.Path) -> bool:
    """The copy holds what the database holds; a copy that does not open or read is not the same."""
    try:
        return _dump_hash(copy) == _dump_hash(file)
    except (sqlite3.Error, OSError):
        return False


def _backup_before_migration(file: pathlib.Path, now: datetime) -> None:
    """If the existing database file has migrations still to run, copy it first to `backups` next to it as
    `tracker_db_<time>_before-<revision>.db`. A failed copy is raised: the migration must not run without it.

    A migration that failed is rolled back whole, and Docker starts the process again every minute: when the newest
    copy before the same revision holds what the database holds, it is the copy, and no new one is made."""
    revision = _revision_of(file)
    if revision is None or revision == ScriptDirectory.from_config(_alembic_config()).get_current_head():
        return
    folder = file.parent / BACKUP_FOLDER
    earlier = _newest_copy_before(folder, revision)
    if earlier is not None and _same_content(file, earlier):
        logging.info("копия перед миграцией с %s уже есть: %s; база с тех пор не менялась", revision, earlier)
        return
    target = folder / backup_name(now, f"before-{revision}")
    try:
        copy_database(file, target)
    except Exception as exc:
        logging.error("No backup before the migration from %s, the database stays as it is: %r", revision, exc)
        raise
    logging.info("Database backup before the migration created: %s", target)


def create_session_factory(url: str = TRACKER_DATABASE_URL, now: datetime | None = None) -> sessionmaker:
    """Open the tracker database, migrate it and return a session factory. A database that already exists and has
    migrations to run is copied first (`now` is the clock of the copy's name; local time)."""
    file = database_file(url)
    if file is not None and file.exists():  # before the engine opens (and so creates) the file
        _backup_before_migration(file, now or datetime.now())
    engine = create_tracker_engine(url)
    migrate(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)
