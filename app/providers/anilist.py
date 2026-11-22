"""AniList provider: anime metadata + airing schedule via GraphQL.

No API key required for public data. Base URL: https://graphql.anilist.co
Rate limit: ~90 requests per minute (soft ceiling).
"""

import asyncio
import logging
import time
from collections import deque
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

import httpx


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
        seasonYear
        startDate { year month day }
        coverImage { large }
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

    # Page/idMal_in, not one aliased Media per id: an unknown id would make AniList answer 404 for the whole request
    BY_MAL_IDS_QUERY = """
    query ($ids: [Int]) {
      Page(page: 1, perPage: 50) {
        media(idMal_in: $ids, type: ANIME) { id idMal }
      }
    }
    """
    IDS_PAGE = 50

    # The airing schedule of several entries at once; an id AniList does not know is simply missing. The second root
    # is the airings of the last days (the latest first; past 50 the oldest are not there, and those are the least needed)
    SCHEDULES_QUERY = """
    query ($ids: [Int], $since: Int, $until: Int) {
      Page(page: 1, perPage: 50) {
        media(id_in: $ids, type: ANIME) {
          id
          status
          episodes
          nextAiringEpisode { episode airingAt }
        }
      }
      recent: Page(perPage: 50) {
        airingSchedules(mediaId_in: $ids, airingAt_greater: $since, airingAt_lesser: $until, sort: TIME_DESC) {
          mediaId
          episode
          airingAt
        }
      }
    }
    """
    RECENT_DAYS = 8  # how far back the airings are asked for
    RECENT_KEY = "recentAirings"  # where `get_schedules` puts the airings of an entry in its record

    # AniList's own request pacing (not TMDb's settings)
    min_call_interval = 1.5      # seconds between consecutive calls
    max_calls_per_minute = 30    # rolling per-minute cap on requests
    backoff_base_seconds = 5.0   # initial wait on HTTP 429 (doubles per retry)
    backoff_max_retries = 3      # attempts before giving up on 429

    def __init__(self) -> None:
        # Throttling state
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

    async def get_anilist_ids(self, mal_ids: Sequence[int]) -> dict[int, int]:
        """AniList ids by MAL id, in one request per 50 ids. A MAL id AniList does not know is missing from the result.

        Raises when a request fails: «AniList is down» must not look like «AniList knows nothing»."""
        wanted = sorted(set(mal_ids))
        found: dict[int, int] = {}
        for start in range(0, len(wanted), self.IDS_PAGE):
            data = await self._post(self.BY_MAL_IDS_QUERY, {"ids": wanted[start:start + self.IDS_PAGE]})
            if data is None:
                raise RuntimeError("AniList request failed")
            for media in (data.get("Page") or {}).get("media") or []:
                if media.get("id") and media.get("idMal"):
                    found[int(media["idMal"])] = int(media["id"])
        return found

    async def get_schedules(self, anilist_ids: Sequence[int], now: datetime | None = None) -> list[dict]:
        """Raw AniList records (status, episode count, next airing episode) of the given entries, 50 ids per request,
        each with its airings of the last 8 days from `now` (an aware moment; the caller's clock) under `recentAirings`.

        The airings come in the same request (no more requests, the same pace). An answer without them, or with a
        broken part, just leaves the records as they are. Raises when a request fails: «AniList is down» must not
        look like «AniList has no schedule»."""
        now = now or datetime.now(timezone.utc)
        until = int(now.timestamp())
        since = int((now - timedelta(days=self.RECENT_DAYS)).timestamp())
        wanted = sorted(set(anilist_ids))
        media: list[dict] = []
        for start in range(0, len(wanted), self.IDS_PAGE):
            ids = wanted[start:start + self.IDS_PAGE]
            data = await self._post(self.SCHEDULES_QUERY, {"ids": ids, "since": since, "until": until})
            if data is None:
                raise RuntimeError("AniList request failed")
            records = (data.get("Page") or {}).get("media") or []
            media.extend(self._with_airings(records, data.get("recent")))
        return media

    @classmethod
    def _with_airings(cls, records: list[dict], recent: object) -> list[dict]:
        """The records, each with the airings of its own id (as AniList sent them; the reading is the adapter's)."""
        nodes = recent.get("airingSchedules") if isinstance(recent, dict) else None
        if not isinstance(nodes, list):
            return records
        by_id: dict[int, list[dict]] = {}
        for node in nodes:
            media_id = node.get("mediaId") if isinstance(node, dict) else None
            if isinstance(media_id, int):
                by_id.setdefault(media_id, []).append(node)
        return [
            {**record, cls.RECENT_KEY: by_id[record["id"]]} if record.get("id") in by_id else record for record in records
        ]
