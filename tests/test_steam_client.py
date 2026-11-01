"""Steam client for prices (spec 3.1 of part 6.2): one `GetItems` request in Russian for the store country, at most 100
apps, and a failure is a `SteamError` whose reason `failures` can tell. An `httpx` transport: no network."""

import asyncio
import json

import httpx
import pytest

from app.providers.steam import MAX_ITEMS, SteamError, SteamProvider
from app.tracker import failures

ITEMS = [{"appid": 1145350, "id": 1145350, "success": 1}]


class FakeSteam:
    """`GetItems` behind a transport: `answer` is a status, an `httpx.Response` or an exception to raise."""

    def __init__(self, answer=200):
        self.answer = answer
        self.asked = []  # the parsed `input_json` of each request

    def __call__(self, request):
        self.asked.append(json.loads(request.url.params["input_json"]))
        if isinstance(self.answer, Exception):
            raise self.answer
        if isinstance(self.answer, httpx.Response):
            return self.answer
        if self.answer == 200:
            return httpx.Response(200, json={"response": {"store_items": ITEMS}})
        return httpx.Response(self.answer, text="Bad Request")


def client_with(fake):
    client = SteamProvider()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(fake))
    return client


def ask(fake, appids=("1145350",), country="il"):
    return asyncio.run(client_with(fake).store_items(list(appids), country))


def failure(fake):
    with pytest.raises(SteamError) as caught:
        ask(fake)
    return caught.value


def reason(error):
    return failures.message_one("Hades II", failures.source_name("steam"), failures.reason_of(error))


def test_the_request_asks_for_the_apps_in_russian_in_the_store_country_with_every_purchase_option():
    fake = FakeSteam()

    items = ask(fake, ["3764200", "1145350"], "il")

    assert items == ITEMS
    assert fake.asked == [{
        "ids": [{"appid": 3764200}, {"appid": 1145350}],
        "context": {"language": "russian", "country_code": "IL"},
        "data_request": {"include_all_purchase_options": True},
    }]


def test_the_request_goes_to_get_items_without_a_key():
    seen = []

    def remember(request):
        seen.append(request.url)
        return httpx.Response(200, json={"response": {"store_items": []}})

    asyncio.run(client_with(remember).store_items(["730"], "ua"))

    assert (seen[0].host, seen[0].path) == ("api.steampowered.com", "/IStoreBrowseService/GetItems/v1/")
    assert set(seen[0].params) == {"input_json"}


def test_no_apps_is_no_request():
    fake = FakeSteam()

    assert ask(fake, []) == []
    assert fake.asked == []


def test_more_than_a_hundred_apps_is_a_mistake_of_the_caller():
    fake = FakeSteam()

    assert ask(fake, [str(n) for n in range(MAX_ITEMS)]) == ITEMS
    with pytest.raises(ValueError):
        ask(fake, [str(n) for n in range(MAX_ITEMS + 1)])
    assert len(fake.asked) == 1


def test_the_client_waits_fifteen_seconds():
    assert SteamProvider()._client.timeout.read == 15.0


def test_a_timeout_is_steam_did_not_answer_in_time():
    error = failure(FakeSteam(httpx.ReadTimeout("slow")))

    assert isinstance(error.cause, httpx.ReadTimeout)
    assert "Steam не ответил вовремя" in reason(error)


def test_no_connection_is_its_own_reason():
    assert failures.reason_of(failure(FakeSteam(httpx.ConnectError("no route")))) == failures.CONNECTION


def test_429_asks_to_wait_and_5xx_is_steam_down():
    assert (failure(FakeSteam(429)).status, failures.reason_of(failure(FakeSteam(429)))) == (429, failures.RATE_LIMIT)
    assert failures.reason_of(failure(FakeSteam(502))) == failures.SOURCE_DOWN


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_any_other_status_is_an_unknown_error_not_a_key_to_check(status):
    error = failure(FakeSteam(status))

    assert error.status is None
    assert failures.reason_of(error) == failures.UNKNOWN
    assert "у Steam неизвестная ошибка, подробности в журнале" in reason(error)


@pytest.mark.parametrize("answer", [
    httpx.Response(200, text="<html>not json</html>"),
    httpx.Response(200, json={"response": {}}),  # what Steam says to a request without input_json
    httpx.Response(200, json={"response": {"store_items": {"appid": 1}}}),
    httpx.Response(200, json={"response": {"store_items": [1, 2]}}),
    httpx.Response(200, json=[]),
])
def test_an_answer_without_a_list_of_store_items_is_a_failure(answer):
    assert failures.reason_of(failure(FakeSteam(answer))) == failures.UNKNOWN


def test_there_is_no_search_of_games_in_steam():
    assert not hasattr(SteamProvider, "search_games")
