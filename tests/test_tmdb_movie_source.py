"""TMDb movie adapter: saved real TMDb responses (tests/fixtures/tmdb) become suggestions and snapshots.

No network: the fixtures were fetched once through TMDbProvider; the adapter only turns responses into data.
"""

import asyncio
import json
import pathlib
from datetime import date

import pytest

from app.tracker.sources.tmdb_movies import TmdbMovieSource, parse_movie, parse_search

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "tmdb"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def run(coro):
    return asyncio.run(coro)


class FakeProvider:
    """Stands in for TMDbProvider: serves the saved responses, 404 (None) for anything else."""

    def __init__(self):
        self.searched = []

    async def search_movie(self, query, page=1, strict=False):
        self.searched.append(query)
        if query == "down":
            if strict:
                raise RuntimeError("TMDb is down")
            return []  # the lenient mode hides the outage as "nothing found"
        return load("search_movie_duna.json")["results"]

    async def get_movie_with_release_dates(self, movie_id):
        try:
            return load(f"movie_{movie_id}.json")
        except FileNotFoundError:
            return None


def test_search_results_become_suggestions_with_russian_and_original_titles():
    suggestions = parse_search(load("search_movie_duna.json")["results"])

    part_two = next(s for s in suggestions if s.external_id == "693134")
    assert part_two.title == "Дюна: Часть вторая"
    assert part_two.original_title == "Dune: Part Two"
    assert part_two.year == 2024
    assert part_two.kind == "movie"


def test_search_keeps_tmdb_order_and_every_id_is_unique():
    suggestions = parse_search(load("search_movie_duna.json")["results"])

    ids = [s.external_id for s in suggestions]
    assert ids[:2] == ["438631", "1170608"]
    assert len(set(ids)) == len(ids)


def test_search_result_without_a_release_date_has_no_year():
    [suggestion] = parse_search([{"id": 5, "title": "Без даты", "original_title": "No date", "release_date": ""}])

    assert suggestion.year is None


def test_released_movie_has_theatrical_and_digital_dates_from_nested_release_dates():
    snapshot = parse_movie(load("movie_693134.json"))

    assert snapshot.external_id == "693134"
    assert snapshot.title == "Дюна: Часть вторая"
    assert snapshot.original_title == "Dune: Part Two"
    assert snapshot.year == 2024
    assert snapshot.genres == ["фантастика", "приключения"]
    # earliest theatrical (type 3) and earliest digital (type 4) over all regions
    assert snapshot.theatrical_date == date(2024, 2, 27)
    assert snapshot.digital_date == date(2024, 4, 15)


def test_announced_movie_without_digital_release_has_no_digital_date():
    snapshot = parse_movie(load("movie_1170608.json"))

    assert snapshot.title == "Дюна: Часть третья"
    assert snapshot.theatrical_date == date(2026, 12, 16)
    assert snapshot.digital_date is None


def test_limited_release_alone_is_not_a_theatrical_date():
    raw = {
        "id": 9,
        "title": "Фильм",
        "original_title": "Film",
        "release_date": "2030-01-01",
        "genres": [],
        "release_dates": {
            "results": [
                {"iso_3166_1": "US", "release_dates": [{"type": 2, "release_date": "2029-12-01T00:00:00.000Z"}]}
            ]
        },
    }

    assert parse_movie(raw).theatrical_date is None


def test_snapshot_state_is_plain_json_for_storage():
    state = parse_movie(load("movie_693134.json")).state()

    assert state == {"theatrical_date": "2024-02-27", "digital_date": "2024-04-15"}
    json.dumps(state)


def test_source_suggests_through_the_provider():
    provider = FakeProvider()

    suggestions = run(TmdbMovieSource(provider).suggest("Дюна"))

    assert provider.searched == ["Дюна"]
    assert suggestions[0].title == "Дюна"


def test_source_search_outage_is_an_error_not_an_empty_result():
    with pytest.raises(RuntimeError):
        run(TmdbMovieSource(FakeProvider()).suggest("down"))


def test_source_snapshot_of_a_known_movie():
    snapshot = run(TmdbMovieSource(FakeProvider()).snapshot("438631"))

    assert snapshot.original_title == "Dune"
    assert snapshot.year == 2021


def test_source_snapshot_of_a_missing_movie_is_none():
    assert run(TmdbMovieSource(FakeProvider()).snapshot("1396")) is None
