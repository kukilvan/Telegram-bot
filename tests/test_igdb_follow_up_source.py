"""IGDB adapter of the follow-up check (spec 3.1–3.2 of stage 6.3) on the saved real answers of 2026-11-04
(`tests/fixtures/igdb/follow-ups-<game>.json`).

No network: the answers were fetched once with the keys; the adapter only turns an answer into a snapshot.
"""

import asyncio
import json
import pathlib
import re
from datetime import date

import pytest

from app.providers.igdb import IgdbError
from app.tracker.core import SourceNotConfigured
from app.tracker.failures import TitleGone
from app.tracker.follow_ups import FollowUps, FollowUpsSnapshot
from app.tracker.sources.igdb_follow_ups import (
    CANDIDATE_FIELDS, FOLLOW_UPS_QUERY, SOURCE_KEY, IgdbFollowUpSource, parse_follow_ups,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "igdb"
GAMES = {
    "witcher-3": 1942, "elden-ring": 119133, "hades": 113112, "hades-2": 228525, "cyberpunk-2077": 1877,
    "uncharted-4": 7331, "lost-legacy": 26193, "spider-man": 19565, "hollow-knight": 14593, "god-of-war": 19560,
    "baldurs-gate-3": 119171, "ac-valhalla": 133004, "gta-6": 52189, "hunter-deathwish": 396020,
}


def answer(name):
    return json.loads((FIXTURES / f"follow-ups-{name}.json").read_text(encoding="utf-8"))


def snapshot(name):
    return parse_follow_ups(answer(name)[0])


def run(coro):
    return asyncio.run(coro)


class FakeIgdb:
    """Stands in for `IGDBProvider`: serves the saved answer of the game asked about and writes down the bodies."""

    def __init__(self, enabled=True, fail=None, empty=False):
        self.enabled = enabled
        self.fail = fail
        self.empty = empty
        self.asked = []

    async def games(self, body, *, at_once=False):
        self.asked.append((body, at_once))
        if self.fail:
            raise self.fail
        number = int(re.search(r"where id = (\d+);", body)[1])
        name = next((name for name, igdb_id in GAMES.items() if igdb_id == number), None)
        return [] if self.empty or name is None else answer(name)


# --- the query ---------------------------------------------------------------------------------------------------------


def test_the_query_names_every_field_of_every_list():
    body = FOLLOW_UPS_QUERY.format(id=1942)
    fields = set(body.removeprefix("fields ").split(";")[0].split(","))
    assert {"name", "game_type", "first_release_date", "collections.name"} <= fields
    for prefix in ("expansions", "standalone_expansions", "remakes", "remasters", "collections.games"):
        for name in CANDIDATE_FIELDS:
            assert f"{prefix}.{name}" in fields, (prefix, name)
    assert body.endswith("where id = 1942;")
    assert "dlcs" not in body and "franchises" not in body
    assert len(body) < 4000  # about 3,300 characters (spec 3.1)


def test_the_fields_of_a_candidate_are_those_of_the_spec():
    assert CANDIDATE_FIELDS == (
        "id", "name", "game_type", "version_parent", "first_release_date", "platforms", "alternative_names.name",
        "alternative_names.comment", "release_dates.date", "release_dates.date_format", "release_dates.y",
        "release_dates.m", "release_dates.platform", "release_dates.release_region", "release_dates.status",
    )


def test_the_saved_answers_have_the_shape_the_query_asks_for():
    asked = {"id", "name", "game_type", "first_release_date", "expansions", "standalone_expansions", "remakes",
             "remasters", "collections"}
    for name in GAMES:
        for game in answer(name):
            assert set(game) <= asked, name
            for collection in game.get("collections", []):
                assert set(collection) <= {"id", "name", "games"}


# --- the parse ---------------------------------------------------------------------------------------------------------


def test_the_witcher_3_gives_its_date_collection_expansions_and_games():
    found = snapshot("witcher-3")
    assert found.own_date == date(2015, 5, 19)
    assert found.collections == ("The Witcher",)
    assert [(c.id, c.name, c.standalone) for c in found.expansions] == [
        ("13166", "Ведьмак 3: Дикая Охота - Кровь и Вино", False),
        ("12503", "Ведьмак 3: Дикая Охота - Каменные сердца", False),
        ("403150", "Ведьмак 3: Дикая Охота — Баллады прошлого", False),
    ]
    ids = {c.id for c in found.games}
    # the remaster of the game itself, the games of the collection, the Russian names of IGDB
    assert {"415005", "194662", "220277", "220276", "19474", "80", "478"} <= ids
    assert next(c.name for c in found.games if c.id == "478") == "Ведьмак 2: Убийцы королей"
    # left out: the game itself, its expansions, DLC (1), another game's expansion (2), mods (5), an update (14)
    assert not ids & {"1942", "13166", "12503", "403150", "226413", "115776", "224493", "230102"}
    assert len(found.games) == 17


def test_a_candidate_keeps_its_first_day_platforms_and_release_records():
    witcher_4 = next(c for c in snapshot("witcher-3").games if c.id == "194662")
    assert witcher_4.first == date(2028, 12, 31)  # a year only: IGDB stores its 31 December
    assert witcher_4.platforms == (6, 167, 169)
    assert [(r.platform, r.type, r.date.text) for r in witcher_4.releases] == [
        (6, "full", "2028"), (167, "full", "2028"), (169, "full", "2028"),
    ]
    sirius = next(c for c in snapshot("witcher-3").games if c.id == "220276")
    assert (sirius.first, sirius.platforms, sirius.releases) == (None, (), ())


def test_the_standalone_expansions_are_expansions_and_not_games_of_the_series():
    uncharted = snapshot("uncharted-4")
    assert [(c.id, c.standalone) for c in uncharted.expansions] == [("26193", True)]
    assert "26193" not in {c.id for c in uncharted.games}
    spider_man = snapshot("spider-man")
    assert [(c.id, c.standalone) for c in spider_man.expansions] == [("134581", True)]
    valhalla = snapshot("ac-valhalla")
    assert {c.id: c.standalone for c in valhalla.expansions} == {
        "185706": False, "140174": False, "140175": False, "152231": True,
    }


def test_only_the_games_themselves_are_games_of_the_series():
    raw = answer("ac-valhalla")[0]
    every = {item["id"]: item["game_type"] for c in raw["collections"] for item in c["games"]}
    kept = {int(c.id) for c in snapshot("ac-valhalla").games}
    assert {every[number] for number in kept} <= {0, 4, 8, 9, 10, 11}
    # an episode (6), a pack (13), a bundle (3), DLC (1) and updates (14) are not games of the series
    assert not kept & {327929, 399892, 399893, 22974, 228706}
    assert {215060, 300976, 337738, 216321} <= kept  # Mirage, Shadows, Black Flag Resynced, Codename Hexe


def test_a_record_with_a_version_parent_is_left_out():
    raw = answer("hades")[0]
    edition = {**raw["collections"][0]["games"][0], "id": 999001, "version_parent": 113112}
    expansion = {"id": 999002, "name": "An edition of an expansion", "game_type": 2, "version_parent": 5}
    raw = {**raw, "collections": [{**raw["collections"][0], "games": raw["collections"][0]["games"] + [edition]}],
           "expansions": [expansion]}
    found = parse_follow_ups(raw)
    assert "999001" not in {c.id for c in found.games}
    assert found.expansions == ()


def test_each_record_is_kept_once_however_many_lists_hold_it():
    # Uncharted 4 Remastered is a remaster of the game and a game of the collection
    ids = [c.id for c in snapshot("uncharted-4").games]
    assert ids.count("168668") == 1
    assert len(ids) == len(set(ids))


def test_a_game_without_a_collection_or_expansions_gives_an_empty_snapshot():
    found = snapshot("hunter-deathwish")
    assert (found.collections, found.expansions, found.games) == ((), (), ())
    assert found.own_date == date(2027, 9, 30)


@pytest.mark.parametrize("name", sorted(GAMES))
def test_every_saved_answer_survives_the_store(name):
    found = snapshot(name)
    stored = json.loads(json.dumps(FollowUps(found, frozenset({"1"})).state()))
    assert FollowUps.from_state(stored) == FollowUps(found, frozenset({"1"}))


def test_garbage_in_the_answer_is_no_such_field():
    found = parse_follow_ups({
        "id": 1, "first_release_date": "soon", "collections": [{"name": 5, "games": "many"}, "x"],
        "expansions": [{"id": "2"}, {"id": 3, "name": None, "platforms": "pc", "release_dates": [None, 7]}, None],
        "remakes": {"id": 4},
    })
    assert found == FollowUpsSnapshot(own_date=None, collections=(), expansions=found.expansions, games=())
    assert [(c.id, c.name, c.platforms, c.releases) for c in found.expansions] == [("3", "3", (), ())]
    assert parse_follow_ups({"expansions": [{"id": 5, "game_type": [4]}]}).expansions[0].standalone is False


# --- the source --------------------------------------------------------------------------------------------------------


def test_the_source_asks_once_with_the_paced_requests_and_parses():
    igdb = FakeIgdb()
    source = IgdbFollowUpSource(igdb)
    assert source.source_key == SOURCE_KEY == "igdb_follow_ups"
    found = run(source.follow_ups("119133"))
    assert [c.name for c in found.expansions] == ["Elden Ring: Shadow of the Erdtree"]
    assert igdb.asked == [(FOLLOW_UPS_QUERY.format(id=119133), False)]


def test_an_empty_answer_means_igdb_no_longer_knows_the_game():
    with pytest.raises(TitleGone):
        run(IgdbFollowUpSource(FakeIgdb(empty=True)).follow_ups("1942"))


def test_a_failure_of_igdb_passes_through():
    with pytest.raises(IgdbError):
        run(IgdbFollowUpSource(FakeIgdb(fail=IgdbError("timeout"))).follow_ups("1942"))


def test_without_keys_nothing_is_asked():
    igdb = FakeIgdb(enabled=False)
    with pytest.raises(SourceNotConfigured):
        run(IgdbFollowUpSource(igdb).follow_ups("1942"))
    assert igdb.asked == []
