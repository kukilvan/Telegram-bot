"""PSN provider — RAWG for search + PlayStation Store for prices in ILS."""

import re
import json
import logging
import asyncio
import time
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

# RAWG API (free, register at https://rawg.io/apidocs)
RAWG_BASE = "https://api.rawg.io/api"
RAWG_PLATFORMS = {"ps5": 18, "ps4": 17}

# PS Store
PS_BASE = "https://store.playstation.com/en-il"
PS_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# Cache
_cache: dict[str, dict[str, Any]] = {}
CACHE_TTL = 12 * 3600
_semaphore = asyncio.Semaphore(2)


class PSNProvider:
    """PSN provider using RAWG for search + PS Store scraping for prices."""

    def __init__(self, rawg_api_key: str = ""):
        self.rawg_api_key = rawg_api_key

    async def close(self):
        pass

    async def search_games(self, query: str, limit: int = 10) -> list[dict]:
        """Search games using RAWG API."""
        if not self.rawg_api_key:
            logger.warning("RAWG API key not provided — PSN search disabled")
            return []

        try:
            coroutines = []
            for platform, pid in RAWG_PLATFORMS.items():
                url = f"{RAWG_BASE}/games?key={self.rawg_api_key}&search={query}&platforms={pid}&page_size={limit}"
                coroutines.append(_fetch(url))
            
            responses = await asyncio.gather(*coroutines, return_exceptions=True)
            
            all_games = {}
            for resp in responses:
                if isinstance(resp, Exception):
                    continue
                try:
                    data = json.loads(resp)
                    for game in data.get("results", []):
                        gid = game["id"]
                        if gid not in all_games:
                            all_games[gid] = game
                except (json.JSONDecodeError, KeyError):
                    continue

            sorted_games = sorted(all_games.values(), key=lambda g: g.get("released") or "", reverse=True)
            
            results = []
            for game in sorted_games[:limit]:
                results.append({
                    "id": str(game["id"]),
                    "name": game.get("name", "Unknown"),
                    "release_date": game.get("released"),
                    "image": game.get("background_image"),
                })
            
            return results
        except Exception as e:
            logger.error(f"RAWG search failed: {e}")
            return []

    async def get_game_details(self, rawg_id: int) -> dict | None:
        """Get game details from RAWG."""
        try:
            url = f"{RAWG_BASE}/games/{rawg_id}?key={self.rawg_api_key}"
            html = await _fetch(url)
            data = json.loads(html)
            
            return {
                "id": str(data.get("id")),
                "name": data.get("name", "Unknown"),
                "release_date": data.get("released"),
                "image": data.get("background_image"),
            }
        except Exception as e:
            logger.error(f"RAWG details failed: {e}")
            return None


async def _fetch(url: str, headers: dict | None = None) -> str:
    async with _semaphore:
        if headers is None:
            headers = {"User-Agent": PS_UA}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.get(url, headers=headers) as resp:
                resp.raise_for_status()
                return await resp.text()
