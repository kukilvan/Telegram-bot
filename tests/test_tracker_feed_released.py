"""Tracker core: «Недавно» from the schedule (KI-29, spec 2 of stage 9.1c) — what came out in the 7 days before adding
or while the title was in the archive, and is not in the event log: the texts of every row of table 2.2 for both
reasons, folding by part and day, the matching against the log, the window edges, `unknown`, the archive, games, the
films of an anime franchise, the order in a day and the empty «Недавно». Titles, seasons, snapshots and events are put
straight into the database; the clock and the time zone are stand-ins. No network."""

from datetime import datetime, timedelta, timezone

import pytest

from app.tracker import feed_released, movie_events, series_events
from app.tracker.feed_rows import FeedTitle
from app.tracker.models import EpisodeTiming, Event, Title, TitleKind, TitleStatus
from tests.test_tracker_feed import (
    ANIME, MOVIE, NOW, SERIES, TODAY, at, day, episode_text, feed, make_tracker, put_event, put_franchise_movie,
    put_movie_dates, put_season, put_title,
)

DAY, UNKNOWN = EpisodeTiming.DAY, EpisodeTiming.UNKNOWN
BEFORE, ARCHIVE = "до добавления в список", "пока тайтл был в архиве"


@pytest.fixture
def session_factory():
    from app.tracker.db import create_session_factory

    return create_session_factory("sqlite://")


@pytest.fixture
def tracker(session_factory):
    return make_tracker(session_factory)


def put_returned(session_factory, name, kind=SERIES, added=None, restored=None, status=TitleStatus.WANT):
    """A title added at `added` and brought back from the archive at `restored` (naive UTC)."""
    with session_factory() as session:
        title = Title(
            kind=kind, name=name, original_name=name, genres=[], poster_path=None, status=status, tracking_enabled=True,
            added_at=added or NOW, status_changed_at=NOW, restored_at=restored,
        )
        session.add(title)
        session.commit()
        return title.id


def put_for(reason, session_factory, name, kind=SERIES):
    """A title for which what came out in the last days is «before adding» (added now) or «in the archive» (added a
    month ago, returned an hour ago)."""
    if reason == BEFORE:
        return put_returned(session_factory, name, kind)
    return put_returned(session_factory, name, kind, added=NOW - timedelta(days=30), restored=NOW - timedelta(hours=1))


def grey(verb, reason):
    return f"{verb} {reason}" if reason == BEFORE else f"{verb}, {reason}"


def lines(result):
    """«Недавно» as (day, [(headline, details)])."""
    return [(d.day, [(r.headline, r.details) for r in d.rows]) for d in result.recent]


def only_row(result):
    [(_, [row])] = lines(result)
    return row


# --- every row of table 2.2 -----------------------------------------------------------------------------------------


def test_the_example_of_the_spec_reads_word_for_word(tracker, session_factory):
    series = put_title(session_factory, "Одни из нас")
    put_season(session_factory, series, 2, {1: at(-20, 0), 2: at(-13, 0), 3: at(-2, 0)}, timing=DAY)

    assert lines(feed(tracker)) == [(day(-2), [("📺 Одни из нас — Сезон 2, серия 3", ("вышла до добавления в список",))])]


@pytest.mark.parametrize("reason", [BEFORE, ARCHIVE])
def test_the_rows_of_episodes_read_as_the_pieces_of_soon(tracker, session_factory, reason):
    one = put_for(reason, session_factory, "Одна")
    put_season(session_factory, one, 2, {2: at(-13, 0), 3: at(-2, 0)}, timing=DAY)
    several = put_for(reason, session_factory, "Несколько")
    put_season(session_factory, several, 2, {2: at(-13, 0), 3: at(-2, 0), 4: at(-2, 0), 5: at(-2, 0)}, timing=DAY)
    premiere = put_for(reason, session_factory, "Премьера")
    put_season(session_factory, premiere, 3, {1: at(-2, 0), 2: at(5, 0)}, timing=DAY)
    opening = put_for(reason, session_factory, "Премьера с сериями")
    put_season(session_factory, opening, 3, {1: at(-2, 0), 2: at(-2, 0)}, timing=DAY)
    part = put_for(reason, session_factory, "Часть")  # a break of more than six weeks starts part 2
    put_season(session_factory, part, 3, {1: at(-80, 0), 2: at(-73, 0), 3: at(-2, 0)}, timing=DAY)

    assert lines(feed(tracker)) == [(day(-2), [
        ("📺 Несколько — Сезон 2, серии 3–5", (grey("вышли", reason),)),
        ("📺 Одна — Сезон 2, серия 3", (grey("вышла", reason),)),
        ("📺 Премьера — Сезон 3 — премьера", (grey("вышла", reason),)),
        ("📺 Премьера с сериями — Сезон 3 — премьера, серии 1–2", (grey("вышли", reason),)),
        ("📺 Часть — Сезон 3, часть 2 — премьера", (grey("вышла", reason),)),
    ])]


@pytest.mark.parametrize("reason", [BEFORE, ARCHIVE])
def test_the_rows_of_films_read_as_the_pieces_of_soon(tracker, session_factory, reason):
    cinema = put_for(reason, session_factory, "Дюна", MOVIE)
    put_movie_dates(session_factory, cinema, theatrical=day(-3), digital=day(40))
    digital = put_for(reason, session_factory, "Аватар", MOVIE)
    put_movie_dates(session_factory, digital, theatrical=day(-60), digital=day(-3))
    both = put_for(reason, session_factory, "Бэтмен", MOVIE)
    put_movie_dates(session_factory, both, theatrical=day(-3), digital=day(-3))

    assert lines(feed(tracker)) == [(day(-3), [
        ("🎬 Аватар — Цифровой релиз", (grey("вышел", reason),)),
        ("🎬 Бэтмен — Премьера в кино и цифровой релиз", (grey("вышли", reason),)),
        ("🎬 Дюна — Премьера в кино", (grey("вышла", reason),)),
    ])]


def test_an_anime_row_has_its_icon_and_the_day_on_the_owners_clock(tracker, session_factory):
    anime = put_title(session_factory, "Магическая битва", kind=ANIME)
    put_season(session_factory, anime, 3, {4: at(-10, 15), 5: at(-3, 22)}, parts=[(1, None)])  # 01:00 next day in Moscow

    assert lines(feed(tracker)) == [(day(-2), [("🎌 Магическая битва — Сезон 3, серия 5", ("вышла до добавления в список",))])]


def test_a_row_from_the_schedule_has_no_hour_and_no_buttons_and_leads_to_its_title(tracker, session_factory):
    film = put_title(session_factory, "Дюна", kind=MOVIE, poster="/d.jpg")
    put_movie_dates(session_factory, film, theatrical=day(-1))

    row = feed(tracker).recent[0].rows[0]

    assert row.at is None and not row.watched and row.follow is None
    assert row.title == FeedTitle(film, MOVIE, "Дюна", "/d.jpg")


def test_nothing_is_queued_for_a_row_from_the_schedule(tracker, session_factory):
    series = put_title(session_factory, "Одни из нас")
    put_season(session_factory, series, 2, {3: at(-2, 0)}, timing=DAY)

    feed(tracker)

    with session_factory() as session:
        assert session.query(Event).count() == 0


# --- the reasons ----------------------------------------------------------------------------------------------------


def test_a_returned_title_shows_what_came_out_before_adding_and_what_came_out_while_in_the_archive(tracker, session_factory):
    series = put_returned(session_factory, "Укрытие", added=at(-3), restored=at(0, 11))
    put_season(session_factory, series, 2, {2: at(-20, 0), 3: at(-4, 0), 4: at(-1, 0), 5: at(0, 0)}, timing=DAY)

    assert lines(feed(tracker)) == [
        (day(0), [("📺 Укрытие — Сезон 2, серия 5", ("вышла, пока тайтл был в архиве",))]),
        (day(-1), [("📺 Укрытие — Сезон 2, серия 4", ("вышла, пока тайтл был в архиве",))]),
        (day(-4), [("📺 Укрытие — Сезон 2, серия 3", ("вышла до добавления в список",))]),
    ]


def test_what_came_out_after_the_baseline_makes_no_row(tracker, session_factory):
    series = put_returned(session_factory, "Укрытие", added=at(-5), restored=at(-3))
    put_season(session_factory, series, 2, {3: at(-2, 0)}, timing=DAY)  # the checks saw it: the log has it, or had it
    film = put_returned(session_factory, "Дюна", MOVIE, added=at(-5))
    put_movie_dates(session_factory, film, theatrical=day(-2))

    assert feed(tracker).recent == ()


def test_a_series_dated_today_is_out_for_a_title_added_later_that_day(tracker, session_factory):
    series = put_returned(session_factory, "Укрытие", added=at(0, 10))
    put_season(session_factory, series, 2, {2: at(-20, 0), 3: at(0, 0)}, timing=DAY)

    assert lines(feed(tracker)) == [(day(0), [("📺 Укрытие — Сезон 2, серия 3", ("вышла до добавления в список",))])]


# --- folding --------------------------------------------------------------------------------------------------------


def test_the_episodes_of_one_part_on_one_day_are_one_row_and_other_days_stay_apart(tracker, session_factory):
    series = put_title(session_factory, "Укрытие")
    put_season(session_factory, series, 2, {2: at(-13, 0), 3: at(-3, 0), 4: at(-2, 0), 5: at(-2, 0)}, timing=DAY)

    assert lines(feed(tracker)) == [
        (day(-2), [("📺 Укрытие — Сезон 2, серии 4–5", ("вышли до добавления в список",))]),
        (day(-3), [("📺 Укрытие — Сезон 2, серия 3", ("вышла до добавления в список",))]),
    ]


def test_two_parts_of_an_anime_season_on_one_day_are_two_rows(tracker, session_factory):
    anime = put_title(session_factory, "Магическая битва", kind=ANIME)
    put_season(session_factory, anime, 3, {11: at(-9, 12), 12: at(-2, 9), 13: at(-2, 15)}, parts=[(1, 12), (13, 12)])

    assert lines(feed(tracker)) == [(day(-2), [
        ("🎌 Магическая битва — Сезон 3, серия 12", ("вышла до добавления в список",)),
        ("🎌 Магическая битва — Сезон 3, часть 2 — премьера", ("вышла до добавления в список",)),
    ])]


# --- the log --------------------------------------------------------------------------------------------------------


def test_an_episode_with_an_event_shows_once_as_the_event(tracker, session_factory):
    series = put_returned(session_factory, "Укрытие", added=NOW - timedelta(days=30), restored=at(0, 11))
    put_season(session_factory, series, 1, {2: at(-9, 0), 3: at(-2, 0)}, timing=DAY)
    put_event(session_factory, series, series_events.EPISODE_OUT, episode_text("Укрытие", 3), at(-2, 8),
              {"season": 1, "episode": 3})  # reported, then archived, then returned within the week

    assert lines(feed(tracker)) == [(day(-2), [("📺 Укрытие — вышла серия 3 из 10", ("Сезон 1",))])]


@pytest.mark.parametrize("type_", [series_events.SEASON_STARTED, series_events.SEASON_ENDED])
def test_the_start_and_the_end_of_a_season_log_their_episode_too(tracker, session_factory, type_):
    series = put_title(session_factory, "Укрытие")
    put_season(session_factory, series, 1, {1: at(-2, 0)}, timing=DAY)
    put_event(session_factory, series, type_, "📺 Укрытие — событие", at(-2, 8), {"season": 1, "episode": 1})

    assert [r.headline for d in feed(tracker).recent for r in d.rows] == ["📺 Укрытие — событие"]


def test_an_event_found_seven_days_ago_still_logs_an_episode_of_the_first_day(tracker, session_factory):
    series = put_title(session_factory, "Укрытие")
    put_season(session_factory, series, 1, {3: at(-6, 0)}, timing=DAY)
    put_event(session_factory, series, series_events.EPISODE_OUT, "📺 старое", at(-7, 12), {"season": 1, "episode": 3})

    assert feed(tracker).recent == ()  # the event is out of the window, and the episode is logged by it


def test_another_episode_of_the_season_is_not_logged_by_an_event_of_its_neighbour(tracker, session_factory):
    series = put_title(session_factory, "Укрытие")
    put_season(session_factory, series, 1, {2: at(-9, 0), 3: at(-2, 0), 4: at(-2, 0)}, timing=DAY)
    put_event(session_factory, series, series_events.EPISODE_OUT, "📺 серия 3", at(-2, 8), {"season": 1, "episode": 3})

    assert lines(feed(tracker)) == [(day(-2), [
        ("📺 серия 3", ()),
        ("📺 Укрытие — Сезон 1, серия 4", ("вышла до добавления в список",)),
    ])]


def test_a_film_date_with_its_event_shows_once_and_the_other_date_still_has_its_row(tracker, session_factory):
    released = put_title(session_factory, "Дюна", kind=MOVIE)
    put_movie_dates(session_factory, released, theatrical=day(-3), digital=day(-1))
    put_event(session_factory, released, movie_events.RELEASED, "🎬 Дюна — вышел в кино", at(-3, 8))
    digital = put_title(session_factory, "Аватар", kind=MOVIE)
    put_movie_dates(session_factory, digital, theatrical=day(-3), digital=day(-3))
    put_event(session_factory, digital, movie_events.DIGITAL, "🎬 Аватар — вышел цифровой релиз", at(-3, 9))

    assert lines(feed(tracker)) == [
        (day(-1), [("🎬 Дюна — Цифровой релиз", ("вышел до добавления в список",))]),
        (day(-3), [
            ("🎬 Аватар — вышел цифровой релиз", ()),
            ("🎬 Дюна — вышел в кино", ()),
            ("🎬 Аватар — Премьера в кино", ("вышла до добавления в список",)),
        ]),
    ]


def test_the_events_of_another_title_of_the_same_show_are_not_its_own(tracker, session_factory):
    """A title deleted and added again has a new number: the events of the old one name another title."""
    old = put_title(session_factory, "Укрытие")
    put_event(session_factory, old, series_events.EPISODE_OUT, "📺 старый", at(-2, 8), {"season": 1, "episode": 3})
    with session_factory() as session:
        session.get(Title, old).status = TitleStatus.DROPPED  # in the archive: no row of its own from the schedule
        session.commit()
    again = put_title(session_factory, "Укрытие")
    put_season(session_factory, again, 1, {2: at(-9, 0), 3: at(-2, 0)}, timing=DAY)

    assert lines(feed(tracker)) == [(day(-2), [
        ("📺 старый", ()),
        ("📺 Укрытие — Сезон 1, серия 3", ("вышла до добавления в список",)),
    ])]


# --- what never makes a row -----------------------------------------------------------------------------------------


def test_the_window_holds_today_minus_6_to_today_and_nothing_after_now(tracker, session_factory):
    series = put_title(session_factory, "Укрытие")
    put_season(session_factory, series, 1, {1: at(-7, 0), 2: at(-6, 0)}, timing=DAY)
    film = put_title(session_factory, "Дюна", kind=MOVIE)
    put_movie_dates(session_factory, film, theatrical=day(-7), digital=day(1))
    anime = put_returned(session_factory, "Фрирен", ANIME, added=at(1))  # an anime episode later today is not out yet
    put_season(session_factory, anime, 1, {1: at(-20, 0), 2: at(0, 11), 3: at(0, 13)}, parts=[(1, None)])

    assert lines(feed(tracker)) == [
        (day(0), [("🎌 Фрирен — Сезон 1, серия 2", ("вышла до добавления в список",))]),
        (day(-6), [("📺 Укрытие — Сезон 1, серия 2", ("вышла до добавления в список",))]),
    ]


def test_an_episode_whose_moment_a_check_found_makes_no_row(tracker, session_factory):
    anime = put_title(session_factory, "Монолог фармацевта", kind=ANIME)
    put_season(session_factory, anime, 1, {6: at(-9), 7: at(-2)}, parts=[(1, None)], timing=UNKNOWN)

    assert feed(tracker).recent == ()


def test_a_title_in_the_archive_a_game_and_a_film_of_an_anime_franchise_make_no_row(tracker, session_factory):
    for status in (TitleStatus.WATCHED, TitleStatus.DROPPED):
        series = put_title(session_factory, f"Архив {status}", status=status)
        put_season(session_factory, series, 1, {3: at(-2, 0)}, timing=DAY)
    film = put_title(session_factory, "Брошенный фильм", kind=MOVIE, status=TitleStatus.DROPPED)
    put_movie_dates(session_factory, film, theatrical=day(-2))
    put_title(session_factory, "Elden Ring", kind=TitleKind.GAME)
    anime = put_title(session_factory, "Магическая битва", kind=ANIME, status=TitleStatus.WAITING)
    put_franchise_movie(session_factory, anime, "Магическая битва 0", day(-2), released=True)

    assert feed(tracker).recent == ()


# --- the order and the empty «Недавно» ------------------------------------------------------------------------------


def test_in_a_day_the_events_come_first_then_the_rows_from_the_schedule_by_name_title_and_season(tracker, session_factory):
    for name in ("Яблоко", "арбуз"):
        put_season(session_factory, put_title(session_factory, name), 1, {2: at(-9, 0), 3: at(-2, 0)}, timing=DAY)
    twice = put_title(session_factory, "Пацаны")
    put_season(session_factory, twice, 3, {1: at(-2, 0)}, timing=DAY)
    put_season(session_factory, twice, 2, {7: at(-12, 0), 8: at(-2, 0)}, timing=DAY)
    other = put_title(session_factory, "Пацаны")
    put_season(session_factory, other, 1, {1: at(-9, 0), 2: at(-2, 0)}, timing=DAY)
    logged = put_returned(session_factory, "Юг", added=at(-30))
    put_event(session_factory, logged, "x", "событие раньше", at(-2, 6))
    put_event(session_factory, logged, "x", "событие позже", at(-2, 9))

    assert [r.headline for r in feed(tracker).recent[0].rows] == [
        "событие позже", "событие раньше",
        "📺 арбуз — Сезон 1, серия 3",
        "📺 Пацаны — Сезон 2, серия 8", "📺 Пацаны — Сезон 3 — премьера",
        "📺 Пацаны — Сезон 1, серия 2",
        "📺 Яблоко — Сезон 1, серия 3",
    ]


def test_recent_is_empty_only_when_there_are_neither_events_nor_rows_from_the_schedule(tracker, session_factory):
    series = put_title(session_factory, "Укрытие")
    put_season(session_factory, series, 2, {3: at(-2, 0)}, timing=DAY)

    result = feed(tracker)

    assert result.recent != () and result.upcoming == ()


# --- the pure part --------------------------------------------------------------------------------------------------


def test_before_adding_wins_over_in_the_archive():
    baseline = feed_released.Baseline(added_at=datetime(2026, 10, 20), restored_at=datetime(2026, 10, 29))

    assert baseline.reason(datetime(2026, 10, 19)) == feed_released.Reason.BEFORE_ADDING
    assert baseline.reason(datetime(2026, 10, 20)) == feed_released.Reason.BEFORE_ADDING  # at the moment of adding: out
    assert baseline.reason(datetime(2026, 10, 25)) == feed_released.Reason.IN_ARCHIVE
    assert baseline.reason(datetime(2026, 10, 30)) is None
    assert feed_released.Baseline(datetime(2026, 10, 20)).reason(datetime(2026, 10, 25)) is None


def test_the_log_is_read_by_title_season_and_episode_and_by_film_date():
    logged = feed_released.logged([
        (1, series_events.EPISODE_OUT, {"season": 2, "episode": 3}),
        (1, series_events.DATE_MOVED, {"season": 2, "episode": 4}),  # not an episode out
        (2, movie_events.RELEASED, {}),
        (3, series_events.EPISODE_OUT, {"season": 1}),  # broken: no episode
    ])

    assert logged == {(1, 2, 3), (2, feed_released.FILM_TYPES[movie_events.RELEASED])}


def test_the_window_is_today_minus_6_to_today():
    assert feed_released.window(TODAY) == (day(-6), day(0))


def test_the_zone_west_of_utc_keeps_the_sources_day(session_factory):
    tracker = make_tracker(session_factory, tz=timezone(timedelta(hours=-5)))
    series = put_title(session_factory, "Укрытие")
    put_season(session_factory, series, 2, {2: at(-12, 0), 3: at(-6, 0)}, timing=DAY)

    assert [d.day for d in feed(tracker).recent] == [day(-6)]
