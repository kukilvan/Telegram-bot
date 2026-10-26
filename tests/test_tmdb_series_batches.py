"""Seasons of a series come in batches: `GET /tv/{id}?append_to_response=season/1,season/2,…` (at most 20 a request).

The provider is driven through a fake HTTP transport; the source runs on saved real TMDb answers («Укрытие» with
4 seasons, «Анатомия страсти» with 23). In the saved answers the episodes' `crew` and `guest_stars` lists are
dropped (3 MB otherwise); nothing else is touched. No network.
"""

import asyncio
import json
import pathlib

import httpx
import pytest

from app.providers.tmdb import MAX_SEASONS_PER_REQUEST, TMDbProvider, TmdbHttpError
from app.tracker.sources.tmdb_series import SEASONS_PER_REQUEST, TmdbSeriesSource, parse_show

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "tmdb"
SILO = 125988
GREYS = 1416  # 23 seasons: a batch of 20 and a batch of 3


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def run(coro):
    return asyncio.run(coro)


def batch_file(tv_id, first, last):
    return load(f"tv_{tv_id}_with_seasons_{first}_{last}.json")


# --- the provider -------------------------------------------------------------------------------


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TMDB_API_KEY", "test-key-0123456789")
    monkeypatch.setenv("TMDB_MIN_CALL_INTERVAL", "0")
    monkeypatch.setenv("TMDB_429_BACKOFF_BASE_SECONDS", "0")
    return TMDbProvider()


def serve(provider, handler):
    provider._client = httpx.AsyncClient(base_url=provider.BASE_URL, transport=httpx.MockTransport(handler))
    return provider


def test_the_provider_asks_for_the_show_with_its_seasons_in_one_request(provider):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"id": SILO, "season/1": {"episodes": []}})

    answer = run(serve(provider, handler).get_tv_with_seasons(SILO, [1, 2, 3]))

    assert answer["season/1"] == {"episodes": []}
    [request] = seen
    assert request.url.path == f"/3/tv/{SILO}"
    assert request.url.params["append_to_response"] == "season/1,season/2,season/3"
    assert request.url.params["language"] == "ru"


def test_the_source_batch_size_is_what_the_provider_accepts():
    assert SEASONS_PER_REQUEST == MAX_SEASONS_PER_REQUEST == 20


def test_the_provider_refuses_more_than_twenty_seasons_in_a_request(provider):
    too_many = list(range(1, MAX_SEASONS_PER_REQUEST + 2))

    with pytest.raises(ValueError):
        run(serve(provider, lambda request: httpx.Response(200, json={})).get_tv_with_seasons(SILO, too_many))


def test_no_series_at_this_id_is_none(provider):
    assert run(serve(provider, lambda request: httpx.Response(404, json={})).get_tv_with_seasons(1, [1])) is None


@pytest.mark.parametrize("status", [401, 500])
def test_other_http_errors_raise_with_their_code(provider, status):
    with pytest.raises(TmdbHttpError) as caught:
        run(serve(provider, lambda request: httpx.Response(status, json={})).get_tv_with_seasons(1, [1]))

    assert caught.value.status == status


def test_a_rate_limit_that_does_not_go_away_raises_429(provider):
    with pytest.raises(TmdbHttpError) as caught:
        run(serve(provider, lambda request: httpx.Response(429, json={})).get_tv_with_seasons(1, [1]))

    assert caught.value.status == 429


# --- the source ---------------------------------------------------------------------------------


class BatchProvider:
    """Serves the saved answers; counts every request, as TMDb would."""

    def __init__(self, tv_id, batches):
        self.tv_id = tv_id
        self.batches = batches  # {(first, last): answer}
        self.requests = []  # ("show",) or ("seasons", [numbers])
        self.broken_batch = None

    async def get_tv_show(self, tv_id):
        self.requests.append(("show",))
        return load(f"tv_{tv_id}.json") if tv_id == self.tv_id else None

    async def get_tv_with_seasons(self, tv_id, numbers):
        self.requests.append(("seasons", list(numbers)))
        if self.broken_batch is not None and self.broken_batch in numbers:
            raise RuntimeError("TMDb is down")
        return self.batches[(numbers[0], numbers[-1])]


def silo_provider():
    return BatchProvider(SILO, {(1, 4): batch_file(SILO, 1, 4)})


def greys_provider():
    return BatchProvider(GREYS, {(1, 20): batch_file(GREYS, 1, 20), (21, 23): batch_file(GREYS, 21, 23)})


def silo_old_way():
    seasons = {n: load(f"tv_{SILO}_season_{n}.json") for n in (1, 2, 3, 4)}
    return parse_show(load(f"tv_{SILO}.json"), seasons)


def test_a_series_of_four_seasons_takes_two_requests_and_matches_the_old_way():
    provider = silo_provider()

    snapshot = run(TmdbSeriesSource(provider).snapshot(str(SILO)))

    assert provider.requests == [("show",), ("seasons", [1, 2, 3, 4])]
    assert snapshot == silo_old_way()


def test_a_series_of_twenty_three_seasons_takes_three_requests():
    provider = greys_provider()

    snapshot = run(TmdbSeriesSource(provider).snapshot(str(GREYS)))

    assert provider.requests == [("show",), ("seasons", list(range(1, 21))), ("seasons", [21, 22, 23])]
    assert [s.number for s in snapshot.seasons] == list(range(1, 24))
    assert all(season.episodes for season in snapshot.seasons[:20])


class CountingProvider:
    """A series of any length: every batch answers with the seasons asked for."""

    def __init__(self, count):
        self.count = count
        self.requests = []

    async def get_tv_show(self, tv_id):
        self.requests.append("show")
        return {"id": 9, "name": "Долгий", "original_name": "Long", "genres": [],
                "seasons": [{"season_number": n, "name": f"Сезон {n}", "episode_count": 1} for n in range(self.count + 1)]}

    async def get_tv_with_seasons(self, tv_id, numbers):
        self.requests.append(len(numbers))
        return {f"season/{n}": {"episodes": [{"episode_number": 1, "air_date": "2026-01-01"}]} for n in numbers}


@pytest.mark.parametrize("seasons, requests", [(1, ["show", 1]), (20, ["show", 20]), (25, ["show", 20, 5]),
                                               (40, ["show", 20, 20]), (41, ["show", 20, 20, 1])])
def test_a_long_series_takes_one_request_for_the_show_and_one_for_every_twenty_seasons(seasons, requests):
    provider = CountingProvider(seasons)

    snapshot = run(TmdbSeriesSource(provider).snapshot("9"))

    assert provider.requests == requests
    assert [s.number for s in snapshot.seasons] == list(range(1, seasons + 1))  # season 0 (specials) is not asked for
    assert all(len(s.episodes) == 1 for s in snapshot.seasons)


def test_a_series_that_vanishes_between_the_two_requests_is_none():
    provider = greys_provider()
    provider.batches[(1, 20)] = None

    assert run(TmdbSeriesSource(provider).snapshot(str(GREYS))) is None


def test_a_failing_batch_fails_the_whole_snapshot():
    provider = greys_provider()
    provider.broken_batch = 21

    with pytest.raises(RuntimeError):
        run(TmdbSeriesSource(provider).snapshot(str(GREYS)))


def test_a_season_missing_from_the_answer_is_empty_as_a_404_season_was():
    provider = silo_provider()
    answer = dict(provider.batches[(1, 4)])
    del answer["season/3"]
    provider.batches[(1, 4)] = answer

    snapshot = run(TmdbSeriesSource(provider).snapshot(str(SILO)))

    third = snapshot.seasons[2]
    assert third.number == 3 and third.expected == 10 and third.episodes == ()
    assert snapshot.seasons[1].episodes  # the others are intact


def test_a_series_without_seasons_asks_for_no_batch():
    provider = BatchProvider(7, {})
    provider.get_tv_show = _show_without_seasons(provider)

    snapshot = run(TmdbSeriesSource(provider).snapshot("7"))

    assert snapshot.seasons == [] and provider.requests == [("show",)]


def _show_without_seasons(provider):
    async def get_tv_show(tv_id):
        provider.requests.append(("show",))
        return {"id": 7, "name": "Пусто", "original_name": "Empty", "genres": [], "seasons": [
            {"season_number": 0, "name": "Спецвыпуски", "episode_count": 1}]}

    return get_tv_show


def test_a_missing_series_is_none_without_asking_for_seasons():
    provider = silo_provider()

    assert run(TmdbSeriesSource(provider).snapshot("693134")) is None
    assert provider.requests == [("show",)]
