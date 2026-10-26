"""Tracker database: engine (WAL), session factory and Alembic migrations.

The schema is created only by Alembic (`app/tracker/migrations`), never by `create_all`.
"""

import pathlib
import threading

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

TRACKER_DATABASE_URL = "sqlite:///./data/tracker.db"  # separate file: the legacy data/bot.db is not touched

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent / "migrations"


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


def migrate(engine: Engine) -> None:
    """Bring the database up to the latest revision (safe to call on every start)."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def create_session_factory(url: str = TRACKER_DATABASE_URL) -> sessionmaker:
    """Open the tracker database, migrate it and return a session factory."""
    engine = create_tracker_engine(url)
    migrate(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)
