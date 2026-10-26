"""TMDb series adapter: saved real TMDb responses (tests/fixtures/tmdb) become suggestions and snapshots.

The fixtures are the real answers for «Укрытие» (Silo, id 125988): `/tv/{id}`, `/tv/{id}/season/{n}` and the
search. Season 4 there is the stub from BUG-12: one future episode and nothing aired. No network.
"""

import asyncio
import json
import pathlib
from datetime import datetime

import pytest

from app.tracker.sources.tmdb_series import TmdbSeriesSource, parse_search, parse_show

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "tmdb"
SILO = 125988


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def run(coro):
    return asyncio.run(coro)


def silo_seasons():
    return {n: load(f"tv_{SILO}_season_{n}.json") for n in (1, 2, 3, 4)}


class FakeProvider:
    """Stands in for TMDbProvider: serves the saved responses, 404 (None) for anything else."""

    def __init__(self):
        self.searched = []
        self.season_calls = []
        self.broken_season = None

    async def search_tv(self, query, page=1, strict=False):
        self.searched.append(query)
        if query == "down":
            if strict:
                raise RuntimeError("TMDb is down")
            return []  # the lenient mode hides the outage as "nothing found"
        return load("search_tv_ukrytie.json")["results"]

    async def get_tv_show(self, tv_id):
        try:
            return load(f"tv_{tv_id}.json")
        except FileNotFoundError:
            return None

    async def get_tv_season(self, tv_id, season_number):
        self.season_calls.append(season_number)
        if season_number == self.broken_season:
            raise RuntimeError("TMDb is down")
        try:
            return load(f"tv_{tv_id}_season_{season_number}.json")
        except FileNotFoundError:
            return None


def test_search_results_become_series_suggestions():
    suggestions = parse_search(load("search_tv_ukrytie.json")["results"])

    silo = next(s for s in suggestions if s.external_id == str(SILO))
    assert silo.kind == "series"
    assert silo.name == "Укрытие"
    assert silo.original_name == "Silo"
    assert silo.year == 2023


def test_search_result_without_a_first_air_date_has_no_year():
    [suggestion] = parse_search([{"id": 5, "name": "Без даты", "original_name": "No date", "first_air_date": ""}])

    assert suggestion.year is None


def test_show_data_comes_from_the_show_response():
    snapshot = parse_show(load(f"tv_{SILO}.json"), silo_seasons())

    assert snapshot.external_id == str(SILO)
    assert snapshot.name == "Укрытие"
    assert snapshot.original_name == "Silo"
    assert snapshot.year == 2023
    assert snapshot.genres  # names, not ids
    assert all(isinstance(g, str) for g in snapshot.genres)


def test_seasons_are_numbered_from_one_with_declared_and_dated_episodes():
    snapshot = parse_show(load(f"tv_{SILO}.json"), silo_seasons())

    assert [s.number for s in snapshot.seasons] == [1, 2, 3, 4]
    third = snapshot.seasons[2]
    assert third.expected == 10
    assert [e.number for e in third.episodes] == list(range(1, 11))
    assert third.episodes[0].air_at == datetime(2026, 7, 2, 0, 0)  # TMDb knows the day, not the hour
    assert third.episodes[-1].air_at == datetime(2026, 9, 3, 0, 0)


def test_the_stub_season_keeps_its_single_future_episode():
    snapshot = parse_show(load(f"tv_{SILO}.json"), silo_seasons())

    stub = snapshot.seasons[3]
    assert stub.number == 4
    assert stub.expected == 1
    assert [e.air_at for e in stub.episodes] == [datetime(2027, 7, 8, 0, 0)]


def test_season_zero_specials_are_not_seasons():
    show = load(f"tv_{SILO}.json")
    show["seasons"] = [{"season_number": 0, "name": "Спецвыпуски", "episode_count": 3}] + show["seasons"]
    specials = {"season_number": 0, "episodes": [{"episode_number": 1, "air_date": "2023-01-01"}]}

    snapshot = parse_show(show, {0: specials, **silo_seasons()})

    assert [s.number for s in snapshot.seasons] == [1, 2, 3, 4]


def test_episode_without_an_air_date_has_no_moment():
    show = {"id": 7, "name": "Шоу", "original_name": "Show", "first_air_date": "", "genres": [],
            "seasons": [{"season_number": 1, "name": "Сезон 1", "episode_count": 2}]}
    season = {"episodes": [{"episode_number": 1, "air_date": "2026-05-01"}, {"episode_number": 2, "air_date": None}]}

    [parsed] = parse_show(show, {1: season}).seasons

    assert [e.air_at for e in parsed.episodes] == [datetime(2026, 5, 1), None]


def test_zero_declared_episodes_means_the_count_is_unknown():
    show = {"id": 7, "name": "Шоу", "original_name": "Show", "genres": [],
            "seasons": [{"season_number": 1, "name": "Сезон 1", "episode_count": 0}]}

    [parsed] = parse_show(show, {1: {"episodes": []}}).seasons

    assert parsed.expected is None


def test_a_season_that_tmdb_does_not_list_has_no_episodes():
    show = {"id": 7, "name": "Шоу", "original_name": "Show", "genres": [],
            "seasons": [{"season_number": 1, "name": "Сезон 1", "episode_count": 6}]}

    [parsed] = parse_show(show, {1: None}).seasons

    assert parsed.expected == 6 and parsed.episodes == ()


def test_source_suggests_through_the_provider():
    provider = FakeProvider()

    suggestions = run(TmdbSeriesSource(provider).suggest("Укрытие"))

    assert provider.searched == ["Укрытие"]
    assert suggestions[0].name == "Укрытие"


def test_source_search_outage_is_an_error_not_an_empty_result():
    with pytest.raises(RuntimeError):
        run(TmdbSeriesSource(FakeProvider()).suggest("down"))


def test_source_snapshot_reads_the_show_and_each_real_season():
    provider = FakeProvider()

    snapshot = run(TmdbSeriesSource(provider).snapshot(str(SILO)))

    assert snapshot.original_name == "Silo"
    assert [s.number for s in snapshot.seasons] == [1, 2, 3, 4]
    assert sorted(provider.season_calls) == [1, 2, 3, 4]


def test_source_snapshot_of_a_missing_series_is_none():
    assert run(TmdbSeriesSource(FakeProvider()).snapshot("693134")) is None


def test_a_failing_season_request_fails_the_whole_snapshot():
    provider = FakeProvider()
    provider.broken_season = 3

    with pytest.raises(RuntimeError):
        run(TmdbSeriesSource(provider).snapshot(str(SILO)))


def test_source_key_is_namespaced_for_series():
    assert TmdbSeriesSource(FakeProvider()).source_key == "tmdb_tv"
