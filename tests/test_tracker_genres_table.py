"""The table of synonyms of genres (KI-30): what each source writes, against the live lists of 2026-11-22, the merge, the
match of a title and the address read through the table."""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.tracker import genres
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import Title, TitleKind, TitleStatus

FIXTURES = Path(__file__).parent / "fixtures"
TMDB = json.loads((FIXTURES / "tmdb" / "genres_ru.json").read_text(encoding="utf-8"))
SHIKIMORI = json.loads((FIXTURES / "shikimori" / "genres_ru.json").read_text(encoding="utf-8"))
T0 = datetime(2026, 11, 22, 12, 0)


class Sender:
    async def send(self, message, actions=()):
        pass


def test_every_name_the_table_uses_exists_in_a_live_list():
    tmdb = {genres.key_of(g["name"]) for kind in TMDB.values() for g in kind}
    shikimori = {genres.key_of(g["russian"]) for g in SHIKIMORI}
    written = {
        "Экшен": shikimori, "Тайна": shikimori, "Боевик и Приключения": tmdb, "НФ и Фэнтези": tmdb,
        "Война и Политика": tmdb,
    }

    assert set(genres.SYNONYMS) == {genres.key_of(name) for name in written}
    for name, source in written.items():
        assert genres.key_of(name) in source, name
        for part in genres.counts_as(name):  # a genre one of the lists has («Политика» only stands in the composite)
            assert genres.key_of(part) in tmdb | shikimori or genres.key_of(part) in genres.key_of(name), part


@pytest.mark.parametrize("written, counts", [
    ("Экшен", ("Боевик",)), ("экшен", ("Боевик",)), ("  Тайна ", ("Детектив",)),
    ("Боевик и Приключения", ("Боевик", "Приключения")), ("НФ и Фэнтези", ("Фантастика", "Фэнтези")),
    ("Война и Политика", ("Военный", "Политика")), ("Драма", ("Драма",)), ("Мыльная опера", ("Мыльная опера",)),
    ("Романтика", ("Романтика",)),
])
def test_a_genre_counts_as_what_the_table_says_and_otherwise_as_itself(written, counts):
    assert genres.counts_as(written) == counts


def test_the_owners_mix_gives_one_name_per_genre():
    mix = [
        ["Экшен", "Фэнтези"], ["боевик"], ["Тайна"], ["детектив"], ["НФ и Фэнтези"], ["Фэнтези"],
        ["Боевик и Приключения"], ["Война и Политика"], ["драма"],
    ]

    assert genres.merge(mix) == [
        "Боевик", "Военный", "Детектив", "Драма", "Политика", "Приключения", "Фантастика", "Фэнтези",
    ]


def test_the_keys_of_a_composite_title_hold_every_part():
    assert genres.keys_of(["НФ и Фэнтези", None, "драма"]) == {"фантастика", "фэнтези", "драма"}
    assert genres.keys_of(["Экшен"]) == genres.keys_of(["боевик"])


@pytest.mark.parametrize("asked, key", [
    ("Экшен", "боевик"), ("экшен", "боевик"), ("НФ и Фэнтези", "фантастика"), ("Боевик", "боевик"),
    ("Чёрная комедия", "черная комедия"), ("", ""), ("  ", ""),
])
def test_the_address_is_read_through_the_table(asked, key):
    assert genres.chosen_key(asked) == key


def put(session_factory, name, genre_list, kind=TitleKind.SERIES):
    with session_factory() as session:
        session.add(Title(
            kind=kind, name=name, original_name=name, genres=list(genre_list), status=TitleStatus.WATCHED,
            tracking_enabled=True, added_at=T0, status_changed_at=T0,
        ))
        session.commit()


def make_tracker():
    factory = create_session_factory("sqlite://")
    return factory, Tracker(factory, clock=lambda: T0.replace(tzinfo=timezone.utc), sender=Sender())


def test_the_filter_lists_a_series_of_a_composite_genre_under_each_part():
    factory, tracker = make_tracker()
    put(factory, "Сериал", ["НФ и Фэнтези"])
    put(factory, "Аниме", ["Экшен", "Фэнтези"], TitleKind.ANIME)
    put(factory, "Фильм", ["боевик"], TitleKind.MOVIE)

    def found(genre):
        return sorted(t.name for t in asyncio.run(tracker.list_titles(genre=genre)))

    assert found("Фэнтези") == ["Аниме", "Сериал"]
    assert found("Фантастика") == ["Сериал"]
    assert found("Боевик") == ["Аниме", "Фильм"] and found("Экшен") == ["Аниме", "Фильм"]
    assert found("НФ и Фэнтези") == ["Сериал"]  # a composite name is its first part
    assert asyncio.run(tracker.genres()) == ["Боевик", "Фантастика", "Фэнтези"]


def test_the_card_keeps_the_names_of_the_source():
    factory, tracker = make_tracker()
    put(factory, "Сериал", ["НФ и Фэнтези", "Экшен"])

    [row] = asyncio.run(tracker.list_titles())

    assert asyncio.run(tracker.title_card(row.id)).genres == ["НФ и Фэнтези", "Экшен"]
