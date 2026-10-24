"""TMDb sequel adapter: saved real TMDb responses (tests/fixtures/tmdb) become a collection snapshot.

No network: the fixtures were fetched once through TMDbProvider; the adapter only turns responses into data.
"""

import asyncio
import json
import pathlib
from datetime import date

import pytest

from app.tracker.sources.tmdb_sequels import TmdbSequelSource, parse_sequels

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "tmdb"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def run(coro):
    return asyncio.run(coro)


class FakeProvider:
    """Stands in for TMDbProvider: serves the saved responses, 404 (None) for anything else."""

    def __init__(self, collection_missing=False):
        self.collections_asked = []
        self.collection_missing = collection_missing

    async def get_movie_with_release_dates(self, movie_id):
        try:
            return load(f"movie_{movie_id}.json")
        except FileNotFoundError:
            return None

    async def get_collection(self, collection_id):
        self.collections_asked.append(collection_id)
        if self.collection_missing:
            return None
        return load(f"collection_{collection_id}.json")


def test_other_movies_of_the_collection_become_parts_and_the_movie_itself_is_left_out():
    snapshot = parse_sequels(load("movie_438631.json"), load("collection_726871.json"))

    assert snapshot.own_date == date(2021, 9, 15)
    assert [(p.external_id, p.title, p.release_date) for p in snapshot.parts] == [
        ("693134", "Дюна: Часть вторая", date(2024, 2, 27)),
        ("1170608", "Дюна: Часть третья", date(2026, 12, 15)),
    ]


def test_movie_outside_any_collection_has_no_parts():
    movie = {"id": 7, "release_date": "2020-01-01", "belongs_to_collection": None}

    snapshot = parse_sequels(movie, None)

    assert snapshot.parts == []
    assert snapshot.own_date == date(2020, 1, 1)


def test_part_without_a_release_date_is_kept_with_no_date():
    movie = {"id": 7, "release_date": "2020-01-01"}
    collection = {"parts": [{"id": 7, "title": "Сам"}, {"id": 8, "title": "Анонс", "release_date": ""}]}

    [part] = parse_sequels(movie, collection).parts

    assert (part.external_id, part.release_date) == ("8", None)


def test_snapshot_state_is_plain_json_for_storage():
    state = parse_sequels(load("movie_438631.json"), load("collection_726871.json")).state()

    assert state["own_date"] == "2021-09-15"
    assert state["parts"][0] == {"id": "693134", "title": "Дюна: Часть вторая", "date": "2024-02-27"}
    json.dumps(state)


def test_source_reads_the_movie_then_its_collection():
    provider = FakeProvider()

    snapshot = run(TmdbSequelSource(provider).snapshot("438631"))

    assert provider.collections_asked == [726871]
    assert len(snapshot.parts) == 2


def test_source_does_not_ask_for_a_collection_when_the_movie_has_none(monkeypatch):
    provider = FakeProvider()

    async def standalone(movie_id):
        return {"id": movie_id, "release_date": "2020-01-01", "belongs_to_collection": None}

    monkeypatch.setattr(provider, "get_movie_with_release_dates", standalone)

    snapshot = run(TmdbSequelSource(provider).snapshot("7"))

    assert provider.collections_asked == []
    assert snapshot.parts == []


def test_source_snapshot_of_a_missing_movie_is_none():
    assert run(TmdbSequelSource(FakeProvider()).snapshot("1396")) is None


def test_a_collection_tmdb_cannot_find_is_an_error_not_an_empty_answer():
    with pytest.raises(LookupError):
        run(TmdbSequelSource(FakeProvider(collection_missing=True)).snapshot("438631"))
