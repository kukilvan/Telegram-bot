"""Tracker database: engine (WAL), session factory and Alembic migrations.

The schema is created only by Alembic (`app/tracker/migrations`), never by `create_all`.
"""

import pathlib

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


def create_tracker_engine(url: str = TRACKER_DATABASE_URL) -> Engine:
    """SQLite engine in WAL mode with foreign keys on. `sqlite://` gives a private in-memory database."""
    file = database_file(url)
    if file is not None:
        file.parent.mkdir(parents=True, exist_ok=True)
    kwargs = {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}} if file is None else {}
    engine = create_engine(url, **kwargs)

    @event.listens_for(engine, "connect")
    def _configure(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")  # no-op for in-memory databases
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

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
