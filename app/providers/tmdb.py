"""TMDb provider: search + details via async httpx, with Phase 7.5 adaptive throttling."""

import asyncio
import logging
import time
from collections import deque

import httpx

from app.config import get_settings


class TMDbProvider:
    """Async TMDb API client with staggered, capped request pacing (Phase 7.5).

    Base URL: https://api.themoviedb.org/3
    Auth: TMDB_API_KEY env var (free registration).
    Rate limit: soft ceiling ~40-50 req/s and no documented daily cap. We never
    fire bulk requests (no batch endpoint exists), so pacing is enforced here:
      * at least `tmdb_min_call_interval` seconds between consecutive calls;
      * rolling per-minute cap (`tmdb_max_calls_per_minute`);
      * HTTP 429 retried with exponential backoff (honoring Retry-After when set).
    Observability: `call_count` counts every real HTTP request so the reduction
    over time can be checked in logs.
    """

    BASE_URL = "https://api.themoviedb.org/3"

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.tmdb_api_key
        self.min_call_interval = float(settings.tmdb_min_call_interval)
        self.max_calls_per_minute = int(settings.tmdb_max_calls_per_minute)
        self.backoff_base_seconds = float(settings.tmdb_429_backoff_base_seconds)
        self.backoff_max_retries = int(settings.tmdb_429_max_retries)

        # Phase 7.5 pacing state
        self._last_call_at: float | None = None      # monotonic time of last real call
        self._window_calls: deque[float] = deque()   # timestamps inside the rolling 60 s window

        # Phase 7.5 observability / degradation flag
        self.call_count = 0   # every real TMDb HTTP request attempted so far
        self.hit_429 = False  # True if the last request batch hit HTTP 429

        # httpx.AsyncClient with connection pooling for long-polling bot.
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=30.0,  # hard timeout; never hang forever
        )

    async def aclose(self) -> None:
        """Close the underlying httpx client."""
        await self._client.aclose()

    async def _throttle(self) -> None:
        """Sleep until pacing limits are satisfied before issuing a request.

        Enforces both the minimum interval since the last call and the rolling
        per-minute cap, so consecutive items are staggered in time instead of
        being fired simultaneously.
        """
        now = time.monotonic()
        while self._window_calls and now - self._window_calls[0] >= 60.0:
            self._window_calls.popleft()
        wait_interval = (
            self.min_call_interval - (now - self._last_call_at)
            if self._last_call_at is not None else 0.0
        )
        if len(self._window_calls) >= self.max_calls_per_minute:
            # Wait until the oldest timestamp in the window ages out (>60 s).
            wait_cap = (self._window_calls[0] + 60.0) - now
        else:
            wait_cap = 0.0
        delay = max(wait_interval, wait_cap, 0.0)
        if delay > 0:
            await asyncio.sleep(delay)
        stamp = time.monotonic()
        self._last_call_at = stamp
        self._window_calls.append(stamp)

    async def _get(self, path: str, params: dict | None = None) -> httpx.Response | None:
        """One throttled GET with exponential backoff on HTTP 429.

        Returns the response, or None if every retry after a persistent 429
        failed (callers degrade to an empty result and move the item to its next slot).
        """
        self.hit_429 = False
        backoff = self.backoff_base_seconds
        for attempt in range(1, self.backoff_max_retries + 1):
            await self._throttle()
            resp = await self._client.get(path, params=params)
            self.call_count += 1
            if resp.status_code == 429:
                self.hit_429 = True
                retry_after_raw = (resp.headers or {}).get("Retry-After")
                try:
                    wait = float(retry_after_raw)
                except (TypeError, ValueError):
                    wait = backoff
                logging.warning(
                    "TMDb 429 on %s; backing off %.1fs (attempt %d/%d)",
                    path, max(wait, 0.0), attempt, self.backoff_max_retries,
                )
                await asyncio.sleep(max(0.0, wait))
                backoff *= 2
                continue
            return resp
        logging.error(
            "TMDb still rate-limited after %d retries on %s; degrading to empty result",
            self.backoff_max_retries, path,
        )
        return None

    async def search_movie(self, query: str, page: int = 1, strict: bool = False) -> list[dict]:
        """Search movies by title (RU or EN). Returns raw TMDb results.

        Endpoint: GET /search/movie?language=ru&include_adult=false&query={query}
        Auth: api_key as query param (standard TMDb REST auth).
        With `strict=True` a failed request raises instead of returning [], so "TMDb is down" is not
        mistaken for "nothing found".
        """
        params = {
            "api_key": self._api_key,
            "language": "ru",  # prefer Russian titles in response
            "include_adult": "false",
            "page": page,
            "query": query,
        }
        resp = await self._get("/search/movie", params)
        if resp is None or resp.status_code != 200:
            logging.error("TMDb search_movie failed (HTTP %s)", resp.status_code if resp else 429)
            if strict:
                raise RuntimeError(f"TMDb search_movie failed (HTTP {resp.status_code if resp else 429})")
            return []
        data = resp.json()
        return data.get("results", [])

    async def search_tv(self, query: str, page: int = 1, strict: bool = False) -> list[dict]:
        """Search TV series by title (RU or EN). Returns raw TMDb results.

        Endpoint: GET /search/tv?language=ru&include_adult=false&query={query}
        Auth: api_key as query param (standard TMDb REST auth).
        With `strict=True` a failed request raises instead of returning [], so "TMDb is down" is not
        mistaken for "nothing found".
        """
        params = {
            "api_key": self._api_key,
            "language": "ru",
            "include_adult": "false",
            "page": page,
            "query": query,
        }
        resp = await self._get("/search/tv", params)
        if resp is None or resp.status_code != 200:
            logging.error("TMDb search_tv failed (HTTP %s)", resp.status_code if resp else 429)
            if strict:
                raise RuntimeError(f"TMDb search_tv failed (HTTP {resp.status_code if resp else 429})")
            return []
        data = resp.json()
        return data.get("results", [])

    async def get_movie_details(self, movie_id: int) -> dict | None:
        """Get full movie details (poster, backdrop, release dates)."""
        params = {"api_key": self._api_key, "language": "ru"}
        resp = await self._get(f"/movie/{movie_id}", params)
        if resp is None or resp.status_code != 200:
            if resp is not None and resp.status_code == 404:
                # Expected during dual-endpoint resolution: TMDb shares one numeric
                # id space across movies and TV, so a TV-only id has no movie.
                logging.debug("TMDb get_movie_details HTTP 404 (no movie at this id)")
            else:
                logging.error("TMDb get_movie_details failed (HTTP %s)", resp.status_code if resp else 429)
            return None
        return resp.json()

    async def get_movie_with_release_dates(self, movie_id: int) -> dict | None:
        """Movie details plus the nested per-region `release_dates` in one request.

        Endpoint: GET /movie/{id}?language=ru&append_to_response=release_dates
        Returns None only when there is no movie at this id (404). Any other failure raises, so the caller
        can tell "no such movie" from "TMDb unavailable".
        """
        params = {"api_key": self._api_key, "language": "ru", "append_to_response": "release_dates"}
        resp = await self._get(f"/movie/{movie_id}", params)
        if resp is None:
            raise RuntimeError("TMDb is rate-limiting requests (HTTP 429)")
        if resp.status_code == 404:
            logging.debug("TMDb get_movie_with_release_dates HTTP 404 (no movie at this id)")
            return None
        if resp.status_code != 200:
            raise RuntimeError(f"TMDb get_movie_with_release_dates failed (HTTP {resp.status_code})")
        return resp.json()

    async def get_collection(self, collection_id: int) -> dict | None:
        """Franchise collection with all its movies (`parts`).

        Endpoint: GET /collection/{id}?language=ru
        Returns None only when there is no collection at this id (404). Any other failure raises, so the
        caller can tell "no such collection" from "TMDb unavailable".
        """
        params = {"api_key": self._api_key, "language": "ru"}
        resp = await self._get(f"/collection/{collection_id}", params)
        if resp is None:
            raise RuntimeError("TMDb is rate-limiting requests (HTTP 429)")
        if resp.status_code == 404:
            logging.debug("TMDb get_collection HTTP 404 (no collection at this id)")
            return None
        if resp.status_code != 200:
            raise RuntimeError(f"TMDb get_collection failed (HTTP {resp.status_code})")
        return resp.json()

    async def get_tv_details(self, tv_id: int) -> dict | None:
        """Get full TV series details (poster, backdrop)."""
        params = {"api_key": self._api_key, "language": "ru"}
        resp = await self._get(f"/tv/{tv_id}", params)
        if resp is None or resp.status_code != 200:
            if resp is not None and resp.status_code == 404:
                # Expected during dual-endpoint resolution: a movie-only id has no TV show.
                logging.debug("TMDb get_tv_details HTTP 404 (no TV at this id)")
            else:
                logging.error("TMDb get_tv_details failed (HTTP %s)", resp.status_code if resp else 429)
            return None
        return resp.json()

    async def get_tv_show(self, tv_id: int) -> dict | None:
        """TV series details with the list of its seasons (`seasons`: number, name, episode_count).

        Endpoint: GET /tv/{id}?language=ru
        Returns None only when there is no series at this id (404: it may be a movie). Any other failure
        raises, so the caller can tell "no such series" from "TMDb unavailable".
        """
        params = {"api_key": self._api_key, "language": "ru"}
        resp = await self._get(f"/tv/{tv_id}", params)
        if resp is None:
            raise RuntimeError("TMDb is rate-limiting requests (HTTP 429)")
        if resp.status_code == 404:
            logging.debug("TMDb get_tv_show HTTP 404 (no TV at this id)")
            return None
        if resp.status_code != 200:
            raise RuntimeError(f"TMDb get_tv_show failed (HTTP {resp.status_code})")
        return resp.json()

    async def get_tv_season(self, tv_id: int, season_number: int) -> dict | None:
        """One season with its episodes (`episodes`: number, ISO `air_date` or null).

        Endpoint: GET /tv/{id}/season/{n}?language=ru
        Returns None only when TMDb has no such season (404). Any other failure raises.
        """
        params = {"api_key": self._api_key, "language": "ru"}
        resp = await self._get(f"/tv/{tv_id}/season/{season_number}", params)
        if resp is None:
            raise RuntimeError("TMDb is rate-limiting requests (HTTP 429)")
        if resp.status_code == 404:
            logging.debug("TMDb get_tv_season HTTP 404 (no such season)")
            return None
        if resp.status_code != 200:
            raise RuntimeError(f"TMDb get_tv_season failed (HTTP {resp.status_code})")
        return resp.json()

    async def get_movie_release_dates(self, movie_id: int) -> list[dict]:
        """Return raw TMDb release dates for a movie (per-region).

        Endpoint: GET /movie/{id}/release_dates?language=ru&watch_region=all
        Each item has keys: region, type ("Digital"|"Physical"|"Theatrical"),
        iso_release_date, date.
        """
        params = {
            "api_key": self._api_key,
            "language": "ru",
            "watch_region": "all",
        }
        resp = await self._get(f"/movie/{movie_id}/release_dates", params)
        if resp is None or resp.status_code != 200:
            logging.error("TMDb get_movie_release_dates failed (HTTP %s)", resp.status_code if resp else 429)
            return []
        data = resp.json()
        return data.get("results", [])

    async def get_movie_credits(self, movie_id: int) -> dict | None:
        """Return movie credits (cast and crew).

        Endpoint: GET /movie/{id}/credits?language=ru
        Returns: {cast: [...], crew: [...]}
        """
        params = {"api_key": self._api_key, "language": "ru"}
        resp = await self._get(f"/movie/{movie_id}/credits", params)
        if resp is None or resp.status_code != 200:
            logging.error("TMDb get_movie_credits failed (HTTP %s)", resp.status_code if resp else 429)
            return None
        return resp.json()

    async def get_movie_watch_providers(self, movie_id: int, region: str = "RU") -> list[dict]:
        """Return watch/provider info for a movie.

        Endpoint: GET /movie/{id}/watch/providers?language=ru&region={region}
        Returns: {results: {RU: {flatrate: [...]}, US: {flatrate: [...]}, ...}}
        """
        params = {"api_key": self._api_key, "language": "ru", "region": region}
        resp = await self._get(f"/movie/{movie_id}/watch/providers", params)
        if resp is None or resp.status_code != 200:
            logging.error("TMDb get_movie_watch_providers failed (HTTP %s)", resp.status_code if resp else 429)
            return []
        data = resp.json()
        results = data.get("results", {})
        region_data = results.get(region) or {}
        return region_data.get("flatrate", [])

    async def get_tv_seasons(self, tv_id: int) -> list[dict]:
        """Return the raw TMDb seasons array for a TV series.

        Endpoint: GET /tv/{id}?language=ru&watch_region=all
        NOTE (verified live): the show-level endpoint returns season metadata
        only — `season_number`, `episode_count` etc. — but NOT the episodes
        array, even with with_seasons/append_to_response. For per-episode air
        dates use get_tv_season_episodes().
        """
        params = {"api_key": self._api_key, "language": "ru", "watch_region": "all"}
        resp = await self._get(f"/tv/{tv_id}", params)
        if resp is None or resp.status_code != 200:
            logging.error("TMDb get_tv_seasons failed (HTTP %s)", resp.status_code if resp else 429)
            return []
        data = resp.json()
        return data.get("seasons") or []

    async def get_tv_credits(self, tv_id: int) -> dict | None:
        """Return TV series credits (cast and crew).

        Endpoint: GET /tv/{id}/credits?language=ru
        Returns: {cast: [...], crew: [...]}
        """
        params = {"api_key": self._api_key, "language": "ru"}
        resp = await self._get(f"/tv/{tv_id}/credits", params)
        if resp is None or resp.status_code != 200:
            logging.error("TMDb get_tv_credits failed (HTTP %s)", resp.status_code if resp else 429)
            return None
        return resp.json()

    async def get_tv_season_episodes(self, tv_id: int, season_number: int) -> list[dict]:
        """Return the raw TMDb episodes array for one TV season.

        Endpoint: GET /tv/{id}/season/{n}?language=ru
        Each episode carries an ISO `air_date` string or null when not aired yet.
        Required because the show-level endpoint does not embed episodes (verified live).
        """
        params = {"api_key": self._api_key, "language": "ru"}
        resp = await self._get(f"/tv/{tv_id}/season/{season_number}", params)
        if resp is None or resp.status_code != 200:
            logging.error("TMDb get_tv_season_episodes failed (HTTP %s)", resp.status_code if resp else 429)
            return []
        data = resp.json()
        return data.get("episodes") or []
