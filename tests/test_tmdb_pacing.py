"""TMDb pacing (spec 2.7 of part 5.2): the search the owner waits for goes at once, ahead of the paced requests, but
counts in the window; a 429 on it is not repeated. Every other request still waits for the pause and the window and
repeats a 429. A fake clock and an `httpx` transport: no network, no real waiting."""

import asyncio

import httpx
import pytest

from app.providers.tmdb import TMDbProvider, TmdbHttpError


class FakeClock:
    """The provider's clock and its sleep: a sleep moves the clock and is written down."""

    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def provider_with(answers, clock):
    """A provider whose requests get `answers` in turn (status codes), the last one again and again."""
    asked = []

    def answer(request):
        asked.append(request.url.path)
        status = answers[min(len(asked) - 1, len(answers) - 1)]
        return httpx.Response(status, json={"results": [{"id": 1}], "id": 1, "seasons": []})

    provider = TMDbProvider()
    provider._client = httpx.AsyncClient(base_url=TMDbProvider.BASE_URL, transport=httpx.MockTransport(answer))
    provider._clock = clock
    provider._sleep = clock.sleep
    provider.min_call_interval = 1.5
    provider.max_calls_per_minute = 3
    provider.backoff_base_seconds = 5.0
    provider.backoff_max_retries = 3
    return provider, asked


def run(coro):
    return asyncio.run(coro)


def fill_the_window(provider, clock):
    """Three paced requests a moment ago: the window is full and the pause is not over."""
    provider._window_calls.extend([clock.now - 2.0, clock.now - 1.0, clock.now])
    provider._last_call_at = clock.now


@pytest.mark.parametrize("search", ["search_movie", "search_tv"])
def test_a_search_waits_neither_for_the_pause_nor_for_a_full_window(search):
    clock = FakeClock()
    provider, asked = provider_with([200], clock)
    fill_the_window(provider, clock)

    results = run(getattr(provider, search)("Дюна", strict=True))

    assert results == [{"id": 1}] and len(asked) == 1
    assert clock.slept == []


def test_a_search_counts_in_the_window_so_the_next_paced_request_waits_longer():
    clock = FakeClock()
    provider, asked = provider_with([200], clock)
    provider._window_calls.extend([clock.now - 50.0, clock.now - 40.0])

    run(provider.search_movie("Дюна", strict=True))  # the third request of the minute
    run(provider.get_tv_show(1))

    assert list(provider._window_calls)[-1] == clock.now and len(asked) == 2
    # the window was full: the paced request waited until the oldest call left it (10 s), not only for the pause
    assert clock.slept == [pytest.approx(10.0)]


@pytest.mark.parametrize("search", ["search_movie", "search_tv"])
def test_a_429_on_a_search_is_not_repeated_and_fails_at_once(search):
    clock = FakeClock()
    provider, asked = provider_with([429, 200], clock)

    with pytest.raises(RuntimeError, match="429"):
        run(getattr(provider, search)("Дюна", strict=True))

    assert len(asked) == 1 and clock.slept == [] and provider.hit_429


def test_a_paced_request_still_waits_for_the_pause_and_for_the_window():
    clock = FakeClock()
    provider, asked = provider_with([200], clock)
    fill_the_window(provider, clock)

    run(provider.get_tv_show(1))

    assert len(asked) == 1
    assert clock.slept == [pytest.approx(58.0)]  # the oldest of the three leaves the window in 58 s


def test_a_paced_request_still_repeats_a_429_after_a_pause():
    clock = FakeClock()
    provider, asked = provider_with([429, 200], clock)

    raw = run(provider.get_tv_show(1))

    assert raw is not None and len(asked) == 2
    assert 5.0 in clock.slept  # the backoff before the second try


def test_a_paced_request_that_stays_rate_limited_raises():
    clock = FakeClock()
    provider, asked = provider_with([429], clock)

    with pytest.raises(TmdbHttpError):
        run(provider.get_tv_show(1))

    assert len(asked) == 3
