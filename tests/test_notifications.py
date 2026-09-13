"""Tests for notification dedup + rules service (in-memory SQLite, no network)."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import MediaItem, User


def _make_session():
    """Fresh in-memory engine + schema; one shared connection (StaticPool)."""
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return factory()


def test_dedup_mark_sent():
    from app.services.notifications import has_been_sent, mark_sent

    s = _make_session()
    user = User(telegram_user_id=454501218)
    s.add(user)
    s.commit()
    item = MediaItem(media_type="movie", canonical_title_en="Dune")
    s.add(item)
    s.flush()  # generate UUID primary key before FK reference
    s.commit()

    fp = "fp-1"
    assert not has_been_sent(s, fp), "nothing sent yet"
    first = mark_sent(s, fp, item.id)
    assert first is True, "first mark should record a new row"
    second = mark_sent(s, fp, item.id)
    assert second is False, "second mark must dedup (no duplicate)"
    s.close()


def test_rules_crud():
    from app.services.notifications import get_enabled_rules, set_rule

    s = _make_session()
    user = User(telegram_user_id=454501218)
    s.add(user)
    s.commit()
    item = MediaItem(media_type="movie", canonical_title_en="Dune")
    s.add(item)
    s.flush()  # generate UUID primary key before FK reference
    s.commit()

    set_rule(s, user.id, item.id, "DIGITAL_RELEASED", True)
    enabled = get_enabled_rules(s, user.id, item.id)
    assert len(enabled) == 1 and enabled[0].event_type == "DIGITAL_RELEASED"

    # Toggle off: rule exists but is no longer enabled.
    set_rule(s, user.id, item.id, "DIGITAL_RELEASED", False)
    enabled = get_enabled_rules(s, user.id, item.id)
    assert len(enabled) == 0, "toggled-off rule must not be returned as enabled"
    s.close()


if __name__ == "__main__":
    # Run directly without pytest (pytest not yet installed in .venv).
    test_dedup_mark_sent()
    test_rules_crud()
    print("notifications tests passed")
