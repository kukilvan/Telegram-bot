"""Steam client: the prices of games from `IStoreBrowseService/GetItems` and the Russian name and description from `appdetails`.

Public endpoints — no API key required.
- Store items: GET https://api.steampowered.com/IStoreBrowseService/GetItems/v1/?input_json=… — the purchase options
  of up to 100 apps in one request (spec 3.1 of part 6.2); a failure raises `SteamError`, so «Steam is down» is never
  mistaken for «no price».
- App details: GET /api/appdetails?appids={appid}&l=russian&filters=basic — only a help when a game is added.

What an answer means is the adapter's business (`app/tracker/sources/steam_prices.py`).
"""

import json
import logging
from collections.abc import Sequence
from typing import Any

import httpx

logger = logging.getLogger(__name__)

MAX_ITEMS = 100  # apps in one `GetItems` request; more is several requests, made by the caller


class SteamError(RuntimeError):
    """Steam could not answer. `status` is the HTTP status of a 429 or a 5xx, `cause` the network exception (a timeout,
    no connection) or the reason the answer could not be read: `failures.reason_of` sorts the reason by them. Any other
    status (400, 403…) is neither, so the reason is «unknown»: Steam has no key to check."""

    def __init__(self, message: str, status: int | None = None, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.cause = cause


class SteamProvider:
    """Steam Store API client."""

    BASE_URL = "https://store.steampowered.com"
    ITEMS_URL = "https://api.steampowered.com/IStoreBrowseService/GetItems/v1/"

    def __init__(self):
        self._client = httpx.AsyncClient(timeout=15.0)
        self.call_count = 0

    async def store_items(self, appids: Sequence[str], country: str) -> list[dict[str, Any]]:
        """The `store_items` of `GetItems` for the apps `appids` (numbers of digits) in the store of `country`, in
        Russian, with every purchase option: as Steam sent them, one request, no repeats. No apps — no request."""
        if len(appids) > MAX_ITEMS:
            raise ValueError(f"at most {MAX_ITEMS} apps in one GetItems request, not {len(appids)}")
        if not appids:
            return []
        query = {
            "ids": [{"appid": int(appid)} for appid in appids],
            "context": {"language": "russian", "country_code": country.upper()},
            "data_request": {"include_all_purchase_options": True},
        }
        try:
            self.call_count += 1
            resp = await self._client.get(self.ITEMS_URL, params={"input_json": json.dumps(query)})
        except httpx.HTTPError as exc:
            raise SteamError(f"Steam GetItems failed: {type(exc).__name__}", cause=exc) from exc
        if resp.status_code == 429 or resp.status_code >= 500:
            raise SteamError(f"Steam GetItems failed (HTTP {resp.status_code})", resp.status_code)
        if resp.status_code != 200:
            raise SteamError(f"Steam GetItems failed (HTTP {resp.status_code})")
        try:
            items = resp.json()["response"]["store_items"]
        except (ValueError, KeyError, TypeError) as exc:
            raise SteamError(f"Steam GetItems answered with no store_items: {type(exc).__name__}", cause=exc) from exc
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise SteamError("Steam GetItems answered with store_items that are no list of records")
        return items

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
