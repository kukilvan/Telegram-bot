"""PSN provider — GraphQL search with ILS prices + RAWG fallback."""

import re
import json
import logging
import asyncio
import time
import urllib.parse
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

# RAWG API
RAWG_BASE = "https://api.rawg.io/api"
RAWG_PLATFORMS = {"ps5": 18, "ps4": 17}

# PS Store GraphQL
PS_GRAPHQL = "https://web.np.playstation.com/api/graphql/v1/op"
PS_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# Cache
_cache: dict[str, dict[str, Any]] = {}
CACHE_TTL = 12 * 3600


class PSNProvider:
    """PSN provider using GraphQL for search with ILS prices."""

    def __init__(self, rawg_api_key: str = "", graphql_hash: str = ""):
        self.rawg_api_key = rawg_api_key
        self.graphql_hash = graphql_hash
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
        """Search games using GraphQL API with ILS prices."""
        # Check cache
        normalized = re.sub(r'\s+', ' ', query.strip().lower())
        cached = _cache.get(normalized)
        if cached and time.time() - cached["ts"] < CACHE_TTL:
            return cached["data"]

        try:
            session = await self._get_session()
            
            params = {
                "operationName": "getSearchResults",
                "variables": json.dumps({
                    "countryCode": "IL",
                    "languageCode": "en",
                    "nextCursor": "",
                    "pageOffset": 0,
                    "pageSize": limit * 3,
                    "searchTerm": query,
                }),
                "extensions": json.dumps({
                    "persistedQuery": {
                        "version": 1,
                        "sha256Hash": self.graphql_hash,
                    }
                })
            }
            
            headers = {
                "User-Agent": PS_UA,
                "apollo-require-preflight": "true",
                "x-apollo-operation-name": "getSearchResults",
                "x-psn-store-locale-override": "en-IL",
            }
            
            url = f"{PS_GRAPHQL}?{urllib.parse.urlencode(params)}"
            
            async with session.get(url, headers=headers) as resp:
                if resp.status == 400:
                    logger.error(f"PSN GraphQL 400: sha256Hash可能需要更新 — требуется обновить psn_graphqlHash для getSearchResults")
                    return []
                resp.raise_for_status()
                data = await resp.json()
            
            # Parse results
            universal = data.get("data", {}).get("universalSearch", {})
            results = universal.get("results", [])
            
            # Filter: only Products with prices
            query_words = query.lower().split()
            filtered = []
            
            for r in results:
                if r.get("__typename") != "Product":
                    continue
                
                name = r.get("name", "")
                price_data = r.get("price")
                if not price_data:
                    continue
                base_raw = price_data.get("basePrice", "")
                
                # Parse base price (format: "ILS ₪279.00" or "ILS 279.00")
                m = re.match(r'ILS\s*[₪]?\s*([\d.]+)', base_raw or "")
                if not m:
                    continue  # "Unavailable" or no price — skip
                
                # Skip DLC, music packs, bundles, bonuses, expansions, remasters
                name_lower = name.lower()
                if any(kw in name_lower for kw in ["music pack", "dlc", "bonus", "bundle", "quadra", "vigilante"]):
                    continue
                # Skip if name contains ":" with extra text after (DLC/expansion) but allow "Complete Edition", "GOTY"
                if ":" in name:
                    parts = name.split(":", 1)
                    suffix = parts[1].strip().lower()
                    if len(suffix) > 10 and not any(kw in suffix for kw in ["complete edition", "goty", "definitive"]):
                        continue
                # Skip remasters, remakes, older games
                if any(kw in name_lower for kw in ["remastered", "remake", "sons of sparta"]):
                    continue
                
                base_price = float(m.group(1))
                
                # Check if all query words are in name
                if not all(w in name.lower() for w in query_words):
                    continue
                
                # Parse sale price
                sale_raw = price_data.get("discountedPrice", "")
                sale_m = re.match(r'ILS ([\d.]+)', sale_raw or "")
                sale_price = float(sale_m.group(1)) if sale_m else None
                
                filtered.append({
                    "id": r.get("id", ""),
                    "name": name,
                    "base_price": base_price,
                    "sale_price": sale_price,
                    "currency": "ILS",
                    "product_id": r.get("id", ""),
                    "url": f"https://store.playstation.com/en-il/product/{r.get('id', '')}",
                })
            
            # Take minimum price (base edition)
            if filtered:
                filtered.sort(key=lambda x: x["base_price"])
                result = filtered[:limit]
            else:
                result = []
            
            # Cache
            _cache[normalized] = {"data": result, "ts": time.time()}
            
            return result
        except Exception as e:
            logger.error(f"PSN GraphQL search failed: {e}")
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
