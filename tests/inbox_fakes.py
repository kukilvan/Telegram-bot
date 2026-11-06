"""Fake clients of TMDb, Shikimori, IGDB and Steam fed with the saved live answers of stage 6.4
(`fixtures/inbox/answers.json`, from `.scratch/6-4-inbox/answers/`), and a core built on the real adapters over them.

Every request is noted, so a test can count the searches of an item (spec 5.5). A query with no saved answer is an
empty answer, as a source that finds nothing; `fail_from` makes a client raise from its n-th request on. Adding a
title asks the details of a record: they are made up from the record the search gave (one aired season of a series).
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import TitleKind
from app.tracker.sources.igdb_games import IgdbGameSource
from app.tracker.sources.shikimori_anime import ShikimoriAnimeSource
from app.tracker.sources.tmdb_find import TmdbFindSource
from app.tracker.sources.tmdb_movies import TmdbMovieSource
from app.tracker.sources.tmdb_series import TmdbSeriesSource

ANSWERS = json.loads((Path(__file__).parent / "fixtures" / "inbox" / "answers.json").read_text(encoding="utf-8"))
SAMPLES_FILE = Path(__file__).parent / "fixtures" / "inbox_samples.md"
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)  # the day the answers were saved

# a lookup by the number of a TMDb link answers the record as the search does (the fields the adapter reads)
MOVIE_BY_ID = {"1485839": ANSWERS["movie:ELDEN RING"][0]}
TV_BY_ID = {"289517": ANSWERS["series:Dead-End Job"][0]}


def samples() -> dict[int, str]:
    text = SAMPLES_FILE.read_text(encoding="utf-8")
    found = re.finditer(r"^## (\d+)\. .*?\n.*?```text\n(.*?)\n```", text, re.S | re.M)
    return {int(match.group(1)): match.group(2) for match in found}


class Requests(list):
    """Every request of the fakes, in order: (service, what)."""

    def of(self, service: str) -> list[str]:
        return [what for who, what in self if who == service]


class _Fake:
    service = ""

    def __init__(self, requests: Requests, answers: dict) -> None:
        self.requests = requests
        self.answers = answers
        self.fail_from: int | None = None  # the number of the request of this client from which it raises

    def _note(self, what: str) -> None:
        self.requests.append((self.service, what))
        if self.fail_from is not None and len(self.requests.of(self.service)) >= self.fail_from:
            raise ConnectionError(f"{self.service} is down")


def _record(answers: dict, prefix: str, number: str) -> dict | None:
    """The record with this id in any saved answer of the searches of `prefix` (`movie:`, `series:`)."""
    found = [
        record for key, answer in answers.items() if key.startswith(prefix) and isinstance(answer, list)
        for record in answer if str(record.get("id")) == str(number)
    ]
    return found[0] if found else None


class FakeTmdb(_Fake):
    service = "tmdb"

    async def search_movie(self, query, strict=False):
        self._note(f"movie:{query}")
        return self.answers.get(f"movie:{query}") or []

    async def search_tv(self, query, strict=False):
        self._note(f"series:{query}")
        return self.answers.get(f"series:{query}") or []

    async def get_movie_with_release_dates(self, movie_id):
        self._note(f"movie-details:{movie_id}")
        record = _record(self.answers, "movie:", movie_id)
        return None if record is None else {**record, "genres": [], "release_dates": {"results": []}}

    async def get_tv_show(self, tv_id):
        self._note(f"tv-details:{tv_id}")
        record = _record(self.answers, "series:", tv_id)
        if record is None:
            return None
        return {**record, "genres": [], "status": "Returning Series",
                "seasons": [{"season_number": 1, "name": "Сезон 1", "episode_count": 2}]}

    async def get_tv_with_seasons(self, tv_id, numbers):
        self._note(f"tv-seasons:{tv_id}")
        episodes = [{"episode_number": 1, "air_date": "2026-10-30"}, {"episode_number": 2, "air_date": "2026-11-30"}]
        return {f"season/{number}": {"episodes": episodes} for number in numbers}

    async def lookup_movie(self, movie_id):
        self._note(f"movie-id:{movie_id}")
        return MOVIE_BY_ID.get(str(movie_id))

    async def lookup_tv(self, tv_id):
        self._note(f"tv-id:{tv_id}")
        return TV_BY_ID.get(str(tv_id))

    async def find_imdb(self, imdb_id):
        self._note(f"find:{imdb_id}")
        return self.answers.get(f"tmdb-find:{imdb_id}") or {"movie_results": [], "tv_results": []}


class FakeShikimori(_Fake):
    service = "shikimori"

    async def search_anime(self, query, strict=False):
        self._note(f"anime:{query}")
        return self.answers.get(f"anime:{query}") or []

    async def fetch_entries(self, ids):
        self._note(f"entries:{','.join(ids)}")
        found = []
        for number in ids:
            saved = self.answers.get(f"shikimori-entries:{number}") or [_record(self.answers, "anime:", number)]
            found.extend(record for record in saved if record)
        return found


class FakeIgdb(_Fake):
    service = "igdb"

    def __init__(self, requests: Requests, answers: dict, enabled: bool = True) -> None:
        super().__init__(requests, answers)
        self.enabled = enabled

    async def games(self, body, *, at_once=False):
        if search := re.match(r'search "(.*?)";', body):
            self._note(f"game:{search.group(1)}")
            return self.answers.get(f"game:{search.group(1)}") or []
        if steam := re.search(r'external_games.uid = "(\d+)"', body):
            self._note(f"steam:{steam.group(1)}")
            return self.answers.get(f"igdb-games-by-steam:{steam.group(1)}") or []
        number = re.search(r"where id = (\d+);", body).group(1)
        self._note(f"id:{number}")
        record = _record(self.answers, "game:", number) or _record(self.answers, "igdb-games-by-steam:", number)
        return [record] if record else []


class FakeSteam(_Fake):
    service = "steam"

    async def app_details(self, appid):
        self._note(f"appdetails:{appid}")
        return self.answers.get(f"steam-appdetails:{appid}")


class FakeSender:
    async def send(self, message, actions=()):
        pass


class Clients:
    """The four fake clients on one list of requests; `extra` adds answers to the saved ones (or replaces them)."""

    def __init__(self, igdb_keys: bool = True, extra: dict | None = None) -> None:
        self.requests = Requests()
        answers = {**ANSWERS, **(extra or {})}
        self.tmdb = FakeTmdb(self.requests, answers)
        self.shikimori = FakeShikimori(self.requests, answers)
        self.igdb = FakeIgdb(self.requests, answers, igdb_keys)
        self.steam = FakeSteam(self.requests, answers)

    def searches(self) -> list[str]:
        """The searches by name (not the lookups of links)."""
        return [what for _, what in self.requests if what.split(":")[0] in ("movie", "series", "anime", "game")]


def tracker_on(clients: Clients, url: str = "sqlite://", clock=lambda: NOW) -> Tracker:
    return Tracker(
        create_session_factory(url),
        clock=clock,
        sender=FakeSender(),
        sources={
            TitleKind.MOVIE: TmdbMovieSource(clients.tmdb),
            TitleKind.SERIES: TmdbSeriesSource(clients.tmdb),
            TitleKind.ANIME: ShikimoriAnimeSource(clients.shikimori),
            TitleKind.GAME: IgdbGameSource(clients.igdb, clients.steam),
        },
        imdb_source=TmdbFindSource(clients.tmdb),
    )
