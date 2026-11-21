"""Russian in games, the pure part (spec 5.1, 5.2, 5.5 and 5.8 of stage 9.1b, ticket 04): the line «Русский: …» for
every row of 5.2 and the rule of «(ПК)»; the strict reading of the supports, the looks and the key `russian` of the own
snapshot; the next look («no data» keeps the previous, «not asked yet» stores nothing), the reference point and what
appeared; the texts, keys, payloads and the sample of `russian_events`; the buttons; `DueTitle.statuses`.
"""

from datetime import datetime

import pytest

from app.tracker import actions, games, russian, russian_events
from app.tracker.games import GameState, carry_over
from app.tracker.platforms import Platform
from app.tracker.russian import IGDB, NOT_ASKED, STEAM, Look, Support, appeared, is_reference, line, next_look

BOTH = Support(True, True)
TEXT = Support(True, False)
VOICE = Support(False, True)
NO = Support(False, False)


# --- the line (spec 5.2) --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "official, fan, body",
    [
        (BOTH, None, "текст и озвучка — официально"),  # Cyberpunk 2077
        (TEXT, None, "текст — официально"),  # Stray, Bloodborne
        (VOICE, None, "озвучка — официально"),
        (TEXT, VOICE, "текст — официально; озвучка — народная"),  # Baldur's Gate 3, Hades II
        (TEXT, BOTH, "текст — официально; озвучка — народная"),  # the fan text is not shown: the official has it
        (VOICE, TEXT, "озвучка — официально; текст — народный"),
        (NO, TEXT, "текст — народный"),  # Lorelei and the Laser Eyes
        (NO, BOTH, "текст и озвучка — народные"),
        (None, VOICE, "озвучка — народная"),
        (BOTH, BOTH, "текст и озвучка — официально"),
        (NO, NO, "нет"),
        (NO, None, "официально нет"),
        (None, None, "нет данных"),
        (None, NO, "нет данных"),
    ],
)
def test_every_row_of_the_line(official, fan, body):
    assert line(official, False, fan, False).text == body


@pytest.mark.parametrize(
    "official, official_pc, fan, marked",
    [
        (BOTH, True, None, True),  # official from Steam
        (BOTH, False, None, False),  # official from IGDB: about the game
        (NO, True, None, True),  # «официально нет» from Steam
        (NO, True, NO, True),  # «нет» from Steam
        (NO, False, NO, False),  # «нет» from IGDB
        (TEXT, False, VOICE, True),  # a fan segment is PC-only
        (None, False, None, False),  # never after «нет данных»
        (None, True, None, False),
    ],
)
def test_the_pc_mark_when_the_owner_plays_elsewhere_and_the_body_rests_on_pc_data(official, official_pc, fan, marked):
    elsewhere = line(official, official_pc, fan, True)

    assert elsewhere.pc is marked
    assert elsewhere.text.endswith(" (ПК)") is marked
    assert line(official, official_pc, fan, False).pc is False  # PC only: no mark


def test_playing_elsewhere_means_a_marked_platform_other_than_pc():
    assert russian.elsewhere([Platform.PC, Platform.PS5]) is True
    assert russian.elsewhere([Platform.PS5]) is True
    assert russian.elsewhere([Platform.PC]) is False
    assert russian.elsewhere([]) is False


# --- strict reading -------------------------------------------------------------------------------------------------


def test_a_support_reads_back_and_garbage_raises():
    assert Support.from_state({"text": True, "voice": False}) == TEXT
    for bad in ({"text": True}, {"text": 1, "voice": 0}, {"text": True, "voice": False, "x": 1}, None, [True, False]):
        with pytest.raises(ValueError):
            Support.from_state(bad)


@pytest.mark.parametrize(
    "look",
    [
        Look(STEAM, "1091500", BOTH),
        Look(IGDB, None, TEXT),
        Look(IGDB, "1", NO),
        Look(None, None),
        Look(None, "1030300"),
    ],
)
def test_a_look_reads_back_as_it_was_stored(look):
    assert Look.from_state(look.state()) == look


def test_the_stored_forms_of_the_spec():
    assert Look(STEAM, "1091500", BOTH).state() == {"source": "steam", "appid": "1091500", "text": True, "voice": True}
    assert Look(IGDB, None, TEXT).state() == {"source": "igdb", "appid": None, "text": True, "voice": False}
    assert Look(None, None).state() == {"source": None, "appid": None}
    assert Look.from_state({}) is None


@pytest.mark.parametrize(
    "state",
    [
        {"source": "zog", "appid": None, "text": True, "voice": True},
        {"source": "steam", "appid": 1091500, "text": True, "voice": True},
        {"source": "steam", "appid": "1"},
        {"source": None, "appid": None, "text": True, "voice": False},
        {"source": "igdb", "appid": None, "text": "yes", "voice": False},
        "steam",
    ],
)
def test_a_spoiled_look_raises(state):
    with pytest.raises(ValueError):
        Look.from_state(state)


def test_the_own_snapshot_keeps_russian_and_reads_it_strictly():
    assert GameState.from_state({"steam_id": None}).russian is NOT_ASKED
    assert "russian" not in GameState().state()
    assert GameState.from_state({"russian": None}).russian is None
    assert GameState(russian=None).state()["russian"] is None
    assert GameState.from_state(GameState(russian=VOICE).state()).russian == VOICE
    with pytest.raises(ValueError):
        GameState.from_state({"russian": {"text": True}})


def test_russian_igdb_stopped_sending_stays_as_it_was():
    assert carry_over(GameState(russian=TEXT), GameState(russian=None)).russian == TEXT
    assert carry_over(GameState(russian=TEXT), GameState()).russian == TEXT
    assert carry_over(GameState(russian=TEXT), GameState(russian=NO)).russian == NO  # a real answer replaces it
    assert carry_over(GameState(), GameState(russian=None)).russian is None


def test_a_game_from_before_the_stage_is_read_as_before():
    assert games.GameState.from_state({"steam_id": "1", "ps_concept": None, "platforms": [6], "releases": []}).steam_id == "1"


# --- the next look, the reference point, what appeared (spec 5.5) -------------------------------------------------------


def test_steam_wins_then_igdb_then_no_data():
    assert next_look(None, BOTH, TEXT, "1") == Look(STEAM, "1", BOTH)
    assert next_look(None, None, TEXT, "1") == Look(IGDB, "1", TEXT)
    assert next_look(None, None, TEXT, None) == Look(IGDB, None, TEXT)
    assert next_look(None, None, None, "1") == Look(None, "1")
    assert next_look(None, NO, TEXT, "1") == Look(STEAM, "1", NO)  # «no Russian» is data


def test_not_asked_yet_without_steam_data_stores_nothing():
    assert next_look(None, None, NOT_ASKED, "1") is None
    assert next_look(None, None, NOT_ASKED, None) is None
    assert next_look(None, TEXT, NOT_ASKED, "1") == Look(STEAM, "1", TEXT)


def test_no_data_keeps_the_previous_look_of_the_same_number():
    steam = Look(STEAM, "1", BOTH)
    igdb = Look(IGDB, "1", TEXT)

    assert next_look(steam, None, TEXT, "1") is steam  # Steam silent: Steam's data stays, IGDB does not replace it
    assert next_look(steam, None, None, "1") is steam
    assert next_look(igdb, None, None, "1") is igdb
    assert next_look(igdb, None, NOT_ASKED, "1") is igdb
    assert next_look(Look(None, "1"), None, None, "1") == Look(None, "1")
    assert next_look(steam, None, None, "2") == Look(None, "2")  # another number: the old data says nothing of it


def test_the_reference_point():
    look = Look(STEAM, "1", BOTH)

    assert is_reference(None, look, False)  # an empty snapshot
    assert is_reference(Look(IGDB, None, TEXT), look, False)  # a Steam page appeared
    assert is_reference(Look(STEAM, "2", BOTH), look, False)  # another number
    assert is_reference(Look(STEAM, "1", NO), Look(IGDB, None, TEXT), False)  # the page went
    assert is_reference(Look(STEAM, "1", NO), look, True)  # the first check after «Вернуть в список»
    assert not is_reference(Look(None, "1"), look, False)  # an announced game: Steam lists its languages
    assert not is_reference(Look(IGDB, "1", TEXT), look, False)


def test_what_appeared():
    assert appeared(None, TEXT) == TEXT
    assert appeared(NO, BOTH) == BOTH
    assert appeared(TEXT, BOTH) == VOICE
    assert appeared(BOTH, TEXT) is None  # Russian that disappears is silent
    assert appeared(BOTH, BOTH) is None
    assert appeared(TEXT, None) is None


# --- messages (spec 5.8) --------------------------------------------------------------------------------------------

PREVIOUS = datetime(2026, 11, 21, 9, 0, 5)


@pytest.mark.parametrize(
    "name, parts, text, key",
    [
        ("Stray", TEXT, "🎮 В «Stray» появился русский текст", "text"),
        ("Hollow Knight: Silksong", VOICE, "🎮 В «Hollow Knight: Silksong» появилась русская озвучка", "voice"),
        ("Hades II", BOTH, "🎮 В «Hades II» появились русский текст и озвучка", "text_voice"),
    ],
)
def test_the_official_texts_keys_and_payloads(name, parts, text, key):
    event = russian_events.official_event(7, name, parts, STEAM, "1030300", False, PREVIOUS)

    assert event.type == russian_events.OFFICIAL
    assert event.text == text
    assert event.dedup_key == f"game:7:russian:official:{key}:from:20261121T090005"
    assert event.data == {"name": name, "parts": key, "source": "steam", "steam_id": "1030300", "pc": False}


def test_the_pc_mark_ends_the_message():
    event = russian_events.official_event(7, "Stray", TEXT, STEAM, "1332010", True, PREVIOUS)

    assert event.text == "🎮 В «Stray» появился русский текст (ПК)"
    assert event.data["pc"] is True


def test_the_sample_is_an_event_of_the_real_type_with_the_steam_page():
    [(sample_id, label, events)] = russian_events.TEST_SAMPLES
    [(event_type, payload)] = events()

    assert (sample_id, label) == ("game-russian", "Игра: появился русский язык")
    assert event_type == russian_events.OFFICIAL
    assert payload["text"] == "🎮 В «Hollow Knight: Silksong» появилась русская озвучка"
    assert payload["steam_id"] == "1030300"
    assert [action.label for action in actions.event_actions(event_type, 1, None, payload)] == ["🛒 Открыть в Steam"]


def test_the_buttons_of_an_official_event_read_the_one_list():
    data = {"steam_id": "1332010"}

    for event_type in russian_events.TYPES:
        buttons = actions.event_actions(event_type, 3, 9, data)
        assert [button.label for button in buttons] == ["📄 Карточка", "🛒 Открыть в Steam"]
        assert buttons[1].url == "https://store.steampowered.com/app/1332010/"
        assert [button.label for button in actions.event_actions(event_type, 3, 9, {"steam_id": None})] == ["📄 Карточка"]
