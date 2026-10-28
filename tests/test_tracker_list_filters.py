"""The rows of the list for the web: a filter by kind and by a set of statuses, the order «newest first» and «by name»,
the poster in the row. The call without arguments is the bot's list and stays as it was. Rows are put straight into the
database, so the moments of adding and the names are exactly what a test needs."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.tracker.core import ListOrder, Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import ARCHIVE_STATUSES, Title, TitleKind, TitleStatus

T0 = datetime(2026, 10, 24, 12, 0)


class FakeSender:
    async def send(self, message, actions=()):
        pass


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def tracker(session_factory):
    return Tracker(session_factory, clock=lambda: T0.replace(tzinfo=timezone.utc), sender=FakeSender())


def put(session_factory, name, kind=TitleKind.MOVIE, status=TitleStatus.WANT, minutes=0, poster=None):
    """A title added `minutes` after T0; returns its number."""
    with session_factory() as session:
        title = Title(
            kind=kind, name=name, original_name=name, genres=[], status=status, tracking_enabled=True,
            added_at=T0 + timedelta(minutes=minutes), status_changed_at=T0, poster_path=poster,
        )
        session.add(title)
        session.commit()
        return title.id


def names(rows):
    return [row.name for row in rows]


def test_the_call_without_arguments_is_the_bots_list_in_the_order_of_adding(tracker, session_factory):
    second = put(session_factory, "Второй", minutes=5)
    first = put(session_factory, "Первый", minutes=1)

    assert [row.id for row in run(tracker.list_titles())] == [second, first]  # by number, as it always was


def test_the_filter_by_kind(tracker, session_factory):
    put(session_factory, "Фильм")
    put(session_factory, "Сериал", kind=TitleKind.SERIES)
    put(session_factory, "Аниме", kind=TitleKind.ANIME)

    assert names(run(tracker.list_titles(kind=TitleKind.SERIES))) == ["Сериал"]
    assert names(run(tracker.list_titles(kind=TitleKind.ANIME))) == ["Аниме"]
    assert names(run(tracker.list_titles(kind=None))) == ["Фильм", "Сериал", "Аниме"]


def test_the_filter_by_a_set_of_statuses(tracker, session_factory):
    for status in TitleStatus:
        put(session_factory, status.value, status=status)

    assert names(run(tracker.list_titles(statuses={TitleStatus.WANT}))) == ["want"]
    assert names(run(tracker.list_titles(statuses={TitleStatus.WATCHED, TitleStatus.DROPPED}))) == ["watched", "dropped"]
    assert len(run(tracker.list_titles(statuses=None))) == len(TitleStatus)  # none: every status
    assert run(tracker.list_titles(statuses=frozenset())) == []  # an empty set is no status at all


def test_without_the_archive_is_every_status_but_the_archive_ones(tracker, session_factory):
    for status in TitleStatus:
        put(session_factory, status.value, status=status)

    rows = run(tracker.list_titles(statuses=frozenset(TitleStatus) - ARCHIVE_STATUSES))

    assert names(rows) == ["want", "in_progress", "waiting", "to_finish"]


def test_kind_and_statuses_work_together(tracker, session_factory):
    put(session_factory, "Хочу фильм")
    put(session_factory, "Хочу сериал", kind=TitleKind.SERIES)
    put(session_factory, "Бросил сериал", kind=TitleKind.SERIES, status=TitleStatus.DROPPED)

    rows = run(tracker.list_titles(TitleKind.SERIES, {TitleStatus.WANT}))

    assert names(rows) == ["Хочу сериал"]


def test_newest_first_with_the_larger_number_first_when_the_moments_are_equal(tracker, session_factory):
    old = put(session_factory, "Старый", minutes=0)
    new = put(session_factory, "Новый", minutes=10)
    same_a = put(session_factory, "Тот же момент A", minutes=5)
    same_b = put(session_factory, "Тот же момент B", minutes=5)

    rows = run(tracker.list_titles(order=ListOrder.ADDED))

    assert [row.id for row in rows] == [new, same_b, same_a, old]


def test_by_name_ignores_case_and_reads_yo_as_ye(tracker, session_factory):
    for name in ("ёж", "Ель", "ежевика", "Яблоко", "Ёлка", "Е-мейл"):
        put(session_factory, name)

    rows = run(tracker.list_titles(order=ListOrder.NAME))

    # «ё» sorts as «е» and case does not count, so «ёж» comes before «ежевика» (its start) and «Ёлка» before «Ель»
    assert names(rows) == ["Е-мейл", "ёж", "ежевика", "Ёлка", "Ель", "Яблоко"]


def test_by_name_puts_digits_then_latin_then_cyrillic(tracker, session_factory):
    for name in ("Берсерк", "Zorro", "300 спартанцев", "apple", "Аватар", "2012", "Batman"):
        put(session_factory, name)

    assert names(run(tracker.list_titles(order=ListOrder.NAME))) == [
        "2012", "300 спартанцев", "apple", "Batman", "Zorro", "Аватар", "Берсерк",
    ]


def test_the_same_name_goes_by_the_smaller_number_first(tracker, session_factory):
    first = put(session_factory, "Дюна", minutes=9)
    second = put(session_factory, "дюна", minutes=1)

    assert [row.id for row in run(tracker.list_titles(order=ListOrder.NAME))] == [first, second]


def test_the_row_carries_the_poster_as_the_title_stores_it(tracker, session_factory):
    put(session_factory, "С постером", poster="/abc.jpg")
    put(session_factory, "Без постера")

    with_poster, without = run(tracker.list_titles())

    assert with_poster.poster_path == "/abc.jpg" and without.poster_path is None
    assert (with_poster.kind, with_poster.year, with_poster.status) == (TitleKind.MOVIE, None, TitleStatus.WANT)
