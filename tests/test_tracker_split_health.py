"""Code health without a visible change (ticket 9.1d.01): the export asks the pollers for what only a kind knows (KI-71),
the Feed asks each poller once and the seasons are read once (F4), a film date is an enum (F5). The behaviour is the one
the baselines of `test_tracker_split_baselines` hold; here the shape is checked."""

from datetime import datetime, timedelta, timezone

import pytest

from app.tracker import feed_released, feed_rows, storage
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.feed_released import FILM_LABELS, FeedParts, FilmDate, Out
from app.tracker.feed_rows import FeedBasis, FeedTitle
from app.tracker.models import (
    EpisodeRecord, ExternalId, SeasonRecord, SourceSnapshot, Title, TitleKind, TitleStatus,
)

NOW = datetime(2026, 10, 30, 12, 0)
TODAY = NOW.date()
MSK = timezone(timedelta(hours=3))


class FakeSender:
    async def send(self, message, actions=()):
        pass


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def tracker(session_factory):
    return Tracker(session_factory, clock=lambda: NOW.replace(tzinfo=timezone.utc), sender=FakeSender(), default_tz=MSK)


def pollers_of(tracker):
    return tracker._feed.pollers


def put_game(session, name, igdb_id, state):
    title = Title(kind=TitleKind.GAME, name=name, original_name=name, genres=[], status=TitleStatus.WANT,
                  tracking_enabled=True, added_at=NOW, status_changed_at=NOW)
    session.add(title)
    session.flush()
    session.add(ExternalId(title_id=title.id, source="igdb", external_id=igdb_id, role="primary"))
    session.add(SourceSnapshot(title_id=title.id, source="igdb", state=state, observed_at=NOW))
    return title


# --- KI-71: the export asks the pollers ----------------------------------------------------------------------


def test_a_game_poller_names_the_base_game_by_the_list_when_the_list_has_it_else_by_igdb(tracker, session_factory):
    with session_factory() as session:
        base = put_game(session, "Ведьмак 3", "1942", {})
        listed = put_game(session, "Кровь и вино", "2000", {"expansion": "expansion", "parent": {"id": "1942", "name": "IGDB name"}})
        orphan = put_game(session, "Без игры", "2001", {"expansion": "standalone", "parent": {"id": "999", "name": "Game IGDB Knows"}})
        plain = put_game(session, "Обычная", "2002", {})
        session.commit()
        ids = [base.id, listed.id, orphan.id, plain.id]
        extras = pollers_of(tracker).reader_of(TitleKind.GAME).export_extras(session, ids)

    assert extras == {listed.id: {"expansion_of": "Ведьмак 3"}, orphan.id: {"expansion_of": "Game IGDB Knows"}}


def test_a_game_whose_state_cannot_be_read_is_left_out_with_a_warning(tracker, session_factory, caplog):
    with session_factory() as session:
        spoiled = put_game(session, "Сломанная", "1", {"expansion": "expansion", "parent": {"id": 5}})
        unknown = put_game(session, "Странная", "2", {"expansion": "mystery", "parent": {"id": "9", "name": "X"}})
        fine = put_game(session, "Хорошая", "3", {"expansion": "expansion", "parent": {"id": "9", "name": "X"}})
        session.commit()
        with caplog.at_level("WARNING"):
            extras = pollers_of(tracker).reader_of(TitleKind.GAME).export_extras(session, [spoiled.id, unknown.id, fine.id])

    assert extras == {fine.id: {"expansion_of": "X"}}
    assert str(spoiled.id) in caplog.text and str(unknown.id) in caplog.text


def test_only_the_titles_asked_for_are_answered(tracker, session_factory):
    with session_factory() as session:
        one = put_game(session, "Одно", "1", {"expansion": "expansion", "parent": {"id": "9", "name": "X"}})
        two = put_game(session, "Другое", "2", {"expansion": "expansion", "parent": {"id": "9", "name": "X"}})
        session.commit()

        assert pollers_of(tracker).reader_of(TitleKind.GAME).export_extras(session, [two.id]) == {two.id: {"expansion_of": "X"}}
        assert pollers_of(tracker).reader_of(TitleKind.GAME).export_extras(session, []) == {}
        assert one.id != two.id


@pytest.mark.parametrize("kind", [TitleKind.MOVIE, TitleKind.SERIES, TitleKind.ANIME])
def test_a_kind_with_nothing_to_add_answers_nothing(tracker, session_factory, kind):
    with session_factory() as session:
        assert pollers_of(tracker).reader_of(kind).export_extras(session, [1, 2, 3]) == {}


# --- F4: one action for the Feed, the seasons read once -------------------------------------------------------


def put_series_title(session, kind, name, numbers):
    title = Title(kind=kind, name=name, original_name=name, genres=[], status=TitleStatus.WANT, tracking_enabled=True,
                  added_at=NOW, status_changed_at=NOW)
    session.add(title)
    session.flush()
    season = SeasonRecord(title_id=title.id, number=1, name="Сезон 1", episode_count=None, watched=False)
    session.add(season)
    session.flush()
    session.add_all(EpisodeRecord(season_id=season.id, number=n, air_at=moment) for n, moment in numbers.items())
    return title


def basis():
    return FeedBasis(MSK, timedelta(weeks=8), TODAY)


@pytest.mark.parametrize("kind", [TitleKind.SERIES, TitleKind.ANIME])
def test_one_feed_call_reads_the_seasons_once_and_cuts_both_parts_from_them(tracker, session_factory, monkeypatch, kind):
    with session_factory() as session:
        title = put_series_title(session, kind, "Сериал", {1: NOW - timedelta(days=2), 2: NOW + timedelta(days=3)})
        session.commit()
        calls = []
        real = storage.load_seasons_of
        monkeypatch.setattr(storage, "load_seasons_of", lambda *args, **kwargs: calls.append(1) or real(*args, **kwargs))
        shown = {title.id: FeedTitle(title.id, kind, title.name, None)}

        parts = pollers_of(tracker).reader_of(kind).feed(session, shown, basis(), NOW)

    assert len(calls) == 1
    assert isinstance(parts, FeedParts)
    assert [p.text for p in parts.pieces] and [o.episode for o in parts.outs] == [1]


@pytest.mark.parametrize("kind", [TitleKind.MOVIE, TitleKind.GAME])
def test_a_kind_with_no_titles_gives_two_empty_lists(tracker, session_factory, kind):
    with session_factory() as session:
        parts = pollers_of(tracker).reader_of(kind).feed(session, {}, basis(), NOW)

    assert parts == FeedParts([], [])


def test_the_feed_parts_of_one_poller_are_not_shared_with_another():
    assert FeedParts().pieces is not FeedParts().pieces and FeedParts().outs is not FeedParts().outs


# --- F5: a film date is an enum ------------------------------------------------------------------------------


def film(day, which):
    return Out(FeedTitle(1, TitleKind.MOVIE, "Дюна", None), day, datetime.combine(day, datetime.min.time()), which)


def test_a_film_date_is_one_of_two_members_and_an_episode_has_none():
    assert [member.name for member in FilmDate] == ["THEATRICAL", "DIGITAL"]
    assert Out(FeedTitle(1, TitleKind.SERIES, "Х", None), TODAY, NOW).film is None
    assert [o.film for o in feed_released.film_outs(FeedTitle(1, TitleKind.MOVIE, "Дюна", None), TODAY, TODAY, TODAY)] == [
        FilmDate.THEATRICAL, FilmDate.DIGITAL,
    ]


def test_the_words_of_a_film_row_are_read_through_the_table():
    assert FILM_LABELS == {FilmDate.THEATRICAL: feed_rows.THEATRICAL, FilmDate.DIGITAL: feed_rows.DIGITAL}
    assert FILM_LABELS[FilmDate.THEATRICAL] == "Премьера в кино" and FILM_LABELS[FilmDate.DIGITAL] == "Цифровой релиз"


@pytest.mark.parametrize(
    "which, headline, grey",
    [
        (FilmDate.THEATRICAL, "🎬 Дюна — Премьера в кино", "вышла до добавления в список"),
        (FilmDate.DIGITAL, "🎬 Дюна — Цифровой релиз", "вышел до добавления в список"),
    ],
)
def test_the_verb_follows_the_enum(which, headline, grey):
    day = TODAY - timedelta(days=2)
    rows = feed_released.released_rows([film(day, which)], {1: feed_released.Baseline(NOW)}, set())

    assert [(row.headline, row.details) for _, row in rows] == [(headline, (grey,))]


def test_both_dates_of_a_film_on_one_day_are_one_row_that_says_both_came_out():
    day = TODAY - timedelta(days=2)
    rows = feed_released.released_rows(
        [film(day, FilmDate.DIGITAL), film(day, FilmDate.THEATRICAL)], {1: feed_released.Baseline(NOW)}, set()
    )

    assert [(row.headline, row.details) for _, row in rows] == [
        ("🎬 Дюна — Премьера в кино и цифровой релиз", ("вышли до добавления в список",))
    ]


def test_an_event_of_the_log_names_the_film_date_the_row_stands_for():
    day = TODAY - timedelta(days=2)
    out = film(day, FilmDate.DIGITAL)
    named = feed_released.logged([(1, "movie_digital", {})])

    assert out.logged_as in named
    assert film(day, FilmDate.THEATRICAL).logged_as not in named
    assert feed_released.released_rows([out], {1: feed_released.Baseline(NOW)}, named) == []
