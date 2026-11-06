"""TMDb adapter for the IMDb links of «Входящие»: `/find` by an IMDb id gives the movie or the series it names.

Parsing is pure (response in, data out) and is tested on a saved real response. The network client (`TMDbProvider`) is
passed in. TMDb answers a movie and a series of one IMDb id in two lists: the movie is taken first, else the series
(spec 3 of stage 6.4), so the suggestion carries the kind it turned out to be.
"""

from typing import Any

from app.tracker.sources import tmdb_movies, tmdb_series
from app.tracker.sources.tmdb_movies import Suggestion

SOURCE_KEY = "tmdb_find"  # only the failures name it: what is found is a movie of `tmdb_movie` or a series of `tmdb_tv`


def parse_find(raw: dict[str, Any] | None) -> Suggestion | None:
    """The first of `movie_results`, else the first of `tv_results`; None when both are empty (soft)."""
    raw = raw if isinstance(raw, dict) else {}
    for results, parse in (("movie_results", tmdb_movies.parse_search), ("tv_results", tmdb_series.parse_search)):
        records = [item for item in raw.get(results) or [] if isinstance(item, dict) and "id" in item]
        if records:
            return parse(records[:1])[0]
    return None


class TmdbFindSource:
    """The lookup of an IMDb id, on top of a `TMDbProvider`-like client."""

    source_key = SOURCE_KEY

    def __init__(self, provider) -> None:
        self._provider = provider

    async def suggest_by_imdb(self, imdb_id: str) -> Suggestion | None:
        """The movie or the series of an IMDb id (`tt…`); None when TMDb knows neither. Goes at once."""
        return parse_find(await self._provider.find_imdb(imdb_id))
