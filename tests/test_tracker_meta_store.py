"""The Meta store (spec 6 and 7 of stage 6.5): the number of a game, the address, the links of the cards, the button
under a release message and a store link sent to the bot.

The saved IGDB answers of 2026-11-28 (`fixtures/igdb/quest-games.json`) go through the adapter; the core runs on fake
sources, no network.
"""

import asyncio
import json
import pathlib
from datetime import date, datetime

import pytest

from app.tracker import delivery, game_events, game_rows
from app.tracker.actions import CARD, META, META_LABEL, Action, event_actions
from app.tracker.candidates import META as META_SOURCE, SourceLink, source_links
from app.tracker.core import IncomingMessage, Tracker
from app.tracker.db import create_session_factory
from app.tracker.delivery_service import DeliveryService, _unit_actions
from app.tracker.errors import SourceNotConfigured
from app.tracker.games import EARLY, FULL, GameState, Release
from app.tracker.models import InboxReason, InboxRecord, TitleKind
from app.tracker.platforms import STORE_COUNTRIES, WORLD, Platform, meta_store_url
from app.tracker.release_dates import ReleaseDate
from app.tracker.results import InboxOutcome
from app.tracker.sources.igdb_games import BY_META_QUERY, META_STORE_SOURCE, IgdbGameSource, parse_game
from inbox_fakes import Clients, tracker_on

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "igdb"
PC, PS5, QUEST_3 = 6, 167, 471
QUEST = Platform.META_QUEST
ASGARD = "2603836099654226"
ASGARD_PAGE = f"https://www.meta.com/experiences/{ASGARD}/"
BY_NUMBER = json.loads((FIXTURES / "by-meta-store-id.json").read_text(encoding="utf-8"))  # Beat Saber, by its number

_ANSWERS = {item["name"]: item for item in json.loads((FIXTURES / "quest-games.json").read_text(encoding="utf-8"))}


def run(coro):
    return asyncio.run(coro)


def answer(start: str) -> dict:
    [item] = [item for name, item in _ANSWERS.items() if name.startswith(start)]
    return item


def with_uid(uid) -> GameState:
    raw = {"id": 1, "name": "x", "external_games": [{"external_game_source": META_STORE_SOURCE, "uid": uid}]}
    return parse_game(raw).game


def state(*records, meta_store_id=None) -> GameState:
    """Records as (IGDB platform, type, date text)."""
    releases = tuple(Release(platform, WORLD, kind, ReleaseDate.parse(day)) for platform, kind, day in records)
    platforms = tuple(sorted({release.platform for release in releases}))
    return GameState(platforms=platforms, releases=releases, meta_store_id=meta_store_id)


# --- the number and the address (spec 6.1, 6.2) ----------------------------------------------------------------------


def test_the_store_number_is_the_uid_of_source_28():
    assert parse_game(answer("Asgard")).game.meta_store_id == ASGARD
    assert parse_game(answer("Supernatural")).game.meta_store_id is None  # IGDB has no store number for it
    assert META_STORE_SOURCE == 28 and f"external_game_source = {META_STORE_SOURCE};" in BY_META_QUERY


@pytest.mark.parametrize("uid", ["beat-saber", "123 456", "", None, "12a"])
def test_a_number_that_is_not_all_digits_is_none(uid):
    assert with_uid(uid).meta_store_id is None


def test_the_number_is_stored_and_a_snapshot_without_the_key_reads():
    game = parse_game(answer("Asgard")).game
    assert game.state()["meta_store_id"] == ASGARD
    assert GameState.from_state(game.state()) == game
    old = {key: value for key, value in game.state().items() if key != "meta_store_id"}
    assert GameState.from_state(old).meta_store_id is None


def test_the_page_by_the_number_else_the_search_by_the_original_name():
    assert meta_store_url(ASGARD, "Asgard's Wrath II") == ASGARD_PAGE
    assert meta_store_url(None, "Supernatural") == "https://www.meta.com/experiences/search/?q=Supernatural"
    assert meta_store_url(None, "Rock & Roll/Бой 2") == (
        "https://www.meta.com/experiences/search/?q=Rock%20%26%20Roll%2F%D0%91%D0%BE%D0%B9%202"
    )


# --- the cards (spec 6.3) -------------------------------------------------------------------------------------------


def test_the_store_link_is_last_and_the_same_in_every_country():
    beat_saber = parse_game(answer("Beat Saber")).game
    for country in STORE_COUNTRIES:
        link = game_rows.store_links(beat_saber, list(Platform), country, "Beat Saber")[-1]
        assert (link.label, link.store, link.checked) == ("Открыть в магазине Meta", "Магазин Meta", False)
        assert link.url == meta_store_url(beat_saber.meta_store_id, "Beat Saber")
    stores = [link.store for link in game_rows.store_links(beat_saber, list(Platform), "il", "Beat Saber")]
    assert stores[0] == "Steam" and stores[-1] == "Магазин Meta"


@pytest.mark.parametrize(
    "game, mine",
    [
        (state((QUEST_3, FULL, "2026-01-01")), [Platform.PC, Platform.PS5]),  # Meta Quest is not mine
        (state((PC, FULL, "2026-01-01"), meta_store_id=ASGARD), [QUEST]),  # the game is not on Meta Quest
    ],
)
def test_no_store_link_without_meta_quest_among_mine_and_in_the_game(game, mine):
    assert [link.store for link in game_rows.store_links(game, mine, "il", "x")] == []


def test_a_game_without_a_number_links_to_the_search():
    [link] = game_rows.store_links(state((QUEST_3, FULL, None)), [QUEST], "il", "Supernatural")
    assert link.url == "https://www.meta.com/experiences/search/?q=Supernatural"


# --- the button (spec 6.4) ------------------------------------------------------------------------------------------

TODAY = date(2026, 11, 10)
LOOK = datetime(2026, 11, 9, 12, 0)


def detect(old, new, original_name="Thief VR"):
    return game_events.detect_events(
        1, "Вор", old, new, "il", tuple(Platform), LOOK, TODAY, TODAY, original_name
    )


@pytest.mark.parametrize("kind, event_type", [(FULL, game_events.RELEASED), (EARLY, game_events.EARLY_ACCESS)])
def test_a_quest_release_carries_the_store_address_of_that_moment(kind, event_type):
    old = state((QUEST_3, kind, "2026-11-12"))
    [event] = detect(old, state((QUEST_3, kind, "2026-11-10"), meta_store_id=ASGARD))
    assert (event.type, event.data["meta_url"]) == (event_type, ASGARD_PAGE)

    [searched] = detect(old, state((QUEST_3, kind, "2026-11-10")))  # by the original name, not the Russian one
    assert searched.data["meta_url"] == "https://www.meta.com/experiences/search/?q=Thief%20VR"


@pytest.mark.parametrize(
    "old, new",
    [
        (state((QUEST_3, FULL, None)), state((QUEST_3, FULL, "2027-03-12"))),  # announced
        (state((QUEST_3, FULL, "2027-03-12")), state((QUEST_3, FULL, "2027-04-02"))),  # moved
        (state((PC, FULL, "2026-11-12")), state((PC, FULL, "2026-11-10"))),  # a PC release
        (state((PS5, FULL, "2026-11-12")), state((PS5, FULL, "2026-11-10"))),
    ],
)
def test_other_events_carry_no_store_address(old, new):
    [event] = detect(old, new)
    assert "meta_url" not in event.data


def test_the_button_follows_the_card_and_a_sample_has_it_alone():
    data = {"meta_url": ASGARD_PAGE}
    assert event_actions(game_events.RELEASED, 5, 7, data) == [
        Action("📄 Карточка", CARD, 7), Action(META_LABEL, META, ASGARD_PAGE, ASGARD_PAGE),
    ]
    assert META_LABEL == "🛒 Открыть в магазине Meta"
    assert event_actions(game_events.RELEASED, 5, None, data) == [Action(META_LABEL, META, ASGARD_PAGE, ASGARD_PAGE)]
    assert event_actions(game_events.RELEASED, 5, 7, {}) == [Action("📄 Карточка", CARD, 7)]


def pending(number, title_id, events):
    return [
        delivery.Pending(
            number + at, number + at, event.type, title_id, event.text, {"text": event.text, **event.data}, LOOK
        )
        for at, event in enumerate(events)
    ]


def released_on(*platforms, meta_store_id=ASGARD):
    old = state(*((number, FULL, "2026-11-12") for number in platforms))
    new = state(*((number, FULL, "2026-11-10") for number in platforms), meta_store_id=meta_store_id)
    return detect(old, new)


def test_a_folded_release_has_the_button_though_pc_leads():
    [unit] = delivery.fold(pending(1, 1, released_on(PC, QUEST_3)), episodes=False)
    assert unit.lead.data["platform"] == "pc" and "meta_url" not in unit.lead.data

    assert [(action.name, action.url) for action in _unit_actions(unit)] == [(CARD, None), (META, ASGARD_PAGE)]


def test_in_a_summary_the_button_names_the_game_and_stands_between_steam_and_the_card():
    discount = delivery.Pending(
        9, 9, "game_discount", 2, "скидка", {"text": "скидка", "name": "Hades", "steam_id": "1145360"}, LOOK
    )
    units = delivery.fold([*pending(1, 1, released_on(PC, QUEST_3)), discount], episodes=False)

    actions = DeliveryService._summary_actions(units, {1: "Вор", 2: "Hades"})

    assert [action.label for action in actions] == [
        "🛒 Открыть в Steam: Hades",
        "🛒 Открыть в магазине Meta: Вор",
        "📄 Карточка: Вор",
        "📄 Карточка: Hades",
    ]


class Sender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, list]] = []

    async def send(self, message, actions=()):
        self.sent.append((message, list(actions)))


def test_the_test_event_sends_the_message_with_the_store_button():
    sender = Sender()
    tracker = Tracker(create_session_factory("sqlite://"), clock=lambda: LOOK, sender=sender)
    [sample] = [sample for sample in tracker.test_samples() if sample.label == "Игра: вышла на Meta Quest"]

    run(tracker.send_test_event(sample.id))

    [(text, actions)] = sender.sent
    assert text.endswith("🎮 Asgard's Wrath II вышла на Meta Quest")
    assert [(action.label, action.url) for action in actions] == [(META_LABEL, ASGARD_PAGE)]


# --- a store link sent to the bot (spec 7) --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "address, number",
    [
        ("https://www.meta.com/experiences/2448060205267927/", "2448060205267927"),
        ("https://www.meta.com/experiences/beat-saber/2448060205267927/", "2448060205267927"),
        ("https://www.meta.com/en-gb/experiences/2448060205267927/", "2448060205267927"),
        ("https://www.oculus.com/experiences/quest/2603836099654226/", ASGARD),
        ("https://www.oculus.com/experiences/app/2108775495884888", "2108775495884888"),
        ("HTTPS://Meta.com/experiences/2448060205267927?utm_source=telegram", "2448060205267927"),
        ("meta.com/en_US/experiences/beat-saber/2448060205267927", "2448060205267927"),
    ],
)
def test_the_forms_of_a_store_link_give_the_number(address, number):
    assert source_links("", (address,)) == (SourceLink(META_SOURCE, number, TitleKind.GAME),)


@pytest.mark.parametrize(
    "address",
    [
        "https://www.meta.com/experiences/search/?q=2448060205267927",
        "https://www.meta.com/experiences/search/2448060205267927/",
        "https://www.meta.com/experiences/",
        "https://www.meta.com/experiences/beat-saber/",
        "https://www.meta.com/experiences/12345/",
        "https://www.meta.com/s/2448060205267927/",
        "https://horizon.meta.com/world/2448060205267927/",
        "https://example.com/experiences/2448060205267927/",
    ],
)
def test_other_meta_addresses_are_ordinary_links(address):
    assert source_links("", (address,)) == ()


BEAT_SABER = parse_game(answer("Beat Saber")).game.meta_store_id
BEAT_SABER_LINK = f"https://www.meta.com/experiences/beat-saber/{BEAT_SABER}/"


def knowing_beat_saber(**kwargs) -> Clients:
    return Clients(extra={f"igdb-games-by-meta:{BEAT_SABER}": BY_NUMBER}, **kwargs)


def take(tracker, text=BEAT_SABER_LINK):
    return run(tracker.take_in(IncomingMessage(text=text, links=(BEAT_SABER_LINK,)))).item_id


def test_the_lookup_asks_igdb_once_by_the_number_of_source_28():
    clients = knowing_beat_saber()
    source = IgdbGameSource(clients.igdb, clients.steam)

    [found] = run(source.suggest_by_meta(BEAT_SABER))

    assert (found.external_id, found.original_name, found.details) == ("83731", "Beat Saber", "ПК, Meta Quest")
    assert clients.requests == [("igdb", f"meta:{BEAT_SABER}")]
    assert run(source.suggest_by_meta("4000000")) == []
    query = BY_META_QUERY.format(uid=BEAT_SABER)
    assert query.startswith("fields name,")
    assert query.endswith(f'where external_games.uid = "{BEAT_SABER}" & external_games.external_game_source = 28; limit 10;')


def test_the_lookup_without_keys_asks_nothing():
    clients = Clients(igdb_keys=False)

    with pytest.raises(SourceNotConfigured):
        run(IgdbGameSource(clients.igdb).suggest_by_meta(BEAT_SABER))
    assert clients.requests == []


def test_a_found_store_link_is_offered_at_once():
    clients = knowing_beat_saber()
    tracker = tracker_on(clients)

    reply = run(tracker.inbox_pause_over(take(tracker)))

    assert reply.outcome == InboxOutcome.OFFER and "Beat Saber" in reply.offer.text
    assert clients.requests == [("igdb", f"meta:{BEAT_SABER}")]


def test_an_unknown_store_number_goes_on_with_the_text_and_ends_in_the_inbox():
    clients = Clients()
    tracker = tracker_on(clients)
    item = take(tracker)

    assert run(tracker.inbox_pause_over(item)).outcome == InboxOutcome.ASK  # as after a link of TMDb nobody knows
    assert run(tracker.answer_kind(item, TitleKind.GAME)).outcome == InboxOutcome.NOT_FOUND

    with tracker.session_factory() as session:
        assert session.get(InboxRecord, item).reason == InboxReason.NOT_FOUND
    assert clients.requests == [("igdb", f"meta:{BEAT_SABER}")] * 2  # no name asked anywhere


def test_a_store_link_without_the_keys_of_igdb_says_so():
    tracker = tracker_on(Clients(igdb_keys=False))

    assert run(tracker.inbox_pause_over(take(tracker))).outcome == InboxOutcome.NOT_CONNECTED
