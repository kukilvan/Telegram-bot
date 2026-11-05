"""What the owner reads of the expansions and sequels in the core (spec 7.1, 7.3, 7.4 of stage 6.3, ticket 03): the view of
a game's card (`FollowUpsView`, `ParentGame`), the line of the parent in the bot card, the word «дополнение» after the
name of a row of the List and the Archive, `Pollers.follows` and `Tracker.follow`.

Driven through the facade as in `test_tracker_game_follow_ups`: fake clock, made-up game source, fake follow-up source.
"""

from datetime import date, timezone

import pytest
from sqlalchemy import event

from app.tracker import cards, games
from app.tracker.cards import FollowUpsView, ParentGame
from app.tracker.core import Tracker, UnknownKind
from app.tracker.db import create_session_factory
from app.tracker.follow_ups import Candidate, FollowUpsSnapshot
from app.tracker.games import FULL, GameDate, GameState, Parent, Release
from app.tracker.models import ARCHIVE_STATUSES, TitleKind, TitleStatus
from test_tracker_follow_ups import TABLE, snapshot
from test_tracker_game_follow_ups import PC, T0, FakeClock, FakeFollowUps, FakeSender, MadeUpGames, add, run

WORLD = 8  # the region of IGDB that counts for every country


WITCHER_3 = "1942"
COLLECTION = "The Witcher"


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def igdb():
    return MadeUpGames()


@pytest.fixture
def follow():
    return FakeFollowUps()


@pytest.fixture
def tracker(session_factory, igdb, follow):
    return Tracker(
        session_factory, clock=FakeClock(T0), sender=FakeSender(), sources={TitleKind.GAME: igdb}, follow_up_source=follow
    )


@pytest.fixture
def tracker_without_follow_ups(session_factory, igdb):
    return Tracker(session_factory, clock=FakeClock(T0), sender=FakeSender(), sources={TitleKind.GAME: igdb})


def candidate(id_, name, year=None, month=None, day=None, standalone=False):
    releases = (Release(PC, WORLD, FULL, GameDate(year, month, day)),) if year else ()
    first = date(year, month or 12, day or 31) if year else None
    return Candidate(id_, name, first=first, platforms=(PC,), releases=releases, standalone=standalone)


def answer_for_witcher(follow):
    follow.answers["1"] = FollowUpsSnapshot(
        own_date=date(2015, 5, 19),
        collections=(COLLECTION,),
        expansions=(
            candidate("20", "Кровь и Вино", 2016, 5, 30),
            candidate("21", "Каменные сердца", 2015, 10, 12),
            candidate("22", "Баллады прошлого"),
        ),
        games=(candidate("30", "The Witcher IV", 2028), candidate("31", "Gwent", 2018, 10, 23)),
    )


def checked_witcher(tracker, igdb, follow):
    answer_for_witcher(follow)
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    return title_id


def tag_of(tracker, title_id, statuses=None):
    return next(row.tag for row in run(tracker.list_titles(statuses=statuses)) if row.id == title_id)


# --- the view of a game's card (7.1) ---------------------------------------------------------------------------------


def test_a_game_for_the_check_has_its_expansions_and_sequels_by_date_with_the_ready_date_texts(tracker, igdb, follow):
    title_id = checked_witcher(tracker, igdb, follow)

    view = run(tracker.title_card(title_id)).follow_ups

    assert view.checked is True and view.collections == (COLLECTION,)
    assert [(line.external_id, line.name, line.when) for line in view.expansions] == [
        ("21", "Каменные сердца", "12 октября 2015"),
        ("20", "Кровь и Вино", "30 мая 2016"),
        ("22", "Баллады прошлого", "дата не объявлена"),
    ]
    assert [(line.external_id, line.when) for line in view.sequels] == [("31", "23 октября 2018"), ("30", "2028")]


@pytest.mark.parametrize("name", sorted(TABLE))
def test_the_cards_on_the_saved_answers_list_what_the_table_of_the_spec_says(tracker, igdb, follow, name):
    follow.answers["1"] = snapshot(name)
    title_id = add(tracker, igdb)
    run(tracker.poll_due())

    view = run(tracker.title_card(title_id)).follow_ups

    assert ([(line.name, line.when) for line in view.expansions], [(line.name, line.when) for line in view.sequels]) == TABLE[name]


def test_the_moment_of_the_check_is_aware_and_on_the_owners_clock(tracker, igdb, follow):
    title_id = checked_witcher(tracker, igdb, follow)

    checked_at = run(tracker.title_card(title_id)).follow_ups.checked_at

    assert checked_at.utcoffset() is not None and checked_at == T0
    assert checked_at.astimezone(timezone.utc).hour == 12


def test_a_game_that_was_not_checked_yet_says_so_before_and_after_it_got_its_snapshot(tracker, igdb, follow):
    title_id = add(tracker, igdb)

    assert run(tracker.title_card(title_id)).follow_ups == FollowUpsView(checked=False)  # no snapshot yet

    follow.failures["1"] = RuntimeError("IGDB is down")  # the snapshot is made, the check fails and stays empty
    run(tracker.poll_due())

    assert run(tracker.title_card(title_id)).follow_ups == FollowUpsView(checked=False)


def test_a_candidate_in_the_list_carries_the_number_of_its_title(tracker, igdb, follow):
    answer_for_witcher(follow)
    igdb.put("20", GameState(platforms=(PC,)), "Кровь и Вино")
    followed = run(tracker.follow("game", "20")).title_id
    title_id = add(tracker, igdb)
    run(tracker.poll_due())

    view = run(tracker.title_card(title_id)).follow_ups

    assert {line.external_id: line.title_id for line in view.expansions} == {"21": None, "20": followed, "22": None}


@pytest.mark.parametrize("status", [TitleStatus.WANT, TitleStatus.IN_PROGRESS, TitleStatus.COMPLETED])
def test_the_games_of_the_three_statuses_have_the_view(tracker, igdb, follow, status):
    title_id = checked_witcher(tracker, igdb, follow)
    if status == TitleStatus.IN_PROGRESS:
        run(tracker.mark_started(title_id))
    elif status == TitleStatus.COMPLETED:
        run(tracker.mark_watched(title_id))

    assert run(tracker.title_card(title_id)).follow_ups.checked is True


def test_a_dropped_game_has_no_view(tracker, igdb, follow):
    title_id = checked_witcher(tracker, igdb, follow)
    run(tracker.mark_dropped(title_id))

    assert run(tracker.title_card(title_id)).follow_ups is None


def test_a_core_without_the_follow_up_source_gives_no_view_and_no_parent(tracker_without_follow_ups, igdb):
    igdb.put("1", GameState(platforms=(PC,)), "Ведьмак 3")
    title_id = run(tracker_without_follow_ups.add_title(TitleKind.GAME, "1")).title_id

    card = run(tracker_without_follow_ups.title_card(title_id))

    assert card.follow_ups is None and card.parent is None


def test_a_spoiled_stored_state_shows_no_blocks_instead_of_breaking_the_card(tracker, igdb, follow, session_factory, caplog):
    from sqlalchemy import select

    from app.tracker.models import SourceSnapshot

    title_id = checked_witcher(tracker, igdb, follow)
    with session_factory() as session:
        stored = session.scalar(select(SourceSnapshot).where(SourceSnapshot.title_id == title_id, SourceSnapshot.source == "igdb_follow_ups"))
        stored.state = {"own_date": None, "expansions": "garbage"}
        session.commit()

    assert run(tracker.title_card(title_id)).follow_ups is None
    assert "spoiled state of the follow-up check" in caplog.text


# --- the parent of an expansion (7.1, 7.2, 8) -------------------------------------------------------------------------


def expansion_state(kind):
    return GameState(platforms=(PC,), expansion=kind, parent=Parent(WITCHER_3, "The Witcher 3: Wild Hunt"))


def test_an_expansion_of_the_list_names_its_parent_with_the_title_of_the_list(tracker, igdb, follow):
    igdb.put(WITCHER_3, GameState(platforms=(PC,)), "Ведьмак 3: Дикая охота")
    parent = run(tracker.add_title(TitleKind.GAME, WITCHER_3)).title_id
    igdb.put("20", expansion_state(games.EXPANSION), "Кровь и Вино")

    expansion = run(tracker.follow("game", "20")).title_id

    assert run(tracker.title_card(expansion)).parent == ParentGame("Ведьмак 3: Дикая охота", parent)


def test_an_expansion_whose_parent_is_not_in_the_list_names_it_as_igdb_does_and_after_a_delete_too(tracker, igdb, follow):
    igdb.put(WITCHER_3, GameState(platforms=(PC,)), "Ведьмак 3: Дикая охота")
    parent = run(tracker.add_title(TitleKind.GAME, WITCHER_3)).title_id
    igdb.put("20", expansion_state(games.EXPANSION), "Кровь и Вино")
    expansion = run(tracker.follow("game", "20")).title_id

    run(tracker.delete_title(parent))

    assert run(tracker.title_card(expansion)).parent == ParentGame("The Witcher 3: Wild Hunt", None)


def test_an_expansion_that_needs_its_game_has_the_parent_and_no_blocks(tracker, igdb, follow):
    igdb.put("20", expansion_state(games.EXPANSION), "Кровь и Вино")
    expansion = run(tracker.follow("game", "20")).title_id
    run(tracker.poll_due())

    card = run(tracker.title_card(expansion))

    assert card.parent == ParentGame("The Witcher 3: Wild Hunt", None) and card.follow_ups is None


def test_a_standalone_expansion_has_the_parent_and_the_blocks(tracker, igdb, follow):
    igdb.put("20", expansion_state(games.STANDALONE), "Miles Morales")
    expansion = run(tracker.follow("game", "20")).title_id

    card = run(tracker.title_card(expansion))

    assert card.parent == ParentGame("The Witcher 3: Wild Hunt", None) and card.follow_ups == FollowUpsView(checked=False)


def test_a_game_that_is_no_expansion_has_no_parent(tracker, igdb, follow):
    title_id = checked_witcher(tracker, igdb, follow)

    assert run(tracker.title_card(title_id)).parent is None


# --- the bot card (7.3) ---------------------------------------------------------------------------------------------


def test_the_bot_card_says_whose_expansion_it_is_after_the_names_and_lists_no_follow_ups(tracker, igdb, follow):
    igdb.put(WITCHER_3, GameState(platforms=(PC,)), "Ведьмак 3: Дикая охота")
    run(tracker.add_title(TitleKind.GAME, WITCHER_3))
    igdb.put("20", expansion_state(games.STANDALONE), "Кровь и Вино")
    expansion = run(tracker.follow("game", "20")).title_id

    lines = cards.format_card(run(tracker.title_card(expansion))).split("\n")

    assert lines[1] == "Кровь и Вино" and lines[2] == "Дополнение к игре «Ведьмак 3: Дикая охота»"
    assert "Кровь и Вино" not in "\n".join(cards.format_card(run(tracker.title_card(1))).split("\n")[3:])


def test_a_game_that_is_no_expansion_has_no_such_line_in_the_bot_card(tracker, igdb, follow):
    title_id = checked_witcher(tracker, igdb, follow)

    assert "Дополнение к игре" not in cards.format_card(run(tracker.title_card(title_id)))


# --- the word after the name in the List and the Archive (7.4) ------------------------------------------------------


def test_an_expansion_of_either_kind_has_the_tag_and_a_game_has_none(tracker, igdb, follow):
    game = add(tracker, igdb, "1", "Ведьмак 3")
    igdb.put("20", expansion_state(games.EXPANSION), "Кровь и Вино")
    igdb.put("21", expansion_state(games.STANDALONE), "Каменные сердца")
    needs_game = run(tracker.follow("game", "20")).title_id
    standalone = run(tracker.follow("game", "21")).title_id

    assert [tag_of(tracker, t) for t in (game, needs_game, standalone)] == ["", "дополнение", "дополнение"]


def test_the_archive_shows_the_tag_too(tracker, igdb, follow):
    igdb.put("20", expansion_state(games.EXPANSION), "Кровь и Вино")
    expansion = run(tracker.follow("game", "20")).title_id
    run(tracker.mark_watched(expansion))

    assert tag_of(tracker, expansion, statuses=ARCHIVE_STATUSES) == "дополнение"


def test_the_list_reads_as_much_for_thirty_games_as_for_one(tracker, igdb, session_factory):
    def reads():
        statements = []
        engine = session_factory.kw["bind"]
        listener = lambda *args: statements.append(args[2])  # noqa: E731
        event.listen(engine, "before_cursor_execute", listener)
        try:
            run(tracker.list_titles())
        finally:
            event.remove(engine, "before_cursor_execute", listener)
        return len([s for s in statements if s.lstrip().upper().startswith("SELECT")])

    add(tracker, igdb, "1")
    one = reads()
    for n in range(2, 31):
        add(tracker, igdb, str(n), f"Игра {n}")

    assert reads() == one


def test_the_card_reads_as_much_for_a_long_list_as_for_a_short_one(tracker, igdb, follow, session_factory):
    def reads(title_id):
        statements = []
        engine = session_factory.kw["bind"]
        listener = lambda *args: statements.append(args[2])  # noqa: E731
        event.listen(engine, "before_cursor_execute", listener)
        try:
            run(tracker.title_card(title_id))
        finally:
            event.remove(engine, "before_cursor_execute", listener)
        return len([s for s in statements if s.lstrip().upper().startswith("SELECT")])

    follow.answers["1"] = FollowUpsSnapshot(
        collections=(COLLECTION,), expansions=(candidate("20", "Одно", 2016),), games=(candidate("30", "Игра", 2028),)
    )
    short = add(tracker, igdb, "1")
    follow.answers["2"] = FollowUpsSnapshot(
        collections=(COLLECTION,),
        expansions=tuple(candidate(str(100 + n), f"Дополнение {n}", 2016) for n in range(40)),
        games=tuple(candidate(str(200 + n), f"Игра {n}", 2028) for n in range(40)),
    )
    long = add(tracker, igdb, "2", "Длинная серия")
    run(tracker.poll_due())

    assert len(run(tracker.title_card(long)).follow_ups.expansions) == 40
    assert reads(short) == reads(long)


# --- «Следить» and the kinds that announce titles (2.2) --------------------------------------------------------------


def test_a_game_follows_while_the_core_has_the_follow_up_source_and_not_without_it(tracker, tracker_without_follow_ups, igdb):
    igdb.put("20", expansion_state(games.EXPANSION), "Кровь и Вино")

    with pytest.raises(UnknownKind):
        run(tracker_without_follow_ups.follow("game", "20"))
    result = run(tracker.follow("game", "20"))

    assert result.created is True and run(tracker.follow("game", "20")).created is False  # twice opens it


def test_an_expansion_of_any_igdb_type_joins_as_a_game_of_its_own(tracker, igdb):
    igdb.put("20", expansion_state(games.EXPANSION), "Кровь и Вино")

    card = run(tracker.title_card(run(tracker.follow("game", "20")).title_id))

    assert (card.kind, card.status, card.name) == (TitleKind.GAME, TitleStatus.WANT, "Кровь и Вино")


@pytest.mark.parametrize("kind", ["series", "anime", "book", ""])
def test_a_kind_that_announces_nothing_or_does_not_exist_is_refused(tracker, kind):
    with pytest.raises(UnknownKind):
        run(tracker.follow(kind, "1"))
