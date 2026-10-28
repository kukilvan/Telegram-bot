"""Tracker core: «Бросил», «Вернуть в список» and the silent first check after the return.

Driven through the facade only: fake clock, fake movie, series and sequel sources, the real Shikimori adapter over the
saved answers for anime, fake sender, in-memory SQLite. No network.
"""

import asyncio
import logging
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from anime_fakes import FakeShikimori, real_anilist
from app.tracker import failures, movie_events, series_events
from app.tracker.core import Tracker, UnknownTitle
from app.tracker.db import create_session_factory
from app.tracker.models import DeliveryItem, DeliveryStatus, Event, SourceSnapshot, Title, TitleStatus
from app.tracker.seasons import Episode, Season
from app.tracker.sources.shikimori_anime import ShikimoriAnimeSource
from app.tracker.sources.tmdb_movies import MovieSnapshot
from app.tracker.sources.tmdb_sequels import CollectionPart, SequelSnapshot
from app.tracker.sources.tmdb_series import SeriesSnapshot
from season_helpers import season_id

T0 = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
JJK, JJK_4 = "40748", "63824"
PART_THREE = CollectionPart("1170608", "Дюна: Часть третья", date(2028, 12, 15))
PART_FOUR = CollectionPart("1300000", "Дюна: Часть четвёртая", None)


def weekly(first_day, count):
    start = datetime.fromisoformat(first_day)
    return tuple(Episode(n + 1, start + timedelta(weeks=n)) for n in range(count))


DUNE = MovieSnapshot(external_id="1", name="Дюна", original_name="Dune", year=2021, genres=[])
# eight episodes a week apart from Monday 5 Oct 2026: three are out at T0
AIRING = SeriesSnapshot(
    external_id="10", name="Идущий", original_name="Running", year=2026, genres=[],
    seasons=[Season(1, "Сезон 1", 8, weekly("2026-10-05", 8))],
)
ENDED = SeriesSnapshot(
    external_id="11", name="Закрытый", original_name="Closed", year=2020, genres=[],
    seasons=[Season(1, "Сезон 1", 6, weekly("2020-01-06", 6)), Season(2, "Сезон 2", 6, weekly("2021-01-04", 6))],
    status="Ended",
)


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

    async def send(self, message, actions=()):
        self.sent.append(message)


class FakeSource:
    def __init__(self, key, *snapshots):
        self.source_key = key
        self.by_id = {s.external_id: s for s in snapshots}
        self.calls: list[str] = []
        self.failing = False

    def update(self, snapshot):
        self.by_id[snapshot.external_id] = snapshot

    async def suggest(self, query):
        return []

    async def snapshot(self, external_id):
        self.calls.append(external_id)
        if self.failing:
            raise ConnectionError("the source is down")
        return self.by_id.get(external_id)


class FakeSequelSource:
    source_key = "tmdb_sequels"

    def __init__(self):
        self.parts: list[CollectionPart] = []
        self.calls: list[str] = []

    async def snapshot(self, external_id):
        self.calls.append(external_id)
        return SequelSnapshot(own_date=date(2021, 9, 15), parts=list(self.parts))


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
def movies():
    return FakeSource("tmdb_movie", DUNE)


@pytest.fixture
def shows():
    return FakeSource("tmdb_tv", AIRING, ENDED)


@pytest.fixture
def sequels():
    return FakeSequelSource()


@pytest.fixture
def shikimori():
    return FakeShikimori()


@pytest.fixture
def anilist():
    return real_anilist()


@pytest.fixture
def tracker(session_factory, clock, sender, movies, shows, sequels, shikimori, anilist):
    return Tracker(
        session_factory, clock=clock, sender=sender,
        sources={"movie": movies, "series": shows, "anime": ShikimoriAnimeSource(shikimori, anilist)},
        sequel_sources={"movie": sequels},
    )


def add(tracker, kind, external_id):
    return run(tracker.add_title(kind, external_id)).title_id


def title(session_factory, title_id):
    with session_factory() as session:
        return session.get(Title, title_id)


def snapshots(session_factory, title_id):
    with session_factory() as session:
        return {s.source: s for s in session.scalars(select(SourceSnapshot).where(SourceSnapshot.title_id == title_id))}


def event_types(session_factory, title_id):
    with session_factory() as session:
        return list(session.scalars(select(Event.type).where(Event.title_id == title_id).order_by(Event.id)))


def queue(session_factory):
    with session_factory() as session:
        return [(item.event_id, item.status) for item in session.scalars(select(DeliveryItem).order_by(DeliveryItem.id))]


def set_status(session_factory, title_id, status):
    with session_factory() as session:
        session.execute(update(Title).where(Title.id == title_id).values(status=status))
        session.commit()


def poll(tracker, clock, **advance):
    clock.advance(**advance)
    return run(tracker.poll_due())


# ---- «Бросил» --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("status", [s for s in TitleStatus if s != TitleStatus.DROPPED])
def test_dropped_from_any_status_goes_to_the_archive_and_stops_tracking(tracker, session_factory, clock, status):
    series = add(tracker, "series", "10")
    set_status(session_factory, series, status)
    clock.advance(hours=1)

    assert run(tracker.mark_dropped(series)).changed is True

    stored = title(session_factory, series)
    assert (stored.status, stored.tracking_enabled) == (TitleStatus.DROPPED, False)
    assert stored.status_changed_at == clock.now.replace(tzinfo=None)


def test_dropped_twice_changes_nothing(tracker, session_factory, clock):
    film = add(tracker, "movie", "1")
    run(tracker.mark_dropped(film))
    first = title(session_factory, film).status_changed_at
    clock.advance(hours=1)

    assert run(tracker.mark_dropped(film)).changed is False
    assert title(session_factory, film).status_changed_at == first


def test_dropped_of_a_title_that_is_not_there_is_unknown(tracker):
    with pytest.raises(UnknownTitle):
        run(tracker.mark_dropped(999))


def test_a_dropped_title_is_not_checked_any_more(tracker, movies, shows, clock):
    film, series = add(tracker, "movie", "1"), add(tracker, "series", "10")
    run(tracker.mark_dropped(film))
    run(tracker.mark_dropped(series))

    poll(tracker, clock, days=30)

    assert movies.calls == ["1"] and shows.calls == ["10"]  # only the snapshots taken when they were added


def test_a_dropped_watched_movie_loses_its_sequel_check(tracker, session_factory, sequels, clock):
    film = add(tracker, "movie", "1")
    run(tracker.mark_watched(film))
    poll(tracker, clock)  # the first look at the collection
    assert "tmdb_sequels" in snapshots(session_factory, film)

    run(tracker.mark_dropped(film))
    poll(tracker, clock, days=8)

    assert set(snapshots(session_factory, film)) == {"tmdb_movie"} and sequels.calls == ["1"]


def test_marks_of_a_dropped_series_are_kept_and_its_status_stays(tracker, session_factory):
    ended = add(tracker, "series", "11")
    run(tracker.mark_dropped(ended))

    run(tracker.set_season_watched(ended, season_id(tracker, ended, 1), True))
    assert title(session_factory, ended).status == TitleStatus.DROPPED
    run(tracker.toggle_season(ended, season_id(tracker, ended, 2)))
    assert title(session_factory, ended).status == TitleStatus.DROPPED  # closed and all marked: still not «Просмотрено»
    run(tracker.set_season_watched(ended, season_id(tracker, ended, 2), False))
    assert run(tracker.mark_all_released(ended)).changed is True

    stored = title(session_factory, ended)
    assert (stored.status, stored.tracking_enabled) == (TitleStatus.DROPPED, False)
    assert run(tracker.title_card(ended)).seasons.watched == (1, 2)


def test_dropped_takes_the_titles_undelivered_messages_out_of_the_queue_and_keeps_the_events(
    tracker, session_factory, movies, clock
):
    film, other = add(tracker, "movie", "1"), add(tracker, "series", "10")
    sent_before = run(tracker.record_event("x", {"text": "ушло"}, "k:sent", title_id=film))
    run(tracker.deliver_pending())
    movies.update(replace(DUNE, theatrical_date=date(2027, 3, 12)))
    poll(tracker, clock, days=2)  # «объявлена дата» waits in the queue
    movies.failing = True
    poll(tracker, clock, days=2)  # and so does «не удалось проверить»
    others = run(tracker.record_event("x", {"text": "чужое"}, "k:other", title_id=other))
    assert event_types(session_factory, film)[-2:] == [movie_events.DATE_ANNOUNCED, failures.SOURCE_FAILED]

    run(tracker.mark_dropped(film))

    left = queue(session_factory)
    with session_factory() as session:
        of_film = set(session.scalars(select(Event.id).where(Event.title_id == film)))
    assert [entry for entry in left if entry[0] in of_film] == [(sent_before, DeliveryStatus.DELIVERED)]
    assert (others, DeliveryStatus.PENDING) in left  # another title's messages stay
    assert event_types(session_factory, film) == ["x", movie_events.DATE_ANNOUNCED, failures.SOURCE_FAILED]


def test_a_fact_whose_message_was_dropped_does_not_come_after_the_return(tracker, session_factory, movies, sender, clock):
    film = add(tracker, "movie", "1")
    announced = replace(DUNE, theatrical_date=date(2027, 3, 12))
    movies.update(announced)
    poll(tracker, clock, days=2)
    run(tracker.mark_dropped(film))

    run(tracker.restore_title(film))
    poll(tracker, clock)  # the silent first check
    poll(tracker, clock, days=8)
    run(tracker.deliver_pending())

    assert sender.sent == []
    assert event_types(session_factory, film) == [movie_events.DATE_ANNOUNCED]  # its key keeps the fact known
    with session_factory() as session:
        key = session.scalar(select(Event.dedup_key).where(Event.title_id == film))
    assert run(tracker.record_event(movie_events.DATE_ANNOUNCED, {"text": "снова"}, key, title_id=film)) is None


def test_the_list_still_has_the_dropped_title_with_its_status(tracker):
    film = add(tracker, "movie", "1")
    run(tracker.mark_dropped(film))

    [row] = run(tracker.list_titles())
    assert (row.id, row.status) == (film, TitleStatus.DROPPED)
    assert run(tracker.title_card(film)).status == TitleStatus.DROPPED


def test_watched_on_a_dropped_movie_makes_it_watched_and_starts_the_sequel_check(tracker, session_factory, sequels, clock):
    film = add(tracker, "movie", "1")
    run(tracker.mark_dropped(film))

    assert run(tracker.mark_watched(film)).changed is True  # the old «Посмотрел» under a message: the last press wins

    assert title(session_factory, film).status == TitleStatus.WATCHED
    poll(tracker, clock)
    assert sequels.calls == ["1"]


# ---- «Вернуть в список» ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("archive", ["mark_watched", "mark_dropped"])
def test_a_movie_comes_back_wanted_and_followed_with_its_check_due_now(tracker, session_factory, clock, archive):
    film = add(tracker, "movie", "1")
    run(getattr(tracker, archive)(film))
    poll(tracker, clock)
    clock.advance(days=3)

    assert run(tracker.restore_title(film)).changed is True

    now = clock.now.replace(tzinfo=None)
    stored = title(session_factory, film)
    assert (stored.status, stored.tracking_enabled) == (TitleStatus.WANT, True)
    assert stored.restored_at == now and stored.status_changed_at == now
    shots = snapshots(session_factory, film)
    assert set(shots) == {"tmdb_movie"} and shots["tmdb_movie"].next_check_at == now


def test_a_dropped_series_comes_back_with_the_status_its_marks_give(tracker, session_factory):
    series = add(tracker, "series", "10")
    run(tracker.set_season_watched(series, season_id(tracker, series, 1), True))
    run(tracker.mark_dropped(series))

    assert run(tracker.restore_title(series)).changed is True

    stored = title(session_factory, series)
    assert (stored.status, stored.tracking_enabled) == (TitleStatus.WAITING, True)  # all that is out is marked


def test_a_dropped_closed_series_with_every_season_marked_comes_back_watched(tracker, session_factory):
    ended = add(tracker, "series", "11")
    run(tracker.mark_dropped(ended))
    run(tracker.mark_all_released(ended))

    assert run(tracker.restore_title(ended)).changed is True

    stored = title(session_factory, ended)
    assert (stored.status, stored.tracking_enabled) == (TitleStatus.WATCHED, False)


def test_a_dropped_series_without_marks_comes_back_wanted(tracker, session_factory):
    series = add(tracker, "series", "10")
    run(tracker.mark_dropped(series))

    run(tracker.restore_title(series))

    assert title(session_factory, series).status == TitleStatus.WANT


def test_a_watched_series_is_not_brought_back_its_marks_gave_it_the_status(tracker, session_factory):
    ended = add(tracker, "series", "11")
    run(tracker.mark_all_released(ended))
    before = title(session_factory, ended)

    assert run(tracker.restore_title(ended)).changed is False

    after = title(session_factory, ended)
    assert (after.status, after.restored_at) == (TitleStatus.WATCHED, None) and after.status_changed_at == before.status_changed_at


@pytest.mark.parametrize("kind, external_id", [("movie", "1"), ("series", "10")])
def test_a_title_out_of_the_archive_is_not_changed(tracker, session_factory, kind, external_id):
    title_id = add(tracker, kind, external_id)

    assert run(tracker.restore_title(title_id)).changed is False
    assert title(session_factory, title_id).restored_at is None


def test_restore_of_a_title_that_is_not_there_is_unknown(tracker):
    with pytest.raises(UnknownTitle):
        run(tracker.restore_title(999))


def test_watched_after_the_return_starts_the_sequel_check_anew_without_events(
    tracker, session_factory, sequels, sender, clock
):
    film = add(tracker, "movie", "1")
    sequels.parts = [PART_THREE]
    run(tracker.mark_watched(film))
    poll(tracker, clock)
    run(tracker.restore_title(film))

    assert run(tracker.mark_watched(film)).changed is True  # no clash with the old sequel snapshot

    sequels.parts = [PART_THREE, PART_FOUR]
    poll(tracker, clock, minutes=1)  # the first look of the new check only records the collection
    run(tracker.deliver_pending())
    assert sender.sent == []
    assert snapshots(session_factory, film)["tmdb_sequels"].state["parts"]


# ---- the first check after the return --------------------------------------------------------------------------

def test_the_first_check_of_a_returned_movie_records_what_happened_silently(tracker, session_factory, movies, sender, clock):
    film = add(tracker, "movie", "1")
    run(tracker.mark_dropped(film))
    movies.update(replace(DUNE, theatrical_date=(T0 + timedelta(days=20)).date()))  # announced and out meanwhile
    clock.advance(days=40)

    run(tracker.restore_title(film))
    report = poll(tracker, clock, seconds=30)
    run(tracker.deliver_pending())

    assert report.polled == 1 and report.events == 0 and sender.sent == []
    assert event_types(session_factory, film) == []
    assert run(tracker.title_card(film)).theatrical_date == (T0 + timedelta(days=20)).date()
    observed = snapshots(session_factory, film)["tmdb_movie"].observed_at
    assert observed > title(session_factory, film).restored_at

    out_digitally = (clock.now + timedelta(days=1)).date()
    movies.update(replace(DUNE, theatrical_date=(T0 + timedelta(days=20)).date(), digital_date=out_digitally))
    poll(tracker, clock, days=8)
    run(tracker.deliver_pending())
    assert event_types(session_factory, film) == [movie_events.DIGITAL]
    assert len(sender.sent) == 1


def test_the_first_check_of_a_returned_series_records_new_episodes_and_a_new_season_silently(
    tracker, session_factory, shows, sender, clock
):
    series = add(tracker, "series", "10")
    run(tracker.mark_dropped(series))
    clock.advance(weeks=2)  # two more episodes came out
    shows.update(replace(AIRING, seasons=[*AIRING.seasons, Season(2, "Сезон 2", 8, weekly("2027-03-01", 8))]))

    run(tracker.restore_title(series))
    poll(tracker, clock, seconds=30)
    run(tracker.deliver_pending())

    assert sender.sent == [] and event_types(session_factory, series) == []
    card = run(tracker.title_card(series))
    assert card.seasons.current.released == 5 and card.seasons.announced.number == 2

    poll(tracker, clock, days=8)  # the sixth episode
    run(tracker.deliver_pending())
    assert event_types(session_factory, series) == [series_events.EPISODE_OUT]
    assert len(sender.sent) == 1


def test_the_first_check_of_a_returned_anime_records_a_started_season_silently(
    tracker, session_factory, shikimori, sender, clock
):
    anime = add(tracker, "anime", JJK)
    run(tracker.mark_dropped(anime))
    shikimori.by_id[JJK_4].update(airedOn={"date": "2026-11-05", "year": 2026}, episodes=12)
    clock.advance(days=12)
    shikimori.by_id[JJK_4].update(
        status="ongoing", episodesAired=1, nextEpisodeAt=datetime(2026, 11, 12, 11, 30, tzinfo=timezone.utc).isoformat()
    )

    run(tracker.restore_title(anime))
    poll(tracker, clock, seconds=30)
    run(tracker.deliver_pending())

    assert sender.sent == [] and event_types(session_factory, anime) == []
    assert any(row.number == 4 and row.can_mark for row in run(tracker.title_card(anime)).season_rows)

    shikimori.by_id[JJK_4].update(
        episodesAired=2, nextEpisodeAt=datetime(2026, 11, 19, 11, 30, tzinfo=timezone.utc).isoformat()
    )
    poll(tracker, clock, days=8)
    run(tracker.deliver_pending())
    assert event_types(session_factory, anime) != [] and len(sender.sent) >= 1


def test_a_failed_first_check_leaves_the_next_good_one_silent(tracker, session_factory, movies, sender, clock):
    film = add(tracker, "movie", "1")
    run(tracker.mark_dropped(film))
    movies.update(replace(DUNE, theatrical_date=(T0 + timedelta(days=20)).date()))
    clock.advance(days=40)
    run(tracker.restore_title(film))
    movies.failing = True

    assert poll(tracker, clock, seconds=30).failed == 1

    movies.failing = False
    assert poll(tracker, clock, minutes=31).polled == 1
    assert movie_events.DATE_ANNOUNCED not in event_types(session_factory, film)
    assert movie_events.RELEASED not in event_types(session_factory, film)


def test_the_first_check_says_so_in_the_log(tracker, clock, caplog):
    film = add(tracker, "movie", "1")
    run(tracker.mark_dropped(film))
    clock.advance(days=1)
    run(tracker.restore_title(film))

    with caplog.at_level(logging.INFO):
        poll(tracker, clock, seconds=30)
        poll(tracker, clock, days=8)

    lines = [r.getMessage() for r in caplog.records if "baseline" in r.getMessage()]
    assert lines == [f"title {film}: first check after return, recorded as the baseline"]


def test_the_sequel_check_of_a_returned_and_watched_again_movie_announces_as_usual(
    tracker, session_factory, sequels, sender, clock
):
    film = add(tracker, "movie", "1")
    run(tracker.mark_dropped(film))
    clock.advance(days=1)
    run(tracker.restore_title(film))
    run(tracker.mark_watched(film))  # before its own first check: the own snapshot is older than the return
    poll(tracker, clock, seconds=30)  # the first look at the collection
    sequels.parts = [PART_THREE]

    poll(tracker, clock, days=8)
    run(tracker.deliver_pending())

    assert any("Дюна: Часть третья" in text for text in sender.sent)


def test_a_sequel_check_that_runs_while_the_movie_is_dropped_is_not_a_failure(tracker, session_factory, sequels, clock):
    film = add(tracker, "movie", "1")
    run(tracker.mark_watched(film))

    real = sequels.snapshot

    async def dropped_meanwhile(external_id):
        await tracker.mark_dropped(film)
        return await real(external_id)

    sequels.snapshot = dropped_meanwhile
    report = poll(tracker, clock, seconds=30)

    assert report.failed == 0 and event_types(session_factory, film) == []
