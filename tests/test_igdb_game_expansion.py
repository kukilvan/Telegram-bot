"""An expansion read as a game (spec 3.3 of stage 6.3): `GAME_QUERY` asks the name of the parent, the own snapshot keeps
`expansion` and `parent`, and reads them strictly. On the saved answers of 2026-11-04 (`tests/fixtures/igdb/game-*.json`).
"""

import json
import pathlib

import pytest

from app.tracker.games import EXPANSION, STANDALONE, GameState, Parent
from app.tracker.sources.igdb_games import GAME_QUERY, parse_game, parse_state

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "igdb"


def game(name):
    return json.loads((FIXTURES / f"game-{name}.json").read_text(encoding="utf-8"))[0]


def test_the_query_asks_the_name_of_the_parent():
    fields = GAME_QUERY.removeprefix("fields ").split(";")[0].split(",")
    assert "parent_game.name" in fields
    assert "parent_game" not in fields


@pytest.mark.parametrize(
    ("name", "kind", "parent"),
    [
        ("blood-and-wine", EXPANSION, Parent("1942", "The Witcher 3: Wild Hunt")),
        ("songs-of-the-past", EXPANSION, Parent("1942", "The Witcher 3: Wild Hunt")),
        ("shadow-of-the-erdtree", EXPANSION, Parent("119133", "Elden Ring")),
        ("phantom-liberty", EXPANSION, Parent("1877", "Cyberpunk 2077")),
        ("lost-legacy", STANDALONE, Parent("7331", "Uncharted 4: A Thief's End")),
        ("miles-morales", STANDALONE, Parent("19565", "Marvel's Spider-Man")),
    ],
)
def test_an_expansion_knows_its_kind_and_its_parent(name, kind, parent):
    state = parse_state(game(name))
    assert (state.expansion, state.parent) == (kind, parent)


def test_blood_and_wine_is_read_as_a_game_of_its_own():
    snapshot = parse_game(game("blood-and-wine"))
    assert snapshot.name == "Ведьмак 3: Дикая Охота - Кровь и Вино"
    assert snapshot.game.steam_id == "378648"
    assert len(snapshot.game.platforms) == 6
    assert snapshot.poster_path and snapshot.genres


def test_a_remaster_with_a_parent_is_no_expansion():
    remaster = {**game("blood-and-wine"), "game_type": 9}  # The Witcher 3 Remastered: type 9, parent 1942
    state = parse_state(remaster)
    assert (state.expansion, state.parent) == (None, None)
    assert "expansion" not in state.state() and "parent" not in state.state()


def test_an_expansion_without_a_readable_parent_is_no_expansion():
    for parent in (None, 1942, {"id": 1942}, {"id": "1942", "name": "X"}, {"id": True, "name": "X"}):
        assert parse_state({**game("blood-and-wine"), "parent_game": parent}).expansion is None


def test_the_kind_and_the_parent_survive_the_store():
    state = parse_state(game("lost-legacy"))
    stored = json.loads(json.dumps(state.state()))
    assert stored["expansion"] == "standalone"
    assert stored["parent"] == {"id": "7331", "name": "Uncharted 4: A Thief's End"}
    assert GameState.from_state(stored) == state


def test_a_snapshot_stored_before_the_stage_reads_as_no_expansion():
    old = {"steam_id": "292030", "ps_concept": None, "platforms": [6], "releases": []}
    state = GameState.from_state(old)
    assert (state.expansion, state.parent) == (None, None)
    assert state.state() == old  # a game keeps the shape of its snapshot


@pytest.mark.parametrize(
    "spoiled",
    [
        {"expansion": "dlc", "parent": {"id": "1", "name": "A"}},
        {"expansion": "expansion", "parent": {"id": "1"}},
        {"expansion": "expansion", "parent": {"name": "A"}},
        {"expansion": "expansion", "parent": {"id": 1, "name": "A"}},
        {"expansion": "expansion", "parent": None},
        {"expansion": "expansion"},
        {"parent": {"id": "1", "name": "A"}},
        {"expansion": "standalone", "parent": "1942"},
    ],
)
def test_a_wrong_kind_or_parent_raises(spoiled):
    with pytest.raises(ValueError):
        GameState.from_state({"platforms": [], "releases": [], **spoiled})
