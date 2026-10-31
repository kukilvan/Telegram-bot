"""Things the core says in one place (ticket 01 of part 6.1): how text is compared, which score is seen, what a
refused score carries, and the text of an event's message. The behaviour itself is covered by the tests of the lists,
the cards and the scores; these are the checks that there is one rule and not a copy of it.

Rows are put straight into the database, so the statuses, the marks and the scores are exactly what a test needs.
"""

import asyncio
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.tracker import delivery, genres, scores, text
from app.tracker.core import CannotScore, ListOrder, Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import SeasonRecord, Title, TitleKind, TitleStatus

T0 = datetime(2026, 10, 24, 12, 0)
APP = Path(__file__).resolve().parent.parent / "app"


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


def put(session_factory, name, *, kind=TitleKind.MOVIE, status=TitleStatus.WATCHED, genres_=(), score=None, seasons=()):
    """A title; `seasons` are (watched, score) pairs. Returns its number and the numbers of its seasons' records."""
    with session_factory() as session:
        title = Title(
            kind=kind, name=name, original_name=name, genres=list(genres_), status=status, tracking_enabled=True,
            added_at=T0, status_changed_at=T0 + timedelta(minutes=1), score=score,
        )
        session.add(title)
        session.flush()
        records = [
            SeasonRecord(title_id=title.id, number=number, name=f"S{number}", watched=watched, score=season_score)
            for number, (watched, season_score) in enumerate(seasons, 1)
        ]
        session.add_all(records)
        session.commit()
        return title.id, [record.id for record in records]


# --- one way to compare text ------------------------------------------------------------------------


def test_the_key_of_a_text_ignores_case_and_takes_yo_for_ye_and_leaves_the_spaces():
    assert text.key("Чёрное ЗЕРКАЛО") == text.key("черное зеркало") == "черное зеркало"
    assert text.key("Ёлка") == text.key("елка")
    assert text.key(" Дюна ") == " дюна "  # whoever must ignore the spaces strips before


def test_a_genre_is_the_key_of_its_text_without_the_spaces_at_its_ends():
    assert genres.key_of("  Чёрная комедия ") == text.key("Чёрная комедия") == "черная комедия"
    assert genres.keys_of([" ДРАМА", "драма ", 7, " "]) == {"драма"}
    assert genres.merge([["Чёрная комедия"], [" черная комедия "]]) == ["Черная комедия"]


def test_the_name_order_the_name_search_and_the_genre_filter_use_the_same_key(tracker, session_factory):
    put(session_factory, "Ёж", genres_=["Чёрная комедия"])
    put(session_factory, "ель", genres_=["черная комедия"])
    put(session_factory, "Ель большая", genres_=["Драма"])

    by_name = [row.name for row in run(tracker.list_titles(order=ListOrder.NAME))]
    assert by_name == ["Ёж", "ель", "Ель большая"]  # «ё» sorts as «е»: «еж» < «ель» < «ель большая»
    assert [row.name for row in run(tracker.list_titles(query="ЕЖ"))] == ["Ёж"]
    assert [row.name for row in run(tracker.list_titles(genre="ЧЁРНАЯ КОМЕДИЯ"))] == ["Ёж", "ель"]


def test_there_is_one_copy_of_the_rule_that_makes_yo_ye():
    copies = [
        path.relative_to(APP).as_posix()
        for path in APP.rglob("*.py")
        if re.search(r"replace\(\s*[\"']ё[\"']", path.read_text(encoding="utf-8"))
    ]
    assert copies == ["tracker/text.py"]


# --- one rule for the score that is seen -------------------------------------------------------------


def title(status, kind=TitleKind.MOVIE, score=None):
    return Title(kind=kind, name="Тайтл", status=status, score=score)


def test_a_title_in_the_archive_can_be_scored_and_one_out_of_it_cannot():
    assert scores.scorable(title(TitleStatus.WATCHED), any_marked=False)
    assert scores.scorable(title(TitleStatus.DROPPED), any_marked=False)
    assert not scores.scorable(title(TitleStatus.WANT), any_marked=False)
    assert not scores.scorable(title(TitleStatus.WANT), any_marked=True)  # a film has no seasons to mark


def test_a_series_out_of_the_archive_can_be_scored_while_a_season_is_marked():
    series = title(TitleStatus.IN_PROGRESS, TitleKind.SERIES)

    assert scores.scorable(series, any_marked=True)
    assert not scores.scorable(series, any_marked=False)


def test_a_season_shows_its_score_only_with_its_mark():
    assert scores.season_score(True, 27) == 27
    assert scores.season_score(False, 27) is None
    assert scores.season_score(True, None) is None


def test_the_visible_score_counts_only_the_scores_of_marked_seasons():
    series = title(TitleStatus.IN_PROGRESS, TitleKind.SERIES)

    view = scores.visible(series, [(True, 27), (True, 25), (False, 30), (True, None)])

    assert view is not None and view.own is None and view.by_seasons
    assert view.shown == 26  # the average of 27 and 25; the unmarked season's 30 does not count
    assert scores.visible(series, [(False, 30)]) is None  # nothing marked: nothing seen
    assert scores.visible(title(TitleStatus.WATCHED, score=28), []).shown == 28  # the own score of a film


def test_the_card_the_list_and_the_archive_show_the_same_score(tracker, session_factory):
    watched, _ = put(session_factory, "Фильм", score=28)
    marked, _ = put(
        session_factory, "Сериал", kind=TitleKind.SERIES, status=TitleStatus.IN_PROGRESS,
        seasons=[(True, 27), (True, 25), (False, 30)],
    )
    unmarked, _ = put(
        session_factory, "Сериал без отметок", kind=TitleKind.SERIES, status=TitleStatus.WANT, seasons=[(False, 30)]
    )

    listed = {row.id: row for row in run(tracker.list_titles())}

    for title_id, shown in ((watched, 28), (marked, 26), (unmarked, None)):
        card = run(tracker.title_card(title_id))
        assert (card.score.shown if card.score else None) == shown
        assert listed[title_id].score == shown


# --- a refused score carries numbers, not text ---------------------------------------------------------


def test_a_refused_score_of_a_title_names_the_title(tracker, session_factory):
    title_id, _ = put(session_factory, "Фильм", status=TitleStatus.WANT)

    with pytest.raises(CannotScore) as refused:
        run(tracker.set_title_score(title_id, 27))

    assert (refused.value.title_id, refused.value.season_id) == (title_id, None)


def test_a_refused_score_of_a_season_names_the_title_and_the_record_of_the_season(tracker, session_factory):
    title_id, (season_id, _) = put(
        session_factory, "Сериал", kind=TitleKind.SERIES, status=TitleStatus.WANT, seasons=[(False, None), (True, None)]
    )

    with pytest.raises(CannotScore) as refused:
        run(tracker.set_season_score(title_id, season_id, 27))

    assert (refused.value.title_id, refused.value.season_id) == (title_id, season_id)


# --- the text of an event's message -----------------------------------------------------------------


def test_the_message_of_an_event_is_its_text_a_test_one_has_a_flask_and_a_textless_one_its_type():
    assert delivery.format_event("episode_out", {"text": "Вышла серия"}) == "Вышла серия"
    assert delivery.format_event("test", {"text": "проверка"}) == "🧪 проверка"
    assert delivery.format_event("episode_out", {}) == "episode_out"
