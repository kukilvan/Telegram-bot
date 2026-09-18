"""IGDB provider: game metadata + release dates via REST API.

Auth: Client-ID header + Bearer token (Twitch OAuth client_credentials flow).
Base URL: https://api.igdb.com/v4/
Rate limit: ~4 requests per second (hard ceiling).
"""

import asyncio
import logging
import time
from collections import deque

import httpx

from app.config import get_settings


class IGDBProvider:
    """Async IGDB API client with throttling and OAuth token management (Phase 9).

    Methods:
      search_games(query) -> list[dict]
      get_game_details(igdb_id) -> dict | None
      get_game_release_dates(igdb_id) -> list[dict]
    """

    BASE_URL = "https://api.igdb.com/v4"
    TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"

    def __init__(self) -> None:
        settings = get_settings()
        self.client_id = settings.igdb_client_id
        self.client_secret = settings.igdb_client_secret
        self.enabled = bool(self.client_id and self.client_secret)
        self.min_call_interval = float(settings.tmdb_min_call_interval)
        self.max_calls_per_minute = int(settings.tmdb_max_calls_per_minute)
        self.backoff_base_seconds = float(settings.tmdb_429_backoff_base_seconds)
        self.backoff_max_retries = int(settings.tmdb_429_max_retries)

        # OAuth state
        self._access_token: str | None = None
        self._token_expires_at: float = 0

        # Throttling state (shared pacing with TMDbProvider)
        self._last_call_at: float | None = None
        self._window_calls: deque[float] = deque()

        # Observability
        self.call_count = 0
        self.hit_429 = False

        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=30.0,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get_oauth_token(self) -> str:
        """Get or refresh the Twitch OAuth access token."""
        if self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token

        resp = await self._client.post(
            self.TWITCH_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        if resp.status_code != 200:
            logging.error("IGDB OAuth failed (HTTP %s)", resp.status_code)
            raise RuntimeError(f"IGDB OAuth failed: HTTP {resp.status_code}")
        data = resp.json()
        self._access_token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 3600)
        return self._access_token

    def _headers(self) -> dict:
        token = self._access_token or ""
        return {
            "Client-ID": self.client_id,
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def _throttle(self) -> None:
        now = time.monotonic()
        while self._window_calls and now - self._window_calls[0] >= 60.0:
            self._window_calls.popleft()
        wait_interval = (
            self.min_call_interval - (now - self._last_call_at)
            if self._last_call_at is not None else 0.0
        )
        if len(self._window_calls) >= self.max_calls_per_minute:
            wait_cap = (self._window_calls[0] + 60.0) - now
        else:
            wait_cap = 0.0
        delay = max(wait_interval, wait_cap, 0.0)
        if delay > 0:
            await asyncio.sleep(delay)
        stamp = time.monotonic()
        self._last_call_at = stamp
        self._window_calls.append(stamp)

    async def _post(self, endpoint: str, body: str) -> list[dict] | None:
        """One throttled POST with OAuth refresh and 429 backoff."""
        for attempt in range(1, self.backoff_max_retries + 1):
            try:
                await self._throttle()
                token = await self._get_oauth_token()
                headers = {
                    "Client-ID": self.client_id,
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "text/plain",
                }
                resp = await self._client.post(endpoint, content=body, headers=headers)
                self.call_count += 1
                if resp.status_code == 429:
                    self.hit_429 = True
                    backoff = self.backoff_base_seconds * (2 ** (attempt - 1))
                    logging.warning("IGDB 429; backing off %.1fs (attempt %d/%d)", backoff, attempt, self.backoff_max_retries)
                    await asyncio.sleep(backoff)
                    continue
                if resp.status_code == 401 and attempt < self.backoff_max_retries:
                    # Token expired, refresh and retry
                    self._access_token = None
                    continue
                if resp.status_code != 200:
                    logging.error("IGDB request failed (HTTP %s)", resp.status_code)
                    return None
                data = resp.json()
                return data if isinstance(data, list) else []
            except httpx.HTTPError as e:
                logging.error("IGDB HTTP error: %s", e)
                return None
        logging.error("IGDB failed after %d retries", self.backoff_max_retries)
        return None

    async def search_games(self, query: str, limit: int = 5) -> list[dict]:
        """Search games by name. Returns raw IGDB results."""
        if not self.enabled:
            return []
        # IGDB search: use 'search' keyword with proper Apicalypse syntax
        body = f'search "{query}"; fields name,first_release_date,cover.url,id;'
        data = await self._post("/games", body)
        if data is None:
            return []
        logging.info(f"IGDB search '{query}': got {len(data)} results")
        if data:
            logging.info(f"IGDB search first result keys: {list(data[0].keys())}")
        return data

    async def get_game_details(self, igdb_id: int) -> dict | None:
        """Get full game details including cover, platforms, release dates."""
        if not self.enabled:
            return None
        body = f"fields name,first_release_date,cover.url,platforms.name,release_dates.date,release_dates.human,release_dates.status,release_dates.platform; where id = {igdb_id};"
        data = await self._post("/games", body)
        if not data:
            return None
        return data[0] if data else None

    async def get_game_release_dates(self, igdb_id: int) -> list[dict]:
        """Get all release dates for a game."""
        body = f"fields date,human,status,platform; where game = {igdb_id};"
        data = await self._post("/release_dates", body)
        return data or []
