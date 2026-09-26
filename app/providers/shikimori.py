"""Shikimori API client: anime search, franchise grouping, season selection.

Uses GraphQL endpoint at {SHIKIMORI_BASE_URL}/api/graphql.
No auth required for public data, only User-Agent header.
Rate limit: 5 req/sec, 90 req/min.
"""

import asyncio
import logging
import time
from collections import deque
from datetime import datetime, timezone

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

SEASON_KINDS = {"tv", "ona"}


def pick_current_season(items: list[dict]) -> dict | None:
    """Pick the current/latest season from a franchise list."""
    if not items:
        return None
    seasons = [a for a in items if a.get("kind") in SEASON_KINDS]
    if not seasons:
        seasons = items
    if not seasons:
        return None
    ongoing = [a for a in seasons if a.get("status") == "ongoing"]
    if ongoing:
        return max(ongoing, key=lambda a: _aired_date(a) or datetime.min.replace(tzinfo=timezone.utc))
    anons = [a for a in seasons if a.get("status") == "anons"]
    if anons:
        return min(anons, key=lambda a: _aired_date(a) or datetime.max.replace(tzinfo=timezone.utc))
    return max(seasons, key=lambda a: _aired_date(a) or datetime.min.replace(tzinfo=timezone.utc))


def get_total_seasons(items: list[dict]) -> int:
    """Count total TV/ONA seasons in a franchise."""
    return len([a for a in items if a.get("kind") in SEASON_KINDS])


class ShikimoriClient:
    """Async Shikimori GraphQL client with throttling."""

    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = settings.shikimori_base_url or "https://shikimori.io"
        self.user_agent = settings.shikimori_user_agent or "Telegram-Bot"
        self.min_call_interval = 0.25
        self.max_calls_per_minute = 90

        self._last_call_at: float | None = None
        self._window_calls: deque[float] = deque()
        self._semaphore = asyncio.Semaphore(5)

        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=30.0,
            headers={
                "User-Agent": self.user_agent,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

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

    async def _post(self, query: str, variables: dict, retries: int = 3) -> dict | None:
        for attempt in range(retries):
            async with self._semaphore:
                await self._throttle()
                try:
                    resp = await self._client.post(
                        "/api/graphql",
                        json={"query": query, "variables": variables},
                    )
                    if resp.status_code == 429:
                        retry_after = int(resp.headers.get("Retry-After", 2))
                        logger.warning(f"Shikimori 429, retry after {retry_after}s")
                        await asyncio.sleep(retry_after)
                        continue
                    if resp.status_code != 200:
                        logger.error(f"Shikimori request failed (HTTP {resp.status_code})")
                        return None
                    data = resp.json()
                    if data.get("errors"):
                        logger.error(f"Shikimori GraphQL errors: {data['errors']}")
                        return None
                    return data
                except Exception as e:
                    if attempt < retries - 1:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    logger.error(f"Shikimori request error: {e}", exc_info=True)
                    return None
        return None

    async def search_anime(self, query: str) -> list[dict]:
        """Search anime by name (supports Russian, English, romaji)."""
        search_query = """
        query Search($search: String!) {
          animes(search: $search, limit: 15) {
            id
            malId
            name
            russian
            english
            kind
            status
            episodes
            episodesAired
            nextEpisodeAt
            airedOn { date year }
            franchise
          }
        }
        """
        data = await self._post(search_query, {"search": query})
        if data is None:
            return []
        items = data.get("data", {}).get("animes", [])
        logger.debug(f"Shikimori search results: {len(items)} items, first: {items[0] if items else 'none'}")
        return items

    async def get_franchise(self, franchise: str) -> list[dict]:
        """Get all anime in a franchise."""
        franchise_query = """
        query Franchise($franchise: String!) {
          animes(franchise: $franchise, limit: 50) {
            id
            malId
            name
            russian
            english
            kind
            status
            episodes
            episodesAired
            nextEpisodeAt
            airedOn { date }
          }
        }
        """
        data = await self._post(franchise_query, {"franchise": franchise})
        if data is None:
            return []
        return data.get("data", {}).get("animes", [])


def _aired_date(item: dict) -> datetime | None:
    """Extract aired date from Shikimori anime item."""
    aired_on = item.get("airedOn")
    if aired_on and isinstance(aired_on, dict):
        date_str = aired_on.get("date")
        if date_str:
            try:
                return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                pass
    next_ep = item.get("nextEpisodeAt")
    if next_ep:
        try:
            return datetime.fromtimestamp(int(next_ep), tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            pass
    return None
