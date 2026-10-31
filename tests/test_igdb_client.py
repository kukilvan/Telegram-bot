"""IGDB client (spec 4.1 of part 6.1): the token of Twitch, a failure is an exception whose reason `failures` can tell,
the search goes at once and the polling keeps the pace. A fake clock and an `httpx` transport: no network, no real
waiting."""

import asyncio

import httpx
import pytest

from app.providers.igdb import IGDBProvider, IgdbError
from app.tracker import failures


class FakeClock:
    """The client's clock and its sleep: a sleep moves the clock and is written down."""

    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class FakeIgdb:
    """Twitch and IGDB behind one transport. `games` — the statuses (or exceptions) of `/games` in turn, the last one
    again and again; `token` — the status of Twitch."""

    def __init__(self, games=(200,), token=200, expires_in=3600):
        self.games = list(games)
        self.token = token
        self.expires_in = expires_in
        self.tokens_given = 0
        self.asked = []  # (path, the token it carried)

    def __call__(self, request):
        if request.url.host == "id.twitch.tv":
            if self.token != 200:
                return httpx.Response(self.token, json={"message": "invalid client secret"})
            self.tokens_given += 1
            return httpx.Response(200, json={"access_token": f"token-{self.tokens_given}", "expires_in": self.expires_in})
        self.asked.append((request.url.path, request.headers["Authorization"]))
        answer = self.games[min(len(self.asked) - 1, len(self.games) - 1)]
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(answer, json=[{"id": 1942}] if answer == 200 else {"message": "error"})


def client_with(fake, clock=None):
    clock = clock or FakeClock()
    client = IGDBProvider("client-id", "client-secret")
    client._client = httpx.AsyncClient(base_url=IGDBProvider.BASE_URL, transport=httpx.MockTransport(fake))
    client._clock = clock
    client._sleep = clock.sleep
    client.min_call_interval = 1.5
    client.max_calls_per_minute = 3
    return client


def run(coro):
    return asyncio.run(coro)


def reason(error):
    return failures.message_one("Ведьмак 3", failures.source_name("igdb"), failures.reason_of(error))


# --- keys and token ----------------------------------------------------------------------------------------------------


def test_the_client_is_enabled_only_with_both_keys():
    assert IGDBProvider("id", "secret").enabled
    assert not IGDBProvider("id", "").enabled
    assert not IGDBProvider("", "secret").enabled
    assert not IGDBProvider().enabled


def test_the_first_request_takes_a_token_and_the_second_one_keeps_it():
    fake = FakeIgdb()
    client = client_with(fake)

    assert run(client.games("fields name; where id = 1942;")) == [{"id": 1942}]
    run(client.games("fields name; where id = 1942;"))

    assert fake.tokens_given == 1
    assert [token for _, token in fake.asked] == ["Bearer token-1", "Bearer token-1"]


def test_a_token_near_its_end_is_taken_anew():
    fake = FakeIgdb(expires_in=120)
    clock = FakeClock()
    client = client_with(fake, clock)

    run(client.games("x"))
    clock.now += 61  # 59 s left: less than the minute of margin
    run(client.games("x"))

    assert fake.tokens_given == 2


def test_a_401_takes_a_new_token_and_repeats_once():
    fake = FakeIgdb(games=[401, 200])
    client = client_with(fake)

    assert run(client.games("x")) == [{"id": 1942}]

    assert [token for _, token in fake.asked] == ["Bearer token-1", "Bearer token-2"]


def test_a_second_401_is_a_failure_about_the_key():
    fake = FakeIgdb(games=[401])
    client = client_with(fake)

    with pytest.raises(IgdbError) as raised:
        run(client.games("x"))

    assert len(fake.asked) == 2 and raised.value.status == 401
    assert "IGDB не принял ключ — проверьте ключ в настройках" in reason(raised.value)


@pytest.mark.parametrize("status", [400, 401, 403])
def test_twitch_refusing_the_token_is_a_failure_about_the_key(status):
    fake = FakeIgdb(token=status)
    client = client_with(fake)

    with pytest.raises(IgdbError) as raised:
        run(client.games("x"))

    assert raised.value.status == 401 and fake.asked == []
    assert "IGDB не принял ключ — проверьте ключ в настройках" in reason(raised.value)


# --- failures and their reasons ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "answer, expected",
    [
        (httpx.ReadTimeout("slow"), "IGDB не ответил вовремя"),
        (httpx.ConnectError("no route"), "не удалось подключиться к IGDB"),
        (503, "IGDB недоступен — у него сейчас сбой"),
        (500, "IGDB недоступен — у него сейчас сбой"),
    ],
)
def test_a_failure_raises_with_its_own_reason(answer, expected):
    client = client_with(FakeIgdb(games=[answer]))

    with pytest.raises(IgdbError) as raised:
        run(client.games("x"))

    assert expected in reason(raised.value)


def test_an_empty_list_is_an_answer_not_a_failure():
    def empty(request):
        if request.url.host == "id.twitch.tv":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        return httpx.Response(200, json=[])

    assert run(client_with(empty).games("x")) == []


# --- pace: the search at once, the polling paced -----------------------------------------------------------------------


def fill_the_window(client, clock):
    """Three paced requests a moment ago: the window is full and the pause is not over."""
    client._window_calls.extend([clock.now - 2.0, clock.now - 1.0, clock.now])
    client._last_call_at = clock.now


def test_a_search_waits_neither_for_the_pause_nor_for_a_full_window():
    clock = FakeClock()
    fake = FakeIgdb()
    client = client_with(fake, clock)
    fill_the_window(client, clock)

    run(client.games("search", at_once=True))

    assert clock.slept == [] and len(fake.asked) == 1


def test_a_search_counts_in_the_window_so_the_next_paced_request_waits_longer():
    clock = FakeClock()
    client = client_with(FakeIgdb(), clock)
    client._window_calls.extend([clock.now - 50.0, clock.now - 40.0])

    run(client.games("search", at_once=True))  # the third request of the minute
    run(client.games("poll"))

    assert clock.slept == [pytest.approx(10.0)]  # until the oldest call leaves the window, not only the pause


def test_a_429_on_a_search_is_not_repeated_and_fails_at_once():
    clock = FakeClock()
    fake = FakeIgdb(games=[429, 200])
    client = client_with(fake, clock)

    with pytest.raises(IgdbError) as raised:
        run(client.games("search", at_once=True))

    assert len(fake.asked) == 1 and clock.slept == [] and client.hit_429
    assert "IGDB просит подождать, слишком много запросов" in reason(raised.value)


def test_a_paced_request_waits_for_the_pause_and_the_window():
    clock = FakeClock()
    client = client_with(FakeIgdb(), clock)
    fill_the_window(client, clock)

    run(client.games("poll"))

    assert clock.slept == [pytest.approx(58.0)]


def test_a_paced_request_repeats_a_429_after_a_pause():
    clock = FakeClock()
    fake = FakeIgdb(games=[429, 429, 200])
    client = client_with(fake, clock)

    assert run(client.games("poll")) == [{"id": 1942}]

    assert len(fake.asked) == 3
    assert 5.0 in clock.slept and 10.0 in clock.slept  # the backoff doubles


def test_a_paced_request_repeats_a_429_at_most_three_times():
    clock = FakeClock()
    fake = FakeIgdb(games=[429])
    client = client_with(fake, clock)

    with pytest.raises(IgdbError) as raised:
        run(client.games("poll"))

    assert len(fake.asked) == 4 and raised.value.status == 429
