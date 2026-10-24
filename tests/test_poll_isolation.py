"""Polling isolation: one failing title/source must not stop the others (fake providers, no network)."""

import asyncio
import logging
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.bot import error_handler
from app.database.base import Base
from app.database.models import ExternalId, MediaItem, User, UserWatchItem
from app.scheduler import polling
from app.scheduler.failures import format_failure_notice, new_failure_notices
from app.services.notifications import set_rule

NOW = datetime(2026, 10, 24, 12, 0, 0)


@pytest.fixture(autouse=True)
def _clean_retry_memory():
    polling._failed_until.clear()
    yield
    polling._failed_until.clear()


def _session():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _movie(session, tmdb_id, title):
    item = MediaItem(media_type="movie", canonical_title_en=title)
    session.add(item)
    session.flush()
    session.add(ExternalId(media_item_id=item.id, source="tmdb", external_id=str(tmdb_id)))
    session.commit()
    return item


class FlakyProvider:
    """Raises for the ids in `broken`; counts calls per id."""

    def __init__(self, broken=()):
        self.broken = {str(b) for b in broken}
        self.calls = {}

    async def get_movie_release_dates(self, movie_id):
        self.calls[str(movie_id)] = self.calls.get(str(movie_id), 0) + 1
        if str(movie_id) in self.broken:
            raise RuntimeError("boom: provider is down")
        return []


def _setup_two_movies():
    s = _session()
    user = User(telegram_user_id=1)
    s.add(user)
    s.commit()
    broken, fine = _movie(s, 111, "Broken Movie"), _movie(s, 222, "Fine Movie")
    for item in (broken, fine):
        s.add(UserWatchItem(user_id=user.id, media_item_id=item.id))
    s.commit()
    return s, broken, fine


def test_one_failing_item_does_not_stop_the_rest_of_the_scan():
    s, broken, fine = _setup_two_movies()
    provider = FlakyProvider(broken=[111])
    seen = []

    results = asyncio.run(
        polling.poll_due_items(s, provider, now=NOW, on_error=lambda item, src, exc: seen.append((item.id, src, type(exc).__name__)))
    )

    assert all(events == [] for _, _, events in results)
    assert provider.calls == {"111": 1, "222": 1}  # the healthy title was still polled
    assert polling._load_state(s, fine.id, "tmdb") is not None  # ...and its baseline stored
    assert polling._load_state(s, broken.id, "tmdb") is None
    assert seen == [(broken.id, "tmdb", "RuntimeError")]  # the failure was reported, not swallowed silently


def test_failed_item_is_skipped_until_retry_time_then_retried():
    s, broken, fine = _setup_two_movies()
    provider = FlakyProvider(broken=[111])

    asyncio.run(polling.poll_due_items(s, provider, now=NOW))
    assert provider.calls["111"] == 1

    # next scan 2 minutes later: the broken item is not hammered again
    asyncio.run(polling.poll_due_items(s, provider, now=NOW + timedelta(minutes=2)))
    assert provider.calls["111"] == 1

    # after the retry delay it is tried again
    later = NOW + timedelta(seconds=polling.RETRY_AFTER_FAILURE_SECONDS + 60)
    asyncio.run(polling.poll_due_items(s, provider, now=later))
    assert provider.calls["111"] == 2


def test_recovered_item_is_forgotten():
    s, broken, _ = _setup_two_movies()
    provider = FlakyProvider(broken=[111])
    asyncio.run(polling.poll_due_items(s, provider, now=NOW))
    assert broken.id in polling._failed_until

    provider.broken.clear()  # the provider is back
    later = NOW + timedelta(seconds=polling.RETRY_AFTER_FAILURE_SECONDS + 60)
    asyncio.run(polling.poll_due_items(s, provider, now=later))
    assert broken.id not in polling._failed_until


def test_failing_on_error_callback_does_not_break_the_scan():
    s, _, fine = _setup_two_movies()

    def bad_callback(item, source, exc):
        raise ValueError("callback is broken too")

    asyncio.run(polling.poll_due_items(s, FlakyProvider(broken=[111]), now=NOW, on_error=bad_callback))
    assert polling._load_state(s, fine.id, "tmdb") is not None


def test_failing_source_keeps_events_found_by_the_other_source(monkeypatch):
    """Anime is polled from TMDb and AniList; events already marked as sent by TMDb must survive an AniList failure."""
    s = _session()
    user = User(telegram_user_id=1)
    s.add(user)
    item = MediaItem(media_type="anime", canonical_title_en="Some Anime")
    s.add(item)
    s.commit()
    set_rule(s, user.id, item.id, "DIGITAL_DATE_ANNOUNCED", True)

    states = iter([{"digital_release": None}, {"digital_release": "2026-12-01"}])

    async def fake_tmdb_state(session, provider, it):
        return next(states)

    async def failing_anilist_state(session, provider, it):
        raise RuntimeError("anilist is down")

    monkeypatch.setattr(polling, "_fetch_tmdb_state", fake_tmdb_state)
    monkeypatch.setattr(polling, "_fetch_anilist_state", failing_anilist_state)

    errors = []
    asyncio.run(polling.poll_item(s, object(), object(), item, user.id, errors=errors))  # baseline
    events = asyncio.run(polling.poll_item(s, object(), object(), item, user.id, errors=errors))

    assert [e.event_type for e in events] == ["DIGITAL_DATE_ANNOUNCED"]
    assert [src for src, _ in errors] == ["anilist", "anilist"]


# ---- owner notices -------------------------------------------------------

def test_owner_is_told_once_per_item_per_day():
    told = {}
    failures = [("a", "Dune", "tmdb", "ReadTimeout"), ("a", "Dune", "anilist", "ReadTimeout"), ("b", "Silo", "tmdb", "HTTPStatusError")]
    first = new_failure_notices(failures, told, NOW)
    assert [n[0] for n in first] == ["Dune", "Silo"]  # Dune once, although two of its sources failed

    assert new_failure_notices(failures, told, NOW + timedelta(hours=1)) == []
    assert [n[0] for n in new_failure_notices(failures, told, NOW + timedelta(hours=25))] == ["Dune", "Silo"]


def test_failure_notice_has_no_exception_details():
    text = format_failure_notice("Dune", "tmdb", "ReadTimeout")
    assert "Dune" in text and "ReadTimeout" in text
    assert "http" not in text.lower() and "api_key" not in text.lower()


# ---- error report to the owner ------------------------------------------

def test_error_report_keeps_quotes_unescaped_so_telegram_can_parse_it():
    text = error_handler._format_error_for_telegram(NameError("name 'datetime' is not defined <x> & y"))
    assert "&#x27;" not in text and "'datetime'" in text
    assert "&lt;x&gt;" in text and "&amp;" in text


def test_rejected_error_report_logs_telegram_reason(monkeypatch, caplog):
    class FakeResponse:
        status_code = 400

        def json(self):
            return {"description": "Bad Request: can't parse entities"}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return FakeResponse()

    monkeypatch.setattr(error_handler.httpx, "AsyncClient", FakeClient)
    with caplog.at_level(logging.ERROR):
        ok = asyncio.run(error_handler._send_error_via_http("123456:TOKEN", "1", "text"))
    assert ok is False
    assert "can't parse entities" in caplog.text
