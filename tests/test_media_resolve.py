"""Tests for TMDb id resolution + stale self-heal (Bug A/B fix), no network."""

import asyncio

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.bot.main import (
    _ensure_media_item,
    _lookup_tmdb_details,
    _make_media_item,
    _resolve_media_for_add,
)
from app.database.base import Base
from app.database.models import (
    ExternalId,
    MediaItem,
    NotificationRule,
    SourceState,
    User,
    UserWatchItem,
)

MOVIE_DETAIL = {
    "id": 60625,
    "title": "Eye Contact",
    "release_date": "2000-11-30",
    "poster_path": "/eye.jpg",
}
TV_DETAIL = {
    "id": 60625,
    "name": "Rick and Morty",
    "first_air_date": "2013-12-02",
    "poster_path": None,
}


class FakeDetailsProvider:
    """Returns canned details for one known id; None otherwise."""

    def __init__(self, movie=MOVIE_DETAIL, tv=TV_DETAIL):
        self.movie = movie
        self.tv = tv

    async def get_movie_details(self, tmdb_id):
        return self.movie if (self.movie and self.movie.get("id") == tmdb_id) else None

    async def get_tv_details(self, tmdb_id):
        return self.tv if (self.tv and self.tv.get("id") == tmdb_id) else None


def _make_session():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return factory()


def _item_count(s):
    return len(s.execute(select(MediaItem)).scalars().all())


def _watch_rows_for(s, media_item_id):
    return len(
        s.execute(
            select(UserWatchItem).where(
                UserWatchItem.media_item_id == media_item_id
            )
        ).scalars().all()
    )


def _seed_item(s, tmdb_id, media_type="movie", title="Eye Contact"):
    """Create an item + ext row plus dependent rows to prove cleanup works."""
    user = User(telegram_user_id=454501218)
    s.add(user)
    item = MediaItem(media_type=media_type, canonical_title_en=title)
    s.add(item)
    s.flush()  # generate UUID primary key before FK reference
    ext = ExternalId(media_item_id=item.id, source="tmdb", external_id=str(tmdb_id))
    s.add(ext)
    watch = UserWatchItem(user_id=user.id, media_item_id=item.id)
    s.add(watch)
    rule = NotificationRule(
        user_id=user.id, media_item_id=item.id,
        event_type="DIGITAL_DATE_ANNOUNCED", enabled=True,
    )
    s.add(rule)
    state = SourceState(media_item_id=item.id, source_name="tmdb", state_data="{}")
    s.add(state)
    s.commit()
    return user, item


def test_make_media_item():
    m = _make_media_item(MOVIE_DETAIL, "movie")
    assert m.media_type == "movie"
    assert m.canonical_title_en == "Eye Contact"
    assert m.year == 2000
    assert m.poster_url == "https://image.tmdb.org/t/p/original/eye.jpg"

    tv = _make_media_item({**TV_DETAIL, "first_air_date": None}, "tv")
    assert tv.media_type == "tv"
    assert tv.canonical_title_en == "Rick and Morty"
    assert tv.year is None
    assert tv.poster_url is None


def test_lookup_tmdb_details():
    both = FakeDetailsProvider()
    r = asyncio.run(_lookup_tmdb_details(both, 60625))
    assert (r[0], r[1]) == (MOVIE_DETAIL, TV_DETAIL)

    movie_only = FakeDetailsProvider(tv=None)
    r2 = asyncio.run(_lookup_tmdb_details(movie_only, 60625))
    assert r2 == (MOVIE_DETAIL, None)

    neither = FakeDetailsProvider(movie=None, tv=None)
    r3 = asyncio.run(_lookup_tmdb_details(neither, 700111))
    assert r3 == (None, None)


def test_ensure_media_item_creates():
    s = _make_session()
    item = _ensure_media_item(s, 60625, TV_DETAIL, "tv")
    assert item.media_type == "tv"
    ext_rows = s.execute(
        select(ExternalId).where(
            (ExternalId.source == "tmdb") & (ExternalId.external_id == "60625")
        )
    ).scalars().all()
    assert len(ext_rows) == 1 and ext_rows[0].media_item_id == item.id
    s.close()


def test_ensure_media_item_returns_existing():
    s = _make_session()
    _, existing = _seed_item(s, 60625, media_type="tv", title="Rick and Morty")
    item = _ensure_media_item(s, 60625, TV_DETAIL, "tv")
    assert item.id == existing.id
    assert _item_count(s) == 1
    s.close()


def test_ensure_media_item_self_heals_stale():
    s = _make_session()
    _, stale = _seed_item(s, 60625, media_type="movie", title="Eye Contact")
    item = _ensure_media_item(s, 60625, TV_DETAIL, "tv")
    assert item.media_type == "tv" and item.id != stale.id
    # Stale item + its dependent rows are gone.
    assert s.get(MediaItem, stale.id) is None
    assert _watch_rows_for(s, stale.id) == 0
    assert (
        len(
            s.execute(
                select(NotificationRule).where(
                    NotificationRule.media_item_id == stale.id
                )
            ).scalars().all()
        )
        == 0
    )
    # Exactly one ext row remains for the id, pointing at the new item.
    ext_rows = s.execute(
        select(ExternalId).where(
            (ExternalId.source == "tmdb") & (ExternalId.external_id == "60625")
        )
    ).scalars().all()
    assert len(ext_rows) == 1 and ext_rows[0].media_item_id == item.id
    s.close()


def test_resolve_media_for_add_not_found():
    s = _make_session()
    provider = FakeDetailsProvider(movie=None, tv=None)
    result = asyncio.run(_resolve_media_for_add(s, 999888777, provider, anilist_provider=None))
    assert result == ("none", None)
    assert _item_count(s) == 0
    s.close()


def test_resolve_media_for_add_single_tv_hit():
    s = _make_session()
    provider = FakeDetailsProvider(movie=None, tv=TV_DETAIL)
    result = asyncio.run(_resolve_media_for_add(s, 60625, provider, anilist_provider=None))
    assert result[0] == "item"
    item = result[1]
    assert item.media_type == "tv" and item.canonical_title_en == "Rick and Morty"
    s.close()


def test_resolve_media_for_add_collision_returns_pick():
    s = _make_session()
    provider = FakeDetailsProvider()  # both endpoints live for this id
    result = asyncio.run(_resolve_media_for_add(s, 60625, provider, anilist_provider=None))
    assert result[0] == "pick_tmdb"
    assert (result[1], result[2]) == (MOVIE_DETAIL, TV_DETAIL)
    # Nothing created until the user picks.
    assert _item_count(s) == 0
    s.close()


def test_resolve_media_for_add_uses_existing_item():
    """One tracked item per (tmdb, id): an existing matching item is returned
    even when TMDb has both a movie and a TV for the same number."""
    s = _make_session()
    _, existing = _seed_item(s, 60625, media_type="movie", title="Eye Contact")
    provider = FakeDetailsProvider()  # both live on TMDb
    result = asyncio.run(_resolve_media_for_add(s, 60625, provider, anilist_provider=None))
    assert result[0] == "item" and result[1].id == existing.id
    assert _item_count(s) == 1
    s.close()


def test_resolve_media_for_add_stale_tv_override():
    """Residue of the old movie-first resolution is self-healed when only the
    TV endpoint still resolves for that id."""
    s = _make_session()
    _, stale = _seed_item(s, 60625, media_type="movie", title="Eye Contact")
    provider = FakeDetailsProvider(movie=None, tv=TV_DETAIL)
    result = asyncio.run(_resolve_media_for_add(s, 60625, provider, anilist_provider=None))
    assert result[0] == "item"
    item = result[1]
    assert item.media_type == "tv" and item.id != stale.id
    assert s.get(MediaItem, stale.id) is None
    s.close()


if __name__ == "__main__":
    test_make_media_item()
    test_lookup_tmdb_details()
    test_ensure_media_item_creates()
    test_ensure_media_item_returns_existing()
    test_ensure_media_item_self_heals_stale()
    test_resolve_media_for_add_not_found()
    test_resolve_media_for_add_single_tv_hit()
    test_resolve_media_for_add_collision_returns_pick()
    test_resolve_media_for_add_uses_existing_item()
    test_resolve_media_for_add_stale_tv_override()
    print("media resolve tests passed")
