"""The link of a game in PlayStation Store, checked at a click (KI-37, spec 1.4 of stage 9.1b): `200` — the concept page,
a redirect to `/error` — the search, a failure or any other answer — the concept page; a day in memory; the route of the
web card; the provider's one `HEAD`.

The real core on in-memory SQLite and a made-up game source; the store is a fake that answers by address.
"""

import re

import httpx
import pytest

from app.providers.playstation import PlayStationError, PlayStationProvider
from app.tracker.cards import format_card
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.games import GameState
from app.tracker.models import TitleKind
from app.tracker.playstation import KEPT_FOR
from app.tracker.settings_store import MY_PLATFORMS_SETTING, STORE_COUNTRY_SETTING
from test_tracker_game_prices import T0, FakeClock, FakeSender, MadeUpGames, add, put_setting, run
from test_web_card import FakeSource, make_client
from test_web_games import FILM

PC, PS4, PS5 = 6, 48, 167
CONCEPT_URL = "https://store.playstation.com/en-il/concept/10018449"
SEARCH_URL = "https://store.playstation.com/en-il/search/Hades%20II"


class Answer:
    def __init__(self, status, location=""):
        self.status, self.location = status, location


class FakeStore:
    """`answers`: the address → what to answer (an Answer, or an exception to raise); an address not listed — `200`."""

    def __init__(self):
        self.answers = {}
        self.calls = []

    async def head(self, url):
        self.calls.append(url)
        answer = self.answers.get(url, Answer(200))
        if isinstance(answer, Exception):
            raise answer
        return answer


MISSING = Answer(302, "/en-il/error?conceptId=10018449&source=x")


@pytest.fixture
def clock():
    return FakeClock(T0)


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def igdb():
    return MadeUpGames()


@pytest.fixture
def store():
    return FakeStore()


@pytest.fixture
def tracker(session_factory, clock, igdb, store):
    return Tracker(
        session_factory, clock=clock, sender=FakeSender(),
        sources={TitleKind.GAME: igdb, TitleKind.MOVIE: FakeSource("tmdb_movie", FILM)}, playstation_source=store,
    )


def game(concept="10018449", platforms=(PC, PS5)):
    return GameState(ps_concept=concept, platforms=tuple(platforms))


def link(tracker, title):
    return run(tracker.playstation_link(title))


# --- the three answers ----------------------------------------------------------------------------------------------


def test_the_page_the_store_has_is_the_concept_page(tracker, igdb, store):
    title = add(tracker, igdb, game())

    assert link(tracker, title) == CONCEPT_URL
    assert store.calls == [CONCEPT_URL]


def test_a_concept_the_store_does_not_have_leads_to_the_search_by_the_original_name(tracker, igdb, store):
    store.answers[CONCEPT_URL] = MISSING
    title = add(tracker, igdb, game())

    assert link(tracker, title) == SEARCH_URL


@pytest.mark.parametrize(
    "answer", [PlayStationError("timeout"), Answer(500), Answer(403), Answer(302, "/en-il/somewhere"), RuntimeError("x")]
)
def test_a_failure_or_any_other_answer_leads_to_the_concept_page(tracker, igdb, store, answer):
    store.answers[CONCEPT_URL] = answer
    title = add(tracker, igdb, game())

    assert link(tracker, title) == CONCEPT_URL


def test_the_search_is_by_the_original_name_with_its_signs_quoted(tracker, igdb, store):
    store.answers[CONCEPT_URL] = MISSING
    title = add(tracker, igdb, game(), name="Marvel's Spider-Man: Miles Morales")

    assert link(tracker, title) == (
        "https://store.playstation.com/en-il/search/Marvel%27s%20Spider-Man%3A%20Miles%20Morales"
    )


# --- the day in memory ----------------------------------------------------------------------------------------------


def test_the_second_click_within_a_day_asks_nothing_and_after_a_day_asks_again(tracker, igdb, store, clock):
    store.answers[CONCEPT_URL] = MISSING
    title = add(tracker, igdb, game())

    assert link(tracker, title) == link(tracker, title) == SEARCH_URL
    assert len(store.calls) == 1
    clock.advance(seconds=KEPT_FOR.total_seconds() - 1)
    link(tracker, title)
    assert len(store.calls) == 1
    clock.advance(seconds=2)
    link(tracker, title)
    assert len(store.calls) == 2


def test_the_page_that_is_there_is_kept_too(tracker, igdb, store):
    title = add(tracker, igdb, game())

    assert link(tracker, title) == link(tracker, title) == CONCEPT_URL
    assert len(store.calls) == 1


def test_another_concept_or_another_locale_asks_again(tracker, igdb, store, session_factory):
    first = add(tracker, igdb, game(), external_id="1")
    second = add(tracker, igdb, game("200520"), external_id="2", name="Bloodborne")
    link(tracker, first)
    link(tracker, second)
    assert len(store.calls) == 2

    put_setting(session_factory, STORE_COUNTRY_SETTING, "tr")
    link(tracker, first)
    assert store.calls[-1] == "https://store.playstation.com/en-tr/concept/10018449" and len(store.calls) == 3


def test_a_failure_is_not_kept_and_the_next_click_asks_again(tracker, igdb, store):
    store.answers[CONCEPT_URL] = PlayStationError("timeout")
    title = add(tracker, igdb, game())
    link(tracker, title)
    store.answers[CONCEPT_URL] = MISSING

    assert link(tracker, title) == SEARCH_URL
    assert len(store.calls) == 2


def test_two_titles_with_one_concept_share_the_answer(tracker, igdb, store):
    one = add(tracker, igdb, game(), external_id="1")
    other = add(tracker, igdb, game(), external_id="2", name="Hades II (Deluxe)")

    link(tracker, one)
    link(tracker, other)

    assert len(store.calls) == 1


# --- no concept, no link, no title ----------------------------------------------------------------------------------


def test_a_game_without_a_concept_gets_the_search_and_nothing_is_asked(tracker, igdb, store):
    title = add(tracker, igdb, game(concept=None))

    assert link(tracker, title) == SEARCH_URL
    assert store.calls == []


def test_no_link_means_the_card(tracker, igdb, session_factory):
    only_pc = add(tracker, igdb, game(platforms=(PC,)), external_id="1")
    assert link(tracker, only_pc) is None  # not on PS5

    on_ps4 = add(tracker, igdb, game(platforms=(PS4,)), external_id="2")
    assert link(tracker, on_ps4) == CONCEPT_URL  # PS4 games run on PS5

    put_setting(session_factory, MY_PLATFORMS_SETTING, ["pc"])
    assert link(tracker, on_ps4) is None  # PS5 is not one of «Мои платформы»

    put_setting(session_factory, MY_PLATFORMS_SETTING, ["pc", "ps5"])
    put_setting(session_factory, STORE_COUNTRY_SETTING, "ru")
    assert link(tracker, on_ps4) is None  # the country has no store
    assert link(tracker, 999) is None  # a title that is gone


def test_a_title_that_is_no_game_has_no_link(tracker):
    film = run(tracker.add_title("movie", "1")).title_id

    assert link(tracker, film) is None


def test_without_a_source_of_the_answers_the_link_is_the_concept_page(session_factory, clock, igdb):
    quiet = Tracker(session_factory, clock=clock, sender=FakeSender(), sources={TitleKind.GAME: igdb})
    title = add(quiet, igdb, game())

    assert link(quiet, title) == CONCEPT_URL


# --- the route of the web card --------------------------------------------------------------------------------------


@pytest.fixture
def client(tracker, tmp_path):
    return make_client(tracker, tmp_path)


def test_the_route_redirects_to_the_concept_page_and_to_the_search(tracker, igdb, store, client):
    title = add(tracker, igdb, game(), external_id="1")
    other = add(tracker, igdb, game("777"), external_id="2")
    store.answers["https://store.playstation.com/en-il/concept/777"] = MISSING

    found = client.get(f"/titles/{title}/playstation")
    missing = client.get(f"/titles/{other}/playstation")

    assert (found.status_code, found.headers["location"]) == (302, CONCEPT_URL)
    assert (missing.status_code, missing.headers["location"]) == (302, SEARCH_URL)


def test_the_route_sends_a_missing_title_a_non_game_and_a_game_without_the_link_to_the_card(tracker, igdb, client):
    only_pc = add(tracker, igdb, game(platforms=(PC,)))
    film = run(tracker.add_title("movie", "1")).title_id

    for title_id in (only_pc, film, 999, 10**30):
        answer = client.get(f"/titles/{title_id}/playstation")
        assert (answer.status_code, answer.headers["location"]) == (302, f"/titles/{title_id}")


def test_a_logged_out_request_goes_to_the_login(tracker, igdb, tmp_path):
    title = add(tracker, igdb, game())
    client = make_client(tracker, tmp_path)
    client.cookies.clear()

    answer = client.get(f"/titles/{title}/playstation")

    assert answer.status_code in (302, 303) and "/login" in answer.headers["location"]


def test_the_web_card_link_goes_through_the_route_only_for_a_game_with_a_concept(tracker, igdb, client):
    with_concept = add(tracker, igdb, game(), external_id="1")
    without = add(tracker, igdb, game(concept=None), external_id="2")

    def href(title):
        html = client.get(f"/titles/{title}").text
        return re.search(r'href="([^"]+)" target="_blank" rel="noopener">Открыть в PlayStation Store', html).group(1)

    assert href(with_concept) == f"/titles/{with_concept}/playstation"
    assert href(without) == SEARCH_URL


def test_the_bot_text_line_keeps_the_concept_address(tracker, igdb):
    title = add(tracker, igdb, game())

    assert f"PS Store: {CONCEPT_URL}" in format_card(run(tracker.title_card(title)))


# --- the provider ---------------------------------------------------------------------------------------------------


def provider_with(handler):
    provider = PlayStationProvider()
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    return provider


def test_the_provider_asks_once_with_head_and_does_not_follow_the_redirect():
    seen = []

    def handler(request):
        seen.append((request.method, str(request.url)))
        return httpx.Response(302, headers={"location": "/en-il/error?conceptId=1"})

    answer = run(provider_with(handler).head(CONCEPT_URL))

    assert seen == [("HEAD", CONCEPT_URL)]
    assert (answer.status, answer.location) == (302, "/en-il/error?conceptId=1")


def test_the_provider_answers_200_without_a_location_and_raises_on_a_failure():
    assert run(provider_with(lambda request: httpx.Response(200)).head(CONCEPT_URL)).location == ""

    def broken(request):
        raise httpx.ConnectTimeout("slow")

    with pytest.raises(PlayStationError):
        run(provider_with(broken).head(CONCEPT_URL))
