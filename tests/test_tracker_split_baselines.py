"""The split of the core changes no behaviour (ticket 9.1d.01): the JSON of the export and the Feed of a sample base are
the same, to the byte, as the documents recorded before the split (`tests/fixtures/split/`). If a test here needs a new
expected value, the move went wrong. The documents are made by the functions below: an owner of a later change that
really changes the export or the Feed records them again on purpose."""

import asyncio
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.games import GameState, Release
from app.tracker.release_dates import ReleaseDate
from app.tracker.models import (
    EpisodeRecord, Event, ExternalId, GamePlatformRecord, MovieRecord, PartRecord, SeasonRecord, SourceSnapshot, Title,
    TitleKind, TitleStatus,
)
from app.tracker.platforms import WORLD
from test_tracker_export import MOSCOW, NOW as EXPORT_NOW, FakeSender, prepared

FIXTURES = Path(__file__).parent / "fixtures" / "split"
NOW = datetime(2026, 10, 30, 12, 0)  # naive UTC, a Friday
TODAY = NOW.date()
MSK = timezone(timedelta(hours=3))
PC, PS5 = 6, 167


def run(coroutine):
    return asyncio.run(coroutine)


def export_text(session_factory) -> str:
    """The JSON of «Скачать всё (JSON)» of the sample base of the export tests, with the migration number set apart
    (a later migration changes it, not the export)."""
    prepared(session_factory)
    tracker = Tracker(session_factory, clock=lambda: EXPORT_NOW, sender=FakeSender(), default_tz=MOSCOW)
    content = run(tracker.export_all()).content.decode("utf-8")
    with session_factory() as session:
        revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar()
    return content.replace(f'"database_revision": "{revision}"', '"database_revision": "<revision>"')


def at(days, hour=12):
    return datetime.combine(TODAY + timedelta(days=days), time(hour, 0))


def put_title(session, name, kind, status=TitleStatus.WANT):
    title = Title(kind=kind, name=name, original_name=name, genres=[], status=status, tracking_enabled=True,
                  added_at=NOW, status_changed_at=NOW)
    session.add(title)
    session.flush()
    return title


def put_season(session, title, number, episodes, parts=()):
    season = SeasonRecord(title_id=title.id, number=number, name=f"Сезон {number}", episode_count=None, watched=False)
    session.add(season)
    session.flush()
    session.add_all(EpisodeRecord(season_id=season.id, number=n, air_at=moment) for n, moment in episodes.items())
    session.add_all(
        PartRecord(title_id=title.id, season_id=season.id, number=index, first_episode=first, episode_count=count,
                   shikimori_id=f"{title.id}-{number}-{index}")
        for index, (first, count) in enumerate(parts, 1)
    )


def put_snapshot(session, title, source, state):
    session.add(ExternalId(title_id=title.id, source=source, external_id=str(title.id), role="primary"))
    session.add(SourceSnapshot(title_id=title.id, source=source, state=state, observed_at=NOW))


def sample_feed(session_factory) -> str:
    """The Feed of a base with every kind: a series and an anime with episodes, parts and a franchise film, movies with
    their two dates (one out before the baseline), games with platforms, events in the window and one in the archive."""
    with session_factory() as session:
        series = put_title(session, "Сериал", TitleKind.SERIES)
        put_season(session, series, 1, {1: at(-3), 2: at(2, 9), 3: at(2, 10), 4: at(9)})
        anime = put_title(session, "Аниме", TitleKind.ANIME)
        put_season(session, anime, 1, {1: at(-2), 2: at(1, 15), 3: at(8, 15), 4: at(15, 15)}, parts=[(1, 2), (3, 2)])
        session.add(MovieRecord(title_id=anime.id, name="Старый фильм", aired_on=TODAY - timedelta(days=2), released=True,
                                shikimori_id="m-past"))
        farther = put_title(session, "Аниме с фильмом", TitleKind.ANIME)  # only «Позже»: a film and a far season
        put_season(session, farther, 1, {1: at(40, 15)})
        session.add(MovieRecord(title_id=farther.id, name="Фильм аниме", aired_on=TODAY + timedelta(days=20), released=False,
                                shikimori_id="m-future"))
        late = put_title(session, "Сериал позже", TitleKind.SERIES)
        put_season(session, late, 1, {1: at(30), 2: None})
        out = put_title(session, "Фильм с датами", TitleKind.MOVIE)
        put_snapshot(session, out, "tmdb_movie", {"theatrical_date": (TODAY - timedelta(days=3)).isoformat(),
                                                  "digital_date": (TODAY - timedelta(days=1)).isoformat()})
        coming = put_title(session, "Фильм впереди", TitleKind.MOVIE)
        put_snapshot(session, coming, "tmdb_movie", {"theatrical_date": (TODAY + timedelta(days=5)).isoformat(),
                                                     "digital_date": (TODAY + timedelta(days=30)).isoformat()})
        one_day = put_title(session, "Фильм одним днём", TitleKind.MOVIE)
        put_snapshot(session, one_day, "tmdb_movie", {"theatrical_date": (TODAY + timedelta(days=2)).isoformat(),
                                                      "digital_date": (TODAY + timedelta(days=2)).isoformat()})
        game = put_title(session, "Игра", TitleKind.GAME)
        records = (
            Release(platform=PC, region=WORLD, type="full", date=ReleaseDate.parse((TODAY + timedelta(days=4)).isoformat())),
            Release(platform=PS5, region=WORLD, type="full", date=ReleaseDate.parse("2027")),
        )
        state = GameState(steam_id=None, ps_concept=None, platforms=(PC, PS5), releases=records).state()
        put_snapshot(session, game, "igdb", state)
        session.add_all(GamePlatformRecord(title_id=game.id, platform=p, playing=True) for p in ("pc", "ps5"))
        far = put_title(session, "Игра позже", TitleKind.GAME)
        far_state = GameState(steam_id=None, ps_concept=None, platforms=(PC,), releases=(
            Release(platform=PC, region=WORLD, type="full", date=ReleaseDate.parse("2027-03")),)).state()
        put_snapshot(session, far, "igdb", far_state)
        session.add(GamePlatformRecord(title_id=far.id, platform="pc", playing=True))
        archived = put_title(session, "В архиве", TitleKind.SERIES, status=TitleStatus.WATCHED)
        put_season(session, archived, 1, {1: at(3)})
        session.add_all([
            Event(type="episode_out", title_id=series.id, payload={"text": "📺 Сериал — вышла серия 1 из 10\nСезон 1"},
                  dedup_key="e1", detected_at=at(-3, 9)),
            Event(type="movie_released", title_id=out.id, payload={"text": "🎬 Фильм с датами — вышел"},
                  dedup_key="e2", detected_at=at(-1, 8)),
        ])
        session.commit()
    tracker = Tracker(session_factory, clock=lambda: NOW.replace(tzinfo=timezone.utc), sender=FakeSender(), default_tz=MSK)
    return repr(run(tracker.feed())) + "\n"


@pytest.fixture
def session_factory(tmp_path):
    return create_session_factory(f"sqlite:///{(tmp_path / 'tracker.db').as_posix()}")


def test_the_export_json_of_the_sample_base_is_the_one_recorded_before_the_split(session_factory):
    expected = (FIXTURES / "export.json").read_text(encoding="utf-8")

    assert export_text(session_factory) == expected


def test_the_feed_of_the_sample_base_is_the_one_recorded_before_the_split(session_factory):
    expected = (FIXTURES / "feed.txt").read_text(encoding="utf-8")

    assert sample_feed(session_factory) == expected


def test_the_recorded_feed_has_something_in_every_part():
    text = (FIXTURES / "feed.txt").read_text(encoding="utf-8")

    assert "upcoming=(" in text and "later=(" in text and "recent=(" in text
    for word in ("Сериал", "Аниме", "Фильм с датами", "Фильм впереди", "Игра", "Фильм «Фильм аниме»", "Сериал позже", "Игра позже"):
        assert word in text, word
    assert "В архиве" not in text
