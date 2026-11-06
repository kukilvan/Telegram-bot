"""Offers of an inbox item (spec 3, 5, 6 of stage 6.4) through the real core and adapters on the saved live answers:
the 18 samples of 5.6, the typos of 5.4, the order of 5.3 and the limits, the weak offer, failures before and after the
first offer, the request budget of 5.5, the links of section 3, the card text of 6.1, «Да» and «Нет» in the core."""

import asyncio
import logging
from datetime import date
from types import SimpleNamespace

import pytest

from app.tracker import offers as module
from app.tracker.candidates import Candidate
from app.tracker.core import IncomingMessage, InboxOutcome, InboxReason, InboxState
from app.tracker.models import GamePlatformRecord, InboxRecord, TitleKind
from app.tracker.offers import Offer, card_text, new_from, searched
from inbox_fakes import ANSWERS, Clients, samples, tracker_on

GAME, SERIES, ANIME, MOVIE = TitleKind.GAME, TitleKind.SERIES, TitleKind.ANIME, TitleKind.MOVIE
TODAY = date(2026, 11, 5)
KINDS = {
    1: GAME, 2: SERIES, 3: GAME, 4: ANIME, 5: GAME, 6: ANIME, 7: GAME, 8: GAME, 9: GAME, 10: GAME, 11: GAME, 12: GAME,
    13: ANIME, 14: ANIME, 15: GAME, 16: GAME, 17: MOVIE, 18: GAME,
}
# 5.6: the offers of each sample, the first one first (its number in the source)
EXPECTED = {
    1: ["414822"], 2: ["289517"], 3: ["370095"], 4: ["62931"], 5: ["250618", "136879", "119133"], 6: ["269"],
    7: ["279621", "379592", "73"], 8: ["222342"], 9: ["319082"], 10: ["404716"], 11: ["422039", "102522"], 12: [],
    13: ["54852"], 14: ["39535"], 15: ["250618"], 16: ["381235"], 17: ["1485839"], 18: ["225582"],
}
CORRECTED, HEADING = module.CORRECTED, module.HEADING


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def clients():
    return Clients()


@pytest.fixture
def tracker(clients):
    return tracker_on(clients)


def take(tracker, text, *, forwarded=False, links=()):
    return run(tracker.take_in(IncomingMessage(text=text, forwarded=forwarded, links=links))).item_id


def stored(tracker, item_id):
    with tracker.session_factory() as session:
        item = session.get(InboxRecord, item_id)
        return None if item is None else [Offer.read(raw) for raw in item.offers]


def entry(tracker, item_id):
    return run(tracker.inbox_item(item_id))


def analysed(tracker, text, kind, *, forwarded=True):
    item = take(tracker, text, forwarded=forwarded)
    return item, run(tracker.answer_kind(item, kind))


# --- the 18 samples --------------------------------------------------------------------------------------


@pytest.mark.parametrize("number", range(1, 19))
def test_each_sample_gives_the_offers_of_the_table_within_the_budget(tracker, clients, number):
    item, reply = analysed(tracker, samples()[number], KINDS[number])

    assert [offer.external_id for offer in stored(tracker, item)] == EXPECTED[number]
    assert 1 <= len(clients.searches()) <= 3  # measured on the 18 samples (5.5)
    if EXPECTED[number]:
        assert reply.outcome == InboxOutcome.OFFER and reply.offer.number == 0
        assert entry(tracker, item).state == InboxState.WAITING
    else:  # sample 12: IGDB has no Fabula Rasa
        assert reply.outcome == InboxOutcome.NOT_FOUND
        assert (entry(tracker, item).state, entry(tracker, item).reason) == (InboxState.INBOX, InboxReason.NOT_FOUND)


def test_the_weak_offer_of_sample_2_is_the_record_tmdb_found_by_a_name_it_does_not_return(tracker):
    item, reply = analysed(tracker, samples()[2], SERIES)

    assert reply.offer.text.startswith("Это оно?\n\n📺 Работа с призрачными перспективами\n꿀알바")


def test_sample_15_says_in_the_list_when_the_game_was_added_before(tracker):
    added = run(tracker.add_title(GAME, "250618"))

    item, reply = analysed(tracker, samples()[15], GAME)

    assert (reply.outcome, reply.title_id) == (InboxOutcome.IN_LIST, added.title_id)
    assert entry(tracker, item) is None  # resolved


# --- typos (5.4) -----------------------------------------------------------------------------------------

TYPOS = [
    ("Реинкарнация безработнго", ANIME, ["39535"], 3),
    ("Phantom Blad Zero", GAME, ["250618"], 4),
    ("Ведьмак 3 Дикая охта", GAME, ["1942"], 3),  # The Witcher 3: Wild Hunt, by «Ведьмак 3: Дикая охота»
    ("Cyberpnk 2077", GAME, ["1877", "397607"], 4),  # Cyberpunk 2077, Cyberpunk 2077: Turf Wars
    ("Игра в кальмра", SERIES, ["93405", "204082"], 3),
    ("Eldn Ring", MOVIE, ["1485839"], 4),
]


@pytest.mark.parametrize(("name", "kind", "corrected", "count"), TYPOS)
def test_a_typo_of_a_name_message_is_corrected_with_the_searches_of_the_table(tracker, clients, name, kind, corrected, count):
    item, reply = analysed(tracker, name, kind, forwarded=False)

    offers = stored(tracker, item)
    assert [o.external_id for o in offers if o.heading == CORRECTED] == corrected
    assert offers[0].heading == CORRECTED and reply.offer.text.startswith(CORRECTED)
    assert len(clients.searches()) == count


def test_dead_end_job_is_not_corrected_and_keeps_its_weak_offer(tracker, clients):
    item, reply = analysed(tracker, "Dead-End Job", SERIES, forwarded=False)

    assert [(o.external_id, o.heading) for o in stored(tracker, item)] == [("289517", HEADING)]
    assert clients.searches() == ["series:Dead-End Job", "series:Dead-End", "series:Job"]


def test_the_weak_offer_comes_after_the_corrected_ones(tracker):
    item, _ = analysed(tracker, "Реинкарнация безработнго", ANIME, forwarded=False)

    assert [o.heading for o in stored(tracker, item)] == [CORRECTED, HEADING]


def test_a_one_word_name_is_not_corrected(tracker, clients):
    analysed(tracker, "Cyberpnk", GAME, forwarded=False)

    assert clients.searches() == ["game:Cyberpnk"]


def test_a_post_is_no_name_message_and_is_not_corrected(tracker, clients):
    analysed(tracker, "Phantom Blad Zero", GAME, forwarded=True)

    assert clients.searches() == ["game:Phantom Blad Zero"]


# --- the order and the limits (made-up records) ----------------------------------------------------------


def record(number, name, released=None, other=()):
    return SimpleNamespace(
        kind=GAME, external_id=str(number), name=name, original_name=name, other_names=tuple(other), released=released,
        details=None, poster_path=None, title_id=None,
    )


def test_the_order_is_the_year_of_the_item_then_new_with_a_date_then_no_date_then_the_rest():
    gathered = module._Gathered([2027], new_from(TODAY))
    records = [
        record(1, "Exodus", date(2001, 1, 1)), record(2, "Exodus"), record(3, "Exodus", date(2025, 12, 1)),
        record(4, "Exodus", date(2027, 4, 7)), record(5, "Exodus", date(2024, 11, 5)),
    ]

    gathered.add(sorted(records, key=gathered.group), HEADING)

    assert [o.external_id for o in gathered.offers] == ["4", "3", "5"]  # at most 3; 2024-11-05 is new to the day
    assert [gathered.group(r) for r in records] == [3, 2, 1, 0, 1]


def test_exact_comes_before_prefix_and_a_candidate_gives_at_most_two():
    gathered = module._Gathered([], new_from(TODAY))
    records = [
        record(1, "Control Resonant Deluxe", date(2026, 1, 1)), record(2, "Something", other=["Control: Resonant"]),
        record(3, "Control: Resonant"), record(4, "Controlled"),
    ]

    assert [r.external_id for r in gathered.matching("Control Resonant", records)] == ["2", "3"]
    assert [r.external_id for r in gathered.matching("Control", records[:1] + records[3:])] == ["1"]


def test_the_half_weight_rule_and_three_candidates_at_most():
    found = [Candidate("A", 10, 0), Candidate("B", 6, 1), Candidate("C", 5, 2), Candidate("D", 5, 3), Candidate("E", 1, 4)]

    assert [c.name for c in searched(found)] == ["A", "B", "C"]
    assert [c.name for c in searched([Candidate("Fishy", 24, 0), Candidate("Scary Baboon", 6, 1)])] == ["Fishy"]
    assert searched([]) == []


def test_new_counts_from_the_same_day_two_years_ago():
    assert new_from(date(2026, 11, 5)) == date(2024, 11, 5)
    assert new_from(date(2028, 2, 29)) == date(2026, 2, 28)


def test_three_offers_at_most_and_each_record_once(tracker):
    item, _ = analysed(tracker, samples()[5], GAME)

    assert len(stored(tracker, item)) == 3


# --- failures and the budget -----------------------------------------------------------------------------


def test_a_source_failing_before_the_first_offer_ends_with_source_failed(tracker, clients):
    clients.igdb.fail_from = 1

    item, reply = analysed(tracker, samples()[5], GAME)

    assert (reply.outcome, reply.kind) == (InboxOutcome.SOURCE_FAILED, GAME)
    assert (entry(tracker, item).state, entry(tracker, item).reason) == (InboxState.INBOX, InboxReason.SOURCE_FAILED)


def test_a_source_failing_after_the_first_offer_is_only_logged(tracker, clients, caplog):
    clients.igdb.fail_from = 2

    with caplog.at_level(logging.WARNING):
        item, reply = analysed(tracker, samples()[5], GAME)

    assert reply.outcome == InboxOutcome.OFFER
    assert [o.external_id for o in stored(tracker, item)] == ["250618"]
    assert "failed after an offer was found" in caplog.text


def test_a_failure_in_the_correction_before_any_offer_fails_the_analysis(tracker, clients):
    clients.tmdb.fail_from = 2

    _, reply = analysed(tracker, "Eldn Ring", MOVIE, forwarded=False)

    assert reply.outcome == InboxOutcome.SOURCE_FAILED


def test_games_without_the_keys_of_igdb_are_not_connected():
    clients = Clients(igdb_keys=False)
    tracker = tracker_on(clients)

    item, reply = analysed(tracker, samples()[5], GAME)

    assert reply.outcome == InboxOutcome.NOT_CONNECTED
    assert entry(tracker, item).reason == InboxReason.NOT_CONNECTED
    assert clients.requests == []


@pytest.mark.parametrize(("text", "kind"), [(name, kind) for name, kind, _, _ in TYPOS] + [("Dead-End Job", SERIES)])
def test_no_item_makes_more_requests_than_the_budget(tracker, clients, text, kind):
    analysed(tracker, text, kind, forwarded=False)

    assert len(clients.requests) <= 10 and len(clients.searches()) <= 1 + 4


# --- links (section 3) -----------------------------------------------------------------------------------


def paused(tracker, text, links=()):
    item = take(tracker, text, links=links)
    return item, run(tracker.inbox_pause_over(item))


@pytest.mark.parametrize(("link", "kind", "number"), [
    ("https://store.steampowered.com/app/1245620/ELDEN_RING/", GAME, "119133"),
    ("https://www.themoviedb.org/movie/1485839-elden-ring", MOVIE, "1485839"),
    ("https://www.themoviedb.org/ru/tv/289517", SERIES, "289517"),
    ("https://shikimori.one/animes/z57612-kikansha-no-mahou", ANIME, "57612"),
    ("https://www.imdb.com/title/tt1160419/", MOVIE, "438631"),
    ("https://www.imdb.com/title/tt11280740/", SERIES, "95396"),
])
def test_a_link_of_a_source_gives_an_offer_and_no_question(tracker, link, kind, number):
    item, reply = paused(tracker, link)

    assert reply.outcome == InboxOutcome.OFFER and reply.kind == kind
    first = stored(tracker, item)[0]
    assert (first.kind, first.external_id, first.heading) == (kind, number, HEADING)
    assert (entry(tracker, item).kind, entry(tracker, item).query) == (kind, first.name)  # «Найти» of a link item


def test_a_steam_number_igdb_does_not_know_is_searched_by_the_name_steam_gives(clients):
    nightreign = ANSWERS["igdb-games-by-steam:2622380"]
    clients = Clients(extra={"igdb-games-by-steam:2622380": [], "game:ELDEN RING NIGHTREIGN": nightreign})
    tracker = tracker_on(clients)

    item, reply = paused(tracker, "https://store.steampowered.com/app/2622380/")

    assert reply.outcome == InboxOutcome.OFFER
    assert [o.external_id for o in stored(tracker, item)] == ["325591"]
    assert clients.requests == [("igdb", "steam:2622380"), ("steam", "appdetails:2622380"), ("igdb", "game:ELDEN RING NIGHTREIGN")]


def test_an_unknown_steam_number_without_a_steam_name_goes_on_as_an_item_without_links(tracker):
    _, reply = paused(tracker, "https://store.steampowered.com/app/4000000/")

    assert reply.outcome == InboxOutcome.ASK


def test_a_game_link_without_the_keys_of_igdb_says_games_are_not_connected():
    tracker = tracker_on(Clients(igdb_keys=False))

    item, reply = paused(tracker, "https://store.steampowered.com/app/1245620/")

    assert reply.outcome == InboxOutcome.NOT_CONNECTED
    assert (entry(tracker, item).state, entry(tracker, item).reason) == (InboxState.INBOX, InboxReason.NOT_CONNECTED)


def test_a_failing_link_source_goes_on_as_an_item_without_links(tracker, clients):
    clients.igdb.fail_from = 1

    _, reply = paused(tracker, "https://store.steampowered.com/app/1245620/")

    assert reply.outcome == InboxOutcome.ASK


def test_a_link_and_a_name_give_the_link_offer_first_then_the_candidates_of_its_kind(tracker):
    item, _ = paused(tracker, "Скидки недели\nBlack Myth: Wukong и Elden Ring https://store.steampowered.com/app/1245620/")

    # Elden Ring of the link, Black Myth: Wukong, then Elden Ring Nightreign (a prefix of «Elden Ring»: its exact record
    # is the offer of the link already)
    assert [o.external_id for o in stored(tracker, item)] == ["119133", "136879", "325591"]


def test_a_link_without_a_source_and_no_name_is_asked_about(tracker):
    _, reply = paused(tracker, "https://youtube.com/watch?v=1")

    assert reply.outcome == InboxOutcome.ASK


# --- the card (6.1) --------------------------------------------------------------------------------------


def offer(**fields):
    base = dict(kind=GAME, external_id="1", name="The Wolf Among Us Remastered", original_name="The Wolf Among Us Remastered",
                released=date(2026, 10, 29), details="ПК, PS5, Xbox Series X|S", poster=None, heading=HEADING)
    return Offer(**{**base, **fields})


def test_the_card_text_of_a_game_out_this_year():
    assert card_text(offer(), TODAY) == "Это оно?\n\n🎮 The Wolf Among Us Remastered\n2026 · ПК, PS5, Xbox Series X|S"


def test_the_card_shows_the_original_name_only_when_its_key_differs_and_the_three_date_forms():
    assert card_text(offer(kind=ANIME, name="Выход смерти: Изоляция", original_name="Death Stranding: Isolations",
                           released=date(2027, 2, 12), details=None), TODAY) == (
        "Это оно?\n\n🎌 Выход смерти: Изоляция\nDeath Stranding: Isolations\nвыйдет 12 февраля 2027"
    )
    assert card_text(offer(name="Control Resonant", original_name="Control: Resonant", released=None, details=None),
                     TODAY).splitlines()[2:] == ["🎮 Control Resonant", "дата не объявлена"]
    assert card_text(offer(heading=CORRECTED, released=TODAY), TODAY).splitlines()[0] == CORRECTED


def test_an_offer_is_stored_and_read_back_the_same():
    kept = offer(poster="https://images.igdb.com/x.jpg", shown=True)

    assert Offer.read(kept.stored()) == kept


# --- «Да» и «Нет» in the core ----------------------------------------------------------------------------


def test_no_shows_the_next_offer_and_after_the_last_the_item_goes_to_the_inbox(tracker):
    item, _ = analysed(tracker, samples()[11], GAME)  # Fishy 2026, Fishy 2004

    second = run(tracker.answer_offer(item, 0, False))
    last = run(tracker.answer_offer(item, 1, False))

    assert (second.outcome, second.offer.number) == (InboxOutcome.OFFER, 1)
    assert last.outcome == InboxOutcome.NOT_FOUND
    assert (entry(tracker, item).state, entry(tracker, item).reason) == (InboxState.INBOX, InboxReason.NOT_FOUND)


def test_a_double_no_goes_past_the_card_the_first_one_showed(tracker):
    item, _ = analysed(tracker, samples()[5], GAME)

    first = run(tracker.answer_offer(item, 0, False))
    second = run(tracker.answer_offer(item, 0, False))

    assert (first.offer.number, second.offer.number) == (1, 2)


def test_yes_adds_a_game_with_playing_here_on_my_platforms_and_resolves_the_item(tracker):
    item, _ = analysed(tracker, samples()[5], GAME)  # Phantom Blade Zero on PC and PS5

    reply = run(tracker.answer_offer(item, 0, True))

    assert reply.outcome == InboxOutcome.ADDED
    with tracker.session_factory() as session:
        marks = {r.platform: r.playing for r in session.query(GamePlatformRecord).filter_by(title_id=reply.title_id)}
    assert marks == {"pc": True, "ps5": True}
    assert entry(tracker, item) is None


def test_yes_on_a_title_added_meanwhile_says_in_the_list(tracker):
    item, _ = analysed(tracker, samples()[5], GAME)
    added = run(tracker.add_title(GAME, "250618"))

    reply = run(tracker.answer_offer(item, 0, True))

    assert (reply.outcome, reply.title_id) == (InboxOutcome.IN_LIST, added.title_id)


def test_no_shows_in_the_list_when_the_next_title_was_added_meanwhile(tracker):
    item, _ = analysed(tracker, samples()[5], GAME)
    added = run(tracker.add_title(GAME, "136879"))

    reply = run(tracker.answer_offer(item, 0, False))

    assert (reply.outcome, reply.title_id) == (InboxOutcome.IN_LIST, added.title_id)
    assert entry(tracker, item) is None


def test_yes_when_the_source_fails_keeps_the_item_and_names_the_kind(tracker, clients):
    item, _ = analysed(tracker, samples()[5], GAME)
    clients.igdb.fail_from = 1

    reply = run(tracker.answer_offer(item, 0, True))

    assert (reply.outcome, reply.kind) == (InboxOutcome.ADD_FAILED, GAME)
    assert entry(tracker, item).state == InboxState.WAITING


def test_yes_when_the_source_no_longer_has_the_record_is_as_no(clients):
    tracker = tracker_on(clients)
    item, _ = analysed(tracker, samples()[11], GAME)
    clients.igdb.answers["game:Fishy"] = []  # the record is gone from IGDB: adding finds nothing
    for key in [k for k in clients.igdb.answers if k.startswith("game:")]:
        clients.igdb.answers[key] = [r for r in clients.igdb.answers[key] if str(r.get("id")) != "422039"]

    reply = run(tracker.answer_offer(item, 0, True))

    assert (reply.outcome, reply.offer.number) == (InboxOutcome.OFFER, 1)


def test_a_number_the_item_does_not_have_is_dead(tracker):
    item, _ = analysed(tracker, samples()[1], GAME)

    assert run(tracker.answer_offer(item, 5, True)).outcome == InboxOutcome.DEAD
    assert run(tracker.answer_offer(item, 5, False)).outcome == InboxOutcome.DEAD


def test_a_kind_press_of_an_item_in_the_inbox_sends_the_offer_and_keeps_it_there(tracker):
    first = take(tracker, "Phantom Blade Zero")
    take(tracker, "Что-то ещё")  # moves the first one to «Входящие» «без ответа»

    reply = run(tracker.answer_kind(first, GAME))

    assert reply.outcome == InboxOutcome.OFFER
    assert entry(tracker, first).state == InboxState.INBOX
    assert entry(tracker, first + 1).state == InboxState.WAITING
