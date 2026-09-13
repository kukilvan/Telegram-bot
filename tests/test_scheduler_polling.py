"""Tests for adaptive polling cycle (fake provider, in-memory SQLite, no network)."""

import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import ExternalId, MediaItem, User


class FakeProvider:
    """Simulates a state change across calls (no real HTTP)."""

    def __init__(self):
        self.calls = 0

    async def get_movie_details(self, movie_id):
        self.calls += 1
        if self.calls == 1:
            return {}  # first poll: no date yet (baseline empty)
        else:
            return {"release_date": "2026-09-10"}


def _make_session():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return factory()


def test_poll_item_cycle():
    from app.scheduler.polling import poll_item

    s = _make_session()
    user = User(telegram_user_id=454501218)
    s.add(user)
    s.commit()
    item = MediaItem(media_type="movie", canonical_title_en="Dune")
    s.add(item)
    s.flush()  # generate UUID primary key before FK reference
    s.commit()
    ext = ExternalId(media_item_id=item.id, source="tmdb", external_id="841")
    s.add(ext)
    s.commit()

    from app.services.notifications import set_rule
    set_rule(s, user.id, item.id, "DIGITAL_DATE_ANNOUNCED", True)

    provider = FakeProvider()
    # Poll 1: baseline (no prior state).
    r1 = asyncio.run(poll_item(s, provider, item, user_id=user.id))
    assert r1 == [], "first poll stores baseline, no event"
    # Poll 2: state change detected + enabled-rule gate passes.
    r2 = asyncio.run(poll_item(s, provider, item, user_id=user.id))
    assert len(r2) == 1 and r2[0].event_type == "DIGITAL_DATE_ANNOUNCED", (
        "state change should produce exactly one event"
    )
    # Poll 3: no re-detection (stored state now matches).
    r3 = asyncio.run(poll_item(s, provider, item, user_id=user.id))
    assert r3 == [], "no duplicate on re-poll"
    s.close()


if __name__ == "__main__":
    # Run directly without pytest (pytest not yet installed in .venv).
    test_poll_item_cycle()
    print("scheduler polling tests passed")
