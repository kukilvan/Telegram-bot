"""PSN provider — simple game search via RAWG API.

Returns: id, name, release_date
No price monitoring, no GraphQL hashes.
"""

import json
import logging

import aiohttp

logger = logging.getLogger(__name__)

RAWG_BASE = "https://api.rawg.io/api"


class PSNProvider:
    """PSN provider using RAWG API for simple game search."""

    def __init__(self, rawg_api_key: str = ""):
        self.rawg_api_key = rawg_api_key
        self._session: aiohttp.ClientSession | None = None

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15),
            )
        return self._session

    async def search_games(self, query: str, limit: int = 10) -> list[dict]:
        """Search PSN games by name. Returns list of {id, name, release_date}."""
        if not query or not self.rawg_api_key:
            return []

        try:
            session = await self._get_session()
            url = f"{RAWG_BASE}/games"
            params = {
                "key": self.rawg_api_key,
                "search": query,
                "platforms": 18,  # PS5
                "ordering": "-releases",
                "page_size": limit,
            }

            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.error(f"RAWG search failed: HTTP {resp.status}")
                    return []
                data = json.loads(await resp.text())

            results = []
            for game in data.get("results", []):
                results.append({
                    "id": str(game.get("id", "")),
                    "name": game.get("name", "Unknown"),
                    "release_date": game.get("released", ""),
                })

            logger.info(f"PSN search '{query}': got {len(results)} results")
            return results

        except Exception as e:
            logger.error(f"PSN search failed: {e}")
            return []

    async def get_game_details(self, rawg_id: int) -> dict | None:
        """Get game details from RAWG."""
        try:
            session = await self._get_session()
            url = f"{RAWG_BASE}/games/{rawg_id}?key={self.rawg_api_key}"

            async with session.get(url) as resp:
                data = json.loads(await resp.text())

            return {
                "id": str(data.get("id")),
                "name": data.get("name", "Unknown"),
                "release_date": data.get("released"),
                "image": data.get("background_image"),
            }
        except Exception as e:
            logger.error(f"RAWG details failed: {e}")
            return None
