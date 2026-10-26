"""Tracker core: the whole public interface that touches the database is asynchronous (docs/coding-standards.md).

Checked on the facade itself, so a new public method that reads the database in the caller's thread is caught here
and not by the next review.
"""

import asyncio
import inspect
import threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.tracker.core import Tracker
from app.tracker.db import create_session_factory

T0 = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


class FakeSender:
    async def send(self, message, actions=()):
        pass


def public_methods():
    return [
        (name, member)
        for name, member in inspect.getmembers(Tracker, predicate=inspect.isfunction)
        if not name.startswith("_")
    ]


def test_no_public_method_that_opens_a_database_session_is_an_ordinary_function():
    blocking = [
        name
        for name, member in public_methods()
        if "session_factory" in inspect.getsource(member) and not inspect.iscoroutinefunction(member)
    ]

    assert blocking == []


@pytest.mark.parametrize(
    "name",
    ["title_card", "list_titles", "watchable_seasons", "delivery_rules", "delivery_check_moment", "part_gap_weeks", "record_event"],
)
def test_the_methods_that_used_to_read_in_the_callers_thread_are_coroutines(name):
    assert inspect.iscoroutinefunction(getattr(Tracker, name))


def test_the_methods_without_a_database_stay_ordinary():
    assert not inspect.iscoroutinefunction(Tracker.test_samples)
    assert not inspect.iscoroutinefunction(Tracker.register_test_sample)


def test_creating_the_core_does_not_open_the_database():
    def forbidden():
        raise AssertionError("the database was opened while the core was being created")

    Tracker(forbidden, clock=lambda: T0, sender=FakeSender(), sources={}, default_tz=ZoneInfo("Asia/Jerusalem"))


def test_the_database_work_of_a_read_runs_off_the_event_loop_thread():
    factory = create_session_factory("sqlite://")
    opened_in = []

    def watching():
        opened_in.append(threading.current_thread())
        return factory()

    tracker = Tracker(watching, clock=lambda: T0, sender=FakeSender(), sources={})

    async def scenario():
        await tracker.list_titles()
        await tracker.delivery_rules()
        return threading.current_thread()

    loop_thread = asyncio.run(scenario())

    assert opened_in and all(thread is not loop_thread for thread in opened_in)
