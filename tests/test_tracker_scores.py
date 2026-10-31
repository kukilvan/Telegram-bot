"""The owner's scores: the scale (pure) and the scores of a film, a season and a series through the facade.

Fake clock and sources, in-memory SQLite, no network. What can be scored and is shown follows table 2.3 of the spec of
part 5.3: a film in the archive, a season with its mark, a series with a marked season or in the archive.
"""

import ast
import asyncio
import inspect
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.tracker import scores
from app.tracker.core import CannotScore, ChangeResult, ScoreView, Tracker, UnknownSeason, UnknownTitle
from app.tracker.db import create_session_factory
from app.tracker.models import SeasonRecord, Title, TitleStatus
from app.tracker.seasons import Episode, Season
from app.tracker.sources.tmdb_movies import MovieSnapshot
from app.tracker.sources.tmdb_series import SeriesSnapshot, Suggestion
from season_helpers import season_id

T0 = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


def weekly(first_day, count):
    start = datetime.fromisoformat(first_day)
    return tuple(Episode(n + 1, start + timedelta(weeks=n)) for n in range(count))


SHOW = SeriesSnapshot(
    external_id="300", name="Шоу", original_name="Show", year=2026, genres=[],
    seasons=[
        Season(1, "Сезон 1", 8, weekly("2026-03-02", 8)),
        Season(2, "Сезон 2", 8, weekly("2026-09-07", 8)),
        Season(3, "Сезон 3", 8, weekly("2026-09-14", 8)),
        Season(4, "Сезон 4", None, ()),
    ],
)
OTHER = SeriesSnapshot(
    external_id="301", name="Другое", original_name="Other", year=2025, genres=[],
    seasons=[Season(1, "Сезон 1", 4, weekly("2025-01-06", 4))],
)
DUNE = MovieSnapshot(external_id="693134", name="Дюна", original_name="Dune", year=2021, genres=["фантастика"])


class FakeSender:
    async def send(self, message, actions=()):
        pass


class FakeSeriesSource:
    source_key = "tmdb_tv"

    async def suggest(self, query):
        return [Suggestion("series", s.external_id, s.name, s.original_name, s.year) for s in (SHOW, OTHER)]

    async def snapshot(self, external_id):
        return {s.external_id: s for s in (SHOW, OTHER)}.get(external_id)


class FakeMovieSource:
    source_key = "tmdb_movie"

    async def suggest(self, query):
        return []

    async def snapshot(self, external_id):
        return DUNE if external_id == DUNE.external_id else None


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def tracker(session_factory):
    return Tracker(
        session_factory, clock=lambda: T0, sender=FakeSender(),
        sources={"series": FakeSeriesSource(), "movie": FakeMovieSource()},
    )


@pytest.fixture
def film(tracker):
    return run(tracker.add_title("movie", DUNE.external_id)).title_id


@pytest.fixture
def show(tracker):
    return run(tracker.add_title("series", SHOW.external_id)).title_id


def score_of(tracker, title_id):
    return run(tracker.title_card(title_id)).score


def row(tracker, title_id, number):
    return next(r for r in run(tracker.title_card(title_id)).season_rows if r.number == number)


def mark(tracker, title_id, number, watched=True):
    run(tracker.set_season_watched(title_id, season_id(tracker, title_id, number), watched))


def score_season(tracker, title_id, number, score):
    return run(tracker.set_season_score(title_id, season_id(tracker, title_id, number), score))


def value(text):
    """The value of a label: «9+» → 28."""
    return next(v for v in scores.SCALE if scores.label(v) == text)


# --- the scale ------------------------------------------------------------------------------------


def test_the_scale_has_twenty_eight_steps_from_ten_down_to_one():
    assert scores.SCALE == tuple(range(30, 2, -1)) and len(scores.SCALE) == 28
    assert [scores.label(v) for v in scores.SCALE[:5]] == ["10", "10−", "9+", "9", "9−"]
    assert [scores.label(v) for v in scores.SCALE[-5:]] == ["2+", "2", "2−", "1+", "1"]
    assert all("-" not in scores.label(v) for v in scores.SCALE)  # the minus sign, not the hyphen
    assert len({scores.label(v) for v in scores.SCALE}) == 28


@pytest.mark.parametrize("off", [2, 31, 0, -3, 100, True, 27.0, "27", None])
def test_a_value_off_the_scale_is_a_mistake_of_the_caller(off):
    with pytest.raises(ValueError):
        scores.label(off)
    with pytest.raises(ValueError):
        scores.check(off)


def test_one_minus_and_ten_plus_are_not_on_the_scale():
    assert "1−" not in {scores.label(v) for v in scores.SCALE} and "10+" not in {scores.label(v) for v in scores.SCALE}
    assert (scores.LOWEST - 1, scores.HIGHEST + 1) == (2, 31)


def test_a_plus_and_a_minus_weigh_a_third_and_order_the_steps():
    assert value("9−") < value("9") < value("9+") < value("10−") < value("10")
    assert (value("9−"), value("9"), value("9+")) == (26, 27, 28)  # 8⅔, 9, 9⅓ in thirds


def test_the_average_is_exact_and_shown_as_the_nearest_step_half_way_up():
    assert scores.average([]) is None
    assert scores.average([value("9")]) == 27
    assert scores.average([value("9"), value("8+")]) == 26  # «9» and «8+» → «9−»
    assert scores.label(scores.rounded(scores.average([value("9"), value("8+")]))) == "9−"
    assert scores.average([value("9"), value("9+")]) == Fraction(55, 2)
    assert scores.label(scores.rounded(Fraction(55, 2))) == "9+"  # exactly half-way: the higher step
    assert scores.rounded(Fraction(82, 3)) == 27  # 27⅓ is nearer to «9»
    assert scores.rounded(Fraction(83, 3)) == 28


def test_the_labels_of_the_scale_are_built_from_the_modifier_not_from_status_words():
    source = Path(inspect.getfile(scores)).read_text(encoding="utf-8")
    literals = {n.value for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Constant) and isinstance(n.value, str)}

    assert not literals & {status.value for status in TitleStatus}
    for scale_function in (scores.check, scores.label, scores.average, scores.rounded):  # the scale knows no statuses
        assert "Status" not in inspect.getsource(scale_function)


# --- a film ---------------------------------------------------------------------------------------


def test_a_film_that_is_wanted_cannot_be_scored_and_shows_no_field(tracker, film):
    with pytest.raises(CannotScore):
        run(tracker.set_title_score(film, value("9")))

    assert score_of(tracker, film) is None


def test_a_watched_film_gets_a_score_that_can_be_replaced_and_taken_off(tracker, film):
    run(tracker.mark_watched(film))
    assert score_of(tracker, film) == ScoreView(None, None, None, by_seasons=False)

    assert run(tracker.set_title_score(film, value("9+"))) == ChangeResult(changed=True)
    assert score_of(tracker, film) == ScoreView(28, None, 28, by_seasons=False)
    assert run(tracker.set_title_score(film, value("9+"))) == ChangeResult(changed=False)
    assert run(tracker.set_title_score(film, value("10"))).changed is True
    assert score_of(tracker, film).shown == 30

    assert run(tracker.set_title_score(film, None)).changed is True
    assert score_of(tracker, film) == ScoreView(None, None, None, by_seasons=False)


def test_a_dropped_film_can_be_scored(tracker, film):
    run(tracker.mark_dropped(film))

    run(tracker.set_title_score(film, value("3")))

    assert score_of(tracker, film).shown == 9


def test_the_score_of_a_film_brought_back_is_kept_unseen_and_shown_again_after_the_next_watch(tracker, film):
    run(tracker.mark_watched(film))
    run(tracker.set_title_score(film, value("8−")))

    run(tracker.restore_title(film))
    assert score_of(tracker, film) is None  # «Хочу»: no field
    with pytest.raises(CannotScore):
        run(tracker.set_title_score(film, value("9")))

    run(tracker.mark_watched(film))
    assert score_of(tracker, film).shown == value("8−")


def test_taking_a_score_off_always_works(tracker, film):
    run(tracker.mark_watched(film))
    run(tracker.set_title_score(film, value("7")))
    run(tracker.restore_title(film))

    assert run(tracker.set_title_score(film, None)).changed is True

    run(tracker.mark_watched(film))
    assert score_of(tracker, film).shown is None


# --- a series and its seasons ---------------------------------------------------------------------


def test_a_series_with_no_mark_out_of_the_archive_cannot_be_scored(tracker, show):
    assert score_of(tracker, show) is None
    with pytest.raises(CannotScore):
        run(tracker.set_title_score(show, value("9")))
    with pytest.raises(CannotScore):  # a season without its mark
        score_season(tracker, show, 1, value("9"))
    assert row(tracker, show, 1).score is None


def test_a_marked_season_gets_a_score_and_the_series_shows_the_average_of_its_seasons(tracker, show):
    mark(tracker, show, 1)
    mark(tracker, show, 2)
    mark(tracker, show, 3)  # marked, not scored: it does not count

    assert score_season(tracker, show, 1, value("9")) == ChangeResult(changed=True)
    score_season(tracker, show, 2, value("8+"))

    assert (row(tracker, show, 1).score, row(tracker, show, 2).score, row(tracker, show, 3).score) == (27, 25, None)
    assert score_of(tracker, show) == ScoreView(None, Fraction(26), 26, by_seasons=True)
    assert scores.label(score_of(tracker, show).shown) == "9−"


def test_a_score_of_a_season_is_replaced_and_taken_off(tracker, show):
    mark(tracker, show, 1)
    score_season(tracker, show, 1, value("6"))

    assert score_season(tracker, show, 1, value("6")).changed is False
    assert score_season(tracker, show, 1, value("7")).changed is True
    assert row(tracker, show, 1).score == value("7")
    assert score_season(tracker, show, 1, None).changed is True
    assert row(tracker, show, 1).score is None
    assert score_of(tracker, show) == ScoreView(None, None, None, by_seasons=False)


def test_the_own_score_of_a_series_stands_over_the_average_until_it_is_taken_off(tracker, show):
    mark(tracker, show, 1)
    mark(tracker, show, 2)
    score_season(tracker, show, 1, value("9"))
    score_season(tracker, show, 2, value("9+"))

    run(tracker.set_title_score(show, value("10")))
    assert score_of(tracker, show) == ScoreView(30, Fraction(55, 2), 30, by_seasons=False)

    run(tracker.set_title_score(show, None))  # «По сезонам»: the average again
    assert score_of(tracker, show) == ScoreView(None, Fraction(55, 2), 28, by_seasons=True)


def test_a_mark_taken_off_hides_the_score_of_the_season_and_drops_it_from_the_average(tracker, show):
    mark(tracker, show, 1)
    mark(tracker, show, 2)
    score_season(tracker, show, 1, value("9"))
    score_season(tracker, show, 2, value("8+"))

    mark(tracker, show, 2, watched=False)
    assert row(tracker, show, 2).score is None
    assert score_of(tracker, show).average == 27
    with pytest.raises(CannotScore):
        score_season(tracker, show, 2, value("5"))
    assert score_season(tracker, show, 2, None).changed is True  # taking it off still works

    mark(tracker, show, 2)
    assert row(tracker, show, 2).score is None  # it was taken off meanwhile


def test_the_score_of_a_season_comes_back_with_its_mark(tracker, show):
    mark(tracker, show, 1)
    mark(tracker, show, 2)
    score_season(tracker, show, 2, value("8+"))

    mark(tracker, show, 2, watched=False)
    mark(tracker, show, 2)

    assert row(tracker, show, 2).score == 25 and score_of(tracker, show).shown == 25


def test_without_marks_the_series_loses_its_field_but_keeps_its_scores(tracker, show):
    mark(tracker, show, 1)
    run(tracker.set_title_score(show, value("7")))

    mark(tracker, show, 1, watched=False)
    assert score_of(tracker, show) is None

    mark(tracker, show, 1)
    assert score_of(tracker, show).own == value("7")


def test_a_dropped_series_without_marks_can_have_its_own_score(tracker, show):
    run(tracker.mark_dropped(show))

    run(tracker.set_title_score(show, value("4")))

    assert score_of(tracker, show) == ScoreView(12, None, 12, by_seasons=False)


def test_a_season_of_another_title_or_one_that_is_gone_is_an_unknown_season(tracker, show):
    other = run(tracker.add_title("series", OTHER.external_id)).title_id
    mark(tracker, other, 1)

    with pytest.raises(UnknownSeason):
        run(tracker.set_season_score(show, season_id(tracker, other, 1), value("9")))
    with pytest.raises(UnknownSeason):
        run(tracker.set_season_score(show, 999, value("9")))
    with pytest.raises(UnknownSeason):
        run(tracker.set_season_score(show, 999, None))
    assert row(tracker, other, 1).score is None


def test_a_title_that_is_not_there_is_an_unknown_title(tracker, show):
    with pytest.raises(UnknownTitle):
        run(tracker.set_title_score(999, value("9")))
    with pytest.raises(UnknownTitle):
        run(tracker.set_title_score(999, None))
    with pytest.raises(UnknownTitle):
        run(tracker.set_season_score(999, season_id(tracker, show, 1), None))


@pytest.mark.parametrize("off", [2, 31])
def test_a_value_off_the_scale_is_refused_before_the_database(tracker, film, off):
    with pytest.raises(ValueError):
        run(tracker.set_title_score(999, off))  # not UnknownTitle: the value is checked first
    with pytest.raises(ValueError):
        run(tracker.set_season_score(999, 1, off))


def test_deleting_a_title_deletes_its_scores(tracker, show, session_factory):
    mark(tracker, show, 1)
    score_season(tracker, show, 1, value("9"))
    run(tracker.set_title_score(show, value("9")))

    run(tracker.delete_title(show))

    with session_factory() as session:
        assert session.scalar(select(func.count(SeasonRecord.id))) == 0
        assert session.scalar(select(func.count(Title.id))) == 0


def test_the_rows_carry_the_record_of_each_season(tracker, show, session_factory):
    with session_factory() as session:
        records = {r.number: r.id for r in session.scalars(select(SeasonRecord).where(SeasonRecord.title_id == show))}

    assert {r.number: r.id for r in run(tracker.title_card(show)).season_rows} == records
    assert {s.number: s.id for s in run(tracker.watchable_seasons(show))} == {n: records[n] for n in (1, 2, 3)}
