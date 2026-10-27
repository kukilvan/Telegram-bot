"""Anime seasons known by the first entry of the source, not by their number: the pure re-laying of what is stored.

No database, no network: stored seasons (with the entry behind each part) and the parts of a fresh answer in,
the stored seasons in the fresh numbering and the plan for the database out.
"""

from datetime import datetime

from app.tracker.anime_events import relayout
from app.tracker.seasons import Episode, PartCut, Season
from app.tracker.sources.shikimori_anime import SeasonPart, SourceIds

DAY = datetime(2026, 1, 1)


def part(season, number, first_episode, entry, count=12):
    return SeasonPart(season, number, first_episode, count, SourceIds(entry, entry))


def stored(number, entries, name=None):
    """A stored season made of the given entries: (id, first_episode, episode_count, episodes out), one cut each."""
    cuts, episodes = [], []
    for entry, first, count, out in entries:
        cuts.append(PartCut(first, count, entry))
        episodes += [Episode(first + i, DAY.replace(day=1 + i)) for i in range(out)]
    expected = sum(c.expected for c in cuts) if all(c.expected for c in cuts) else None
    return Season(number, name or f"Сезон {number}", expected, tuple(episodes), tuple(cuts), source_id=entries[0][0])


def numbers(season):
    return [e.number for e in season.episodes]


def test_an_unchanged_chain_gives_the_same_seasons_and_changes_no_number():
    one, two = stored(1, [("A", 1, 12, 12)]), stored(2, [("B", 1, 12, 5)])

    layout = relayout([one, two], [part(1, 1, 1, "A"), part(2, 1, 1, "B")])

    assert [(s.number, s.source_id, numbers(s)) for s in layout.seasons] == [
        (1, "A", list(range(1, 13))),
        (2, "B", [1, 2, 3, 4, 5]),
    ]
    assert layout.renumber == {1: 1, 2: 2}
    assert layout.dissolved == {}
    assert layout.had == {"A", "B"}


def test_an_entry_inserted_in_the_middle_moves_the_later_season_to_the_next_number_with_its_dates():
    one, two = stored(1, [("A", 1, 12, 12)]), stored(2, [("C", 1, 12, 5)])

    layout = relayout([one, two], [part(1, 1, 1, "A"), part(2, 1, 1, "X"), part(3, 1, 1, "C")])

    assert layout.renumber == {1: 1, 2: 3}
    assert [(s.number, s.source_id) for s in layout.seasons] == [(1, "A"), (3, "C")]  # nothing is stored for X
    assert layout.seasons[1].episodes == two.episodes  # the dates of the season that moved are the same ones
    assert layout.dissolved == {}
    assert layout.had == {"A", "C"}  # X is new to the title


def test_an_entry_that_leaves_the_seasons_dissolves_its_season_and_the_later_one_takes_its_number():
    seasons = [stored(1, [("A", 1, 12, 12)]), stored(2, [("B", 1, 12, 12)]), stored(3, [("C", 1, 12, 5)])]

    layout = relayout(seasons, [part(1, 1, 1, "A"), part(2, 1, 1, "C")])

    assert layout.renumber == {1: 1, 3: 2}
    assert layout.dissolved == {2: "B"}
    assert [(s.number, s.source_id, numbers(s)) for s in layout.seasons] == [
        (1, "A", list(range(1, 13))),
        (2, "C", [1, 2, 3, 4, 5]),
    ]


def test_a_season_that_becomes_part_two_of_the_one_before_brings_its_episodes_along_with_their_dates():
    one, two = stored(1, [("A", 1, 12, 12)]), stored(2, [("B", 1, 12, 12)])

    layout = relayout([one, two], [part(1, 1, 1, "A"), part(1, 2, 13, "B")])

    [season] = layout.seasons
    assert (season.number, season.source_id, numbers(season)) == (1, "A", list(range(1, 25)))
    assert season.episodes[12:] == tuple(Episode(e.number + 12, e.air_at) for e in two.episodes)
    assert [(c.first_episode, c.source_id) for c in season.cuts] == [(1, "A"), (13, "B")]
    assert len(season.parts()) == 2  # the old state has the two parts too: the cut is nothing new
    assert layout.renumber == {1: 1}
    assert layout.dissolved == {2: "B"}


def test_a_part_that_becomes_a_season_of_its_own_takes_its_episodes_with_it():
    both = stored(1, [("A", 1, 12, 12), ("B", 13, 12, 7)])

    layout = relayout([both], [part(1, 1, 1, "A"), part(2, 1, 1, "B")])

    assert [(s.number, s.source_id, numbers(s)) for s in layout.seasons] == [
        (1, "A", list(range(1, 13))),
        (2, "B", [1, 2, 3, 4, 5, 6, 7]),
    ]
    assert layout.renumber == {1: 1}
    assert layout.dissolved == {}


def test_an_episode_keeps_its_number_inside_the_entry_when_the_part_before_it_changes_size():
    both = stored(1, [("A", 1, 12, 12), ("B", 13, 12, 3)])

    layout = relayout([both], [part(1, 1, 1, "A", count=13), part(1, 2, 14, "B")])  # A got a thirteenth episode

    [season] = layout.seasons
    assert [(e.number, e.air_at) for e in season.episodes if e.number >= 13] == [
        (14, both.episodes[12].air_at),
        (15, both.episodes[13].air_at),
        (16, both.episodes[14].air_at),
    ]
    assert [c.first_episode for c in season.cuts] == [1, 14]


def test_the_episodes_of_an_entry_that_is_gone_are_dropped():
    both = stored(1, [("A", 1, 12, 12), ("B", 13, 12, 7)])

    layout = relayout([both], [part(1, 1, 1, "A")])

    [season] = layout.seasons
    assert numbers(season) == list(range(1, 13))
    assert [c.source_id for c in season.cuts] == ["A"]
    assert layout.had == {"A", "B"}


def test_the_announced_count_of_a_part_stays_as_it_was_stored():
    one = stored(1, [("A", 1, 12, 12)])

    layout = relayout([one], [part(1, 1, 1, "A", count=13)])  # the source now announces 13

    [season] = layout.seasons
    assert (season.expected, [c.expected for c in season.cuts]) == (12, [12])


def test_a_season_with_no_stored_parts_is_taken_as_it_is_by_its_number():
    old = Season(2, "Сезон 2", 12, (Episode(1, DAY), Episode(2, DAY)))

    layout = relayout([old], [part(1, 1, 1, "A"), part(2, 1, 1, "B")])

    assert layout.seasons == (old,)
    assert layout.renumber == {2: 2}
    assert layout.dissolved == {}
    assert layout.had == frozenset()


def test_an_answer_with_no_entries_at_all_dissolves_nothing():
    one, two = stored(1, [("A", 1, 12, 12)]), stored(2, [("B", 1, 12, 5)])

    layout = relayout([one, two], [])  # a franchise left with films only, or a source that said nothing

    assert layout.seasons == (one, two)
    assert (layout.renumber, layout.dissolved) == ({1: 1, 2: 2}, {})
    assert layout.had == {"A", "B"}


def test_nothing_stored_gives_nothing():
    layout = relayout([], [part(1, 1, 1, "A")])

    assert (layout.seasons, layout.renumber, layout.dissolved, layout.had) == ((), {}, {}, frozenset())
