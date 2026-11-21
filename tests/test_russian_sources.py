"""What the sources say about Russian (spec 5.5 of stage 9.1b, ticket 04): Steam's `supported_languages` on the saved
answers of 2026-11-21 (US, RU, the coming-soon list of Israel) and made-up records — the flags, `success: 15`, an empty
or missing list, a malformed one; the request of the languages (the store of the United States, packs of 100); IGDB's
`language_supports` on its saved answer. No network: an `httpx` transport and fakes.
"""

import asyncio
import json
import pathlib

import httpx
import pytest

from app.tracker.russian import Support
from app.tracker.sources import igdb_games, steam_languages
from app.tracker.sources.steam_languages import SteamLanguageSource, parse_item, parse_items
from app.tracker.sources.steam_prices import UnreadAnswer
from test_steam_client import client_with

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def items(name):
    return json.loads((FIXTURES / "steam" / name).read_text(encoding="utf-8"))["response"]["store_items"]


def by_appid(name):
    return {str(item["appid"]): item for item in items(name)}


# --- Steam: the saved answers ---------------------------------------------------------------------------------------

US = {
    "1091500": Support(True, True),  # Cyberpunk 2077
    "1332010": Support(True, False),  # Stray
    "1145350": Support(True, False),  # Hades II
    "1030300": Support(True, True),  # Hollow Knight: Silksong
    "1086940": Support(True, False),  # Baldur's Gate 3
    "2008920": Support(False, False),  # Lorelei and the Laser Eyes: languages listed, no Russian
    "632470": Support(True, False),  # Disco Elysium - The Final Cut
    "480490": Support(True, True),  # Prey
    "292030": Support(True, True),  # The Witcher 3
}


@pytest.mark.parametrize("appid", sorted(US))
def test_the_us_answer_gives_the_flags_of_russian_text_and_voice(appid):
    assert parse_item(by_appid("getitems_languages_us.json")[appid]) == US[appid]


def test_an_app_steam_does_not_know_says_nothing():
    unknown = [item for item in items("getitems_languages_us.json") if item.get("success") == 15]

    assert len(unknown) == 1 and parse_item(unknown[0]) is None


def test_in_russia_even_cyberpunk_answers_15_without_languages_so_it_says_nothing():
    assert [parse_item(item) for item in items("getitems_languages_ru.json")] == [None, None]


def test_upcoming_games_list_their_languages_too():
    coming = by_appid("getitems_coming_soon_il.json")

    assert parse_item(coming["3590480"]) == Support(True, False)  # Discard: subtitles and the interface
    assert parse_item(coming["5532830"]) == Support(True, False)  # only `supported`: the interface is text
    assert parse_item(coming["4860910"]) == Support(False, False)  # two languages, no Russian


# --- Steam: made-up records ------------------------------------------------------------------------------------------


def record(*languages, **extra):
    return {"appid": 1, "success": 1, "supported_languages": list(languages), **extra}


def language(number, supported=True, full_audio=False, subtitles=False):
    return {"elanguage": number, "eadditionallanguage": -1, "supported": supported, "full_audio": full_audio,
            "subtitles": subtitles}


@pytest.mark.parametrize(
    "flags, support",
    [
        ({"supported": True}, Support(True, False)),
        ({"supported": False, "subtitles": True}, Support(True, False)),
        ({"supported": False, "full_audio": True}, Support(False, True)),
        ({"supported": True, "full_audio": True, "subtitles": True}, Support(True, True)),
        ({"supported": False}, Support(False, False)),
    ],
)
def test_text_is_supported_or_subtitles_and_voice_is_full_audio(flags, support):
    assert parse_item(record(language(0), language(8, **flags))) == support


def test_an_empty_or_missing_list_says_nothing():
    assert parse_item(record()) is None
    assert parse_item({"appid": 1, "success": 1}) is None


@pytest.mark.parametrize(
    "languages",
    [
        "russian",
        [["elanguage", 8]],
        [{"supported": True, "full_audio": False, "subtitles": False}],
        [{"elanguage": "8", "supported": True, "full_audio": False, "subtitles": False}],
        [{"elanguage": True, "supported": True, "full_audio": False, "subtitles": False}],
        [{"elanguage": 8, "supported": "yes", "full_audio": False, "subtitles": False}],
        [{"elanguage": 0, "supported": True, "subtitles": False}],
    ],
)
def test_a_list_that_is_not_records_with_yes_no_flags_cannot_be_read(languages):
    with pytest.raises(ValueError):
        parse_item({"appid": 1, "success": 1, "supported_languages": languages})


@pytest.mark.parametrize("success", [None, 2, "1", True])
def test_an_unknown_success_cannot_be_read(success):
    with pytest.raises(ValueError):
        parse_item({"appid": 1, "success": success, "supported_languages": [language(8)]})


def test_one_unreadable_game_leaves_the_others_of_the_answer():
    answer = [
        record(language(8)) | {"appid": 1},
        {"appid": 2, "success": 1, "supported_languages": "garbage"},
    ]

    found = parse_items(answer, ["1", "2", "3", "x"])

    assert found["1"] == Support(True, False)
    assert isinstance(found["2"], UnreadAnswer) and "supported_languages" in str(found["2"])
    assert isinstance(found["3"], UnreadAnswer)  # no record in the answer
    assert found["x"] is None  # no number of Steam: says nothing, not asked


# --- Steam: the request ----------------------------------------------------------------------------------------------


class LanguageAnswer:
    def __init__(self):
        self.asked = []

    def __call__(self, request):
        self.asked.append(json.loads(request.url.params["input_json"]))
        return httpx.Response(200, json={"response": {"store_items": items("getitems_languages_us.json")}})


def test_the_languages_are_asked_in_the_us_store_whatever_the_country_and_only_the_languages():
    fake = LanguageAnswer()
    source = SteamLanguageSource(client_with(fake))

    found = asyncio.run(source.russian(["1091500", "1332010", "1091500", "not-a-number"]))

    assert fake.asked == [{
        "ids": [{"appid": 1091500}, {"appid": 1332010}],
        "context": {"language": "russian", "country_code": "US"},
        "data_request": {"include_supported_languages": True},
    }]
    assert found == {"1091500": Support(True, True), "1332010": Support(True, False), "not-a-number": None}
    assert steam_languages.STORE_COUNTRY == "US"


def test_nothing_to_ask_is_no_request():
    fake = LanguageAnswer()

    assert asyncio.run(SteamLanguageSource(client_with(fake)).russian(["abc"])) == {"abc": None}
    assert fake.asked == []


def test_a_failed_request_is_a_failure_of_the_whole_pack():
    from app.providers.steam import SteamError

    source = SteamLanguageSource(client_with(lambda request: httpx.Response(503)))

    with pytest.raises(SteamError):
        asyncio.run(source.russian(["1091500"]))


# --- IGDB -------------------------------------------------------------------------------------------------------------


def igdb_games_saved():
    data = json.loads((FIXTURES / "igdb" / "language_supports.json").read_text(encoding="utf-8"))
    return {game["name"]: game for game in data["games"]}


@pytest.mark.parametrize(
    "name, support",
    [
        ("Cyberpunk 2077", Support(True, True)),  # 1 audio, 2 subtitles, 3 interface
        ("The Witcher 3: Wild Hunt", Support(True, True)),
        ("Bloodborne", Support(True, False)),  # 2 and 3
        ("Grand Theft Auto VI", Support(True, False)),
        ("Hades II", Support(True, False)),
        ("Yomawari: Night Alone", Support(False, False)),  # four languages, no Russian
    ],
)
def test_igdb_language_supports_give_russian_by_language_22(name, support):
    assert igdb_games.russian_support(igdb_games_saved()[name]) == support


def test_igdb_without_languages_says_nothing_and_garbage_is_skipped():
    assert igdb_games.russian_support({}) is None
    assert igdb_games.russian_support({"language_supports": []}) is None
    assert igdb_games.russian_support({"language_supports": "x"}) is None
    assert igdb_games.russian_support(
        {"language_supports": ["x", {"language": 22, "language_support_type": 1}]}
    ) == Support(False, True)


def test_the_own_query_asks_the_languages_and_the_state_keeps_russian():
    assert "language_supports.language,language_supports.language_support_type" in igdb_games.GAME_QUERY
    raw = {**igdb_games_saved()["Bloodborne"], "platforms": [48]}

    state = igdb_games.parse_state(raw)

    assert state.russian == Support(True, False)
    assert state.state()["russian"] == {"text": True, "voice": False}
