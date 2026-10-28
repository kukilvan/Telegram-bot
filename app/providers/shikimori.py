"""Shikimori API client: anime search, franchise grouping, season selection.

Uses GraphQL endpoint at {SHIKIMORI_BASE_URL}/api/graphql.
No auth required for public data, only User-Agent header.
Rate limit: 5 req/sec, 90 req/min.
"""

import asyncio
import logging
import time
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

SEASON_KINDS = {"tv", "ona"}
MIN_SEASON_DURATION = 15  # minutes; filters out chibi ONAs and short specials


@dataclass
class FranchiseSummary:
    """Summary of a Shikimori franchise."""
    franchise_key: str
    title_ru: str | None
    title_romaji: str | None
    seasons: list[dict]  # sorted TV/ONA seasons
    current: dict  # current season
    current_index: int  # 1-based
    total_seasons: int
    total_episodes_aired: int  # sum across all seasons


def _extract_base_title(items: list[dict]) -> str | None:
    """Extract base title from the first TV/ONA item (main series)."""
    for item in items:
        if item.get("kind") in SEASON_KINDS:
            name = item.get("name", "")
            if name:
                return name
    return None


def _name_matches_base(name: str, base_title: str) -> bool:
    """Check if a name matches the base title (for season filtering)."""
    if not name or not base_title:
        return False
    name_lower = name.lower().strip()
    base_lower = base_title.lower().strip()
    # Direct match or starts with base title
    if name_lower == base_lower:
        return True
    if name_lower.startswith(base_lower + ":") or name_lower.startswith(base_lower + " "):
        return True
    # Check for "Season N", "Part N", "2", "3" etc. at the end
    # e.g., "Jujutsu Kaisen Season 4", "Jujutsu Kaisen 2", "Jujutsu Kaisen Part 2"
    for suffix in [" season ", " season", " part ", " part", " 2", " 3", " 4", " 5"]:
        if name_lower.endswith(suffix) and name_lower[:-len(suffix)].strip() == base_lower.strip():
            return True
    return False


def get_seasons(items: list[dict]) -> list[dict]:
    """Filter and sort seasons from franchise items."""
    # First filter by kind and duration
    candidates = [
        a for a in items
        if a.get("kind") in SEASON_KINDS
        and (a.get("duration") or 24) >= MIN_SEASON_DURATION
    ]
    if not candidates:
        return list(items)
    
    # Extract base title from the first TV/ONA item (main series)
    base_title = _extract_base_title(candidates)
    
    # Filter by name matching base title (excludes crossovers, unrelated entries)
    if base_title:
        seasons = [a for a in candidates if _name_matches_base(a.get("name", ""), base_title)]
        if seasons:
            candidates = seasons
    
    far = datetime.max.replace(tzinfo=timezone.utc)
    return sorted(candidates, key=lambda a: _aired_date(a) or far)


def pick_current_season(items: list[dict]) -> dict | None:
    """Pick the current/latest season from a franchise list."""
    seasons = get_seasons(items)
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
    return len(get_seasons(items))


def _aired_date(item: dict) -> datetime | None:
    """Extract aired date from Shikimori anime item."""
    aired_on = item.get("airedOn")
    if aired_on and isinstance(aired_on, dict):
        date_str = aired_on.get("date")
        if date_str:
            try:
                return datetime.fromisoformat(str(date_str)).replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                pass
    next_ep = item.get("nextEpisodeAt")
    if next_ep:
        try:
            # Handle both ISO string and timestamp
            if isinstance(next_ep, str):
                return datetime.fromisoformat(next_ep).replace(tzinfo=timezone.utc)
            return datetime.fromtimestamp(int(next_ep), tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            pass
    return None


class ShikimoriError(Exception):
    """Shikimori could not answer (network, HTTP error or GraphQL error); an empty answer is not an error.

    `status` is the HTTP status of the failed answer and `cause` the network exception, when the client knows them."""

    def __init__(self, message: str, status: int | None = None, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.cause = cause


ENTRY_QUERY = """
query Entries($ids: String!) {
  animes(ids: $ids, limit: 50) {
    id malId name russian english kind status episodes episodesAired nextEpisodeAt duration
    airedOn { date year } releasedOn { date } franchise
    poster { originalUrl } genres { russian kind }
    related { relationKind relationText anime { id kind } }
  }
}
"""


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
        # why the latest failed request failed (HTTP status, exception); with concurrent requests it may belong to a
        # neighbour, which only makes the reason in an owner notice approximate
        self._last_failure: tuple[int | None, BaseException | None] = (None, None)

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
        self._last_failure = (None, None)
        for attempt in range(retries):
            async with self._semaphore:
                await self._throttle()
                try:
                    resp = await self._client.post(
                        "/api/graphql",
                        json={"query": query, "variables": variables},
                    )
                    if resp.status_code == 429:
                        self._last_failure = (429, None)
                        retry_after = int(resp.headers.get("Retry-After", 2))
                        logger.warning("Shikimori 429, retry after %ss", retry_after)
                        await asyncio.sleep(retry_after)
                        continue
                    if resp.status_code != 200:
                        self._last_failure = (resp.status_code, None)
                        logger.error("Shikimori request failed (HTTP %s)", resp.status_code)
                        return None
                    data = resp.json()
                    if data.get("errors"):
                        logger.error("Shikimori GraphQL errors: %s", data["errors"])
                        return None
                    return data
                except Exception as e:
                    self._last_failure = (None, e)
                    if attempt < retries - 1:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    logger.error("Shikimori request error: %s", e, exc_info=True)
                    return None
        return None

    async def search_anime(self, query: str, strict: bool = False) -> list[dict]:
        """Search anime by name (supports Russian, English, romaji).

        By default a failing request looks like «nothing found»; `strict` raises `ShikimoriError` instead."""
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
            poster { originalUrl }
          }
        }
        """
        data = await self._post(search_query, {"search": query})
        if data is None:
            if strict:
                status, cause = self._last_failure
                raise ShikimoriError("search failed", status, cause)
            return []
        items = data.get("data", {}).get("animes", [])
        logger.debug("Shikimori search results: %d items, first: %s", len(items), items[0] if items else "none")
        return items

    async def fetch_entries(self, ids: Sequence[str]) -> list[dict]:
        """Entries with their relations by Shikimori id (at most 50). Raises `ShikimoriError` on a failed request;
        an id Shikimori does not know is just missing from the answer."""
        data = await self._post(ENTRY_QUERY, {"ids": ",".join(ids)})
        if data is None:
            status, cause = self._last_failure
            raise ShikimoriError("entries request failed", status, cause)
        return data.get("data", {}).get("animes") or []

    async def get_by_id(self, shiki_id: str) -> dict | None:
        """Get a single anime by Shikimori ID."""
        query = """
        query ById($ids: String!) {
          animes(ids: $ids, limit: 1) {
            id
            malId
            name
            russian
            english
            kind
            status
            duration
            episodes
            episodesAired
            nextEpisodeAt
            airedOn { date year }
            franchise
          }
        }
        """
        data = await self._post(query, {"ids": shiki_id})
        if data is None:
            return None
        items = data.get("data", {}).get("animes", [])
        return items[0] if items else None

    async def get_franchise(self, franchise: str, page: int = 1) -> list[dict]:
        """Get all anime in a franchise with pagination."""
        query = """
        query Franchise($franchise: String!, $page: Int) {
          animes(franchise: $franchise, page: $page, limit: 50) {
            id
            malId
            name
            russian
            english
            kind
            status
            duration
            episodes
            episodesAired
            nextEpisodeAt
            airedOn { date }
            franchise
          }
        }
        """
        all_items = []
        current_page = page
        while True:
            data = await self._post(query, {"franchise": franchise, "page": current_page})
            if data is None:
                break
            items = data.get("data", {}).get("animes", [])
            if not items:
                break
            all_items.extend(items)
            logger.debug("Shikimori franchise %r page %s: %d items (total: %d)", franchise, current_page, len(items), len(all_items))
            if len(items) < 50:
                break
            current_page += 1
        return all_items

    async def build_franchise_summary(self, franchise_key: str) -> FranchiseSummary | None:
        """Build a franchise summary from franchise key."""
        if franchise_key.startswith("single:"):
            shiki_id = franchise_key.replace("single:", "")
            item = await self.get_by_id(shiki_id)
            if not item:
                return None
            franchise_key = item.get("franchise") or f"single:{shiki_id}"
            items = [item]
        else:
            items = await self.get_franchise(franchise_key)
            if not items:
                return None

        seasons = get_seasons(items)
        if not seasons:
            seasons = items

        current = pick_current_season(items)
        if not current:
            return None

        title_ru = seasons[0].get("russian") or seasons[0].get("name")
        title_romaji = seasons[0].get("name")

        total_episodes_aired = sum(
            s.get("episodesAired") or s.get("episodes") or 0
            for s in seasons
            if s.get("status") == "released"
        )

        return FranchiseSummary(
            franchise_key=franchise_key,
            title_ru=title_ru,
            title_romaji=title_romaji,
            seasons=seasons,
            current=current,
            current_index=next((i+1 for i, s in enumerate(seasons) if s.get("id") == current.get("id")), 1),
            total_seasons=len(seasons),
            total_episodes_aired=total_episodes_aired,
        )
