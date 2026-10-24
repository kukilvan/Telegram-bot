"""Shikimori anime adapter: saved real responses (tests/fixtures/shikimori) become franchises. No network.

The four fixtures are the real entries of the franchises the audit checked (One Piece, Jujutsu Kaisen,
Kusuriya no Hitorigoto, Made in Abyss), each with everything reachable through prequel and sequel relations,
as the `animes(ids: ...)` query returns it. `search_jujutsu.json` is a real search answer.
"""

import asyncio
from datetime import datetime

import pytest

from anime_fakes import FakeAniList, FakeShikimori, load

from app.tracker.sources.shikimori_anime import (
    ShikimoriAnimeSource,
    build_snapshot,
    chain_order,
    collect_entries,
    parse_entry,
    parse_search,
)

NOW = datetime(2026, 10, 24, 12, 0)

ONE_PIECE, JJK, KUSURIYA, ABYSS = "21", "40748", "54492", "34599"


def run(coro):
    return asyncio.run(coro)


def franchise(fixture, start, anilist=None):
    source = ShikimoriAnimeSource(FakeShikimori(fixture), anilist)
    return run(source.snapshot(start))


def part_ids(snapshot, season):
    return [p.ids.shikimori for p in snapshot.parts if p.season == season]


def entries_of(*fixtures):
    return {a["id"]: parse_entry(a) for name in fixtures for a in load(name)}


# --- the four franchises of the audit -----------------------------------------------------------


def test_one_piece_is_one_season():
    snapshot = franchise("one_piece.json", ONE_PIECE)

    assert [s.number for s in snapshot.seasons] == [1]
    assert snapshot.movies == []
    assert snapshot.title == "Ван-Пис"
    assert snapshot.original_title == "One Piece"
    assert snapshot.year == 1999


def test_a_season_of_one_entry_is_one_part_however_long_it_has_been_on_air():
    [season] = franchise("one_piece.json", ONE_PIECE).seasons

    [part] = season.parts()  # 1180 episodes dated 1999 and the next one in 2026: no gap splits it
    assert (part.split, part.released(NOW)) == (False, 1180)


def test_one_piece_has_no_known_total_and_its_aired_episodes_are_out():
    [season] = franchise("one_piece.json", ONE_PIECE).seasons

    assert season.expected is None
    assert season.released(NOW) == 1180
    assert season.total() is None  # the card says «из ?»


def test_jujutsu_kaisen_has_four_seasons_and_the_prequel_film_is_a_franchise_movie():
    snapshot = franchise("jujutsu_kaisen.json", JJK)

    assert [s.number for s in snapshot.seasons] == [1, 2, 3, 4]
    assert [part_ids(snapshot, n) for n in (1, 2, 3, 4)] == [["40748"], ["51009"], ["57658"], ["63824"]]
    assert [m.ids.shikimori for m in snapshot.movies] == ["48561"]
    assert snapshot.movies[0].name == "Магическая битва 0. Фильм"


def test_jujutsu_kaisen_season_four_is_not_a_part_although_the_russian_name_says_part_2():
    snapshot = franchise("jujutsu_kaisen.json", JJK)

    assert all(len(s.cuts) == 1 for s in snapshot.seasons)  # no season is made of several parts
    assert snapshot.seasons[3].released(NOW) == 0  # announced, no date yet
    assert snapshot.seasons[3].first_air_at() is None


def test_kusuriya_has_three_seasons_and_the_third_has_two_parts():
    snapshot = franchise("kusuriya.json", KUSURIYA)

    assert [s.number for s in snapshot.seasons] == [1, 2, 3]
    assert part_ids(snapshot, 1) == ["54492"]
    assert part_ids(snapshot, 2) == ["58514"]
    assert part_ids(snapshot, 3) == ["61987", "62841"]
    assert [(p.season, p.number) for p in snapshot.parts] == [(1, 1), (2, 1), (3, 1), (3, 2)]
    assert snapshot.movies == []


def test_kusuriya_third_season_runs_its_parts_through_one_episode_numbering():
    snapshot = franchise("kusuriya.json", KUSURIYA)
    third = snapshot.seasons[2]
    first, second = third.parts()

    assert [p.first_episode for p in snapshot.parts if p.season == 3] == [1, 13]
    assert third.expected == 24
    assert (first.number, first.expected, first.released(NOW)) == (1, 12, 4)
    assert (second.number, second.expected, second.released(NOW)) == (2, 12, 0)
    assert second.first_air_at() == datetime(2027, 4, 1)  # the premiere day announced for part 2
    assert first.next_air_at(NOW) == datetime(2026, 10, 30, 14, 0)  # 17:00 at +03:00 is 14:00 UTC


def test_made_in_abyss_has_two_seasons_and_its_films():
    snapshot = franchise("made_in_abyss.json", ABYSS)

    assert [s.number for s in snapshot.seasons] == [1, 2]
    assert part_ids(snapshot, 1) == ["34599"]
    assert part_ids(snapshot, 2) == ["41084"]
    # the three films before season 2, the new one that came out yesterday and its announced second part
    assert [m.ids.shikimori for m in snapshot.movies] == ["37514", "37515", "36862", "54250", "65248"]
    assert [m.released for m in snapshot.movies] == [True, True, True, True, False]  # an announced film is not out
    assert snapshot.movies[-1].aired_on is None


def test_the_franchise_is_the_same_whichever_entry_the_owner_picked():
    from_season = franchise("jujutsu_kaisen.json", JJK)
    from_film = franchise("jujutsu_kaisen.json", "48561")
    from_last = franchise("jujutsu_kaisen.json", "63824")

    assert from_season.external_id == from_film.external_id == from_last.external_id == JJK
    assert [s.name for s in from_film.seasons] == [s.name for s in from_season.seasons]
    assert from_last.parts == from_season.parts and from_last.movies == from_season.movies


def test_the_title_is_the_first_season_and_not_a_film_that_came_before_it():
    snapshot = franchise("jujutsu_kaisen.json", "48561")

    assert snapshot.external_id == JJK
    assert snapshot.title == "Магическая битва"
    assert snapshot.year == 2020
    assert snapshot.genres  # Russian genre names only, no demographics or themes
    assert "Сёнен" not in franchise("one_piece.json", ONE_PIECE).genres


def test_the_franchise_key_is_kept_in_the_state_of_the_snapshot():
    snapshot = franchise("kusuriya.json", KUSURIYA)

    assert snapshot.franchise == "maomao_no_hitorigoto"
    assert snapshot.state() == {"franchise": "maomao_no_hitorigoto"}


# --- the episodes Shikimori can tell -------------------------------------------------------------


def test_finished_season_has_all_its_episodes_out_and_an_unfilled_counter_does_not_hide_them():
    snapshot = franchise("jujutsu_kaisen.json", JJK)

    assert [(s.number, s.released(NOW), s.total()) for s in snapshot.seasons] == [
        (1, 24, 24), (2, 23, 23), (3, 12, 12), (4, 0, None)
    ]
    raw = dict(load("jujutsu_kaisen.json")[0], episodesAired=0, status="released", episodes=24)
    [season] = chain_of(raw).seasons
    assert season.released(NOW) == 24


def test_an_airing_season_names_its_next_episode_and_a_season_with_a_premiere_day_is_announced_on_it():
    kusuriya = franchise("kusuriya.json", KUSURIYA)
    airing = kusuriya.seasons[2].parts()[0]

    assert airing.status(NOW) == "airing"
    assert airing.next_air_at(NOW) == datetime(2026, 10, 30, 14, 0)

    announced = kusuriya.seasons[2].parts()[1]
    assert announced.status(NOW) == "announced"


# --- ids: every entry has its own, nothing twice ------------------------------------------------


def test_every_part_and_film_has_shikimori_and_mal_ids_that_are_the_same_number():
    snapshot = franchise("made_in_abyss.json", ABYSS)

    for ids in [p.ids for p in snapshot.parts] + [m.ids for m in snapshot.movies]:
        assert ids.shikimori and ids.mal == ids.shikimori
    everything = [p.ids.shikimori for p in snapshot.parts] + [m.ids.shikimori for m in snapshot.movies]
    assert len(everything) == len(set(everything)) == 7


def test_anilist_ids_come_from_the_mal_ids_in_one_request():
    anilist = FakeAniList()
    snapshot = franchise("kusuriya.json", KUSURIYA, anilist)

    assert anilist.asked == [[54492, 58514, 61987, 62841]]
    assert [p.ids.anilist for p in snapshot.parts] == ["154492", "158514", "161987", "162841"]


def test_an_anilist_id_that_two_entries_share_is_kept_for_the_first_only():
    anilist = FakeAniList({61987: 777, 62841: 777, 54492: 11, 58514: 12})
    snapshot = franchise("kusuriya.json", KUSURIYA, anilist)

    assert [p.ids.anilist for p in snapshot.parts] == ["11", "12", "777", None]
    stored = [p.ids.anilist for p in snapshot.parts if p.ids.anilist]
    assert len(stored) == len(set(stored))


def test_films_get_anilist_ids_too_and_an_unknown_one_stays_empty():
    anilist = FakeAniList({34599: 1, 41084: 2, 37514: 3})
    snapshot = franchise("made_in_abyss.json", ABYSS, anilist)

    assert [m.ids.anilist for m in snapshot.movies] == ["3", None, None, None, None]


def test_anilist_failure_leaves_the_ids_empty_but_the_franchise_is_there():
    anilist = FakeAniList()
    anilist.broken = True
    snapshot = franchise("jujutsu_kaisen.json", JJK, anilist)

    assert [s.number for s in snapshot.seasons] == [1, 2, 3, 4]
    assert all(p.ids.anilist is None for p in snapshot.parts)


def test_without_an_anilist_client_the_ids_stay_empty():
    assert all(p.ids.anilist is None for p in franchise("jujutsu_kaisen.json", JJK).parts)


# --- failures and the shape of the chain --------------------------------------------------------


def test_shikimori_failure_is_an_error_not_an_empty_franchise():
    shikimori = FakeShikimori("jujutsu_kaisen.json")
    shikimori.broken = True

    with pytest.raises(ConnectionError):
        run(ShikimoriAnimeSource(shikimori).snapshot(JJK))


def test_an_unknown_entry_is_none():
    assert franchise("jujutsu_kaisen.json", "999999") is None


def test_each_entry_is_asked_for_once_and_only_prequels_and_sequels_are_followed():
    shikimori = FakeShikimori("jujutsu_kaisen.json")
    run(collect_entries(shikimori.fetch_entries, JJK))

    asked = [i for batch in shikimori.fetched for i in batch]
    assert sorted(asked) == sorted(set(asked)) == sorted(shikimori.by_id)  # side stories etc. are never asked for


def test_the_chain_is_ordered_from_the_beginning_whatever_the_dates_say():
    entries = entries_of("made_in_abyss.json")
    # the announced film has no date: it still comes after the film it follows
    assert [e.id for e in chain_order(entries)] == ["34599", "37514", "37515", "36862", "41084", "54250", "65248"]


def test_relations_that_loop_do_not_hang_the_order():
    a = parse_entry(_raw("1", "A", chain=[("sequel", "2"), ("prequel", "2")], aired="2020-01-01"))
    b = parse_entry(_raw("2", "B", chain=[("sequel", "1"), ("prequel", "1")], aired="2021-01-01"))

    assert [e.id for e in chain_order({"1": a, "2": b})] == ["1", "2"]


def _raw(id_, name, kind="tv", chain=(), aired=None, duration=24, status="released", episodes=12, russian=None):
    return {
        "id": id_, "malId": id_, "name": name, "russian": russian, "kind": kind, "status": status,
        "episodes": episodes, "episodesAired": episodes if status == "released" else 0, "nextEpisodeAt": None,
        "duration": duration, "airedOn": {"date": aired}, "releasedOn": {"date": None}, "franchise": "f",
        "poster": None, "genres": [],
        "related": [{"relationKind": k, "relationText": k, "anime": {"id": o, "kind": "tv"}} for k, o in chain],
    }


def chain_of(*raws):
    return build_snapshot({r["id"]: parse_entry(r) for r in raws})


def test_part_marks_join_the_season_before_it():
    names = ["Show", "Show Part 2", "Show 2nd Cour", "Show Cour 3", "Show Season 2"]
    raws = [
        _raw(str(i + 1), name, aired=f"20{20 + i}-01-01",
             chain=([("prequel", str(i))] if i else []) + ([("sequel", str(i + 2))] if i < len(names) - 1 else []))
        for i, name in enumerate(names)
    ]
    snapshot = chain_of(*raws)

    assert [s.number for s in snapshot.seasons] == [1, 2]
    assert [len(s.cuts) for s in snapshot.seasons] == [4, 1]
    assert [(p.season, p.number) for p in snapshot.parts] == [(1, 1), (1, 2), (1, 3), (1, 4), (2, 1)]


def test_part_one_starts_a_season_and_a_part_without_a_season_before_it_becomes_one():
    snapshot = chain_of(
        _raw("1", "Show Part 2", aired="2020-01-01", chain=[("sequel", "2")]),
        _raw("2", "Show Part 1", aired="2021-01-01", chain=[("prequel", "1")]),
    )

    assert [s.number for s in snapshot.seasons] == [1, 2]


def test_ova_specials_recaps_and_short_onas_are_not_seasons_but_pass_the_chain_on():
    snapshot = chain_of(
        _raw("1", "Show", aired="2020-01-01", chain=[("sequel", "2")]),
        _raw("2", "Show OVA", kind="ova", aired="2020-06-01", chain=[("prequel", "1"), ("sequel", "3")]),
        _raw("3", "Show Chibi", kind="ona", duration=3, aired="2020-09-01", chain=[("prequel", "2"), ("sequel", "4")]),
        _raw("4", "Show Recap", kind="tv_special", aired="2020-10-01", chain=[("prequel", "3"), ("sequel", "5")]),
        _raw("5", "Show 2", aired="2021-01-01", chain=[("prequel", "4")]),
    )

    assert [s.name for s in snapshot.seasons] == ["Show", "Show 2"]
    assert snapshot.movies == []


def test_an_ona_of_normal_length_is_a_season():
    snapshot = chain_of(_raw("1", "Show", kind="ona", duration=24))

    assert [s.number for s in snapshot.seasons] == [1]


def test_a_franchise_of_films_alone_has_no_seasons_and_still_a_title():
    snapshot = chain_of(_raw("1", "Film", kind="movie", aired="2016-08-26", episodes=1, russian="Фильм"))

    assert snapshot.seasons == [] and [m.name for m in snapshot.movies] == ["Фильм"]
    assert (snapshot.external_id, snapshot.title) == ("1", "Фильм")


def test_a_chain_with_nothing_to_watch_is_none():
    assert chain_of(_raw("1", "Opening", kind="pv")) is None


def test_part_marks_are_read_from_the_original_name_only():
    snapshot = chain_of(
        _raw("1", "Show", aired="2020-01-01", chain=[("sequel", "2")]),
        _raw("2", "Show: Kouhen", aired="2021-01-01", chain=[("prequel", "1")], russian="Шоу. Часть 2"),
    )

    assert [s.number for s in snapshot.seasons] == [1, 2]


# --- search ------------------------------------------------------------------------------------


def test_search_gives_one_suggestion_per_franchise_named_after_its_first_season():
    suggestions = parse_search(load_search())

    jjk = next(s for s in suggestions if s.external_id == JJK)
    assert (jjk.kind, jjk.title, jjk.original_title, jjk.year) == ("anime", "Магическая битва", "Jujutsu Kaisen", 2020)
    assert sum(1 for s in suggestions if s.title.startswith("Магическая битва")) == 1  # not one per season or film


def test_search_leaves_out_promo_videos_and_music_but_keeps_other_franchises():
    suggestions = parse_search(load_search())
    titles = [s.title for s in suggestions]

    assert "Магическая битва PV" not in titles
    assert "Восставшие на бой" not in titles  # a music video
    assert "Морское сражение" in titles  # a film with no franchise is its own suggestion


def test_search_failure_is_an_error_not_an_empty_list():
    shikimori = FakeShikimori("jujutsu_kaisen.json")
    shikimori.broken = True

    with pytest.raises(ConnectionError):
        run(ShikimoriAnimeSource(shikimori).suggest("jujutsu"))


def load_search():
    return load("search_jujutsu.json")
