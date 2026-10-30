"""Searching the list by name, the filter by a merged genre, `genres`, the orders «по оценке» and «сначала недавние»,
and the score in a row. Rows are put straight into the database, so the moments, the genres and the scores are exactly
what a test needs. The call without arguments is the bot's list and stays as it was."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event

from app.tracker import genres, scores
from app.tracker.core import ListOrder, Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import SeasonRecord, Title, TitleKind, TitleStatus

T0 = datetime(2026, 10, 24, 12, 0)
WATCHED = TitleStatus.WATCHED


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


def put(session_factory, name, *, original=None, kind=TitleKind.MOVIE, status=WATCHED, genres_=(), score=None,
        changed=0, seasons=()):
    """A title whose status changed `changed` minutes after T0; `seasons` are (watched, score) pairs."""
    with session_factory() as session:
        title = Title(
            kind=kind, name=name, original_name=original if original is not None else name, genres=list(genres_),
            status=status, tracking_enabled=True, added_at=T0, status_changed_at=T0 + timedelta(minutes=changed),
            score=score,
        )
        session.add(title)
        session.flush()
        for number, (watched, season_score) in enumerate(seasons, 1):
            session.add(SeasonRecord(title_id=title.id, number=number, name=f"S{number}", watched=watched, score=season_score))
        session.commit()
        return title.id


def names(rows):
    return [row.name for row in rows]


# --- search by name -----------------------------------------------------------------------------


def test_the_search_ignores_case_and_yo_and_finds_a_part_of_the_name(tracker, session_factory):
    put(session_factory, "Дюна")
    put(session_factory, "Чёрное зеркало", kind=TitleKind.SERIES)
    put(session_factory, "Пацаны")

    assert names(run(tracker.list_titles(query="ДЮН"))) == ["Дюна"]
    assert names(run(tracker.list_titles(query="чёрное"))) == ["Чёрное зеркало"]
    assert names(run(tracker.list_titles(query="черное ЗЕРК"))) == ["Чёрное зеркало"]
    assert names(run(tracker.list_titles(query="цан"))) == ["Пацаны"]


def test_the_search_looks_into_the_original_name_too(tracker, session_factory):
    put(session_factory, "Дюна", original="Dune")
    put(session_factory, "Пацаны", original="The Boys")

    assert names(run(tracker.list_titles(query="dune"))) == ["Дюна"]
    assert names(run(tracker.list_titles(query="BOYS"))) == ["Пацаны"]


def test_spaces_at_the_ends_of_the_query_do_not_count_and_an_empty_query_finds_everything(tracker, session_factory):
    put(session_factory, "Дюна")
    put(session_factory, "Пацаны")

    assert names(run(tracker.list_titles(query="  дюна "))) == ["Дюна"]
    for empty in (None, "", "   "):
        assert names(run(tracker.list_titles(query=empty))) == ["Дюна", "Пацаны"]


def test_the_search_works_with_the_filters_and_nothing_found_is_an_empty_list(tracker, session_factory):
    put(session_factory, "Дюна")
    put(session_factory, "Дюна: часть вторая", status=TitleStatus.WANT)
    put(session_factory, "Дюна, сериал", kind=TitleKind.SERIES)

    assert names(run(tracker.list_titles(kind=TitleKind.MOVIE, statuses={WATCHED}, query="дюна"))) == ["Дюна"]
    assert run(tracker.list_titles(query="такого нет")) == []


# --- genres -------------------------------------------------------------------------------------


def test_genres_that_differ_in_case_or_yo_are_one_genre():
    assert genres.merge([["драма", "Боевик"], ["Драма"], ["  драма "]]) == ["Боевик", "Драма"]
    assert genres.merge([["Чёрная комедия"], ["черная комедия"]]) == ["Черная комедия"]
    assert genres.label(["драма", "Драма"]) == "Драма"


def test_synonyms_of_different_sources_stay_different_genres():
    assert genres.merge([["Боевик"], ["Экшен"], ["Боевик и Приключения"]]) == ["Боевик", "Боевик и Приключения", "Экшен"]


def test_genres_ignore_whatever_is_not_a_name():
    assert genres.merge([[None, 5, "", "  ", "Драма"]]) == ["Драма"]


def test_the_filter_by_a_genre_merges_the_writings(tracker, session_factory):
    put(session_factory, "Один", genres_=["драма"])
    put(session_factory, "Два", genres_=["Драма", "Боевик"])
    put(session_factory, "Три", genres_=["Экшен"])
    put(session_factory, "Четыре")

    assert names(run(tracker.list_titles(genre="Драма"))) == ["Один", "Два"]
    assert names(run(tracker.list_titles(genre="Боевик"))) == ["Два"]
    assert names(run(tracker.list_titles(genre="Вестерн"))) == []
    assert names(run(tracker.list_titles(genre=None))) == ["Один", "Два", "Три", "Четыре"]


def test_genres_under_the_filters_of_kind_and_status(tracker, session_factory):
    put(session_factory, "Фильм", genres_=["драма", "Комедия"])
    put(session_factory, "Сериал", kind=TitleKind.SERIES, genres_=["Драма", "Фантастика"])
    put(session_factory, "Хочу", status=TitleStatus.WANT, genres_=["Ужасы"])

    assert run(tracker.genres()) == ["Драма", "Комедия", "Ужасы", "Фантастика"]
    assert run(tracker.genres(statuses={WATCHED})) == ["Драма", "Комедия", "Фантастика"]
    assert run(tracker.genres(kind=TitleKind.SERIES, statuses={WATCHED})) == ["Драма", "Фантастика"]
    assert run(tracker.genres(statuses=frozenset())) == []


# --- orders -------------------------------------------------------------------------------------


def test_the_order_by_score_puts_the_best_first_and_the_unscored_last(tracker, session_factory):
    put(session_factory, "Девять", score=27)
    put(session_factory, "Без оценки")
    put(session_factory, "Десять", score=30)
    put(session_factory, "Девять с плюсом", score=28)

    assert names(run(tracker.list_titles(order=ListOrder.SCORE))) == ["Десять", "Девять с плюсом", "Девять", "Без оценки"]


def test_the_same_score_puts_the_later_change_of_status_first_then_the_larger_number(tracker, session_factory):
    old = put(session_factory, "Давно", score=27, changed=0)
    new = put(session_factory, "Недавно", score=27, changed=10)
    twin_a = put(session_factory, "Близнец А", score=27, changed=5)
    twin_b = put(session_factory, "Близнец Б", score=27, changed=5)

    rows = run(tracker.list_titles(order=ListOrder.SCORE))

    assert [row.id for row in rows] == [new, twin_b, twin_a, old]


def test_the_order_by_score_uses_the_exact_average_and_not_the_rounded_one(tracker, session_factory):
    # 27 and 28 average 27.5 (shown as 28); 28 and 28 average 28: the exact value orders them
    lower = put(session_factory, "Среднее 27,5", kind=TitleKind.SERIES, status=TitleStatus.IN_PROGRESS, seasons=[(True, 27), (True, 28)], changed=10)
    higher = put(session_factory, "Среднее 28", kind=TitleKind.SERIES, status=TitleStatus.IN_PROGRESS, seasons=[(True, 28), (True, 28)], changed=0)

    rows = run(tracker.list_titles(order=ListOrder.SCORE))

    assert [row.id for row in rows] == [higher, lower]
    assert [row.score for row in rows] == [28, 28]  # both read «9+»


def test_the_order_archived_puts_the_latest_change_first(tracker, session_factory):
    put(session_factory, "Старый", changed=0)
    put(session_factory, "Новый", changed=20)
    put(session_factory, "Средний", changed=10)

    assert names(run(tracker.list_titles(order=ListOrder.ARCHIVED))) == ["Новый", "Средний", "Старый"]


def test_the_order_by_name_still_works_with_the_search(tracker, session_factory):
    put(session_factory, "Яблоко")
    put(session_factory, "Ёж")
    put(session_factory, "Арбуз")

    assert names(run(tracker.list_titles(order=ListOrder.NAME, query="б"))) == ["Арбуз", "Яблоко"]


def test_the_call_without_arguments_is_still_the_bots_list_in_the_order_of_numbers(tracker, session_factory):
    first = put(session_factory, "Первый", score=30)
    second = put(session_factory, "Второй")

    assert [row.id for row in run(tracker.list_titles())] == [first, second]


# --- the score in a row -------------------------------------------------------------------------


def test_a_row_shows_the_own_score_of_a_film_in_the_archive(tracker, session_factory):
    put(session_factory, "Дюна", score=28)

    row = run(tracker.list_titles())[0]

    assert (row.score, row.score_by_seasons) == (28, False)
    assert scores.label(row.score) == "9+"


def test_a_row_shows_the_average_of_the_marked_seasons(tracker, session_factory):
    put(
        session_factory, "Сериал", kind=TitleKind.SERIES, status=TitleStatus.IN_PROGRESS,
        seasons=[(True, 27), (True, 25), (True, None), (False, 30)],  # the last season has no mark: its score is unseen
    )

    row = run(tracker.list_titles())[0]

    assert (row.score, row.score_by_seasons) == (26, True)  # 26 is «9−»


def test_the_own_score_of_a_series_goes_over_the_average(tracker, session_factory):
    put(session_factory, "Сериал", kind=TitleKind.SERIES, status=TitleStatus.IN_PROGRESS, score=30, seasons=[(True, 27)])

    row = run(tracker.list_titles())[0]

    assert (row.score, row.score_by_seasons) == (30, False)


def test_a_score_that_cannot_be_shown_is_not_in_the_row(tracker, session_factory):
    put(session_factory, "Хочу", status=TitleStatus.WANT, score=30)  # a film brought back to the list
    put(session_factory, "Сериал без отметок", kind=TitleKind.SERIES, status=TitleStatus.WANT, score=30, seasons=[(False, 27)])
    put(session_factory, "Без оценки")

    assert [row.score for row in run(tracker.list_titles())] == [None, None, None]


def test_a_hidden_score_does_not_order_the_rows(tracker, session_factory):
    hidden = put(session_factory, "Спрятанная", status=TitleStatus.WANT, score=30)
    shown = put(session_factory, "Видимая", score=3)

    assert [row.id for row in run(tracker.list_titles(order=ListOrder.SCORE))] == [shown, hidden]


def test_the_number_of_queries_does_not_grow_with_the_number_of_titles(tracker, session_factory):
    statements = []
    event.listen(session_factory.kw["bind"], "before_cursor_execute", lambda *args: statements.append(args[2]))

    def count() -> int:
        statements.clear()
        run(tracker.list_titles(order=ListOrder.SCORE, query="т", genre="Драма"))
        return len(statements)

    put(session_factory, "Тайтл", kind=TitleKind.SERIES, genres_=["Драма"], seasons=[(True, 27)])
    few = count()
    for i in range(30):
        put(session_factory, f"Тайтл {i}", kind=TitleKind.SERIES, genres_=["Драма"], seasons=[(True, 27), (True, 25)])

    assert count() == few
