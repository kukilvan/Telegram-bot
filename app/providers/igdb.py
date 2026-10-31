"""IGDB client: queries to `/games` in the Apicalypse language of IGDB, with the token of Twitch and the pace of IGDB.

Auth: Client-ID header + Bearer token (Twitch OAuth client_credentials flow).
Base URL: https://api.igdb.com/v4/
Rate limit: ~4 requests per second (hard ceiling); the polling keeps well below it.

What to ask is the adapter's business (`app/tracker/sources/igdb_games.py`); the client only sends the query, keeps the
token and the pace, and raises `IgdbError` on a failure, so «IGDB is down» is never mistaken for «nothing found».
"""

import asyncio
import logging
import time
from collections import deque
from typing import Any

import httpx

TOKEN_REJECTED = (400, 401, 403)  # Twitch does not take the keys


class IgdbError(RuntimeError):
    """IGDB could not answer. `status` is the HTTP status of the failed answer (401 also when Twitch did not take the keys)
    and `cause` the network exception, when the client knows them: `failures.reason_of` sorts the reason by them."""

    def __init__(self, message: str, status: int | None = None, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.cause = cause


class IGDBProvider:
    """Async IGDB client: the keys come from the caller, the token lives in memory until its end (less a minute)."""

    BASE_URL = "https://api.igdb.com/v4"
    TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"

    # IGDB's own request pacing (not TMDb's settings)
    min_call_interval = 1.5      # seconds between consecutive calls
    max_calls_per_minute = 30    # rolling per-minute cap on requests
    backoff_base_seconds = 5.0   # initial wait on HTTP 429 (doubles per retry)
    backoff_max_retries = 3      # repeats of a request that got HTTP 429
    token_margin_seconds = 60.0  # a token this close to its end is taken anew

    def __init__(self, client_id: str = "", client_secret: str = "") -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.enabled = bool(client_id and client_secret)

        self._clock = time.monotonic  # what the pacing and the token read and wait with; a test puts its own clock here
        self._sleep = asyncio.sleep
        self._access_token: str | None = None
        self._token_expires_at = 0.0
        self._last_call_at: float | None = None
        self._window_calls: deque[float] = deque()

        self.call_count = 0  # every real IGDB request attempted so far (the token of Twitch not counted)
        self.hit_429 = False

        self._client = httpx.AsyncClient(base_url=self.BASE_URL, timeout=30.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def games(self, body: str, *, at_once: bool = False) -> list[dict[str, Any]]:
        """The records of `/games` for the query `body`. An empty list is an answer, not a failure.

        `at_once` is the search the owner waits for (the suggestions): it waits neither for the pause nor for the
        window, but counts in them, so the paced requests after it wait a little longer; a 429 fails at once, without
        the repeats (they would make the owner wait half a minute). Any other request waits for the pace and repeats a
        429 up to `backoff_max_retries` times. A 401 takes a new token and repeats the request once."""
        return await self._post("/games", body, at_once=at_once)

    async def _post(self, endpoint: str, body: str, *, at_once: bool) -> list[dict[str, Any]]:
        self.hit_429 = False
        backoff = self.backoff_base_seconds
        repeats_429 = 0
        token_renewed = False
        while True:
            if at_once:
                self._count()
            else:
                await self._throttle()
            resp = await self._send(endpoint, body)
            if resp.status_code == 401 and not token_renewed:
                token_renewed = True
                self._access_token = None
                continue
            if resp.status_code == 429:
                self.hit_429 = True
                if at_once or repeats_429 >= self.backoff_max_retries:
                    logging.warning("IGDB 429 on %s; not repeated", endpoint)
                    raise IgdbError(f"IGDB is rate-limiting requests on {endpoint} (HTTP 429)", 429)
                repeats_429 += 1
                logging.warning(
                    "IGDB 429 on %s; backing off %.1fs (repeat %d/%d)", endpoint, backoff, repeats_429, self.backoff_max_retries,
                )
                await self._sleep(backoff)
                backoff *= 2
                continue
            if resp.status_code != 200:
                raise IgdbError(f"IGDB {endpoint} failed (HTTP {resp.status_code})", resp.status_code)
            try:
                data = resp.json()
            except ValueError as exc:
                raise IgdbError(f"IGDB {endpoint} answered with no JSON", cause=exc) from exc
            if not isinstance(data, list):
                raise IgdbError(f"IGDB {endpoint} answered with no list")
            return data

    async def _send(self, endpoint: str, body: str) -> httpx.Response:
        token = await self._token()
        headers = {"Client-ID": self.client_id, "Authorization": f"Bearer {token}", "Content-Type": "text/plain"}
        try:
            resp = await self._client.post(endpoint, content=body, headers=headers)
        except httpx.HTTPError as exc:
            raise IgdbError(f"IGDB {endpoint} failed: {type(exc).__name__}", cause=exc) from exc
        self.call_count += 1
        return resp

    async def _token(self) -> str:
        """The token of Twitch: taken at the first request and kept until its end, less a minute."""
        if self._access_token and self._clock() < self._token_expires_at - self.token_margin_seconds:
            return self._access_token
        data = {"grant_type": "client_credentials", "client_id": self.client_id, "client_secret": self.client_secret}
        try:
            resp = await self._client.post(self.TWITCH_TOKEN_URL, data=data)
        except httpx.HTTPError as exc:
            raise IgdbError(f"Twitch token request failed: {type(exc).__name__}", cause=exc) from exc
        if resp.status_code in TOKEN_REJECTED:
            raise IgdbError(f"Twitch did not take the keys (HTTP {resp.status_code})", 401)
        if resp.status_code != 200:
            raise IgdbError(f"Twitch token request failed (HTTP {resp.status_code})", resp.status_code)
        try:
            answer = resp.json()
            token, lifetime = answer["access_token"], float(answer.get("expires_in", 3600))
        except (ValueError, KeyError, TypeError) as exc:
            raise IgdbError("Twitch answered with no token", cause=exc) from exc
        self._access_token = token
        self._token_expires_at = self._clock() + lifetime
        return token

    async def _throttle(self) -> None:
        """Sleep until the pause since the last request and the per-minute cap allow the next one."""
        now = self._clock()
        self._forget_old(now)
        wait_interval = self.min_call_interval - (now - self._last_call_at) if self._last_call_at is not None else 0.0
        wait_cap = (self._window_calls[0] + 60.0) - now if len(self._window_calls) >= self.max_calls_per_minute else 0.0
        delay = max(wait_interval, wait_cap, 0.0)
        if delay > 0:
            await self._sleep(delay)
        self._count()

    def _forget_old(self, now: float) -> None:
        while self._window_calls and now - self._window_calls[0] >= 60.0:
            self._window_calls.popleft()

    def _count(self) -> None:
        """A request goes out now: it counts in the window and starts the pause before the next paced one."""
        stamp = self._clock()
        self._forget_old(stamp)
        self._last_call_at = stamp
        self._window_calls.append(stamp)
