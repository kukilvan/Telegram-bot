"""_ensure_igdb_item: IGDB gives first_release_date as a unix timestamp (regression: NameError on `datetime`)."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.bot.main import _ensure_igdb_item
from app.database.base import Base


def _session():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_unix_timestamp_gives_year():
    s = _session()
    item = _ensure_igdb_item(s, 1, {"name": "Witcher", "first_release_date": 1431993600})  # 2015-05-19
    assert item.year == 2015
    assert item.media_type == "game"


def test_year_is_utc_not_local_time():
    # 2026-01-01 00:00 UTC must be 2026 even on a machine west of UTC
    s = _session()
    item = _ensure_igdb_item(s, 2, {"name": "New Year Game", "first_release_date": 1767225600})
    assert item.year == 2026


def test_string_date_and_missing_date():
    s = _session()
    assert _ensure_igdb_item(s, 3, {"name": "A", "first_release_date": "2024-03-05"}).year == 2024
    assert _ensure_igdb_item(s, 4, {"name": "B"}).year is None


def test_existing_item_is_returned_not_duplicated():
    s = _session()
    first = _ensure_igdb_item(s, 5, {"name": "C", "first_release_date": 1431993600})
    again = _ensure_igdb_item(s, 5, {"name": "C", "first_release_date": 1431993600})
    assert first.id == again.id
