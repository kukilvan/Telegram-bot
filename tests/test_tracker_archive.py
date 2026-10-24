"""Tracker core: «Посмотрел» moves a movie to the archive; the archive is checked weekly for sequels.

Driven through the facade only: fake clock, fake movie and sequel sources, fake sender, in-memory SQLite.
"""

import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.tracker.actions import CARD, FOLLOW, WATCHED, card_actions
from app.tracker.core import Tracker, UnknownEvent, UnknownTitle
from app.tracker.db import create_session_factory
from app.tracker.models import Event, SourceSnapshot, Title
from app.tracker.sources.tmdb_movies import MovieSnapshot
from app.tracker.sources.tmdb_sequels import CollectionPart, SequelSnapshot

T0 = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
DUNE = "438631"
PART_TWO = CollectionPart("693134", "Дюна: Часть вторая", date(2024, 2, 27))
PART_THREE = CollectionPart("1170608", "Дюна: Часть третья", date(2026, 12, 15))


class FakeClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, **delta):
        self.now += timedelta(**delta)


class FakeSender:
    def __init__(self):
        self.sent: list[str] = []
        self.actions: list[tuple] = []

    async def send(self, message, actions=()):
        self.sent.append(message)
        self.actions.append(tuple(actions))


def movie(external_id, title="Дюна", theatrical=None):
    return MovieSnapshot(
        external_id=external_id, title=title, original_title=title, year=2021, genres=[], theatrical_date=theatrical
    )


class FakeMovieSource:
    source_key = "tmdb_movie"

    def __init__(self):
        self.by_id = {}
        self.calls: list[str] = []

    def update(self, snapshot):
        self.by_id[snapshot.external_id] = snapshot

    async def suggest(self, query):
        return []

    async def snapshot(self, external_id):
        self.calls.append(external_id)
        return self.by_id.get(external_id)


class FakeSequelSource:
    source_key = "tmdb_sequels"

    def __init__(self):
        self.by_id: dict[str, SequelSnapshot] = {}
        self.failing: set[str] = set()
        self.calls: list[str] = []

    def set(self, external_id, *parts, own_date=date(2021, 9, 15)):
        self.by_id[external_id] = SequelSnapshot(own_date=own_date, parts=list(parts))

    async def snapshot(self, external_id):
        self.calls.append(external_id)
        if external_id in self.failing:
            raise ConnectionError("tmdb is down")
        return self.by_id.get(external_id)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def clock():
    return FakeClock(T0)


@pytest.fixture
def sender():
    return FakeSender()


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def source():
    return FakeMovieSource()


@pytest.fixture
def sequels():
    return FakeSequelSource()


@pytest.fixture
def tracker(session_factory, clock, sender, source, sequels):
    return Tracker(
        session_factory, clock=clock, sender=sender, sources={"movie": source}, sequel_sources={"movie": sequels}
    )


def add(tracker, source, snapshot):
    source.update(snapshot)
    return run(tracker.add_title("movie", snapshot.external_id)).title_id


def archive(tracker, source, sequels, *parts, external_id=DUNE, title="Дюна"):
    """Add a movie, mark it watched and let the first check record what its collection already holds."""
    title_id = add(tracker, source, movie(external_id, title=title))
    sequels.set(external_id, *parts)
    run(tracker.mark_watched(title_id))
    run(tracker.poll_due())
    return title_id


def week_later(tracker, clock, days=7):
    clock.advance(days=days)
    run(tracker.poll_due())
    run(tracker.deliver_pending())


def status_of(session_factory, title_id):
    with session_factory() as s:
        return s.get(Title, title_id).status


def next_check(session_factory, title_id, source_key):
    with session_factory() as s:
        return s.scalar(
            select(SourceSnapshot.next_check_at).where(
                SourceSnapshot.title_id == title_id, SourceSnapshot.source == source_key
            )
        )


# --- «Посмотрел» ---------------------------------------------------------------------------------


def test_marking_watched_changes_the_status_shown_in_the_list_and_the_card(tracker, source):
    title_id = add(tracker, source, movie(DUNE))

    result = run(tracker.mark_watched(title_id))

    assert result.changed is True
    assert [t.status for t in tracker.list_titles()] == ["watched"]
    assert tracker.title_card(title_id).status == "watched"


def test_marking_watched_twice_changes_nothing_the_second_time(tracker, source, clock, session_factory):
    title_id = add(tracker, source, movie(DUNE))
    run(tracker.mark_watched(title_id))
    clock.advance(days=1)

    result = run(tracker.mark_watched(title_id))

    assert result.changed is False
    with session_factory() as s:
        assert s.get(Title, title_id).status_changed_at == T0.replace(tzinfo=None)


def test_marking_an_unknown_title_watched_is_an_error(tracker):
    with pytest.raises(UnknownTitle):
        run(tracker.mark_watched(999))


def test_the_card_of_a_watched_movie_still_shows_its_dates(tracker, source):
    title_id = add(tracker, source, movie(DUNE, theatrical=date(2021, 9, 15)))
    run(tracker.mark_watched(title_id))

    assert tracker.title_card(title_id).theatrical_date == date(2021, 9, 15)


def test_the_card_offers_watched_only_while_the_movie_is_wanted(tracker, source):
    title_id = add(tracker, source, movie(DUNE))
    assert [(a.name, a.arg) for a in card_actions(tracker.title_card(title_id))] == [(WATCHED, title_id)]

    run(tracker.mark_watched(title_id))

    assert card_actions(tracker.title_card(title_id)) == []


# --- the archive is not checked for its own release ----------------------------------------------


def test_a_watched_movie_is_not_polled_for_its_own_release(tracker, source, sequels, clock, sender):
    title_id = add(tracker, source, movie(DUNE))
    sequels.set(DUNE)
    run(tracker.mark_watched(title_id))
    source.calls.clear()
    source.update(movie(DUNE, theatrical=date(2026, 12, 16)))  # a date that would be news for a wanted movie

    week_later(tracker, clock, days=30)

    assert source.calls == []
    assert sender.sent == []


def test_a_wanted_movie_is_not_checked_for_sequels(tracker, source, sequels, clock):
    add(tracker, source, movie(DUNE))
    sequels.set(DUNE, PART_THREE)

    week_later(tracker, clock, days=30)

    assert sequels.calls == []


# --- the weekly check for sequels ----------------------------------------------------------------


def test_sequels_already_in_the_collection_when_archiving_are_not_news(tracker, source, sequels, clock, sender):
    archive(tracker, source, sequels, PART_TWO, PART_THREE)

    week_later(tracker, clock)

    assert sender.sent == []


def test_a_new_sequel_in_the_collection_is_announced_once(tracker, source, sequels, clock, sender):
    archive(tracker, source, sequels, PART_TWO)
    sequels.set(DUNE, PART_TWO, PART_THREE)

    week_later(tracker, clock)
    week_later(tracker, clock)

    [message] = sender.sent
    assert "Анонсировано продолжение: Дюна: Часть третья" in message
    assert "«Дюна»" in message
    assert "15 декабря 2026" in message


def test_a_sequel_without_a_date_is_announced_with_an_unannounced_date(tracker, source, sequels, clock, sender):
    archive(tracker, source, sequels)
    sequels.set(DUNE, CollectionPart("9", "Дюна: Мессия", None))

    week_later(tracker, clock)

    [message] = sender.sent
    assert "Дюна: Мессия" in message
    assert "не объявлена" in message


def test_a_movie_that_joins_a_collection_later_gets_its_sequel_announced(tracker, source, sequels, clock, sender):
    archive(tracker, source, sequels)  # stood alone when archived
    sequels.set(DUNE, PART_THREE)  # TMDb created a collection after the sequel was announced

    week_later(tracker, clock)

    assert len(sender.sent) == 1


def test_an_earlier_movie_of_the_collection_is_not_a_sequel(tracker, source, sequels, clock, sender):
    archive(tracker, source, sequels)
    sequels.set(DUNE, CollectionPart("1", "Дюна (1984)", date(1984, 12, 14)))

    week_later(tracker, clock)

    assert sender.sent == []


def test_a_part_the_collection_drops_and_returns_is_not_announced_twice(tracker, source, sequels, clock, sender):
    archive(tracker, source, sequels)
    sequels.set(DUNE, PART_THREE)
    week_later(tracker, clock)
    sequels.set(DUNE)  # the collection lost it for a moment
    week_later(tracker, clock)
    sequels.set(DUNE, PART_THREE)

    week_later(tracker, clock)

    assert len(sender.sent) == 1


def test_the_announcement_offers_to_follow_the_sequel_and_not_to_mark_watched(tracker, source, sequels, clock, sender):
    archive(tracker, source, sequels)
    sequels.set(DUNE, PART_THREE)

    week_later(tracker, clock)

    [actions] = sender.actions
    assert [a.name for a in actions] == [FOLLOW]


def test_movie_event_messages_offer_watched_and_the_card_for_their_movie(tracker, source, clock, sender):
    title_id = add(tracker, source, movie(DUNE))
    source.update(movie(DUNE, theatrical=date(2027, 5, 5)))

    clock.advance(days=2)
    run(tracker.poll_due())
    run(tracker.deliver_pending())

    [actions] = sender.actions
    assert [(a.name, a.arg) for a in actions] == [(WATCHED, title_id), (CARD, title_id)]


def test_test_events_have_no_buttons(tracker, sender):
    run(tracker.send_test_event("ping"))

    assert sender.actions == [()]


def test_an_archived_movie_is_checked_once_a_week(tracker, source, sequels, clock, session_factory):
    title_id = archive(tracker, source, sequels)

    assert next_check(session_factory, title_id, "tmdb_sequels") == clock().replace(tzinfo=None) + timedelta(days=7)
    sequels.calls.clear()
    clock.advance(days=6)
    run(tracker.poll_due())
    assert sequels.calls == []

    clock.advance(days=1)
    run(tracker.poll_due())
    assert sequels.calls == [DUNE]


def test_marking_watched_schedules_the_first_check_right_away(tracker, source, sequels, clock):
    title_id = add(tracker, source, movie(DUNE))
    sequels.set(DUNE)
    run(tracker.mark_watched(title_id))

    run(tracker.poll_due())

    assert sequels.calls == [DUNE]


def test_a_failing_sequel_check_is_postponed_and_the_other_movies_are_still_checked(
    tracker, source, sequels, clock, sender, session_factory
):
    bad = archive(tracker, source, sequels, external_id="1", title="Сбойный")
    archive(tracker, source, sequels, external_id="2", title="Рабочий")
    sequels.failing.add("1")
    sequels.set("2", PART_THREE)
    clock.advance(days=7)

    report = run(tracker.poll_due())
    run(tracker.deliver_pending())

    assert (report.failed, report.polled) == (1, 1)
    assert len(sender.sent) == 1
    assert next_check(session_factory, bad, "tmdb_sequels") == clock().replace(tzinfo=None) + timedelta(minutes=30)


def test_one_sequel_of_a_franchise_is_announced_once_however_many_of_its_movies_are_archived(
    tracker, source, sequels, clock, sender
):
    archive(tracker, source, sequels, external_id="1", title="Первая часть")
    archive(tracker, source, sequels, external_id="2", title="Вторая часть")
    sequels.set("1", PART_THREE)
    sequels.set("2", PART_THREE)

    week_later(tracker, clock)

    assert len(sender.sent) == 1


def test_a_sequel_the_owner_already_follows_is_not_announced(tracker, source, sequels, clock, sender):
    archive(tracker, source, sequels)
    add(tracker, source, movie(PART_THREE.external_id, title="Дюна: Часть третья"))
    sequels.set(DUNE, PART_THREE)

    week_later(tracker, clock)

    assert sender.sent == []


def test_a_movie_without_a_sequel_source_is_archived_and_never_checked(session_factory, clock, sender, source):
    tracker = Tracker(session_factory, clock=clock, sender=sender, sources={"movie": source})
    title_id = add(tracker, source, movie(DUNE))

    run(tracker.mark_watched(title_id))
    clock.advance(days=30)
    report = run(tracker.poll_due())

    assert report.failed == 0
    assert tracker.title_card(title_id).status == "watched"


# --- «Следить» -----------------------------------------------------------------------------------


def announce(tracker, source, sequels, clock, sender, *parts):
    archive(tracker, source, sequels)
    sequels.set(DUNE, *parts)
    week_later(tracker, clock)
    with tracker.session_factory() as s:
        return s.scalars(select(Event.id).where(Event.type == "movie_sequel_announced")).first()


def test_nothing_is_added_to_the_list_until_the_owner_follows(tracker, source, sequels, clock, sender):
    announce(tracker, source, sequels, clock, sender, PART_THREE)

    assert [t.name for t in tracker.list_titles()] == ["Дюна"]


def test_following_a_sequel_adds_it_as_wanted(tracker, source, sequels, clock, sender):
    event_id = announce(tracker, source, sequels, clock, sender, PART_THREE)
    source.update(movie(PART_THREE.external_id, title="Дюна: Часть третья", theatrical=date(2026, 12, 15)))

    result = run(tracker.follow_sequel(event_id))

    assert result.created is True
    assert [(t.name, t.status) for t in tracker.list_titles()] == [("Дюна", "watched"), ("Дюна: Часть третья", "want")]


def test_following_twice_opens_the_title_instead_of_adding_a_second_one(tracker, source, sequels, clock, sender):
    event_id = announce(tracker, source, sequels, clock, sender, PART_THREE)
    source.update(movie(PART_THREE.external_id, title="Дюна: Часть третья"))
    first = run(tracker.follow_sequel(event_id))

    second = run(tracker.follow_sequel(event_id))

    assert second.created is False
    assert second.title_id == first.title_id
    assert len(tracker.list_titles()) == 2


def test_the_followed_sequel_is_polled_like_any_wanted_movie(tracker, source, sequels, clock, sender):
    event_id = announce(tracker, source, sequels, clock, sender, PART_THREE)
    source.update(movie(PART_THREE.external_id, title="Дюна: Часть третья"))
    run(tracker.follow_sequel(event_id))
    sender.sent.clear()
    source.update(movie(PART_THREE.external_id, title="Дюна: Часть третья", theatrical=date(2026, 12, 16)))

    clock.advance(days=2)
    run(tracker.poll_due())
    run(tracker.deliver_pending())

    assert any("объявлена дата премьеры" in m for m in sender.sent)


def test_following_an_unknown_event_is_an_error(tracker):
    with pytest.raises(UnknownEvent):
        run(tracker.follow_sequel(999))


def test_only_a_sequel_announcement_can_be_followed(tracker, source, sender):
    run(tracker.send_test_event("ping"))
    with tracker.session_factory() as s:
        test_event_id = s.scalars(select(Event.id)).first()

    with pytest.raises(UnknownEvent):
        run(tracker.follow_sequel(test_event_id))


# --- the owner's test-event button ---------------------------------------------------------------


def test_the_sequel_announcement_is_in_the_test_event_menu(tracker, sender):
    assert "movie-sequel" in [k.id for k in tracker.test_event_kinds()]

    result = run(tracker.send_test_event("movie-sequel"))

    assert result.delivered is True
    assert "Анонсировано продолжение" in sender.sent[0]
