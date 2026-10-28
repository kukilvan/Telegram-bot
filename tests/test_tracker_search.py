"""Tracker core: the suggestions of the search (poster, the number of the title already in the list) and adding a title
that is in the list already under another id (KI-2: an anime franchise that Shikimori gave a new prequel).

Driven through the facade only: fake clock, the real TMDb and Shikimori adapters over the saved real answers of the
search (the Shikimori one got the posters of the same entries from the saved chain answers: the request for posters
came later), in-memory SQLite. No network.
"""

import asyncio
import copy
import json
import logging
import pathlib
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from anime_fakes import FakeAniList, FakeShikimori
from app.tracker.core import SourceFailed, Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import Title, TitleKind
from app.tracker.seasons import Episode, Season
from app.tracker.sources import tmdb_movies, tmdb_series
from app.tracker.sources.shikimori_anime import ShikimoriAnimeSource
from app.tracker.sources.tmdb_movies import TmdbMovieSource
from app.tracker.sources.tmdb_series import SeriesSnapshot

T0 = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
TMDB = pathlib.Path(__file__).parent / "fixtures" / "tmdb"
JJK, JJK_2, JJK_FINAL, ABYSS, KUSURIYA = "40748", "51009", "63824", "34599", "54492"
JJK_POSTER = "https://shikimori.io/uploads/poster/animes/40748/af4f2db18f17de4d7c6491f6f92cd9d9.jpeg"
PREQUEL = "90000"


def load(name):
    return json.loads((TMDB / name).read_text(encoding="utf-8"))


class FakeSender:
    async def send(self, message, actions=()):
        pass


class FakeTmdb:
    """The TMDb client for the movie adapter: the saved search for «Дюна» and the saved «Dune» (2021)."""

    def __init__(self):
        self.down = False

    async def search_movie(self, query, strict=False):
        if self.down:
            raise RuntimeError("TMDb search_movie failed (HTTP 429)")
        return load("search_movie_duna.json")["results"]

    async def get_movie_with_release_dates(self, movie_id):
        return load("movie_438631.json") if movie_id == 438631 else None


class FakeSeries:
    """A series source that answers the saved search for «Укрытие» and knows the first of the series found."""

    source_key = tmdb_series.SOURCE_KEY

    async def suggest(self, query):
        return tmdb_series.parse_search(load("search_tv_ukrytie.json")["results"])

    async def snapshot(self, external_id):
        if external_id != "125988":
            return None
        season = Season(1, "Сезон 1", 2, (Episode(1, datetime(2025, 1, 1)), Episode(2, datetime(2025, 1, 8))))
        return SeriesSnapshot(external_id="125988", name="Укрытие", original_name="Silo", year=2023, seasons=[season])


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def shikimori():
    return FakeShikimori()


@pytest.fixture
def tmdb():
    return FakeTmdb()


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def tracker(session_factory, tmdb, shikimori):
    return Tracker(
        session_factory, clock=lambda: T0, sender=FakeSender(),
        sources={
            "movie": TmdbMovieSource(tmdb),
            "series": FakeSeries(),
            "anime": ShikimoriAnimeSource(shikimori, FakeAniList()),
        },
    )


def titles(session_factory):
    with session_factory() as session:
        return session.scalar(select(func.count()).select_from(Title))


def by_id(suggestions):
    return {s.external_id: s for s in suggestions}


# --- posters ---------------------------------------------------------------------------------------------------


def test_the_suggestions_of_tmdb_carry_the_posters_of_the_search_answer(tracker):
    suggestions = by_id(run(tracker.search(TitleKind.MOVIE, "дюна")))

    assert suggestions["438631"].poster_path == "/3hbXNclcHaj5KiF6kK41GBMjyFr.jpg"
    series = by_id(run(tracker.search(TitleKind.SERIES, "укрытие")))
    assert series["125988"].poster_path == "/gRkvq6FgiGRdtCwhVIozaUqhoDL.jpg"


def test_the_suggestions_of_shikimori_carry_the_poster_of_the_entry_shown(tracker):
    suggestions = run(tracker.search(TitleKind.ANIME, "магическая битва"))

    shown = by_id(suggestions)[JJK]
    assert shown.poster_path == JJK_POSTER
    assert by_id(suggestions)["52254"].poster_path is None  # Shikimori gave no poster: the page shows the icon


def test_the_search_asks_shikimori_for_the_poster():
    from app.providers import shikimori

    source = pathlib.Path(shikimori.__file__).read_text(encoding="utf-8")
    search = source[source.index("async def search_anime"):source.index("async def fetch_entries")]
    assert "poster { originalUrl }" in search


def test_the_bot_still_gets_the_fields_it_used_before(tracker):
    suggestions = run(tracker.search(TitleKind.MOVIE, "дюна"))

    assert [(s.kind, s.external_id, s.name, s.original_name, s.year) for s in suggestions] == [
        (s.kind, s.external_id, s.name, s.original_name, s.year)
        for s in tmdb_movies.parse_search(load("search_movie_duna.json")["results"])
    ]


# --- the number of the title in the list -------------------------------------------------------------------------


def test_nothing_is_in_the_list_yet_so_no_suggestion_has_a_title(tracker):
    for kind, query in [(TitleKind.MOVIE, "дюна"), (TitleKind.SERIES, "укрытие"), (TitleKind.ANIME, "битва")]:
        assert all(s.title_id is None for s in run(tracker.search(kind, query)))


def test_an_added_movie_and_series_have_their_number_in_the_suggestions(tracker):
    film = run(tracker.add_title(TitleKind.MOVIE, "438631")).title_id
    series = run(tracker.add_title(TitleKind.SERIES, "125988")).title_id

    movies = by_id(run(tracker.search(TitleKind.MOVIE, "дюна")))
    shows = by_id(run(tracker.search(TitleKind.SERIES, "укрытие")))

    assert movies["438631"].title_id == film and movies["693134"].title_id is None
    assert shows["125988"].title_id == series and shows["214993"].title_id is None


def test_a_number_belongs_to_its_own_kind_only(tracker):
    """TMDb shares one id space between movies and series: a series with the number of a film is not that film."""
    run(tracker.add_title(TitleKind.MOVIE, "438631"))

    assert by_id(run(tracker.search(TitleKind.SERIES, "укрытие")))["125988"].title_id is None


def test_an_added_anime_has_its_number_in_the_suggestions(tracker):
    anime = run(tracker.add_title(TitleKind.ANIME, JJK)).title_id

    assert by_id(run(tracker.search(TitleKind.ANIME, "битва")))[JJK].title_id == anime


def test_an_anime_is_known_by_the_id_of_a_later_part_too(tracker, shikimori, monkeypatch):
    """The search found only later seasons of the franchise: the suggestion shows the earliest of them, which is not
    the first season the title is stored by."""
    anime = run(tracker.add_title(TitleKind.ANIME, JJK)).title_id
    later = [a for a in shikimori_search() if a["id"] in (JJK_2, JJK_FINAL)]

    async def search_anime(query, strict=False):
        return later

    monkeypatch.setattr(shikimori, "search_anime", search_anime)

    [suggestion] = run(tracker.search(TitleKind.ANIME, "битва"))
    assert suggestion.external_id == JJK_2 and suggestion.title_id == anime


def test_the_numbers_are_read_once_after_the_source_answered(tracker, session_factory):
    run(tracker.add_title(TitleKind.MOVIE, "438631"))
    reads = []
    original = tracker._titles._known_ids

    def counted(poller, ids):
        reads.append(list(ids))
        return original(poller, ids)

    tracker._titles._known_ids = counted
    run(tracker.search(TitleKind.MOVIE, "дюна"))

    assert len(reads) == 1 and "438631" in reads[0]


def test_a_failing_source_is_a_source_failure_with_its_cause(tracker, tmdb):
    tmdb.down = True

    with pytest.raises(SourceFailed) as caught:
        run(tracker.search(TitleKind.MOVIE, "дюна"))

    assert str(caught.value) == "tmdb_movie" and isinstance(caught.value.__cause__, RuntimeError)


def test_an_unknown_kind_is_still_a_key_error(tracker):
    with pytest.raises(KeyError):
        run(tracker.search("game", "дюна"))


# --- KI-2: the franchise is the same title whatever entry is its first season now ---------------------------------


def shikimori_search():
    return json.loads(
        (pathlib.Path(__file__).parent / "fixtures" / "shikimori" / "search_jujutsu.json").read_text(encoding="utf-8")
    )["data"]["animes"]


def give_a_prequel(shikimori, first_season, *, also_before=()):
    """Shikimori adds a new TV entry that comes before `first_season` (and before each of `also_before`)."""
    first = shikimori.by_id[first_season]
    prequel = copy.deepcopy(first)
    prequel.update(
        id=PREQUEL, malId=PREQUEL, name="Prequel", russian="Приквел", airedOn={"date": "2010-01-01", "year": 2010},
        related=[{"relationKind": "sequel", "anime": {"id": int(i)}} for i in (first_season, *also_before)],
    )
    shikimori.by_id[PREQUEL] = prequel
    for later in (first_season, *also_before):
        entry = shikimori.by_id[later]
        entry["related"] = [*(entry.get("related") or []), {"relationKind": "prequel", "anime": {"id": int(PREQUEL)}}]


def test_ki_2_the_franchise_with_a_new_prequel_opens_the_title_that_is_there(tracker, shikimori, session_factory):
    first = run(tracker.add_title(TitleKind.ANIME, ABYSS))
    give_a_prequel(shikimori, ABYSS)

    again = run(tracker.add_title(TitleKind.ANIME, PREQUEL))

    assert first.created and not again.created and again.title_id == first.title_id
    assert titles(session_factory) == 1


def test_ki_2_a_suggestion_of_the_prequel_has_no_number_but_adding_it_makes_no_copy(tracker, shikimori, session_factory):
    """The prequel is stored nowhere yet, so the suggestion is not marked «В списке»; «Добавить» still opens the title."""
    first = run(tracker.add_title(TitleKind.ANIME, ABYSS)).title_id
    give_a_prequel(shikimori, ABYSS)
    known = run(asyncio.to_thread(tracker._titles._known_ids, tracker._titles.pollers.of(TitleKind.ANIME), [PREQUEL]))

    assert known == {}
    assert run(tracker.add_title(TitleKind.ANIME, PREQUEL)).title_id == first and titles(session_factory) == 1


def test_ki_2_an_anime_is_opened_by_a_franchise_film_too(tracker, session_factory):
    first = run(tracker.add_title(TitleKind.ANIME, ABYSS)).title_id

    again = run(tracker.add_title(TitleKind.ANIME, "37515"))  # «Made in Abyss Movie 2», a film of the chain

    assert not again.created and again.title_id == first and titles(session_factory) == 1


def test_ki_2_a_snapshot_that_names_two_titles_opens_the_smaller_number_and_warns(
    tracker, shikimori, session_factory, caplog
):
    abyss = run(tracker.add_title(TitleKind.ANIME, ABYSS)).title_id
    kusuriya = run(tracker.add_title(TitleKind.ANIME, KUSURIYA)).title_id
    give_a_prequel(shikimori, ABYSS, also_before=(KUSURIYA,))  # Shikimori joined the two chains

    with caplog.at_level(logging.WARNING):
        again = run(tracker.add_title(TitleKind.ANIME, PREQUEL))

    assert abyss < kusuriya and again.title_id == abyss and not again.created
    assert titles(session_factory) == 2
    assert f"names the titles [{abyss}, {kusuriya}]" in caplog.text
