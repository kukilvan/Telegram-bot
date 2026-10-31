"""IGDB game adapter (spec 4.2–4.6 of part 6.1): saved real IGDB and Steam answers (tests/fixtures/igdb, tests/fixtures/
steam) become suggestions and snapshots; the Steam client reads `appdetails` in Russian.

No network: the IGDB answers were fetched once with the keys, the Steam ones need none; the adapter only turns answers
into data.
"""

import asyncio
import json
import logging
import pathlib

import httpx
import pytest

from app.providers.steam import SteamProvider
from app.tracker.core import SourceNotConfigured
from app.tracker.games import GameState
from app.tracker.sources.igdb_games import (
    GAME_QUERY, SEARCH_QUERY, IgdbGameSource, clean_query, parse_game, parse_search, plain_text,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
GAMES = {
    "bloodborne": 7334, "gta-6": 52189, "hades-2": 228525, "hunter-deathwish": 396020, "pop-remake": 138383,
    "ultimate-theater": 367400, "witcher-3": 1942, "witcher-4": 194662, "yomawari": 11589,
}


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def game(name):
    return load(f"igdb/game-{name}.json")[0]


def steam(appid):
    entry = load(f"steam/appdetails_{appid}.json")[str(appid)]
    return entry.get("data")


def run(coro):
    return asyncio.run(coro)


class FakeIgdb:
    """Stands in for IGDBProvider: serves the saved answers by the query it gets and writes down how it was asked."""

    def __init__(self, enabled=True, search="search-vedmak-filtered.json"):
        self.enabled = enabled
        self.search = search
        self.asked = []  # (body, at_once)

    async def games(self, body, *, at_once=False):
        self.asked.append((body, at_once))
        if body.startswith("search"):
            return load(f"igdb/{self.search}")
        number = int(body.rsplit("=", 1)[1].strip(" ;"))
        name = next((name for name, igdb_id in GAMES.items() if igdb_id == number), None)
        return load(f"igdb/game-{name}.json") if name else []


class FakeSteam:
    def __init__(self, answers):
        self.answers = answers
        self.asked = []

    async def app_details(self, appid):
        self.asked.append(appid)
        return self.answers.get(appid)


# --- search ------------------------------------------------------------------------------------------------------------


def test_the_witcher_3_without_the_filter_gives_one_suggestion():
    # editions, a bundle, DLC, a mod and an update are left out by the adapter itself
    suggestions = parse_search(load("igdb/search-the-witcher-3.json"))

    assert [(s.external_id, s.name, s.original_name, s.year) for s in suggestions] == [
        ("1942", "Ведьмак 3: Дикая охота", "The Witcher 3: Wild Hunt", 2015),
    ]
    assert suggestions[0].kind == "game"


def test_vedmak_gives_five_games_with_their_russian_names_in_the_order_of_igdb():
    suggestions = parse_search(load("igdb/search-vedmak-filtered.json"))

    assert [s.name for s in suggestions] == [
        "Ведьмак 2: Убийцы королей. Расширенное издание",
        "Ведьмак 2: Убийцы королей",
        "Ведьмак",
        "Ведьмак 3: Дикая охота",
        "Кровная вражда: Ведьмак. Истории",
    ]


def test_a_suggestion_has_its_platforms_in_the_order_of_the_tracker_and_a_cover():
    witcher_3, thronebreaker = (s for s in parse_search(load("igdb/search-vedmak-filtered.json")) if s.external_id in ("1942", "107300"))

    assert witcher_3.details == "ПК, PS5, PS4, Xbox Series X|S, Xbox One, Switch 2, Switch"
    assert thronebreaker.details == "ПК, PS4, Xbox One, Switch"  # Mac and others are not platforms of the tracker
    assert witcher_3.poster_path == "https://images.igdb.com/igdb/image/upload/t_cover_big/coaarl.jpg"


def test_a_game_on_no_platform_of_the_tracker_has_no_line_and_no_cover_is_none():
    (suggestion,) = parse_search([{"id": 1, "name": "Mac only", "game_type": 0, "platforms": [14]}])

    assert suggestion.details is None and suggestion.poster_path is None and suggestion.year is None


def test_quotes_and_backslashes_are_taken_out_of_the_query():
    igdb = FakeIgdb()

    run(IgdbGameSource(igdb).suggest(' "ведьмак\\" '))

    assert igdb.asked == [(SEARCH_QUERY.format(query="ведьмак"), True)]
    assert 'search "ведьмак";' in igdb.asked[0][0]
    assert "where game_type = (0,4,8,9,10,11) & version_parent = null; limit 10;" in igdb.asked[0][0]


def test_a_query_of_nothing_but_quotes_asks_nothing():
    igdb = FakeIgdb()

    assert run(IgdbGameSource(igdb).suggest('""')) == []
    assert igdb.asked == [] and clean_query(' "\\" ') == ""


def test_the_search_goes_at_once_and_the_snapshot_is_paced():
    igdb = FakeIgdb()
    source = IgdbGameSource(igdb)

    run(source.suggest("ведьмак"))
    run(source.snapshot("1942"))

    assert [at_once for _, at_once in igdb.asked] == [True, False]
    assert igdb.asked[1][0] == GAME_QUERY.format(id=1942)


def test_without_keys_every_request_raises_before_the_network():
    igdb = FakeIgdb(enabled=False)
    source = IgdbGameSource(igdb, FakeSteam({}))

    for request in (source.suggest("ведьмак"), source.snapshot("1942"), source.snapshot_to_add("1942")):
        with pytest.raises(SourceNotConfigured):
            run(request)
    assert igdb.asked == []


# --- snapshot ----------------------------------------------------------------------------------------------------------


EXPECTED_STATES = {
    "bloodborne": {
        "steam_id": None, "ps_concept": "200520", "platforms": [48],
        "releases": [
            {"platform": 48, "region": 5, "type": "full", "date": "2015-03-26"},
            {"platform": 48, "region": 2, "type": "full", "date": "2015-03-24"},
            {"platform": 48, "region": 1, "type": "full", "date": "2015-03-27"},
        ],
    },
    "gta-6": {
        "steam_id": None, "ps_concept": "10000730", "platforms": [167, 169],
        "releases": [
            {"platform": 169, "region": 8, "type": "full", "date": "2026-11-19"},
            {"platform": 167, "region": 8, "type": "full", "date": "2026-11-19"},
        ],
    },
    "hades-2": {
        "steam_id": "1145350", "ps_concept": "10018449", "platforms": [6, 130, 167, 169, 508],
        "releases": [  # the early access and the full release of the PC; the Mac (14) is not a platform of the tracker
            {"platform": 6, "region": 8, "type": "early", "date": "2024-05-06"},
            {"platform": 130, "region": 8, "type": "full", "date": "2025-09-25"},
            {"platform": 508, "region": 8, "type": "full", "date": "2025-09-25"},
            {"platform": 6, "region": 8, "type": "full", "date": "2025-09-25"},
            {"platform": 169, "region": 8, "type": "full", "date": "2026-04-14"},
            {"platform": 167, "region": 8, "type": "full", "date": "2026-04-14"},
        ],
    },
    "hunter-deathwish": {
        "steam_id": "4434610", "ps_concept": None, "platforms": [6, 167, 169],
        "releases": [
            {"platform": 167, "region": 8, "type": "full", "date": "2027-Q3"},
            {"platform": 169, "region": 8, "type": "full", "date": "2027-Q3"},
            {"platform": 6, "region": 8, "type": "full", "date": "2027-Q3"},
        ],
    },
    "pop-remake": {
        "steam_id": None, "ps_concept": None, "platforms": [6, 48, 49, 167, 169],
        "releases": [
            {"platform": 6, "region": 8, "type": "cancelled", "date": None},
            {"platform": 167, "region": 8, "type": "cancelled", "date": None},
            {"platform": 169, "region": 8, "type": "cancelled", "date": None},
            {"platform": 48, "region": 8, "type": "cancelled", "date": None},
            {"platform": 49, "region": 8, "type": "cancelled", "date": None},
        ],
    },
    "ultimate-theater": {
        "steam_id": "1541370", "ps_concept": None, "platforms": [6, 167],
        "releases": [
            {"platform": 6, "region": 8, "type": "full", "date": "2025-10-29"},
            {"platform": 167, "region": 8, "type": "full", "date": None},  # «TBD»
        ],
    },
    "witcher-3": {
        "steam_id": "292030", "ps_concept": "204794", "platforms": [6, 48, 49, 130, 167, 169, 508],
        "releases": [
            {"platform": 48, "region": 8, "type": "full", "date": "2015-05-19"},
            {"platform": 167, "region": 8, "type": "full", "date": "2022-12-14"},
            {"platform": 49, "region": 8, "type": "full", "date": "2015-05-19"},
            {"platform": 169, "region": 8, "type": "full", "date": "2022-12-14"},
            {"platform": 130, "region": 8, "type": "full", "date": "2021-01-28"},
            {"platform": 6, "region": 8, "type": "full", "date": "2015-05-19"},
            {"platform": 508, "region": 8, "type": "full", "date": "2026-09-29"},
        ],
    },
    "witcher-4": {
        "steam_id": None, "ps_concept": None, "platforms": [6, 167, 169],
        "releases": [  # the year without a kind is a full release; `date` of IGDB is its 31 December, `y` is the year
            {"platform": 6, "region": 8, "type": "full", "date": "2028"},
            {"platform": 167, "region": 8, "type": "full", "date": "2028"},
            {"platform": 169, "region": 8, "type": "full", "date": "2028"},
        ],
    },
    "yomawari": {
        "steam_id": "477870", "ps_concept": None, "platforms": [6, 167],  # the Vita (46) is not a platform of the tracker
        "releases": [
            {"platform": 6, "region": 2, "type": "full", "date": "2016-10-25"},
            {"platform": 6, "region": 1, "type": "full", "date": "2016-10-28"},
            {"platform": 167, "region": 2, "type": "full", "date": "2026-11-05"},
            {"platform": 167, "region": 5, "type": "full", "date": "2026-05-13"},
        ],
    },
}


@pytest.mark.parametrize("name", sorted(GAMES))
def test_every_saved_game_becomes_its_state(name):
    snapshot = parse_game(game(name))

    assert snapshot.state() == EXPECTED_STATES[name]
    assert snapshot.external_id == str(GAMES[name])


@pytest.mark.parametrize("name", sorted(GAMES))
def test_the_dates_are_kept_in_the_snapshot_and_read_back_the_same(name):
    # BUG-15: the dates of the platforms are stored (as JSON, like the snapshot is) and come back unchanged
    snapshot = parse_game(game(name))

    stored = json.loads(json.dumps(snapshot.state()))

    assert GameState.from_state(stored) == snapshot.game


def test_unknown_kinds_of_release_are_not_taken():
    raw = {"id": 1, "name": "Beta", "platforms": [6], "release_dates": [
        {"platform": 6, "release_region": 8, "status": 2, "date_format": 0, "date": 1714953600},  # beta
        {"platform": 6, "release_region": 8, "status": 34, "date_format": 0, "date": 1714953600},  # preorder entry
        {"platform": 6, "release_region": 8, "date_format": 2, "y": 2027},  # no kind: the full release
    ]}

    assert parse_game(raw).state()["releases"] == [{"platform": 6, "region": 8, "type": "full", "date": "2027"}]


def test_a_concept_of_playstation_store_counts_only_as_a_number():
    raw = {"id": 1, "name": "X", "external_games": [
        {"external_game_source": 36, "uid": "UP0001-CUSA00001_00-GAME"},
        {"external_game_source": 1, "uid": "42"},
    ]}

    state = parse_game(raw).state()

    assert (state["ps_concept"], state["steam_id"]) == (None, "42")


def test_genres_are_translated_and_an_unknown_one_stays_as_it_is():
    assert parse_game(game("hades-2")).genres == ["Ролевая", "Слэшер", "Приключения", "Инди"]
    assert parse_game({"id": 1, "name": "X", "genres": [{"name": "Shooter"}, {"name": "Brand New"}]}).genres == [
        "Шутер", "Brand New",
    ]


def test_the_cover_is_a_whole_address_and_none_without_one():
    assert parse_game(game("witcher-3")).poster_path == "https://images.igdb.com/igdb/image/upload/t_cover_big/coaarl.jpg"
    assert parse_game({"id": 1, "name": "X"}).poster_path is None


def test_the_year_comes_from_the_first_release_and_none_without_one():
    assert parse_game(game("hades-2")).year == 2025
    assert parse_game(game("pop-remake")).year is None


def test_an_empty_answer_is_no_game():
    source = IgdbGameSource(FakeIgdb(), FakeSteam({}))

    assert run(source.snapshot("1")) is None
    assert run(source.snapshot_to_add("1")) is None


# --- name and description (spec 4.4) -----------------------------------------------------------------------------------


def test_the_russian_name_of_igdb_comes_before_the_name_of_steam():
    snapshot = parse_game(game("witcher-3"), steam(292030))

    assert snapshot.name == "Ведьмак 3: Дикая охота"  # not «… — Обновлённое издание», the product of Steam
    assert snapshot.original_name == "The Witcher 3: Wild Hunt"
    assert snapshot.overview.startswith("Обновлённое издание игры «Ведьмак 3: Дикая Охота»")


def test_the_name_of_steam_counts_when_igdb_has_no_russian_one_and_it_has_russian_letters():
    raw = dict(game("witcher-3"), alternative_names=[])

    assert parse_game(raw, steam(292030)).name == "Ведьмак 3: Дикая Охота — Обновлённое издание"


def test_a_latin_name_of_steam_is_not_taken_but_a_russian_description_is():
    snapshot = parse_game(game("hades-2"), steam(1145350))

    assert snapshot.name == "Hades II"
    assert snapshot.overview.startswith("Обуздайте тёмную магию")


def test_without_steam_the_name_and_the_description_are_of_igdb():
    snapshot = parse_game(game("hades-2"))

    assert snapshot.name == "Hades II"
    assert snapshot.overview == game("hades-2")["summary"]


def test_a_description_of_steam_without_russian_letters_is_not_taken():
    snapshot = parse_game(game("hades-2"), {"name": "Hades II", "short_description": "Battle beyond the Underworld."})

    assert snapshot.overview == game("hades-2")["summary"]


def test_no_description_anywhere_is_none():
    assert parse_game({"id": 1, "name": "X"}).overview is None


def test_the_description_of_steam_is_plain_text():
    assert plain_text("<b>Ведьмак</b>&nbsp;и&quot;Цири&quot;<br>\n\n  едут  <i>дальше</i>") == 'Ведьмак и"Цири" едут дальше'


def test_steam_is_asked_only_when_a_game_is_added():
    steam_client = FakeSteam({"1145350": steam(1145350)})
    source = IgdbGameSource(FakeIgdb(), steam_client)

    polled = run(source.snapshot("228525"))
    added = run(source.snapshot_to_add("228525"))

    assert polled.overview == game("hades-2")["summary"]
    assert added.overview.startswith("Обуздайте тёмную магию")
    assert steam_client.asked == ["1145350"]


def test_a_game_without_an_app_in_steam_does_not_ask_steam():
    steam_client = FakeSteam({})

    run(IgdbGameSource(FakeIgdb(), steam_client).snapshot_to_add("7334"))  # Bloodborne: PS4 only

    assert steam_client.asked == []


def test_steam_not_answering_adds_the_game_by_what_igdb_knows():
    snapshot = run(IgdbGameSource(FakeIgdb(), FakeSteam({})).snapshot_to_add("1942"))

    assert snapshot.name == "Ведьмак 3: Дикая охота"
    assert snapshot.overview == game("witcher-3")["summary"]


# --- the Steam client --------------------------------------------------------------------------------------------------


def steam_with(answer):
    asked = []

    def transport(request):
        asked.append(request.url)
        if isinstance(answer, Exception):
            raise answer
        return answer

    client = SteamProvider()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    return client, asked


def test_steam_details_are_asked_in_russian_and_basic():
    client, asked = steam_with(httpx.Response(200, json=load("steam/appdetails_292030.json")))

    details = run(client.app_details("292030"))

    assert details["name"] == "Ведьмак 3: Дикая Охота — Обновлённое издание"
    assert asked[0].path == "/api/appdetails"
    assert dict(asked[0].params) == {"appids": "292030", "l": "russian", "filters": "basic"}


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(200, json=load("steam/appdetails_999999999.json")),  # `success: false`
        httpx.Response(500, json={}),
        httpx.ReadTimeout("slow"),
        httpx.Response(200, text="not json"),
    ],
)
def test_steam_failing_is_none_and_an_info_line(answer, caplog):
    client, _ = steam_with(answer)

    with caplog.at_level(logging.INFO, logger="app.providers.steam"):
        assert run(client.app_details("999999999")) is None

    steam_lines = [record.levelno for record in caplog.records if record.name == "app.providers.steam"]
    assert steam_lines == [logging.INFO]


def test_steam_waits_fifteen_seconds_at_most():
    assert SteamProvider()._client.timeout.read == 15.0
