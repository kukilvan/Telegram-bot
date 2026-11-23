"""The companies of IGDB among the candidates of an inbox item (spec 7.3 of stage 9.1d, KI-59): the request text, the rule
of 20 games on the saved answers of `/companies`, the drop that moves the next candidate up, who is not asked, and the
failures that never fail the analysis."""

import asyncio
import logging

import httpx
import pytest

from app.providers.igdb import IGDBProvider, IgdbError
from app.tracker.candidates import Candidate, name_key
from app.tracker.core import IncomingMessage, InboxOutcome
from app.tracker.errors import SourceNotConfigured
from app.tracker.models import TitleKind
from app.tracker.offers import MAX_COMPANY_ASKED, OfferSearch
from app.tracker.sources import igdb_companies
from app.tracker.sources.igdb_companies import COMPANY_GAMES, COMPANY_WORDS, askable, companies_query, company_keys
from app.tracker.sources.igdb_games import IgdbGameSource
from inbox_fakes import ANSWERS, COMPANIES, Clients, tracker_on

GAME, MOVIE, SERIES = TitleKind.GAME, TitleKind.MOVIE, TitleKind.SERIES
COMPANY_NAMES = ["Ubisoft", "Mojang", "Remedy", "Bethesda", "Blizzard", "Capcom", "FromSoftware", "Valve", "Netflix", "Rockstar"]
NOT_COMPANY_NAMES = [
    "Control", "Halo", "Portal", "Hades", "Metro", "Arcane", "Marvel", "Dune", "Doom", "Fallout", "Batman", "Witcher",
    "Frostpunk", "Silksong", "Elden Ring",
]
UBISOFT_POST = "Ubisoft анонсировала новую игру, и все очень этому рады сегодня"


def run(coro):
    return asyncio.run(coro)


def source_on(clients=None) -> IgdbGameSource:
    clients = clients or Clients()
    return IgdbGameSource(clients.igdb, clients.steam)


def companies(names, clients=None) -> set[str]:
    return set(run(source_on(clients).companies(names)))


def companies_asked(clients) -> list[str]:
    return clients.requests.of("igdb")


# --- the request ------------------------------------------------------------------------------------------------------


def test_the_request_names_every_candidate_alone_and_with_every_company_word():
    words = ["Entertainment", "Studios", "Studio", "Games", "Softworks", "Interactive", "Productions", "Software",
             "Publishing", "Digital", "Inc"]
    assert list(COMPANY_WORDS) == words
    body = companies_query(["Ubisoft", "Control"])

    assert body.startswith('fields name,developed,published; where name ~ "Ubisoft" | name ~ "Ubisoft Entertainment" | ')
    assert body.endswith('| name ~ "Control Digital" | name ~ "Control Inc"; limit 500;')
    assert body.count(" | ") == 2 * 12 - 1 and body.count("name ~ ") == 24
    assert 'name ~ "Ubisoft Studios" | name ~ "Ubisoft Studio" | name ~ "Ubisoft Games"' in body


def test_a_name_with_a_quote_or_a_backslash_is_not_asked_and_asks_nothing():
    assert not askable('Say "Hi"') and not askable("A\\B") and not askable("  ") and askable("Control: Resonant")
    clients = Clients()

    assert companies(['Say "Hi"', "A\\B"], clients) == set()
    assert clients.requests == []  # none to ask — no request


def test_the_client_posts_the_request_to_companies_at_once():
    asked = []

    def fake(request):
        if request.url.host == "id.twitch.tv":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        asked.append((request.url.path, request.content.decode()))
        return httpx.Response(200, json=[{"name": "Ubisoft Entertainment", "developed": [1], "published": []}])

    client = IGDBProvider("id", "secret")
    client._client = httpx.AsyncClient(base_url=IGDBProvider.BASE_URL, transport=httpx.MockTransport(fake))
    client._window_calls.extend([client._clock()] * client.max_calls_per_minute)  # a full window does not stop it

    answer = run(client.companies("fields name; limit 1;"))

    assert asked == [("/v4/companies", "fields name; limit 1;")] and answer[0]["name"] == "Ubisoft Entertainment"


def test_a_429_of_the_companies_request_fails_at_once_without_a_repeat():
    answers = []

    def fake(request):
        if request.url.host == "id.twitch.tv":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        answers.append(request.url.path)
        return httpx.Response(429, json={"message": "slow down"})

    client = IGDBProvider("id", "secret")
    client._client = httpx.AsyncClient(base_url=IGDBProvider.BASE_URL, transport=httpx.MockTransport(fake))

    with pytest.raises(IgdbError):
        run(client.companies("fields name;"))

    assert answers == ["/v4/companies"]


# --- the rule of 20 games on the saved answers ----------------------------------------------------------------------


def test_the_saved_answers_are_the_real_ones_and_the_limit_is_20_games():
    assert COMPANY_GAMES == 20
    counts = {c["name"]: len(c["developed"]) + len(c["published"]) for c in COMPANIES}
    assert counts["Ubisoft Entertainment"] == 1362 and counts["Control Entertainment"] == 9 and counts["Halo Studios"] == 17


def test_the_companies_are_the_names_with_20_games_in_one_of_their_answers():
    assert companies(COMPANY_NAMES + NOT_COMPANY_NAMES) == {name_key(name) for name in COMPANY_NAMES}


@pytest.mark.parametrize("name", COMPANY_NAMES)
def test_a_company_is_asked_alone(name):
    assert companies([name]) == {name_key(name)}


@pytest.mark.parametrize("name", NOT_COMPANY_NAMES)
def test_a_game_named_like_a_small_studio_is_no_company(name):
    assert companies([name]) == set()


def test_the_answers_of_the_names_are_told_apart_by_their_asked_name():
    # Ubisoft's answers (1362 games) never make «Control» a company, and «Marvel Games» (16) does not make «Marvel» one
    assert companies(["Control", "Ubisoft"]) == {name_key("Ubisoft")}
    assert companies(["Marvel"]) == set()


def test_the_games_are_counted_from_the_lists_and_from_numbers_and_garbage_counts_nothing():
    answers = [
        {"name": "Big Studio", "developed": list(range(12)), "published": list(range(8))},
        {"name": "Edge Case", "developed": list(range(19)), "published": []},
        {"name": "Numbers", "developed": 20, "published": 0},
        {"name": "Garbage", "developed": "many", "published": None},
        {"name": "Bool", "developed": True, "published": True},
        {"developed": list(range(50))},
        "text",
        {"name": 5, "developed": list(range(50))},
    ]

    # «Big Studio» is «Big» and a word of the list; «Edge Case» is no name of the list and «Edge» has 19 games anyway
    assert company_keys(["Big", "Edge", "Numbers", "Garbage", "Bool"], answers) == {"big", "numbers"}
    assert company_keys(["Edge Case", "Big Studio"], answers) == {"big studio"}  # a name has one exact answer: 19 < 20
    assert company_keys(["Big"], [{"name": "BIG STUDIO", "developed": list(range(30))}]) == {"big"}  # no case


def test_only_the_names_of_the_list_are_variants_of_a_name():
    answers = [{"name": "Ubisoft Montreal", "developed": list(range(400)), "published": []}]

    assert company_keys(["Ubisoft"], answers) == frozenset()  # «Ubisoft Montreal» is not asked, whatever IGDB answers
    assert igdb_companies.LIMIT == 500


def test_no_keys_raise_before_the_network():
    clients = Clients(igdb_keys=False)

    with pytest.raises(SourceNotConfigured):
        companies(["Ubisoft"], clients)

    assert clients.requests == []


# --- the analysis ------------------------------------------------------------------------------------------------------


def take(tracker, text, *, forwarded=False, links=()):
    return run(tracker.take_in(IncomingMessage(text=text, forwarded=forwarded, links=links))).item_id


def analysed(tracker, text, kind, *, forwarded=True):
    item = take(tracker, text, forwarded=forwarded)
    return item, run(tracker.answer_kind(item, kind))


def requests_of(clients, prefix):
    return [what for _, what in clients.requests if what.startswith(prefix)]


def test_ubisoft_is_not_searched_and_without_another_candidate_the_item_goes_to_the_inbox():
    clients = Clients()
    tracker = tracker_on(clients)

    item, reply = analysed(tracker, UBISOFT_POST, GAME)

    assert reply.outcome == InboxOutcome.NOT_FOUND
    assert len(requests_of(clients, "companies:")) == 1 and clients.searches() == []


def test_the_next_candidate_moves_up_when_a_company_is_dropped():
    clients = Clients()
    tracker = tracker_on(clients)

    item, reply = analysed(tracker, "Ubisoft анонсировала новую игру, а ещё Elden Ring, и все очень рады", GAME)

    assert clients.searches() == ["game:Elden Ring"]  # «Ubisoft» is first by position and weight, yet not searched
    assert reply.outcome == InboxOutcome.OFFER


def test_one_request_asks_every_name_with_a_latin_letter_and_the_names_without_one_are_left():
    clients = Clients()
    tracker = tracker_on(clients)

    analysed(tracker, "Ubisoft и «Бука» и «Elden Ring» и «2077» вот тут слова слова", GAME)

    [body] = requests_of(clients, "companies:")
    assert 'name ~ "Ubisoft"' in body and 'name ~ "Elden Ring"' in body
    assert "Бука" not in body and "2077" not in body


def test_a_name_message_is_not_asked_and_is_searched_as_typed():
    clients = Clients()
    tracker = tracker_on(clients)

    item, reply = analysed(tracker, "Ubisoft", GAME, forwarded=False)

    assert requests_of(clients, "companies:") == [] and "game:Ubisoft" in clients.searches()


def test_a_quoted_name_message_is_not_asked_either():
    clients = Clients()
    tracker = tracker_on(clients)

    analysed(tracker, "«Ubisoft Quest»", GAME, forwarded=False)

    assert requests_of(clients, "companies:") == [] and clients.searches()[0] == "game:Ubisoft Quest"


def test_a_name_steam_gave_a_link_is_not_asked_but_a_name_of_the_text_is():
    nightreign = ANSWERS["igdb-games-by-steam:2622380"]
    clients = Clients(extra={"igdb-games-by-steam:2622380": [], "game:ELDEN RING NIGHTREIGN": nightreign})
    tracker = tracker_on(clients)
    item = take(tracker, "Ubisoft анонсировала новую игру и все очень этому рады https://store.steampowered.com/app/2622380/")

    reply = run(tracker.inbox_pause_over(item))

    [body] = requests_of(clients, "companies:")
    assert 'name ~ "Ubisoft"' in body and "NIGHTREIGN" not in body
    assert reply.outcome == InboxOutcome.OFFER
    assert clients.searches() == ["game:ELDEN RING NIGHTREIGN"]  # the company is dropped, Steam's name is searched


def test_nothing_is_asked_without_a_latin_candidate():
    clients = Clients()
    tracker = tracker_on(clients)

    analysed(tracker, "Вчера вышла новая Дюна, и все очень этому рады сегодня", MOVIE)

    assert requests_of(clients, "companies:") == [] and clients.searches() == ["movie:Дюна"]


def test_a_cyrillic_company_is_not_asked_and_stays_a_candidate_of_weight_2():
    clients = Clients()
    tracker = tracker_on(clients)

    analysed(tracker, "Вышла новая игра, а Юбисофт анонсировала ещё и слова слова", GAME)

    assert requests_of(clients, "companies:") == [] and clients.searches() == ["game:Юбисофт"]


def test_the_request_goes_once_per_analysis_whatever_the_kind():
    clients = Clients()
    tracker = tracker_on(clients)

    analysed(tracker, "Ubisoft анонсировала ELDEN RING и ещё слова слова слова", MOVIE)

    assert len(requests_of(clients, "companies:")) == 1 and clients.searches() == ["movie:ELDEN RING"]


@pytest.mark.parametrize("how", ["no keys", "a failure", "a 429"])
def test_no_keys_a_failure_and_a_429_log_a_warning_and_the_analysis_goes_on(how, caplog):
    clients = Clients(igdb_keys=how != "no keys")
    if how == "a failure":
        clients.igdb.fail_from = 1
    if how == "a 429":
        async def refuse(body):
            raise IgdbError("IGDB is rate-limiting requests on /companies (HTTP 429)", 429)

        clients.igdb.companies = refuse
    tracker = tracker_on(clients)

    with caplog.at_level(logging.WARNING):
        item, reply = analysed(tracker, "Ubisoft анонсировала ELDEN RING и ещё слова слова слова", MOVIE)

    assert "companies" in caplog.text and "failed" in caplog.text
    assert reply.outcome == InboxOutcome.OFFER  # the candidates stay as the fixed list left them: «ELDEN RING» found
    assert clients.searches() == ["movie:Ubisoft", "movie:ELDEN RING"]  # «Ubisoft» is not dropped


def test_with_no_keys_a_game_item_says_not_connected_as_before(caplog):
    clients = Clients(igdb_keys=False)
    tracker = tracker_on(clients)

    with caplog.at_level(logging.WARNING):
        item, reply = analysed(tracker, UBISOFT_POST, GAME)

    assert reply.outcome == InboxOutcome.NOT_CONNECTED and clients.requests == []


# --- OfferSearch asks the first 10 -----------------------------------------------------------------------------------


class Asked:
    def __init__(self, answer=frozenset(), fail=None):
        self.answer, self.fail, self.names = frozenset(answer), fail, []

    async def companies(self, names):
        self.names.append(list(names))
        if self.fail:
            raise self.fail
        return self.answer & {name_key(name) for name in names}  # the real source tells only about the asked names


def search_with(source) -> OfferSearch:
    return OfferSearch(titles=None, pollers=None, company_source=source)


def candidates_of(*names, weight=6):
    return [Candidate(name, weight - number / 10, number) for number, name in enumerate(names)]


def test_the_first_ten_candidates_with_a_latin_letter_are_asked():
    source = Asked()
    names = ["Первый", *(f"Game{n}" for n in range(15))]

    kept = run(search_with(source)._without_companies(candidates_of(*names)))

    assert MAX_COMPANY_ASKED == 10
    assert source.names == [[f"Game{n}" for n in range(10)]] and [c.name for c in kept] == names


def test_the_companies_found_are_dropped_by_their_name_key_and_the_order_stays():
    source = Asked({name_key("Ubisoft")})

    kept = run(search_with(source)._without_companies(candidates_of("UBISOFT", "Control", "Ubisoft", "Dune")))

    assert [c.name for c in kept] == ["Control", "Dune"]


def test_a_candidate_of_the_weight_of_a_whole_name_is_never_asked():
    source = Asked({name_key("Ubisoft")})
    found = [Candidate("Ubisoft", 100, 0), Candidate("Control", 6, 1)]

    kept = run(search_with(source)._without_companies(found))

    assert source.names == [["Control"]] and [c.name for c in kept] == ["Ubisoft", "Control"]


def test_none_to_ask_sends_nothing_and_no_source_keeps_the_candidates():
    source = Asked()
    run(search_with(source)._without_companies(candidates_of("Дюна", "Мастер")))
    run(search_with(source)._without_companies([]))

    assert source.names == []
    assert [c.name for c in run(search_with(None)._without_companies(candidates_of("Ubisoft")))] == ["Ubisoft"]


@pytest.mark.parametrize("failure", [SourceNotConfigured("no keys"), IgdbError("down", 500), ConnectionError("x")])
def test_a_failure_keeps_the_candidates_and_writes_a_warning(failure, caplog):
    source = Asked({name_key("Ubisoft")}, fail=failure)

    with caplog.at_level(logging.WARNING):
        kept = run(search_with(source)._without_companies(candidates_of("Ubisoft", "Control")))

    assert [c.name for c in kept] == ["Ubisoft", "Control"]
    assert "companies" in caplog.text and any(r.levelno == logging.WARNING for r in caplog.records)
