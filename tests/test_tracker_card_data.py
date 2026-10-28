"""Tracker core: what the web card needs of the core — the seasons as rows, «Отметить все вышедшие», the poster and
the description, the state-asked-for mark of a season. The bot's card stays as it was (its own tests)."""

import asyncio
import json
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from anime_fakes import FakeAniList, FakeShikimori
from app.tracker import cards, seasons
from app.tracker.cards import format_card
from app.tracker.core import Tracker, UnknownSeason, UnknownTitle
from app.tracker.db import create_session_factory
from app.tracker.models import TitleStatus
from app.tracker.seasons import Episode, Season
from app.tracker.sources.shikimori_anime import ShikimoriAnimeSource
from app.tracker.sources.tmdb_movies import MovieSnapshot
from app.tracker.sources.tmdb_series import SeriesSnapshot, Suggestion, parse_show

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "tmdb"
T0 = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
NOW = datetime(2026, 10, 24, 12, 0)  # naive UTC, as the pure functions take it


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def silo():
    return parse_show(load("tv_125988.json"), {n: load(f"tv_125988_season_{n}.json") for n in (1, 2, 3, 4)})


def weekly(first_day, count):
    start = datetime.fromisoformat(first_day)
    return tuple(Episode(n + 1, start + timedelta(weeks=n)) for n in range(count))


NAMED = SeriesSnapshot(
    external_id="300", name="С именами", original_name="Named", year=2026, genres=["драма"],
    seasons=[
        Season(1, "Сезон 1", 8, weekly("2026-03-02", 8)),
        Season(2, "Магическая битва", 8, weekly("2026-09-07", 8)),
        Season(3, "Season 3", None, ()),
    ],
    poster_path="/named.jpg", overview="Про имена",
)
ANNOUNCED_ONLY = SeriesSnapshot(
    external_id="301", name="Только анонс", original_name="Soon", year=2027, genres=[],
    seasons=[Season(1, "Сезон 1", 6, ())],
)
DUNE = MovieSnapshot(
    external_id="693134", name="Дюна", original_name="Dune", year=2021, genres=["фантастика"],
    poster_path="/dune.jpg", overview="Пол Атрейдес...",
)


class FakeSender:
    async def send(self, message, actions=()):
        pass


class FakeSeriesSource:
    source_key = "tmdb_tv"

    def __init__(self, *snapshots):
        self.by_id = {s.external_id: s for s in snapshots}

    async def suggest(self, query):
        return [Suggestion("series", s.external_id, s.name, s.original_name, s.year) for s in self.by_id.values()]

    async def snapshot(self, external_id):
        return self.by_id.get(external_id)


class FakeMovieSource:
    source_key = "tmdb_movie"

    async def suggest(self, query):
        return []

    async def snapshot(self, external_id):
        return DUNE if external_id == DUNE.external_id else None


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def shikimori():
    return FakeShikimori()


@pytest.fixture
def tracker(shikimori):
    return Tracker(
        create_session_factory("sqlite://"), clock=lambda: T0, sender=FakeSender(),
        sources={
            "series": FakeSeriesSource(silo(), NAMED, ANNOUNCED_ONLY),
            "movie": FakeMovieSource(),
            "anime": ShikimoriAnimeSource(shikimori, FakeAniList()),
        },
    )


def add(tracker, kind, external_id):
    return run(tracker.add_title(kind, external_id)).title_id


def card(tracker, title_id):
    return run(tracker.title_card(title_id))


# --- the mark of a season is the state asked for ---------------------------------------------------------------------

def test_a_season_with_nothing_out_cannot_be_marked_or_unmarked(tracker):
    title = add(tracker, "series", "125988")  # season 4 is announced

    with pytest.raises(UnknownSeason):
        run(tracker.set_season_watched(title, 4, True))
    with pytest.raises(UnknownSeason):
        run(tracker.set_season_watched(title, 4, False))
    assert card(tracker, title).seasons.watched == ()


def test_marking_and_unmarking_ask_for_a_state_so_repeating_changes_nothing(tracker):
    title = add(tracker, "series", "125988")

    run(tracker.set_season_watched(title, 1, True))
    run(tracker.set_season_watched(title, 1, True))
    assert card(tracker, title).seasons.watched == (1,)
    run(tracker.set_season_watched(title, 1, False))
    run(tracker.set_season_watched(title, 1, False))
    assert card(tracker, title).seasons.watched == ()


# --- «Отметить все вышедшие» -----------------------------------------------------------------------------------------

def test_mark_all_released_marks_exactly_the_seasons_with_something_out(tracker):
    title = add(tracker, "series", "125988")

    result = run(tracker.mark_all_released(title))

    assert result.changed is True
    assert card(tracker, title).seasons.watched == (1, 2, 3)  # season 4 is announced and stays unmarked


def test_mark_all_released_recounts_the_status(tracker):
    title = add(tracker, "series", "125988")
    assert card(tracker, title).status == TitleStatus.WANT

    run(tracker.mark_all_released(title))

    assert card(tracker, title).status != TitleStatus.WANT  # every released season is marked: «Жду», «Просмотрено» or «Досмотреть»


def test_mark_all_released_keeps_the_marks_there_are_and_a_repeat_changes_nothing(tracker):
    title = add(tracker, "series", "125988")
    run(tracker.set_season_watched(title, 2, True))

    first = run(tracker.mark_all_released(title))
    second = run(tracker.mark_all_released(title))

    assert (first.changed, second.changed) == (True, False)
    assert card(tracker, title).seasons.watched == (1, 2, 3)


def test_mark_all_released_has_nothing_to_do_for_a_film_or_for_nothing_out(tracker):
    film = add(tracker, "movie", "693134")
    announced_only = add(tracker, "series", "301")

    assert run(tracker.mark_all_released(film)).changed is False
    assert card(tracker, film).status == TitleStatus.WANT
    assert run(tracker.mark_all_released(announced_only)).changed is False
    assert card(tracker, announced_only).seasons.watched == ()


def test_mark_all_released_of_a_missing_title_is_unknown_title(tracker):
    with pytest.raises(UnknownTitle):
        run(tracker.mark_all_released(999))


# --- the rows of the seasons ---------------------------------------------------------------------------------------

def test_the_card_has_a_row_per_season_with_marks_and_the_announcement(tracker):
    title = add(tracker, "series", "125988")
    run(tracker.set_season_watched(title, 1, True))

    rows = card(tracker, title).season_rows

    assert [(r.number, r.watched, r.can_mark) for r in rows] == [(1, True, True), (2, False, True), (3, False, True), (4, False, False)]
    assert rows[0].progress is not None and rows[0].announcement is None
    assert rows[3].progress is None and rows[3].announcement is not None


def test_the_text_of_a_row_is_the_line_of_the_bot_card_with_the_season_name_added(tracker):
    title = add(tracker, "series", "300")
    c = card(tracker, title)

    texts = [cards.season_row_text(r, c.tz) for r in c.season_rows]

    assert texts[0].startswith("Сезон 1: вышло 8 из 8")  # «Сезон 1» is no name worth adding
    assert texts[1].startswith("Сезон 2 — Магическая битва: вышло ")
    assert texts[2] == "Сезон 3 анонсирован, дата не объявлена"  # «Season 3» is the default name, too
    bot_lines = format_card(c).splitlines()
    assert any(line.startswith("Сезон 2: вышло ") for line in bot_lines)  # the bot card has no names


def test_a_bot_card_is_the_same_whatever_the_rows_hold(tracker):
    title = add(tracker, "series", "300")
    c = card(tracker, title)

    from dataclasses import replace
    assert format_card(c) == format_card(replace(c, season_rows=()))


def test_a_season_that_airs_in_parts_shows_the_current_part_in_its_row():
    gap = timedelta(weeks=6)
    parted = Season(1, "Сезон 1", 12, weekly("2026-01-05", 6) + tuple(
        Episode(7 + n, datetime(2026, 9, 14) + timedelta(weeks=n)) for n in range(6)
    ))

    [row] = seasons.rows([parted], [], NOW, gap)

    assert row.progress.part == 2
    assert cards.season_row_text(row).startswith("Сезон 1, часть 2: вышло 6 из 6")


def test_rows_skip_specials_and_come_in_order():
    given = [Season(2, "Б", 4, weekly("2026-01-05", 4)), Season(0, "Спешлы", 2, ()), Season(1, "А", 4, weekly("2025-01-05", 4))]

    assert [r.number for r in seasons.rows(given, {1}, NOW)] == [1, 2]
    assert [r.watched for r in seasons.rows(given, {1}, NOW)] == [True, False]


def test_a_season_label_names_the_season_only_when_it_has_a_name_of_its_own():
    assert cards.season_label(3) == "Сезон 3"
    assert cards.season_label(3, 1) == "Сезон 3, часть 1"
    assert cards.season_label(3, 1, "Сезон 3") == "Сезон 3, часть 1"
    assert cards.season_label(2, None, "SEASON 2") == "Сезон 2"
    assert cards.season_label(2, None, "  ") == "Сезон 2"
    assert cards.season_label(2, None, "Магическая битва: Смертельная миграция") == (
        "Сезон 2 — Магическая битва: Смертельная миграция"
    )


# --- the poster, the description and the films of a franchise ------------------------------------------------------

def test_the_card_carries_the_poster_and_the_description(tracker):
    film = card(tracker, add(tracker, "movie", "693134"))
    series = card(tracker, add(tracker, "series", "300"))

    assert (film.poster_path, film.overview) == ("/dune.jpg", "Пол Атрейдес...")
    assert (series.poster_path, series.overview) == ("/named.jpg", "Про имена")
    assert film.season_rows == () and series.franchise_movies == ()


def test_a_card_without_poster_or_description_has_empty_ones(tracker):
    c = card(tracker, add(tracker, "series", "125988"))

    assert c.poster_path is None or isinstance(c.poster_path, str)
    assert isinstance(c.overview, str)


def test_the_card_of_an_anime_lists_every_film_of_the_franchise_not_the_last_five(tracker, shikimori):
    for index in range(8):  # as the bot's own test of a long list does it: eight films hung on One Piece
        shikimori.by_id[f"9{index}"] = {
            **shikimori.by_id["37514"], "id": f"9{index}", "malId": f"9{index}", "name": f"Film {index}",
            "russian": f"Фильм {index}", "airedOn": {"date": f"20{10 + index}-01-01"},
            "related": [{"relationKind": "prequel", "relationText": "", "anime": {"id": "21", "kind": "tv"}}],
        }
        shikimori.by_id["21"]["related"].append(
            {"relationKind": "sequel", "relationText": "", "anime": {"id": f"9{index}", "kind": "movie"}}
        )

    c = card(tracker, add(tracker, "anime", "21"))

    assert len(c.franchise_movies) == 8  # the bot says «последние пять», the web has all of them
    assert "Фильмы франшизы (8), последние:" in format_card(c)
