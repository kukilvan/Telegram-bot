"""TMDb provider: search + details via async httpx."""

import logging

import httpx

from app.config import get_settings


class TMDbProvider:
    """Async TMDb API client.

    Base URL: https://api.themoviedb.org/3
    Auth: TMDB_API_KEY env var (free registration).
    Rate limit: ~40 RPS soft ceiling per API key.
    """

    BASE_URL = "https://api.themoviedb.org/3"

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.tmdb_api_key
        # httpx.AsyncClient with connection pooling for long-polling bot.
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=30.0,  # hard timeout; never hang forever
        )

    async def aclose(self) -> None:
        """Close the underlying httpx client."""
        await self._client.aclose()

    async def search_movie(
        self, query: str, page: int = 1
    ) -> list[dict]:
        """Search movies by title (RU or EN). Returns raw TMDb results.

        Endpoint: GET /search/movie?language=ru&include_adult=false&query={query}
        Auth: api_key as query param (standard TMDb REST auth).
        """
        params = {
            "api_key": self._api_key,
            "language": "ru",  # prefer Russian titles in response
            "include_adult": "false",
            "page": page,
            "query": query,
        }
        resp = await self._client.get("/search/movie", params=params)
        if resp.status_code != 200:
            logging.error("TMDb search_movie HTTP %s", resp.status_code)
            return []
        data = resp.json()
        return data.get("results", [])

    async def search_tv(
        self, query: str, page: int = 1
    ) -> list[dict]:
        """Search TV series by title (RU or EN). Returns raw TMDb results.

        Endpoint: GET /search/tv?language=ru&include_adult=false&query={query}
        Auth: api_key as query param (standard TMDb REST auth).
        """
        params = {
            "api_key": self._api_key,
            "language": "ru",
            "include_adult": "false",
            "page": page,
            "query": query,
        }
        resp = await self._client.get("/search/tv", params=params)
        if resp.status_code != 200:
            logging.error("TMDb search_tv HTTP %s", resp.status_code)
            return []
        data = resp.json()
        return data.get("results", [])

    async def get_movie_details(self, movie_id: int) -> dict | None:
        """Get full movie details (poster, backdrop, release dates)."""
        params = {"api_key": self._api_key, "language": "ru"}
        resp = await self._client.get(f"/movie/{movie_id}", params=params)
        if resp.status_code != 200:
            logging.error("TMDb get_movie_details HTTP %s", resp.status_code)
            return None
        return resp.json()

    async def get_tv_details(self, tv_id: int) -> dict | None:
        """Get full TV series details (poster, backdrop)."""
        params = {"api_key": self._api_key, "language": "ru"}
        resp = await self._client.get(f"/tv/{tv_id}", params=params)
        if resp.status_code != 200:
            logging.error("TMDb get_tv_details HTTP %s", resp.status_code)
            return None
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
        resp = await self._client.get(
            f"/movie/{movie_id}/release_dates", params=params
        )
        if resp.status_code != 200:
            logging.error("TMDb get_movie_release_dates HTTP %s", resp.status_code)
            return []
        data = resp.json()
        return data.get("results", [])
