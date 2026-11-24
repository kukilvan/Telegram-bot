"""Offers of «Входящие» after stage 9.1d (spec 8): the date of an offer as precise as its source (KI-64), the English
names of TMDb for a typo (KI-61), the links of the chosen kind looked up again at a kind press (KI-62) and the request
budget of 8.4 — on the saved live answers (`fixtures/igdb/search_date_format.json`, `fixtures/tmdb/dead_end_job.json`
and the answers of 6.4)."""

import asyncio
import json
import logging
from datetime import date
from pathlib import Path

import pytest

from app.tracker.core import IncomingMessage, InboxOutcome
from app.tracker.models import InboxRecord, TitleKind
from app.tracker.offer_cards import CORRECTED, HEADING, Offer, card_text, released_line
from app.tracker.release_dates import NOT_ANNOUNCED, ReleaseDate
from app.tracker.sources import igdb_games, shikimori_anime, tmdb_series
from inbox_fakes import ANSWERS, Clients, tracker_on

FIXTURES = Path(__file__).parent / "fixtures"
IGDB_DATES = json.loads((FIXTURES / "igdb" / "search_date_format.json").read_text(encoding="utf-8"))["answer"]
DEAD_END = json.loads((FIXTURES / "tmdb" / "dead_end_job.json").read_text(encoding="utf-8"))["answer"]
TODAY = date(2026, 11, 23)  # the day the answers of 9.1d were saved
GAME, SERIES, MOVIE = TitleKind.GAME, TitleKind.SERIES, TitleKind.MOVIE
STEAM_ELDEN_RING = "https://store.steampowered.com/app/1245620/ELDEN_RING/"


def run(coro):
    return asyncio.run(coro)


def take(tracker, text, *, forwarded=False, links=()):
    return run(tracker.take_in(IncomingMessage(text=text, forwarded=forwarded, links=links))).item_id


def stored(tracker, item_id):
    with tracker.session_factory() as session:
        return [Offer.read(raw) for raw in session.get(InboxRecord, item_id).offers]


# --- KI-64: the card line ---------------------------------------------------------------------------------


@pytest.mark.parametrize(("released", "line"), [
    (ReleaseDate.of_day(date(2027, 2, 12)), "выйдет 12 февраля 2027"),  # a day after today
    (ReleaseDate(year=2028), "выйдет в 2028"),  # approximate, not ended
    (ReleaseDate(year=2027, quarter=2), "выйдет во 2 квартале 2027"),
    (ReleaseDate(year=2027, month=1), "выйдет в январе 2027"),
    (ReleaseDate(year=2026), "выйдет в 2026"),  # the year of today has not ended
    (ReleaseDate(year=2026, quarter=4), "выйдет в 4 квартале 2026"),
    (ReleaseDate(year=2026, quarter=3), "2026"),  # approximate, ended
    (ReleaseDate(year=2025), "2025"),
    (ReleaseDate.of_day(date(2026, 10, 29)), "2026"),  # a day that has passed
    (ReleaseDate.of_day(TODAY), "2026"),  # today is no «выйдет»
    (NOT_ANNOUNCED, "дата не объявлена"),
])
def test_the_line_of_the_date_of_an_offer_on_every_form(released, line):
    assert released_line(released, TODAY) == line


# --- KI-64: the date of each source -------------------------------------------------------------------------


def igdb_line(name, index=0):
    record = igdb_games.parse_records(IGDB_DATES[name])[index]
    return released_line(record.released, TODAY)


def test_igdb_gives_the_precision_of_the_record_of_the_first_release():
    assert igdb_line("The Witcher IV") == "выйдет в 2028"  # `date_format` 2 on all three platforms
    assert igdb_line("Intergalactic: The Heretic Prophet") == "выйдет в 2027"
    assert igdb_line("Marvel 1943") == "выйдет в 2027"
    assert igdb_line("Fishy Bar") == "выйдет во 2 квартале 2027"  # 4: quarter 2
    silksong = {r.external_id: r.released for r in igdb_games.parse_records(IGDB_DATES["Hollow Knight: Silksong"])}
    assert silksong["115289"] == ReleaseDate.of_day(date(2025, 9, 4))  # 0: a day
    assert released_line(silksong["115289"], TODAY) == "2025"


def test_the_least_precise_record_of_the_first_release_wins_and_none_matching_is_the_year():
    first = 1830211200  # 2027-12-31 in UTC
    day = {"date": first, "date_format": 0, "y": 2027, "m": 12}
    year = {"date": first, "date_format": 2, "y": 2027, "m": 12}
    quarter = {"date": first, "date_format": 6, "y": 2027, "m": 12}
    other = {"date": first - 86400 * 400, "date_format": 0, "y": 2026, "m": 11}

    def of(*records):
        return igdb_games.first_release({"first_release_date": first, "release_dates": list(records)})

    assert of(day, year) == ReleaseDate(year=2027)
    assert of(day, quarter) == ReleaseDate(year=2027, quarter=4)
    assert of(day) == ReleaseDate.of_day(date(2027, 12, 31))
    assert of(other) == ReleaseDate(year=2027)  # never a made-up day
    assert of() == ReleaseDate(year=2027)
    assert igdb_games.first_release({"release_dates": [day]}) == NOT_ANNOUNCED


def test_the_search_of_igdb_asks_the_records_of_the_dates():
    assert "release_dates.date,release_dates.date_format,release_dates.y,release_dates.m" in igdb_games.SEARCH_QUERY


def test_shikimori_gives_the_precision_of_its_premiere():
    raw = dict(ANSWERS["anime:Блич"][0])

    month = shikimori_anime.parse_search([{**raw, "airedOn": {"date": "2027-01-01", "year": 2027, "month": 1, "day": None}}])
    year = shikimori_anime.parse_search([{**raw, "airedOn": {"date": "2028-01-01", "year": 2028, "month": None, "day": None}}])

    assert (month[0].released, released_line(month[0].released, TODAY)) == (ReleaseDate(2027, 1), "выйдет в январе 2027")
    assert released_line(year[0].released, TODAY) == "выйдет в 2028"


def test_tmdb_gives_a_day():
    record = ANSWERS["series:Dead-End Job"][0]

    assert tmdb_series.parse_search([record])[0].released == ReleaseDate.of_day(date(2026, 10, 30))


def test_an_offer_stored_before_this_stage_reads_as_a_day_and_new_ones_keep_their_precision():
    old = {"kind": "game", "external_id": "1", "name": "Игра", "original_name": "Game", "released": "2026-10-29",
           "details": None, "poster": None, "heading": HEADING, "shown": False}

    assert Offer.read(old).released == ReleaseDate.of_day(date(2026, 10, 29))
    assert card_text(Offer.read(old), TODAY).splitlines()[-1] == "2026"
    assert Offer.read({**old, "released": None}).released == NOT_ANNOUNCED
    quarter = Offer.read({**old, "released": "2027-Q4"})
    assert quarter.stored()["released"] == "2027-Q4"
    assert card_text(quarter, TODAY).splitlines()[-1] == "выйдет в 4 квартале 2027"
    with pytest.raises(ValueError):
        Offer.read({**old, "released": "скоро"})  # strict: garbage is a bug of ours


# --- KI-61: the English names of a typo ---------------------------------------------------------------------


def dead_end(**replaced):
    """The saved answers of «Dead-End Jb»: the searches in Russian and the English search of «Dead-End»."""
    answers = {
        "series:Dead-End Jb": DEAD_END["search_ru"]["Dead-End Jb"],
        "series:Dead-End": DEAD_END["search_ru"]["Dead-End"],
        "series:Dead-End Job": DEAD_END["search_ru"]["Dead-End Job"],
        "series-en:Dead-End Jb": DEAD_END["search_en_typo"],
        "series-en:Dead-End": DEAD_END["search_en_short"],
    }
    return Clients(extra={**answers, **replaced})


def test_a_typo_finds_the_english_name_and_offers_the_record_of_the_same_id_in_russian():
    clients = dead_end()
    tracker = tracker_on(clients)
    item = take(tracker, "Dead-End Jb")

    reply = run(tracker.answer_kind(item, SERIES))

    offers = stored(tracker, item)
    assert [(o.external_id, o.name, o.heading) for o in offers] == [
        ("289517", "Работа с призрачными перспективами", CORRECTED)
    ]
    assert reply.offer.text.startswith("Возможно, вы имели в виду:\n\n📺 Работа с призрачными перспективами")
    assert clients.searches() == ["series:Dead-End Jb", "series:Dead-End", "series-en:Dead-End", "series:Dead-End Job"]


def test_without_the_same_id_in_the_russian_search_the_english_record_is_the_offer():
    tracker = tracker_on(dead_end(**{"series:Dead-End Job": DEAD_END["search_ru"]["Dead-End"][:2]}))
    item = take(tracker, "Dead-End Jb")

    run(tracker.answer_kind(item, SERIES))

    assert [(o.external_id, o.name, o.heading) for o in stored(tracker, item)] == [("289517", "Dead-End Job", CORRECTED)]


def test_shikimori_and_igdb_are_not_asked_in_english():
    clients = Clients()
    tracker = tracker_on(clients)

    run(tracker.answer_kind(take(tracker, "Phantom Blad Zero"), GAME))

    assert not [what for what in clients.searches() if "-en:" in what]


def test_a_failing_english_search_before_any_offer_fails_the_analysis():
    clients = dead_end()
    clients.tmdb.fail_from = 3  # «Dead-End Jb», «Dead-End» in Russian, then the English one fails
    tracker = tracker_on(clients)

    reply = run(tracker.answer_kind(take(tracker, "Dead-End Jb"), SERIES))

    assert reply.outcome == InboxOutcome.SOURCE_FAILED


def test_a_failing_english_search_after_an_offer_goes_to_the_log(caplog):
    clients = dead_end(**{"series:Dead-End Jb": DEAD_END["search_ru"]["Dead-End"][:1]})  # a weak offer first
    clients.tmdb.fail_from = 3
    tracker = tracker_on(clients)

    with caplog.at_level(logging.WARNING):
        reply = run(tracker.answer_kind(take(tracker, "Dead-End Jb"), SERIES))

    assert reply.outcome == InboxOutcome.OFFER
    assert "failed after an offer was found" in caplog.text


# --- KI-62: a kind press looks the links of its kind up again ----------------------------------------------


def test_a_steam_link_that_failed_at_the_pause_gives_its_card_after_the_press_of_game():
    clients = Clients()
    tracker = tracker_on(clients)
    item = take(tracker, f"Смотрите {STEAM_ELDEN_RING}", links=(STEAM_ELDEN_RING,))
    clients.igdb.fail_from = 1
    assert run(tracker.inbox_pause_over(item)).outcome == InboxOutcome.ASK
    clients.igdb.fail_from = None

    reply = run(tracker.answer_kind(item, GAME))

    assert (reply.outcome, stored(tracker, item)[0].external_id) == (InboxOutcome.OFFER, "119133")
    assert stored(tracker, item)[0].heading == HEADING


def test_a_link_of_another_kind_is_not_looked_up():
    clients = Clients()
    tracker = tracker_on(clients)
    item = take(tracker, f"Смотрите {STEAM_ELDEN_RING}", links=(STEAM_ELDEN_RING,))
    clients.requests.clear()

    run(tracker.answer_kind(item, MOVIE))

    assert not clients.requests.of("igdb") and not clients.requests.of("steam")


def test_a_failing_link_at_the_press_goes_to_the_log_and_the_candidates_still_go(caplog):
    clients = Clients()
    tracker = tracker_on(clients)
    item = take(tracker, f"Elden Ring {STEAM_ELDEN_RING}", links=(STEAM_ELDEN_RING,))
    clients.igdb.fail_from = 1

    with caplog.at_level(logging.WARNING):
        run(tracker.answer_kind(item, GAME))

    assert "looking up a link of an inbox item failed" in caplog.text


# --- 8.4: the request budget --------------------------------------------------------------------------------

UNKNOWN_STEAM = [f"https://store.steampowered.com/app/{n}/" for n in (11, 12, 13)]
LONG_POST = "Скидки недели: Black Myth Wukong, Elden Ring, Hades, Control Resonant и Cyberpunk 2077 " + " ".join(UNKNOWN_STEAM)


def test_the_end_of_the_pause_makes_at_most_ten_requests():
    clients = Clients()
    tracker = tracker_on(clients)
    item = take(tracker, LONG_POST, forwarded=True, links=tuple(UNKNOWN_STEAM))

    run(tracker.inbox_pause_over(item))

    assert 0 < len(clients.requests) <= 10


def test_a_kind_press_makes_at_most_seventeen_requests():
    clients = Clients()
    tracker = tracker_on(clients)
    item = take(tracker, LONG_POST, forwarded=True, links=tuple(UNKNOWN_STEAM))
    clients.requests.clear()

    run(tracker.answer_kind(item, GAME))

    assert 3 <= len(clients.requests) <= 17  # the three links are looked up again


def test_a_typo_of_a_series_name_makes_at_most_four_searches_and_three_in_english():
    clients = Clients()
    tracker = tracker_on(clients)

    run(tracker.answer_kind(take(tracker, "Ничего Такого Нет"), SERIES))

    english = [what for what in clients.searches() if what.startswith("series-en:")]
    assert len(english) == 3 and len(clients.searches()) - len(english) == 1 + 3  # nothing close anywhere
