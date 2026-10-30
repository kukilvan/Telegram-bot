"""Tracker core: the feed (`Tracker.feed()`) — «Скоро» by days, «Позже», «Недавно», the owner's clock, the rows and their
buttons, one read whatever the number of titles. Titles, seasons, snapshots and events are put straight into the
database, so the dates are exactly what a test needs; the clock and the time zone are stand-ins. No network."""

import asyncio
from datetime import date, datetime, time, timedelta, timezone

import pytest
from sqlalchemy import event as sa_event

from app.tracker import failures, feed_rows, movie_events, sequel_events
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import (
    EpisodeRecord, Event, ExternalId, MovieRecord, PartRecord, SeasonRecord, SourceSnapshot, Title, TitleKind, TitleStatus,
)
from app.tracker.series_events import EPISODE_OUT

NOW = datetime(2026, 10, 30, 12, 0)  # a Friday, naive UTC like everything stored
TODAY = NOW.date()
MSK = timezone(timedelta(hours=3))
SERIES, ANIME, MOVIE = TitleKind.SERIES, TitleKind.ANIME, TitleKind.MOVIE


class FakeSender:
    async def send(self, message, actions=()):
        pass


class FakeMovieSource:
    source_key = "tmdb_movie"

    async def suggest(self, query):
        return []

    async def snapshot(self, external_id):
        return None


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


def make_tracker(session_factory, tz=MSK, now=NOW):
    return Tracker(
        session_factory, clock=lambda: now.replace(tzinfo=timezone.utc), sender=FakeSender(),
        sources={"movie": FakeMovieSource()}, default_tz=tz,
    )


@pytest.fixture
def tracker(session_factory):
    return make_tracker(session_factory)


def at(days, hour=12, minute=0):
    """A naive UTC moment `days` after today."""
    return datetime.combine(TODAY + timedelta(days=days), time(hour, minute))


def day(days):
    return TODAY + timedelta(days=days)


def put_title(session_factory, name, kind=SERIES, status=TitleStatus.WANT, poster=None):
    with session_factory() as session:
        title = Title(
            kind=kind, name=name, original_name=name, genres=[], poster_path=poster, status=status,
            tracking_enabled=True, added_at=NOW, status_changed_at=NOW,
        )
        session.add(title)
        session.commit()
        return title.id


def put_season(session_factory, title_id, number, episodes, parts=()):
    """`episodes`: number → moment (None: no date); `parts`: (first episode, count) of the source entries of an anime."""
    with session_factory() as session:
        record = SeasonRecord(title_id=title_id, number=number, name=f"Сезон {number}", episode_count=None, watched=False)
        session.add(record)
        session.flush()
        session.add_all(EpisodeRecord(season_id=record.id, number=n, air_at=moment) for n, moment in episodes.items())
        session.add_all(
            PartRecord(title_id=title_id, season_id=record.id, number=index, first_episode=first, episode_count=count,
                       shikimori_id=f"{title_id}-{number}-{index}")
            for index, (first, count) in enumerate(parts, 1)
        )
        session.commit()


def put_movie_dates(session_factory, title_id, theatrical=None, digital=None, external_id=None):
    with session_factory() as session:
        external_id = external_id or str(title_id)
        session.add(ExternalId(title_id=title_id, source="tmdb_movie", external_id=external_id, role="primary"))
        state = movie_events.MovieDates(theatrical, digital).to_state()
        session.add(SourceSnapshot(title_id=title_id, source="tmdb_movie", state=state, observed_at=NOW))
        session.commit()


def put_franchise_movie(session_factory, title_id, name, aired_on, released=False):
    with session_factory() as session:
        session.add(MovieRecord(title_id=title_id, name=name, aired_on=aired_on, released=released,
                                shikimori_id=f"m-{name}"))
        session.commit()


def put_event(session_factory, title_id, type_, text, found, data=None, key=None):
    with session_factory() as session:
        session.add(Event(type=type_, title_id=title_id, payload={"text": text, **(data or {})},
                          dedup_key=key or f"{type_}:{title_id}:{found.isoformat()}:{text}", detected_at=found))
        session.commit()


def episode_text(name, number):
    return f"📺 {name} — вышла серия {number} из 10\nСезон 1"


def feed(tracker):
    return run(tracker.feed())


def soon(result):
    """«Скоро» as (day, [(name, text, hour)])."""
    return [(d.day, [(r.title.name, r.text, r.at) for r in d.rows]) for d in result.upcoming]


def later(result):
    return [(r.title.name, r.day, r.text) for r in result.later]


def recent(result):
    return [(d.day, [r.headline for r in d.rows]) for d in result.recent]


# --- «Скоро» and «Позже»: the days ----------------------------------------------------------------------------------


def test_soon_holds_today_to_today_plus_13_and_the_next_day_goes_later(tracker, session_factory):
    near = put_title(session_factory, "Укрытие")
    put_season(session_factory, near, 2, {4: at(-1), 5: at(0), 6: at(13)})
    far = put_title(session_factory, "Пацаны")
    put_season(session_factory, far, 5, {1: at(14), 2: at(21)})

    result = feed(tracker)

    assert soon(result) == [
        (day(0), [("Укрытие", "Сезон 2, серия 5", None)]),
        (day(13), [("Укрытие", "Сезон 2, серия 6", None)]),
    ]
    assert later(result) == [("Пацаны", day(14), "Сезон 5 — премьера")]  # only the nearest date


def test_a_title_with_a_row_in_the_two_weeks_is_not_repeated_later(tracker, session_factory):
    weekly = put_title(session_factory, "Укрытие")
    put_season(session_factory, weekly, 2, {5: at(3), 6: at(10), 7: at(17), 8: at(24)})

    result = feed(tracker)

    assert [d.day for d in result.upcoming] == [day(3), day(10)]
    assert result.later == ()


def test_later_is_by_date_then_by_name_with_the_full_row(tracker, session_factory):
    for name, days in (("Яблоко", 40), ("Арбуз", 40), ("Банан", 20)):
        put_season(session_factory, put_title(session_factory, name), 1, {1: at(days), 2: at(days)})

    assert later(feed(tracker)) == [
        ("Банан", day(20), "Сезон 1 — премьера, серии 1–2"),
        ("Арбуз", day(40), "Сезон 1 — премьера, серии 1–2"),
        ("Яблоко", day(40), "Сезон 1 — премьера, серии 1–2"),
    ]


def test_an_episode_without_a_date_and_an_archived_title_are_not_in_the_feed(tracker, session_factory):
    undated = put_title(session_factory, "Без даты")
    put_season(session_factory, undated, 1, {1: None, 2: None})
    for status in (TitleStatus.WATCHED, TitleStatus.DROPPED):
        archived = put_title(session_factory, f"Архив {status}", status=status)
        put_season(session_factory, archived, 3, {1: at(2)})
    film = put_title(session_factory, "Брошенный фильм", kind=MOVIE, status=TitleStatus.DROPPED)
    put_movie_dates(session_factory, film, theatrical=day(2))

    result = feed(tracker)

    assert result.upcoming == () and result.later == ()
    assert result.has_titles


# --- the owner's clock ----------------------------------------------------------------------------------------------


def test_an_anime_episode_late_in_the_utc_evening_is_tomorrow_on_the_owners_clock(tracker, session_factory):
    anime = put_title(session_factory, "Магическая битва", kind=ANIME)
    put_season(session_factory, anime, 3, {4: at(-1), 5: at(0, 23, 30)}, parts=[(1, None)])

    assert soon(feed(tracker)) == [(day(1), [("Магическая битва", "Сезон 3, серия 5", time(2, 30))])]


def test_a_tmdb_date_is_the_day_as_the_source_gives_it_whatever_the_time_zone(session_factory):
    tracker = make_tracker(session_factory, tz=timezone(timedelta(hours=-5)))
    series = put_title(session_factory, "Укрытие")
    put_season(session_factory, series, 2, {4: at(-7, 0), 5: at(3, 0)})  # TMDb: midnight of the day

    assert soon(feed(tracker)) == [(day(3), [("Укрытие", "Сезон 2, серия 5", None)])]


def test_an_anime_moment_at_exactly_midnight_utc_is_a_day_without_an_hour(tracker, session_factory):
    anime = put_title(session_factory, "Фрирен", kind=ANIME)
    put_season(session_factory, anime, 2, {1: at(5, 0)}, parts=[(1, None)])

    assert soon(feed(tracker)) == [(day(5), [("Фрирен", "Сезон 2 — премьера", None)])]


def test_today_is_the_date_on_the_owners_clock(session_factory):
    late = datetime.combine(TODAY, time(22, 0))  # 01:00 tomorrow in Moscow
    tracker = make_tracker(session_factory, now=late)
    series = put_title(session_factory, "Укрытие")
    put_season(session_factory, series, 2, {4: at(0, 0), 5: at(1, 0)})

    assert [d.day for d in feed(tracker).upcoming] == [day(1)]


def test_today_shows_what_is_out_already(tracker, session_factory):
    anime = put_title(session_factory, "Магическая битва", kind=ANIME)
    put_season(session_factory, anime, 3, {4: at(-7, 7), 5: at(0, 7)}, parts=[(1, None)])  # 10:00 in Moscow, it is 15:00

    assert soon(feed(tracker)) == [(day(0), [("Магическая битва", "Сезон 3, серия 5", time(10, 0))])]


# --- what a row says --------------------------------------------------------------------------------------------------


def test_several_episodes_of_a_season_on_one_day_are_one_row_with_a_range(tracker, session_factory):
    series = put_title(session_factory, "Укрытие")
    put_season(session_factory, series, 2, {4: at(-7), 5: at(2), 6: at(2), 7: at(2), 8: at(2), 10: at(4)})

    assert soon(feed(tracker)) == [
        (day(2), [("Укрытие", "Сезон 2, серии 5–8", None)]),
        (day(4), [("Укрытие", "Сезон 2, серия 10", None)]),
    ]


def test_the_first_episode_of_a_season_is_its_premiere_with_the_rest_of_the_day(tracker, session_factory):
    alone = put_title(session_factory, "Пацаны")
    put_season(session_factory, alone, 3, {1: at(2), 2: at(9)})
    whole = put_title(session_factory, "Укрытие")
    put_season(session_factory, whole, 2, {n: at(3) for n in range(1, 9)})

    assert soon(feed(tracker)) == [
        (day(2), [("Пацаны", "Сезон 3 — премьера", None)]),
        (day(3), [("Укрытие", "Сезон 2 — премьера, серии 1–8", None)]),
        (day(9), [("Пацаны", "Сезон 3, серия 2", None)]),
    ]


def test_the_first_episode_of_a_later_part_is_the_premiere_of_the_part(tracker, session_factory):
    series = put_title(session_factory, "Уэнсдэй")  # a break of more than six weeks (the default) splits the season
    put_season(session_factory, series, 2, {1: at(-80), 2: at(-73), 3: at(5), 4: at(5), 5: at(12)})
    anime = put_title(session_factory, "Магическая битва", kind=ANIME)  # anime: the parts are entries of the source
    put_season(session_factory, anime, 3, {12: at(-7, 15), 13: at(6, 15)}, parts=[(1, 12), (13, 12)])

    assert soon(feed(tracker)) == [
        (day(5), [("Уэнсдэй", "Сезон 2, часть 2 — премьера, серии 3–4", None)]),
        (day(6), [("Магическая битва", "Сезон 3, часть 2 — премьера", time(18, 0))]),
        (day(12), [("Уэнсдэй", "Сезон 2, серия 5", None)]),
    ]


def test_a_film_has_its_two_dates_and_one_row_when_they_fall_on_one_day(tracker, session_factory):
    apart = put_title(session_factory, "Дюна", kind=MOVIE)
    put_movie_dates(session_factory, apart, theatrical=day(1), digital=day(40))
    together = put_title(session_factory, "Аватар", kind=MOVIE)
    put_movie_dates(session_factory, together, theatrical=day(2), digital=day(2))
    out = put_title(session_factory, "Вышедший", kind=MOVIE)
    put_movie_dates(session_factory, out, theatrical=day(-30), digital=day(-1))

    result = feed(tracker)

    assert soon(result) == [
        (day(1), [("Дюна", "Премьера в кино", None)]),
        (day(2), [("Аватар", "Премьера в кино и цифровой релиз", None)]),
    ]
    assert later(result) == []  # «Дюна» has a row in the two weeks: its digital release is not repeated later


def test_a_film_of_an_anime_franchise_not_out_yet(tracker, session_factory):
    anime = put_title(session_factory, "Магическая битва", kind=ANIME, status=TitleStatus.WAITING)
    put_franchise_movie(session_factory, anime, "Магическая битва 0", day(4))
    put_franchise_movie(session_factory, anime, "Вышедший фильм", day(5), released=True)
    put_franchise_movie(session_factory, anime, "Без даты", None)

    assert soon(feed(tracker)) == [(day(4), [("Магическая битва", "Фильм «Магическая битва 0»", None)])]


def test_everything_of_a_title_on_one_day_is_one_row(tracker, session_factory):
    series = put_title(session_factory, "Пацаны")
    put_season(session_factory, series, 3, {1: at(5)})
    put_season(session_factory, series, 2, {7: at(-7), 8: at(5)})

    assert soon(feed(tracker)) == [(day(5), [("Пацаны", "Сезон 2, серия 8; Сезон 3 — премьера", None)])]


def test_in_a_day_the_rows_without_an_hour_come_first_by_name_then_the_rest_by_the_hour(tracker, session_factory):
    for name in ("Яблоко", "арбуз"):
        put_season(session_factory, put_title(session_factory, name), 1, {3: at(2, 0)})
    for name, hour in (("Позднее", 15), ("Раннее", 9)):
        put_season(session_factory, put_title(session_factory, name, kind=ANIME), 1, {3: at(2, hour)}, parts=[(1, None)])

    assert [name for name, _, _ in soon(feed(tracker))[0][1]] == ["арбуз", "Яблоко", "Раннее", "Позднее"]


def test_a_row_carries_its_title(tracker, session_factory):
    series = put_title(session_factory, "Укрытие", poster="/p.jpg")
    put_season(session_factory, series, 2, {5: at(2)})

    row = feed(tracker).upcoming[0].rows[0]

    assert row.title == feed_rows.FeedTitle(series, SERIES, "Укрытие", "/p.jpg")


# --- «Недавно» --------------------------------------------------------------------------------------------------------


def test_recent_holds_today_to_today_minus_6_on_the_owners_clock_latest_first(tracker, session_factory):
    series = put_title(session_factory, "Укрытие")
    start_of_day_6 = datetime.combine(day(-6), time(0)) - timedelta(hours=3)  # midnight in Moscow
    put_event(session_factory, series, "x", "шесть дней назад", start_of_day_6)
    put_event(session_factory, series, "x", "семь дней назад", start_of_day_6 - timedelta(minutes=1))
    put_event(session_factory, series, "x", "сегодня утром", at(0, 6))
    put_event(session_factory, series, "x", "сегодня днём", at(0, 10))

    assert recent(feed(tracker)) == [(day(0), ["сегодня днём", "сегодня утром"]), (day(-6), ["шесть дней назад"])]


def test_recent_holds_the_events_of_dropped_and_watched_titles_but_no_failures_and_no_test_events(tracker, session_factory):
    dropped = put_title(session_factory, "Брошенный", status=TitleStatus.DROPPED)
    watched = put_title(session_factory, "Дюна", kind=MOVIE, status=TitleStatus.WATCHED)
    put_event(session_factory, dropped, EPISODE_OUT, "📺 Брошенный — вышла серия 3\nСезон 1", at(0, 8))
    put_event(session_factory, watched, sequel_events.SEQUEL_ANNOUNCED, "🎬 Анонсировано продолжение", at(0, 9))
    put_event(session_factory, watched, failures.SOURCE_FAILED, "Не удалось проверить", at(0, 10))
    put_event(session_factory, None, "test", "Тестовое", at(0, 11))

    rows = feed(tracker).recent[0].rows

    assert [r.headline for r in rows] == ["🎬 Анонсировано продолжение", "📺 Брошенный — вышла серия 3"]
    assert rows[1].details == ("Сезон 1",)  # the other lines of the message, apart
    assert rows[1].at == datetime.combine(TODAY, time(11, 0))  # on the owner's clock


def test_a_deleted_title_leaves_the_feed(tracker, session_factory):
    series = put_title(session_factory, "Укрытие")
    put_season(session_factory, series, 2, {5: at(2)})
    put_event(session_factory, series, "x", "событие", at(0, 8))

    run(tracker.delete_title(series))
    result = feed(tracker)

    assert result.upcoming == () and result.recent == () and not result.has_titles


def test_episodes_of_one_season_found_on_one_day_are_folded_as_in_the_summary(tracker, session_factory):
    series = put_title(session_factory, "Укрытие")
    other = put_title(session_factory, "Пацаны")
    for number, hour in ((5, 6), (6, 9)):
        put_event(session_factory, series, EPISODE_OUT, episode_text("Укрытие", number), at(0, hour),
                  {"season": 1, "episode": number})
    put_event(session_factory, other, EPISODE_OUT, episode_text("Пацаны", 2), at(0, 7), {"season": 1, "episode": 2})
    put_event(session_factory, series, EPISODE_OUT, episode_text("Укрытие", 4), at(-1, 9), {"season": 1, "episode": 4})

    result = feed(tracker)

    assert recent(result) == [
        (day(0), ["📺 Укрытие — вышли серии 5–6", "📺 Пацаны — вышла серия 2 из 10"]),
        (day(-1), ["📺 Укрытие — вышла серия 4 из 10"]),
    ]
    assert result.recent[0].rows[0].at == datetime.combine(TODAY, time(12, 0))  # the latest of the folded ones


# --- the buttons of «Недавно» -----------------------------------------------------------------------------------------


def test_watched_is_offered_under_a_movie_event_only_while_the_movie_is_wanted(tracker, session_factory):
    wanted = put_title(session_factory, "Дюна", kind=MOVIE)
    seen = put_title(session_factory, "Аватар", kind=MOVIE, status=TitleStatus.WATCHED)
    series = put_title(session_factory, "Укрытие")
    put_event(session_factory, wanted, movie_events.RELEASED, "🎬 Дюна — вышел в кино", at(0, 6))
    put_event(session_factory, seen, movie_events.DIGITAL, "🎬 Аватар — цифровой релиз", at(0, 7))
    put_event(session_factory, series, EPISODE_OUT, "📺 Укрытие — вышла серия 5", at(0, 8), {"season": 1, "episode": 5})

    rows = {r.title.name: r for r in feed(tracker).recent[0].rows}

    assert rows["Дюна"].watched and not rows["Аватар"].watched and not rows["Укрытие"].watched
    assert all(r.follow is None for r in rows.values())


def test_follow_is_offered_under_a_sequel_announcement_with_its_title_when_the_list_has_it(tracker, session_factory):
    dune = put_title(session_factory, "Дюна", kind=MOVIE, status=TitleStatus.WATCHED)
    three = put_title(session_factory, "Дюна: Часть третья", kind=MOVIE)
    put_movie_dates(session_factory, three, external_id="3")
    for sequel_id, hour in (("3", 6), ("4", 7)):
        put_event(session_factory, dune, sequel_events.SEQUEL_ANNOUNCED, f"🎬 Анонсировано продолжение {sequel_id}",
                  at(0, hour), {"kind": "movie", "sequel_id": sequel_id})
    put_event(session_factory, dune, sequel_events.SEQUEL_ANNOUNCED, "🎬 Старый формат", at(0, 8))

    rows = {r.headline: r for r in feed(tracker).recent[0].rows}

    assert rows["🎬 Анонсировано продолжение 3"].follow == feed_rows.SequelOffer(MOVIE, "3", three)
    assert rows["🎬 Анонсировано продолжение 4"].follow == feed_rows.SequelOffer(MOVIE, "4", None)
    assert rows["🎬 Старый формат"].follow is None
    assert not any(r.watched for r in rows.values())


# --- empty places -----------------------------------------------------------------------------------------------------


def test_an_empty_list_has_an_empty_feed(tracker):
    result = feed(tracker)

    assert result == feed_rows.Feed((), (), (), has_titles=False)


def test_a_list_with_nothing_coming_and_nothing_found(tracker, session_factory):
    put_title(session_factory, "Тихий")

    result = feed(tracker)

    assert result == feed_rows.Feed((), (), (), has_titles=True)


# --- one read ---------------------------------------------------------------------------------------------------------


def fill(session_factory, count):
    for n in range(count):
        series = put_title(session_factory, f"Сериал {n}")
        put_season(session_factory, series, 1, {1: at(-3), 2: at(4)})
        put_event(session_factory, series, EPISODE_OUT, episode_text(f"Сериал {n}", 1), at(-3), {"season": 1, "episode": 1})
        anime = put_title(session_factory, f"Аниме {n}", kind=ANIME)
        put_season(session_factory, anime, 1, {1: at(2, 15)}, parts=[(1, None)])
        put_franchise_movie(session_factory, anime, f"Фильм {n}", day(30))
        film = put_title(session_factory, f"Фильм {n}", kind=MOVIE, status=TitleStatus.WATCHED)
        put_event(session_factory, film, sequel_events.SEQUEL_ANNOUNCED, "🎬 Анонс", at(-1),
                  {"kind": "movie", "sequel_id": f"s{n}"})
        wanted = put_title(session_factory, f"Новый {n}", kind=MOVIE)
        put_movie_dates(session_factory, wanted, theatrical=day(9))


def count_reads(session_factory, tracker):
    statements = []
    engine = session_factory.kw["bind"]

    def note(conn, cursor, statement, *args):
        statements.append(statement)

    sa_event.listen(engine, "before_cursor_execute", note)
    try:
        result = feed(tracker)
    finally:
        sa_event.remove(engine, "before_cursor_execute", note)
    return len(statements), result


def test_the_feed_reads_as_much_for_one_title_of_each_sort_as_for_fifty():
    one, fifty = create_session_factory("sqlite://"), create_session_factory("sqlite://")
    fill(one, 1)
    fill(fifty, 50)

    reads_one, small = count_reads(one, make_tracker(one))
    reads_fifty, big = count_reads(fifty, make_tracker(fifty))

    assert reads_one == reads_fifty
    assert len(big.upcoming[0].rows) == 50 and len(big.recent) == 2  # the fifty were really read


# --- KI-10: «Посмотрел» is no check of a source -----------------------------------------------------------------------


class FakeSequelSource:
    source_key = "tmdb_sequels"

    async def snapshot(self, external_id):
        from app.tracker.sources.tmdb_sequels import SequelSnapshot

        return SequelSnapshot(own_date=date(2021, 9, 15), parts=[])


class FakeReleaseSource(FakeMovieSource):
    async def snapshot(self, external_id):
        from app.tracker.sources.tmdb_movies import MovieSnapshot

        return MovieSnapshot(external_id=external_id, name="Дюна", original_name="Dune", year=2021, genres=[])


def test_watched_does_not_move_the_last_check_and_the_first_real_sequel_check_does(session_factory):
    moments = [NOW]
    tracker = Tracker(
        session_factory, clock=lambda: moments[-1].replace(tzinfo=timezone.utc), sender=FakeSender(),
        sources={"movie": FakeReleaseSource()}, sequel_sources={"movie": FakeSequelSource()}, default_tz=timezone.utc,
    )
    title_id = run(tracker.add_title("movie", "1")).title_id
    added = run(tracker.overview()).last_check_at

    moments.append(NOW + timedelta(hours=1))
    run(tracker.mark_watched(title_id))
    assert run(tracker.overview()).last_check_at == added

    moments.append(NOW + timedelta(hours=2))
    run(tracker.poll_due())
    assert run(tracker.overview()).last_check_at == moments[-1].replace(tzinfo=timezone.utc)


def test_the_sequels_know_whether_their_source_has_answered():
    assert not sequel_events.Sequels.from_state({}).checked
    assert sequel_events.Sequels.from_state({"own_date": None, "parts": []}).checked
    assert sequel_events.Sequels().checked  # what a source hands over has been looked at
