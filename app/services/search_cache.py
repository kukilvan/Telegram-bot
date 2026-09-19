"""In-memory search result cache.

Search results are cached for 5 minutes to avoid redundant API calls.
Uses a simple TTL dict with automatic cleanup on every set() call.
"""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 300  # 5 minutes
MAX_CACHE_SIZE = 1000  # Max number of entries before forced eviction


class SearchCache:
    """Simple in-memory TTL cache with automatic cleanup."""

    def __init__(self):
        self._cache: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        """Get cached value if not expired."""
        entry = self._cache.get(key)
        if entry is None:
            return None
        timestamp, value = entry
        if time.monotonic() - timestamp > CACHE_TTL_SECONDS:
            del self._cache[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        """Cache a value with current timestamp. Cleans up expired entries first."""
        # Phase 19: Clean up expired entries before adding new one
        self._cleanup_expired()
        self._cache[key] = (time.monotonic(), value)

    def _cleanup_expired(self) -> None:
        """Remove all expired entries. Runs on every set() call."""
        now = time.monotonic()
        expired_keys = [
            k for k, (ts, _) in self._cache.items()
            if now - ts > CACHE_TTL_SECONDS
        ]
        for k in expired_keys:
            del self._cache[k]

        # Phase 19: If cache is still too large, evict oldest entries (LRU-style)
        if len(self._cache) > MAX_CACHE_SIZE:
            sorted_items = sorted(self._cache.items(), key=lambda x: x[1][0])
            for k, _ in sorted_items[:len(self._cache) - MAX_CACHE_SIZE]:
                del self._cache[k]
            logger.info(f"Search cache evicted {len(sorted_items) - MAX_CACHE_SIZE} oldest entries")

    def clear(self) -> None:
        """Clear all cached entries."""
        self._cache.clear()

    @property
    def size(self) -> int:
        """Return current cache size."""
        return len(self._cache)


# Global singleton
search_cache = SearchCache()
