"""Lookups of the links of «Входящие» in the sources (spec 3 and 11 of stage 6.4) on the saved live answers: TMDb by
the number of a movie or a series and by an IMDb id (`/find`), Shikimori by the number of an entry, IGDB by its number
and by the number of a Steam app, the name Steam gives; the date `Suggestion.released` of every search."""

import asyncio
from datetime import date

import httpx
import pytest

from app.providers.tmdb import TMDbProvider, TmdbHttpError
from app.tracker.errors import SourceNotConfigured
from app.tracker.models import TitleKind
from app.tracker.sources import igdb_games, shikimori_anime, tmdb_movies, tmdb_series
from app.tracker.sources.igdb_games import IgdbGameSource
from app.tracker.sources.shikimori_anime import ShikimoriAnimeSource
from app.tracker.sources.tmdb_find import TmdbFindSource, parse_find
from app.tracker.sources.tmdb_movies import TmdbMovieSource
from app.tracker.sources.tmdb_series import TmdbSeriesSource
from inbox_fakes import ANSWERS, Clients


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def clients():
    return Clients()


# --- the date of a search answer -------------------------------------------------------------------------


def test_every_search_gives_the_date_of_its_answer():
    assert tmdb_movies.parse_search(ANSWERS["movie:ELDEN RING"])[0].released == date(2028, 3, 3)
    assert tmdb_series.parse_search(ANSWERS["series:Dead-End Job"])[0].released == date(2026, 10, 30)
    assert shikimori_anime.parse_search(ANSWERS["anime:Блич"])[0].released == date(2004, 10, 5)
    alien = igdb_games.parse_search(ANSWERS["game:Alien: Isolation 2"])
    assert [(s.external_id, s.released) for s in alien][:1] == [("319082", None)]  # announced: no date


def test_a_date_that_is_garbage_is_no_date():
    raw = [{"id": 1, "title": "X", "release_date": "скоро"}, {"id": 2, "title": "Y", "release_date": ""}]

    assert [s.released for s in tmdb_movies.parse_search(raw)] == [None, None]
    assert igdb_games.parse_search([{"id": 3, "name": "Z", "game_type": 0, "first_release_date": "x"}])[0].released is None


def test_the_other_names_are_the_alternatives_of_igdb_and_the_english_name_of_shikimori():
    elden = igdb_games.parse_records(ANSWERS["igdb-games-by-steam:2622380"])[0]
    bleach = shikimori_anime.parse_search(ANSWERS["anime:Блич"])[0]

    assert "Elden Ring: Nightreign" in elden.other_names
    assert bleach.other_names == ("Блич", "Bleach")


# --- the lookups -----------------------------------------------------------------------------------------


def test_tmdb_gives_a_movie_and_a_series_by_their_numbers(clients):
    movie = run(TmdbMovieSource(clients.tmdb).suggest_by_id("1485839"))
    show = run(TmdbSeriesSource(clients.tmdb).suggest_by_id("289517"))

    assert (movie.kind, movie.name, movie.released) == (TitleKind.MOVIE, "Elden Ring", date(2028, 3, 3))
    assert (show.kind, show.name, show.original_name) == (TitleKind.SERIES, "Работа с призрачными перспективами", "꿀알바")
    assert run(TmdbMovieSource(clients.tmdb).suggest_by_id("7")) is None


def test_an_imdb_id_is_the_movie_first_else_the_series(clients):
    source = TmdbFindSource(clients.tmdb)

    dune = run(source.suggest_by_imdb("tt1160419"))
    severance = run(source.suggest_by_imdb("tt11280740"))

    assert (dune.kind, dune.external_id, dune.name) == (TitleKind.MOVIE, "438631", "Дюна")
    assert (severance.kind, severance.external_id, severance.original_name) == (TitleKind.SERIES, "95396", "Severance")
    assert run(source.suggest_by_imdb("tt0000001")) is None
    assert parse_find(None) is None and parse_find({"movie_results": [{"no": "id"}]}) is None


def test_shikimori_gives_the_entry_of_a_link_not_its_franchise(clients):
    found = run(ShikimoriAnimeSource(clients.shikimori).suggest_by_id("57612"))

    assert (found.external_id, found.name) == ("57612", "Магия вернувшегося должна быть особенной 2")
    assert found.released == date(2026, 10, 8)
    assert run(ShikimoriAnimeSource(clients.shikimori).suggest_by_id("1")) is None


def test_igdb_gives_the_games_of_a_steam_number_in_one_request(clients):
    source = IgdbGameSource(clients.igdb, clients.steam)

    found = run(source.suggest_by_steam("1245620"))

    assert [(s.external_id, s.name, s.details) for s in found] == [("119133", "Elden Ring", "ПК, PS5, PS4, Xbox Series X|S, Xbox One, Switch 2")]
    assert clients.requests == [("igdb", "steam:1245620")]
    assert run(source.suggest_by_steam("4000000")) == []


def test_the_query_by_a_steam_number_asks_the_external_games_of_steam():
    query = igdb_games.BY_STEAM_QUERY.format(uid=2622380)

    assert 'where external_games.uid = "2622380" & external_games.external_game_source = 1;' in query
    assert query.startswith("fields name,") and "alternative_names.name" in query


def test_igdb_gives_a_game_by_its_own_number(clients):
    found = run(IgdbGameSource(clients.igdb, clients.steam).suggest_by_id("250618"))

    assert (found.external_id, found.name) == ("250618", "Phantom Blade Zero")


def test_the_name_steam_gives_an_app(clients):
    source = IgdbGameSource(clients.igdb, clients.steam)

    assert run(source.steam_name("2622380")) == "ELDEN RING NIGHTREIGN"
    assert run(source.steam_name("4000000")) is None
    assert run(IgdbGameSource(clients.igdb).steam_name("2622380")) is None  # no Steam client: no name


def test_igdb_without_keys_asks_nothing():
    clients = Clients(igdb_keys=False)
    source = IgdbGameSource(clients.igdb, clients.steam)

    with pytest.raises(SourceNotConfigured):
        run(source.suggest_by_steam("1245620"))
    with pytest.raises(SourceNotConfigured):
        run(source.suggest_by_id("1"))
    assert clients.requests == []


# --- the provider ----------------------------------------------------------------------------------------


def provider_answering(status, body):
    asked = []

    def answer(request):
        asked.append((request.url.path, dict(request.url.params)))
        return httpx.Response(status, json=body)

    provider = TMDbProvider()
    provider._client = httpx.AsyncClient(base_url=TMDbProvider.BASE_URL, transport=httpx.MockTransport(answer))
    provider._window_calls.extend([0.0] * 100)  # a full window: a lookup still goes at once
    return provider, asked


def test_find_imdb_asks_tmdb_find_at_once():
    provider, asked = provider_answering(200, {"movie_results": [], "tv_results": []})

    assert run(provider.find_imdb("tt1160419")) == {"movie_results": [], "tv_results": []}
    [(path, params)] = asked
    assert path.endswith("/find/tt1160419") and params["external_source"] == "imdb_id" and params["language"] == "ru"


@pytest.mark.parametrize("lookup", ["lookup_movie", "lookup_tv"])
def test_a_lookup_of_a_number_is_none_on_404_and_raises_on_another_failure(lookup):
    missing, _ = provider_answering(404, {})
    broken, _ = provider_answering(500, {})

    assert run(getattr(missing, lookup)(1)) is None
    with pytest.raises(TmdbHttpError):
        run(getattr(broken, lookup)(1))
