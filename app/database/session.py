"""Database engine and session factory."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.base import Base

DATABASE_URL = "sqlite:///./data/bot.db"  # dev; prod will be PostgreSQL


def ensure_data_dir() -> None:
    """Create the parent directory of a SQLite URL if it does not exist.

    SQLite cannot create a database file inside a missing directory, so any
    connection to DATABASE_URL must first guarantee its parent exists.
    """
    import pathlib

    rel = DATABASE_URL.split("///")[-1]  # e.g. "./data/bot.db"
    db_dir = pathlib.Path(rel).parent
    db_dir.mkdir(parents=True, exist_ok=True)



def get_engine():
    return create_engine(DATABASE_URL, echo=False)


def get_session_factory(engine=None):
    engine = engine or get_engine()
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    return session_factory


def init_db():
    """Create tables (dev only; prod uses Alembic migrations)."""
    from app.database.models import User  # noqa — ensure models are imported

    engine = get_engine()
    Base.metadata.create_all(engine)
