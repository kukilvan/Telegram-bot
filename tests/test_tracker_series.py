"""Tracker core: a series with seasons (add, card, watched seasons).

Driven through the facade only: fake clock, fake series source, in-memory SQLite. The «Укрытие» case runs
on the saved real TMDb answers; the other shapes of a season are built by hand.
"""

import asyncio
import json
import pathlib
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.tracker.actions import DELETE, SEASONS, WATCHED, card_actions
from app.tracker.cards import format_card
from app.tracker.core import Tracker, UnknownSeason, UnknownTitle
from app.tracker.db import create_session_factory
from app.tracker.models import ExternalId, SourceSnapshot, Title
from app.tracker.seasons import Episode, Season
from app.tracker.sources.tmdb_series import SeriesSnapshot, Suggestion, parse_show

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "tmdb"
T0 = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def silo():
    seasons = {n: load(f"tv_125988_season_{n}.json") for n in (1, 2, 3, 4)}
    return parse_show(load("tv_125988.json"), seasons)


def weekly(first_day, count):
    """`count` episodes one week apart, the first on `first_day` (midnight, the day TMDb names)."""
    start = datetime.fromisoformat(first_day)
    return tuple(Episode(n + 1, start + timedelta(weeks=n)) for n in range(count))


def show(external_id, name, *seasons):
    return SeriesSnapshot(
        external_id=external_id, title=name, original_title=name, year=2026, genres=["драма"], seasons=list(seasons)
    )


# Monday 7 Sep 2026 + 5 weeks: five episodes are out by 10 Oct, the sixth comes on Monday 12 Oct
AIRING = show(
    "200", "Идущий",
    Season(1, "Сезон 1", 8, weekly("2026-03-02", 8)),
    Season(2, "Сезон 2", 8, weekly("2026-09-07", 8)),
)
NEW_SHOW = show("201", "Новичок", Season(1, "Сезон 1", 6, ()))
UNKNOWN_COUNT = show("202", "Без счёта", Season(1, "Сезон 1", None, weekly("2026-10-05", 3)))
TWO_STUBS = show(
    "203", "Две заглушки",
    Season(1, "Сезон 1", 6, weekly("2026-01-05", 6)),
    Season(2, "Сезон 2", 6, weekly("2027-03-01", 6)),
    Season(3, "Сезон 3", None, ()),
)
# four dated episodes (3, 10, 17 and 24 Oct) of ten announced: nothing is scheduled after the fourth
NO_NEXT_DATE = show("204", "Без даты", Season(1, "Сезон 1", 10, weekly("2026-10-03", 4)))
WITH_SPECIALS = show(
    "205", "Со спецвыпусками",
    Season(0, "Спецвыпуски", 2, weekly("2026-01-01", 2)),
    Season(1, "Сезон 1", 4, weekly("2026-01-05", 4)),
)


class FakeClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class FakeSender:
    async def send(self, message, actions=()):
        pass


class FakeSeriesSource:
    source_key = "tmdb_tv"

    def __init__(self, *snapshots):
        self.by_id = {s.external_id: s for s in snapshots}
        self.snapshot_calls = 0

    async def suggest(self, query):
        return [Suggestion("series", s.external_id, s.title, s.original_title, s.year) for s in self.by_id.values()]

    async def snapshot(self, external_id):
        self.snapshot_calls += 1
        return self.by_id.get(external_id)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def clock():
    return FakeClock(T0)


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def series(clock):
    return FakeSeriesSource(
        silo(), AIRING, NEW_SHOW, UNKNOWN_COUNT, TWO_STUBS, NO_NEXT_DATE, WITH_SPECIALS
    )


@pytest.fixture
def tracker(session_factory, clock, series):
    return Tracker(session_factory, clock=clock, sender=FakeSender(), sources={"series": series})


def card_text(tracker, external_id):
    result = run(tracker.add_title("series", external_id))
    return format_card(run(tracker.title_card(result.title_id)))


# --- adding a series ----------------------------------------------------------------------------


def test_added_series_is_in_the_list_with_status_want(tracker):
    result = run(tracker.add_title("series", "125988"))

    [entry] = run(tracker.list_titles())
    assert result.created is True
    assert (entry.kind, entry.name, entry.year, entry.status) == ("series", "Укрытие", 2023, "want")


def test_series_is_stored_under_its_own_source_key(tracker, session_factory):
    run(tracker.add_title("series", "125988"))

    with session_factory() as s:
        [external] = list(s.scalars(select(ExternalId)))
        [snapshot] = list(s.scalars(select(SourceSnapshot)))
    assert (external.source, external.external_id, external.role) == ("tmdb_tv", "125988", "primary")
    assert snapshot.source == "tmdb_tv"


def test_adding_the_same_series_again_opens_the_existing_title(tracker, series, session_factory):
    first = run(tracker.add_title("series", "125988"))
    second = run(tracker.add_title("series", "125988"))

    assert (second.created, second.title_id) == (False, first.title_id)
    assert series.snapshot_calls == 1
    with session_factory() as s:
        assert len(list(s.scalars(select(Title)))) == 1


def test_unknown_series_id_is_reported_and_nothing_is_stored(tracker):
    from app.tracker.core import TitleNotFound

    with pytest.raises(TitleNotFound):
        run(tracker.add_title("series", "1"))

    assert run(tracker.list_titles()) == []


# --- what the card says about seasons ------------------------------------------------------------


def test_silo_stub_season_is_announced_and_the_last_released_season_stays_current(tracker):
    text = card_text(tracker, "125988")

    assert "Сезон 3: вышло 10 из 10" in text
    assert "Сезон 4 анонсирован" in text
    assert "8 июля 2027" in text
    assert "вышло 0 из 1" not in text


def test_airing_season_shows_progress_and_the_next_episode_day(tracker, clock):
    clock.now = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)

    text = card_text(tracker, "200")

    assert "Сезон 2: вышло 5 из 8, следующая — пн, 12 окт" in text
    assert "анонсирован" not in text


def test_an_episode_counts_as_released_only_when_its_moment_has_come(tracker, clock):
    clock.now = datetime(2026, 10, 11, 23, 59, tzinfo=timezone.utc)
    result = run(tracker.add_title("series", "200"))
    assert run(tracker.title_card(result.title_id)).seasons.current.released == 5

    clock.now = datetime(2026, 10, 12, 0, 0, tzinfo=timezone.utc)
    assert run(tracker.title_card(result.title_id)).seasons.current.released == 6


def test_a_new_show_without_aired_episodes_is_announced_not_zero_of_six(tracker):
    text = card_text(tracker, "201")

    assert "Сезон 1 анонсирован" in text
    assert "дата не объявлена" in text
    assert "вышло" not in text


def test_unknown_episode_count_reads_as_a_question_mark(tracker, clock):
    clock.now = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)

    text = card_text(tracker, "202")

    assert "Сезон 1: вышло 3 из ?" in text


def test_airing_season_without_a_known_next_date_says_so(tracker):
    text = card_text(tracker, "204")

    assert "Сезон 1: вышло 4 из 10, следующая — не объявлена" in text


def test_only_the_nearest_announced_season_gets_a_line(tracker):
    text = card_text(tracker, "203")

    assert "Сезон 1: вышло 6 из 6" in text
    assert "Сезон 2 анонсирован" in text
    assert "1 марта 2027" in text
    assert "Сезон 3" not in text


def test_season_zero_is_not_a_season(tracker):
    result = run(tracker.add_title("series", "205"))

    text = format_card(run(tracker.title_card(result.title_id)))

    assert "Сезон 0" not in text
    assert "Сезон 1: вышло 4 из 4" in text
    assert [s.number for s in run(tracker.watchable_seasons(result.title_id))] == [1]


def test_series_card_has_names_year_genres_and_status(tracker):
    text = card_text(tracker, "125988")

    assert text.splitlines()[0] == "📺 Сериал · Хочу"
    assert "Укрытие · Silo" in text
    assert "Год: 2023" in text
    assert "Премьера в кино" not in text  # movie lines do not belong on a series card


# --- watched seasons ----------------------------------------------------------------------------


def test_seasons_with_released_episodes_can_be_marked_the_announced_one_cannot(tracker):
    result = run(tracker.add_title("series", "125988"))

    choices = run(tracker.watchable_seasons(result.title_id))

    assert [(c.number, c.watched) for c in choices] == [(1, False), (2, False), (3, False)]


def test_marked_seasons_show_on_the_card_and_unmarking_removes_them(tracker):
    result = run(tracker.add_title("series", "125988"))

    run(tracker.set_season_watched(result.title_id, 1, True))
    run(tracker.set_season_watched(result.title_id, 2, True))
    assert "Просмотрены сезоны: 1, 2" in format_card(run(tracker.title_card(result.title_id)))
    assert [c.watched for c in run(tracker.watchable_seasons(result.title_id))] == [True, True, False]

    run(tracker.set_season_watched(result.title_id, 1, False))
    assert "Просмотрены сезоны: 2" in format_card(run(tracker.title_card(result.title_id)))


def test_marking_twice_is_harmless(tracker):
    result = run(tracker.add_title("series", "125988"))

    run(tracker.set_season_watched(result.title_id, 3, True))
    run(tracker.set_season_watched(result.title_id, 3, True))

    assert run(tracker.title_card(result.title_id)).seasons.watched == (3,)


def test_a_card_without_marks_has_no_watched_line(tracker):
    assert "Просмотрены" not in card_text(tracker, "125988")


def test_marking_an_unknown_title_or_season_is_an_error(tracker):
    result = run(tracker.add_title("series", "125988"))

    with pytest.raises(UnknownTitle):
        run(tracker.set_season_watched(999, 1, True))
    with pytest.raises(UnknownSeason):
        run(tracker.set_season_watched(result.title_id, 9, True))
    with pytest.raises(UnknownSeason):
        run(tracker.set_season_watched(result.title_id, 0, True))


def test_marking_a_season_while_others_are_unwatched_makes_the_series_in_progress(tracker):
    result = run(tracker.add_title("series", "125988"))

    run(tracker.set_season_watched(result.title_id, 3, True))

    assert run(tracker.list_titles())[0].status == "in_progress"  # the other seasons are still unwatched; the automatic statuses are in test_tracker_series_statuses


# --- buttons ------------------------------------------------------------------------------------


def test_series_card_offers_the_seasons_button_and_not_watched(tracker):
    result = run(tracker.add_title("series", "125988"))

    actions = card_actions(run(tracker.title_card(result.title_id)))

    assert [a.name for a in actions] == [SEASONS, DELETE]
    assert actions[0].arg == result.title_id
    assert WATCHED not in [a.name for a in actions]
