"""Tracker core: deleting a title wipes it completely (rows, events, queue entries) and does not disturb the rest.

Driven through the facade only: fake clock, fake sources, fake sender, in-memory SQLite. The anime case runs
on the saved real Shikimori answers.
"""

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from anime_fakes import FakeAniList, FakeShikimori
from app.tracker import sequel_events
from app.tracker.core import Tracker, UnknownEvent, UnknownKind, UnknownTitle
from app.tracker.db import create_session_factory
from app.tracker.models import (
    DeliveryItem,
    EpisodeRecord,
    Event,
    ExternalId,
    MovieRecord,
    PartRecord,
    SeasonRecord,
    SourceSnapshot,
    Title,
)
from app.tracker.seasons import Episode, Season
from app.tracker.sources.shikimori_anime import ShikimoriAnimeSource
from app.tracker.sources.tmdb_movies import MovieSnapshot
from app.tracker.sources.tmdb_sequels import CollectionPart, SequelSnapshot
from app.tracker.sources.tmdb_series import SeriesSnapshot

T0 = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
DUNE, DUNE_3 = "438631", "1170608"
ABYSS = "34599"
TITLE_TABLES = (Title, ExternalId, SeasonRecord, EpisodeRecord, PartRecord, MovieRecord, SourceSnapshot, Event, DeliveryItem)


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
        self.before_send = None  # an async hook run while a message is on its way

    async def send(self, message, actions=()):
        if self.before_send is not None:
            await self.before_send()
        self.sent.append(message)


def movie(external_id, title="Дюна", theatrical=None):
    return MovieSnapshot(
        external_id=external_id, title=title, original_title=title, year=2021, genres=[], theatrical_date=theatrical
    )


class FakeMovieSource:
    source_key = "tmdb_movie"

    def __init__(self):
        self.by_id: dict[str, MovieSnapshot] = {}
        self.on_snapshot = None  # an async hook run while the source «answers»

    async def suggest(self, query):
        return []

    async def snapshot(self, external_id):
        if self.on_snapshot is not None:
            await self.on_snapshot()
        return self.by_id.get(external_id)


class FakeSequelSource:
    source_key = "tmdb_sequels"

    def __init__(self):
        self.parts: list[CollectionPart] = []

    async def snapshot(self, external_id):
        return SequelSnapshot(own_date=date(2021, 9, 15), parts=list(self.parts))


class FakeSeriesSource:
    source_key = "tmdb_tv"

    def __init__(self, snapshot):
        self._snapshot = snapshot

    async def suggest(self, query):
        return []

    async def snapshot(self, external_id):
        return self._snapshot


def run(coro):
    return asyncio.run(coro)


SERIES = SeriesSnapshot(
    external_id="200",
    title="Идущий",
    original_title="Идущий",
    year=2026,
    genres=[],
    seasons=[
        Season(1, "Сезон 1", 3, tuple(Episode(n + 1, datetime(2026, 3, 2) + timedelta(weeks=n)) for n in range(3))),
        Season(2, "Сезон 2", 3, tuple(Episode(n + 1, datetime(2026, 9, 7) + timedelta(weeks=n)) for n in range(3))),
    ],
)


@pytest.fixture
def clock():
    return FakeClock(T0)


@pytest.fixture
def sender():
    return FakeSender()


@pytest.fixture
def movies():
    return FakeMovieSource()


@pytest.fixture
def sequels():
    return FakeSequelSource()


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def tracker(session_factory, clock, sender, movies, sequels):
    return Tracker(
        session_factory,
        clock=clock,
        sender=sender,
        sources={
            "movie": movies,
            "series": FakeSeriesSource(SERIES),
            "anime": ShikimoriAnimeSource(FakeShikimori(), FakeAniList()),
        },
        sequel_sources={"movie": sequels},
    )


def add_movie(tracker, movies, external_id=DUNE, title="Дюна", theatrical=None):
    movies.by_id[external_id] = movie(external_id, title, theatrical)
    return run(tracker.add_title("movie", external_id)).title_id


def counts(session_factory) -> dict[str, int]:
    with session_factory() as s:
        return {model.__tablename__: s.scalar(select(func.count()).select_from(model)) for model in TITLE_TABLES}


def rows_left(session_factory) -> int:
    return sum(counts(session_factory).values())


def pending_queue(session_factory) -> int:
    with session_factory() as s:
        return s.scalar(select(func.count()).select_from(DeliveryItem).where(DeliveryItem.status == "pending"))


# --- what goes -----------------------------------------------------------------------------------


def test_a_deleted_movie_leaves_no_row_of_its_own_behind(tracker, movies, session_factory):
    title_id = add_movie(tracker, movies, theatrical=date(2027, 5, 5))
    run(tracker.record_event("movie_date_announced", {"text": "x"}, "movie:1:date", title_id=title_id))
    run(tracker.deliver_pending())
    run(tracker.record_event("movie_date_moved", {"text": "y"}, "movie:1:moved", title_id=title_id))  # still unsent
    assert rows_left(session_factory) > 0

    run(tracker.delete_title(title_id))

    assert counts(session_factory) == {model.__tablename__: 0 for model in TITLE_TABLES}
    assert run(tracker.list_titles()) == []
    assert run(tracker.title_card(title_id)) is None


def test_a_deleted_series_takes_its_seasons_and_episodes_with_it(tracker, session_factory):
    title_id = run(tracker.add_title("series", "200")).title_id
    run(tracker.record_event("series_ended", {"text": "x"}, "series:1:s1:ended", title_id=title_id))
    with session_factory() as s:
        assert s.scalar(select(func.count()).select_from(EpisodeRecord)) == 6

    run(tracker.delete_title(title_id))

    assert counts(session_factory) == {model.__tablename__: 0 for model in TITLE_TABLES}


def test_a_deleted_anime_takes_its_parts_and_franchise_films_with_it(tracker, session_factory):
    title_id = run(tracker.add_title("anime", ABYSS)).title_id
    before = counts(session_factory)
    assert before["season_parts"] > 0 and before["franchise_movies"] > 0 and before["seasons"] > 0
    run(tracker.record_event("anime_movie_out", {"text": "x"}, "anime:1:movie:1", title_id=title_id))

    run(tracker.delete_title(title_id))

    assert counts(session_factory) == {model.__tablename__: 0 for model in TITLE_TABLES}


def test_the_other_titles_are_left_as_they_are(tracker, movies, session_factory):
    keep = add_movie(tracker, movies, DUNE_3, "Дюна: Часть третья")
    gone = add_movie(tracker, movies, DUNE)
    run(tracker.record_event("movie_released", {"text": "keep"}, "keep", title_id=keep))
    run(tracker.record_event("movie_released", {"text": "gone"}, "gone", title_id=gone))
    run(tracker.record_event("test", {"text": "no title"}, "ping"))

    run(tracker.delete_title(gone))

    assert [t.id for t in run(tracker.list_titles())] == [keep]
    with session_factory() as s:
        assert sorted(s.scalars(select(Event.dedup_key))) == ["keep", "ping"]
        assert s.scalar(select(func.count()).select_from(DeliveryItem)) == 2


def test_deleting_says_which_title_went(tracker, movies):
    title_id = add_movie(tracker, movies)

    result = run(tracker.delete_title(title_id))

    assert result.name == "Дюна"


def test_deleting_a_title_that_is_not_there_is_an_error_and_changes_nothing(tracker, movies, session_factory):
    keep = add_movie(tracker, movies)
    run(tracker.record_event("movie_released", {"text": "keep"}, "keep", title_id=keep))
    before = counts(session_factory)

    with pytest.raises(UnknownTitle):
        run(tracker.delete_title(999))
    with pytest.raises(UnknownTitle):
        run(tracker.delete_title(keep + 1))

    assert counts(session_factory) == before


def test_deleting_twice_is_an_error_the_second_time(tracker, movies):
    title_id = add_movie(tracker, movies)
    run(tracker.delete_title(title_id))

    with pytest.raises(UnknownTitle):
        run(tracker.delete_title(title_id))


# --- what is still in the queue ------------------------------------------------------------------


def test_an_unsent_event_of_a_deleted_title_never_reaches_the_owner(tracker, movies, sender):
    title_id = add_movie(tracker, movies)
    run(tracker.record_event("movie_released", {"text": "🎬 Дюна — вышел в кино"}, "k", title_id=title_id))

    run(tracker.delete_title(title_id))
    report = run(tracker.deliver_pending())
    digest = run(tracker.digest_now())

    assert sender.sent == []
    assert (report.delivered, report.failed) == (0, 0)
    assert (digest.events, digest.delivered) == (0, False)


def test_a_new_title_with_the_number_of_a_deleted_one_gets_its_own_events(tracker, movies, sender, clock):
    first = add_movie(tracker, movies)
    movies.by_id[DUNE] = movie(DUNE, theatrical=date(2027, 5, 5))
    clock.advance(days=1)
    run(tracker.poll_due())
    run(tracker.deliver_pending())
    assert len(sender.sent) == 1
    run(tracker.delete_title(first))

    second = add_movie(tracker, movies)  # the same movie again: no marks and no past events
    assert second == first  # SQLite hands out the number of the row that was just deleted
    movies.by_id[DUNE] = movie(DUNE, theatrical=date(2027, 5, 5))
    clock.advance(days=1)
    run(tracker.poll_due())
    run(tracker.deliver_pending())

    assert len(sender.sent) == 2  # the old dedup key did not silence the new title
    assert [t.status for t in run(tracker.list_titles())] == ["want"]


def test_adding_a_deleted_title_again_starts_from_scratch(tracker, movies):
    title_id = add_movie(tracker, movies)
    run(tracker.mark_watched(title_id))
    run(tracker.delete_title(title_id))

    again = run(tracker.add_title("movie", DUNE))

    assert again.created is True
    assert run(tracker.title_card(again.title_id)).status == "want"


def test_an_event_cannot_be_recorded_for_a_title_that_is_gone(tracker, session_factory):
    assert run(tracker.record_event("movie_released", {"text": "x"}, "orphan", title_id=999)) is None

    assert rows_left(session_factory) == 0


def test_the_database_itself_refuses_an_event_of_a_title_that_does_not_exist(session_factory):
    with session_factory() as s:
        s.add(Event(type="x", title_id=999, payload={}, dedup_key="k", detected_at=T0.replace(tzinfo=None)))
        with pytest.raises(IntegrityError):
            s.commit()


def test_the_database_itself_removes_the_events_and_queue_of_a_deleted_title(tracker, movies, session_factory):
    title_id = add_movie(tracker, movies)
    run(tracker.record_event("movie_released", {"text": "x"}, "k1", title_id=title_id))
    with session_factory() as s:
        s.execute(delete(Title).where(Title.id == title_id))  # no help from the core
        s.commit()

    assert rows_left(session_factory) == 0


def test_an_event_without_a_title_is_allowed(tracker, session_factory):
    assert run(tracker.record_event("ping", {"text": "x"}, "k2")) is not None


# --- the sequel announcement ---------------------------------------------------------------------


def announce_sequel(tracker, movies, sequels, clock):
    title_id = add_movie(tracker, movies)
    run(tracker.mark_watched(title_id))
    run(tracker.poll_due())  # the first look at the collection
    sequels.parts = [CollectionPart(DUNE_3, "Дюна: Часть третья", date(2026, 12, 15))]
    movies.by_id[DUNE_3] = movie(DUNE_3, "Дюна: Часть третья", date(2026, 12, 15))
    clock.advance(days=7)
    run(tracker.poll_due())
    return title_id


def sequel_event_id(session_factory):
    with session_factory() as s:
        return s.scalar(select(Event.id).where(Event.type == sequel_events.SEQUEL_ANNOUNCED))


def test_a_title_followed_from_an_announcement_stays_after_the_original_is_deleted(
    tracker, movies, sequels, clock, session_factory
):
    original = announce_sequel(tracker, movies, sequels, clock)
    run(tracker.deliver_pending())
    followed = run(tracker.follow_sequel(sequel_event_id(session_factory))).title_id

    run(tracker.delete_title(original))

    assert [t.id for t in run(tracker.list_titles())] == [followed]
    assert run(tracker.title_card(followed)).title == "Дюна: Часть третья"
    assert run(tracker.title_card(followed)).status == "want"


def test_a_delivered_announcement_goes_with_the_film_and_leaves_no_event_or_queue_entry(
    tracker, movies, sequels, clock, session_factory
):
    original = announce_sequel(tracker, movies, sequels, clock)
    run(tracker.deliver_pending())

    run(tracker.delete_title(original))

    assert rows_left(session_factory) == 0


def test_the_follow_button_under_an_old_announcement_still_works_after_the_film_is_deleted(
    tracker, movies, sequels, clock, session_factory
):
    original = announce_sequel(tracker, movies, sequels, clock)
    run(tracker.deliver_pending())

    run(tracker.delete_title(original))
    result = run(tracker.follow_sequel_of("movie", DUNE_3))  # the button carries the kind and the id, not the event

    assert result.created is True
    assert [t.name for t in run(tracker.list_titles())] == ["Дюна: Часть третья"]


def test_the_old_kind_of_follow_button_needs_its_event_and_says_so_when_it_is_gone(
    tracker, movies, sequels, clock, session_factory
):
    original = announce_sequel(tracker, movies, sequels, clock)
    run(tracker.deliver_pending())
    event_id = sequel_event_id(session_factory)
    assert run(tracker.follow_sequel(event_id)).created is True  # works while the event is there

    run(tracker.delete_title(original))

    with pytest.raises(UnknownEvent):
        run(tracker.follow_sequel(event_id))


def test_following_a_kind_nobody_announces_sequels_for_is_refused(tracker):
    with pytest.raises(UnknownKind):
        run(tracker.follow_sequel_of("game", "1"))


def test_an_announcement_nobody_has_seen_goes_with_the_film(tracker, movies, sequels, clock, session_factory):
    original = announce_sequel(tracker, movies, sequels, clock)  # queued, not delivered
    event_id = sequel_event_id(session_factory)
    assert pending_queue(session_factory) == 1

    run(tracker.delete_title(original))
    run(tracker.deliver_pending())

    with pytest.raises(UnknownEvent):
        run(tracker.follow_sequel(event_id))
    assert rows_left(session_factory) == 0


def test_a_film_deleted_and_added_again_can_announce_the_same_sequel_again(
    tracker, movies, sequels, clock, sender, session_factory
):
    original = announce_sequel(tracker, movies, sequels, clock)
    run(tracker.deliver_pending())
    run(tracker.delete_title(original))
    sequels.parts = []

    again = announce_sequel_again(tracker, movies, sequels, clock)

    assert again == original
    run(tracker.deliver_pending())
    assert sum("Анонсировано продолжение" in text for text in sender.sent) == 2


def announce_sequel_again(tracker, movies, sequels, clock):
    title_id = add_movie(tracker, movies)
    run(tracker.mark_watched(title_id))
    sequels.parts = []
    run(tracker.poll_due())
    sequels.parts = [CollectionPart(DUNE_3, "Дюна: Часть третья", date(2026, 12, 15))]
    clock.advance(days=7)
    run(tracker.poll_due())
    return title_id


# --- at the same time as the poll and the delivery ----------------------------------------------


def test_deleting_a_title_while_it_is_polled_does_not_break_the_poll(tracker, movies, clock, session_factory, caplog):
    keep = add_movie(tracker, movies, DUNE_3, "Дюна: Часть третья")
    gone = add_movie(tracker, movies)
    movies.by_id[DUNE] = movie(DUNE, theatrical=date(2027, 5, 5))
    movies.by_id[DUNE_3] = movie(DUNE_3, "Дюна: Часть третья", date(2027, 6, 6))
    clock.advance(days=1)

    async def delete_while_answering():
        movies.on_snapshot = None
        await tracker.delete_title(gone)

    movies.on_snapshot = delete_while_answering
    with caplog.at_level(logging.WARNING):
        report = run(tracker.poll_due())

    assert report.failed == 0 and report.notices == 0
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
    assert [t.id for t in run(tracker.list_titles())] == [keep]
    with session_factory() as s:
        assert {e.title_id for e in s.scalars(select(Event))} <= {keep}


def test_a_title_deleted_after_its_answer_came_leaves_nothing_behind(tracker, movies, clock, session_factory, caplog):
    gone = add_movie(tracker, movies)
    movies.by_id[DUNE] = movie(DUNE, theatrical=date(2027, 5, 5))
    clock.advance(days=1)
    original = tracker._apply_snapshot

    def apply_after_deleting(due, snapshot):
        run_in_loop = asyncio.new_event_loop()
        try:
            run_in_loop.run_until_complete(tracker.delete_title(gone))
        finally:
            run_in_loop.close()
        return original(due, snapshot)

    tracker._apply_snapshot = apply_after_deleting
    with caplog.at_level(logging.WARNING):
        report = run(tracker.poll_due())

    assert report.failed == 0 and report.notices == 0
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
    assert rows_left(session_factory) == 0


def test_deleting_a_title_while_a_message_is_on_its_way_does_not_break_the_delivery(
    tracker, movies, sender, session_factory, caplog
):
    gone = add_movie(tracker, movies)
    other = add_movie(tracker, movies, DUNE_3, "Дюна: Часть третья")
    run(tracker.record_event("movie_released", {"text": "first"}, "a", title_id=gone))
    run(tracker.record_event("movie_released", {"text": "second"}, "b", title_id=other))

    async def delete_during_send():
        sender.before_send = None
        await tracker.delete_title(gone)

    sender.before_send = delete_during_send
    with caplog.at_level(logging.WARNING):
        report = run(tracker.deliver_pending())

    assert report.failed == 0
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
    assert [t.id for t in run(tracker.list_titles())] == [other]
    with session_factory() as s:
        assert [e.dedup_key for e in s.scalars(select(Event))] == ["b"]
