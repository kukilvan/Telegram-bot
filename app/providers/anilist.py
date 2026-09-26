"""AniList provider: anime metadata + airing schedule via GraphQL.

No API key required for public data. Base URL: https://graphql.anilist.co
Rate limit: ~90 requests per minute (soft ceiling).
"""

import asyncio
import logging
import time
from collections import deque

import httpx

from app.config import get_settings


class AniListProvider:
    """Async AniList GraphQL client with throttling (Phase 8).

    Methods:
      search_anime(query) -> list[dict]
      get_anime_details(anilist_id) -> dict | None
      get_next_episode(anilist_id) -> dict | None
    """

    BASE_URL = "https://graphql.anilist.co"

    SEARCH_QUERY = """
    query ($search: String, $page: Int, $perPage: Int) {
      Page(page: $page, perPage: $perPage) {
        pageInfo {
          currentPage
          hasNextPage
          perPage
        }
        media(search: $search, type: ANIME) {
          id
          title {
            romaji
            english
            native
          }
          format
          status
          episodes
          seasonYear
          coverImage {
            large
          }
        }
      }
    }
    """

    DETAILS_QUERY = """
    query ($id: Int) {
      Media(id: $id, type: ANIME) {
        id
        idMal
        title {
          romaji
          english
          native
        }
        format
        status
        episodes
        season
        seasonYear
        coverImage {
          large
        }
        nextAiringEpisode {
          airingAt
          timeUntilAiring
          episode
        }
      }
    }
    """

    BY_MAL_QUERY = """
    query ($idMal: Int) {
      Media(idMal: $idMal, type: ANIME) {
        id
        idMal
        status
        episodes
        nextAiringEpisode {
          episode
          airingAt
          timeUntilAiring
        }
        title {
          romaji
          english
        }
      }
    }
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.min_call_interval = float(settings.tmdb_min_call_interval)
        self.max_calls_per_minute = int(settings.tmdb_max_calls_per_minute)
        self.backoff_base_seconds = float(settings.tmdb_429_backoff_base_seconds)
        self.backoff_max_retries = int(settings.tmdb_429_max_retries)

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

    async def _post(self, query: str, variables: dict) -> dict | None:
        self.hit_429 = False
        backoff = self.backoff_base_seconds
        for attempt in range(1, self.backoff_max_retries + 1):
            await self._throttle()
            resp = await self._client.post(
                "/",
                json={"query": query, "variables": variables},
                headers={"Content-Type": "application/json"},
            )
            self.call_count += 1
            if resp.status_code == 429:
                self.hit_429 = True
                retry_after_raw = (resp.headers or {}).get("Retry-After")
                try:
                    wait = float(retry_after_raw)
                except (TypeError, ValueError):
                    wait = backoff
                logging.warning(
                    "AniList 429; backing off %.1fs (attempt %d/%d)",
                    max(wait, 0.0), attempt, self.backoff_max_retries,
                )
                await asyncio.sleep(max(0.0, wait))
                backoff *= 2
                continue
            if resp.status_code != 200:
                logging.error("AniList request failed (HTTP %s)", resp.status_code)
                return None
            data = resp.json()
            if "errors" in data:
                logging.error("AniList GraphQL error: %s", data["errors"])
                return None
            return data.get("data", {})
        logging.error("AniList rate-limited after %d retries; returning None", self.backoff_max_retries)
        return None

    async def search_anime(self, query: str, page: int = 1) -> list[dict]:
        """Search anime by title (romaji/English/native). Returns raw AniList results."""
        data = await self._post(
            self.SEARCH_QUERY,
            {"search": query, "page": page, "perPage": 10},
        )
        if data is None:
            return []
        page_data = data.get("Page") or {}
        return page_data.get("media") or []

    async def get_anime_details(self, anilist_id: int) -> dict | None:
        """Get full anime details including next airing episode."""
        data = await self._post(self.DETAILS_QUERY, {"id": anilist_id})
        if data is None:
            return None
        return data.get("Media")

    async def get_next_episode(self, anilist_id: int) -> dict | None:
        """Get the next airing episode for an anime (convenience wrapper)."""
        details = await self.get_anime_details(anilist_id)
        if details is None:
            return None
        return details.get("nextAiringEpisode")

    async def get_anime_by_mal(self, mal_id: int) -> dict | None:
        """Get anime details from AniList using MAL ID."""
        data = await self._post(self.BY_MAL_QUERY, {"idMal": mal_id})
        if data is None:
            return None
        return data.get("Media")
