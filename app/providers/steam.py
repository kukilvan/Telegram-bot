"""Steam Store provider.

Public endpoints — no API key required.
- App details: GET /api/appdetails?appids={appid}&l=russian&filters=basic
"""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class SteamProvider:
    """Steam Store API client."""

    BASE_URL = "https://store.steampowered.com"

    def __init__(self):
        self._client = httpx.AsyncClient(timeout=15.0)
        self.call_count = 0

    async def app_details(self, appid: str) -> dict[str, Any] | None:
        """The basic details of an app in Russian (`name`, `short_description`…), as Steam names the product.

        Only a help when a game is added: a failure, a timeout or `success: false` (no such app) is None and an `info`
        line in the log, and the game is added by what IGDB knows."""
        try:
            self.call_count += 1
            resp = await self._client.get(
                f"{self.BASE_URL}/api/appdetails",
                params={"appids": appid, "l": "russian", "filters": "basic"},
            )
            resp.raise_for_status()
            entry = resp.json().get(str(appid)) or {}
            details = entry.get("data")
            if not entry.get("success") or not isinstance(details, dict):
                logger.info("Steam has no app %s", appid)
                return None
            return details
        except Exception as e:  # whatever goes wrong, the game is added without Steam
            logger.info("Steam appdetails failed for %s: %s", appid, type(e).__name__)
            return None

    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()
