"""Tracker core: an anime franchise as one title (add, card, ids, watched seasons).

Driven through the facade only: fake clock, the real Shikimori adapter over the saved real answers of the four
franchises of the audit, in-memory SQLite. No network.
"""

import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from anime_fakes import FakeAniList, FakeShikimori
from app.tracker.actions import DELETE, card_actions
from app.tracker.cards import format_card
from app.tracker.core import Tracker, TitleNotFound
from app.tracker.db import create_session_factory
from app.tracker.models import ExternalId, MovieRecord, PartRecord, SeasonRecord, SourceSnapshot, Title
from app.tracker.sources.shikimori_anime import ShikimoriAnimeSource

T0 = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
ONE_PIECE, JJK, KUSURIYA, ABYSS = "21", "40748", "54492", "34599"


class FakeSender:
    async def send(self, message, actions=()):
        pass


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def shikimori():
    return FakeShikimori()


@pytest.fixture
def anilist():
    return FakeAniList()


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def tracker(session_factory, shikimori, anilist):
    return Tracker(
        session_factory,
        clock=lambda: T0,
        sender=FakeSender(),
        sources={"anime": ShikimoriAnimeSource(shikimori, anilist)},
    )


def add(tracker, external_id):
    return run(tracker.add_title("anime", external_id))


def card(tracker, external_id):
    return format_card(tracker.title_card(add(tracker, external_id).title_id))


# --- adding a franchise --------------------------------------------------------------------------


def test_the_franchise_is_one_title_named_after_its_first_season(tracker):
    result = add(tracker, JJK)

    [entry] = tracker.list_titles()
    assert result.created is True
    assert (entry.kind, entry.name, entry.year, entry.status) == ("anime", "Магическая битва", 2020, "want")


def test_the_title_is_known_by_its_first_season_and_keeps_the_franchise_key_in_its_state(tracker, session_factory):
    add(tracker, "48561")  # picked through the prequel film

    with session_factory() as s:
        [external] = list(s.scalars(select(ExternalId)))
        [snapshot] = list(s.scalars(select(SourceSnapshot)))
    assert (external.source, external.external_id, external.role) == ("shikimori", JJK, "primary")
    assert (snapshot.source, snapshot.state) == ("shikimori", {"franchise": "jujutsu_kaisen"})


def test_two_unconnected_chains_of_one_franchise_are_two_titles(tracker, shikimori, session_factory):
    other = dict(shikimori.by_id["54492"], id="9001", malId="9001", related=[])  # same franchise key, no relation
    shikimori.by_id["9001"] = other

    first = add(tracker, KUSURIYA)
    second = add(tracker, "9001")

    assert (first.created, second.created) == (True, True)
    assert first.title_id != second.title_id


def test_another_entry_of_the_same_franchise_opens_the_same_title(tracker, session_factory):
    first = add(tracker, JJK)
    from_film = add(tracker, "48561")
    from_last_season = add(tracker, "63824")

    assert (from_film.created, from_last_season.created) == (False, False)
    assert from_film.title_id == from_last_season.title_id == first.title_id
    with session_factory() as s:
        assert len(list(s.scalars(select(Title)))) == 1
        assert len(list(s.scalars(select(PartRecord)))) == 4  # the seasons are not stored twice


def test_an_unknown_entry_is_reported_and_nothing_is_stored(tracker):
    with pytest.raises(TitleNotFound):
        add(tracker, "999999")

    assert tracker.list_titles() == []


def test_shikimori_failure_stores_nothing(tracker, shikimori):
    shikimori.broken = True

    with pytest.raises(ConnectionError):
        add(tracker, JJK)

    assert tracker.list_titles() == []


def test_the_search_offers_one_suggestion_per_franchise(tracker):
    suggestions = run(tracker.search("anime", "магическая битва"))

    assert [(s.kind, s.external_id, s.title) for s in suggestions if s.external_id == JJK] == [
        ("anime", JJK, "Магическая битва")
    ]


# --- what the card says: the audit's franchises ---------------------------------------------------


def test_one_piece_card_is_one_season_with_an_unknown_total(tracker):
    text = card(tracker, ONE_PIECE)

    assert text.startswith("🎌 Аниме · Хочу\nВан-Пис · One Piece")
    assert "Сезон 1: вышло 1180 из ?, следующая — вс, 25 окт" in text
    assert "Сезон 2" not in text
    assert "Фильмы франшизы" not in text


def test_jujutsu_kaisen_card_has_four_seasons_and_the_film_apart(tracker):
    text = card(tracker, JJK)

    assert "Сезон 3: вышло 12 из 12" in text
    assert "Сезон 4 анонсирован, дата не объявлена" in text
    assert "Фильмы франшизы: Магическая битва 0. Фильм (2021)" in text
    assert [s.number for s in tracker.watchable_seasons(1)] == [1, 2, 3]  # season 4 has nothing to watch yet


def test_kusuriya_card_names_the_part_of_the_third_season(tracker):
    text = card(tracker, KUSURIYA)

    assert "Сезон 3, часть 1: вышло 4 из 12, следующая — пт, 30 окт" in text
    assert "анонсирован" not in text  # part 2 is a part of season 3, not a new season
    assert "Фильмы франшизы" not in text


def test_kusuriya_card_names_the_second_part_once_the_first_one_is_out(tracker, shikimori):
    shikimori.by_id["61987"].update(episodesAired=12, nextEpisodeAt=None, status="released")

    text = card(tracker, KUSURIYA)

    assert "Сезон 3, часть 1: вышло 12 из 12; часть 2 — с 1 апреля" in text


def test_made_in_abyss_card_has_two_seasons_and_the_films(tracker):
    text = card(tracker, ABYSS)

    assert "Сезон 2: вышло 12 из 12" in text
    assert "Сезон 3" not in text
    films = next(line for line in text.splitlines() if line.startswith("Фильмы франшизы"))
    assert films.startswith("Фильмы франшизы: Созданный в Бездне: Начало путешествия (2019), ")
    assert films.endswith("Созданный в бездне: Тайна пробуждения. Часть 2 — анонсирован")
    assert "Тайна пробуждения (2026)," in films


def test_a_long_list_of_films_shows_the_latest(tracker, shikimori):
    for index in range(8):
        shikimori.by_id[f"9{index}"] = {
            **shikimori.by_id["37514"], "id": f"9{index}", "malId": f"9{index}", "name": f"Film {index}",
            "russian": f"Фильм {index}", "airedOn": {"date": f"20{10 + index}-01-01"},
            "related": [{"relationKind": "prequel", "relationText": "", "anime": {"id": ONE_PIECE, "kind": "tv"}}],
        }
        shikimori.by_id[ONE_PIECE]["related"].append(
            {"relationKind": "sequel", "relationText": "", "anime": {"id": f"9{index}", "kind": "movie"}}
        )

    text = card(tracker, ONE_PIECE)

    assert "Фильмы франшизы (8), последние: Фильм 3 (2013), Фильм 4 (2014), Фильм 5 (2015), Фильм 6 (2016), Фильм 7 (2017)" in text


# --- ids: every season and part has its own, nothing twice ----------------------------------------


def stored_parts(session_factory):
    with session_factory() as s:
        return [
            (p.number, p.first_episode, p.episode_count, p.shikimori_id, p.mal_id, p.anilist_id, season.number)
            for p, season in s.execute(
                select(PartRecord, SeasonRecord).join(SeasonRecord, SeasonRecord.id == PartRecord.season_id).order_by(PartRecord.id)
            )
        ]


def test_every_season_and_part_stores_its_shikimori_mal_and_anilist_ids(tracker, session_factory):
    add(tracker, KUSURIYA)

    assert stored_parts(session_factory) == [
        (1, 1, 24, "54492", "54492", "154492", 1),
        (1, 1, 24, "58514", "58514", "158514", 2),
        (1, 1, 12, "61987", "61987", "161987", 3),
        (2, 13, 12, "62841", "62841", "162841", 3),
    ]


def test_films_store_their_ids_too(tracker, session_factory):
    add(tracker, ABYSS)

    with session_factory() as s:
        films = [(m.name, m.shikimori_id, m.mal_id, m.anilist_id, m.released) for m in s.scalars(select(MovieRecord).order_by(MovieRecord.id))]
    assert films[0] == ("Созданный в Бездне: Начало путешествия", "37514", "37514", "137514", True)
    assert [f[1] for f in films] == ["37514", "37515", "36862", "54250", "65248"]
    assert films[-1][4] is False


def test_the_same_id_is_never_stored_twice_for_a_title(tracker, session_factory, anilist):
    anilist.ids = {54492: 5, 58514: 5, 61987: 5, 62841: 6}  # AniList holds three Shikimori entries as one record

    add(tracker, KUSURIYA)

    anilist_ids = [p[5] for p in stored_parts(session_factory)]
    assert anilist_ids == ["5", None, None, "6"]


def test_the_database_itself_refuses_a_second_row_for_the_same_id(tracker, session_factory):
    add(tracker, KUSURIYA)

    with session_factory() as s:
        part = s.scalars(select(PartRecord)).first()
        s.add(PartRecord(title_id=part.title_id, season_id=part.season_id, number=9, first_episode=99,
                         episode_count=None, shikimori_id=part.shikimori_id, mal_id=None, anilist_id=None))
        with pytest.raises(IntegrityError):
            s.commit()


def test_anilist_failure_does_not_stop_the_add_and_leaves_its_ids_empty(tracker, session_factory, anilist):
    anilist.broken = True

    result = add(tracker, KUSURIYA)

    assert result.created is True
    assert [p[5] for p in stored_parts(session_factory)] == [None, None, None, None]
    assert [p[3] for p in stored_parts(session_factory)] == ["54492", "58514", "61987", "62841"]


# --- watched seasons -----------------------------------------------------------------------------


def test_the_seasons_offered_for_marking_are_those_with_a_released_episode(tracker):
    jjk = add(tracker, JJK).title_id
    kusuriya = add(tracker, KUSURIYA).title_id

    assert [s.number for s in tracker.watchable_seasons(jjk)] == [1, 2, 3]
    assert [s.number for s in tracker.watchable_seasons(kusuriya)] == [1, 2, 3]  # season 3 has begun


def test_a_franchise_of_films_alone_has_no_seasons_to_mark_and_no_button_for_it(tracker, shikimori):
    film = dict(shikimori.by_id["37514"], id="8001", malId="8001", related=[])
    shikimori.by_id["8001"] = film

    title = add(tracker, "8001").title_id

    assert tracker.watchable_seasons(title) == []
    assert "Сезонов пока нет" in format_card(tracker.title_card(title))
    assert [a.name for a in card_actions(tracker.title_card(title))] == [DELETE]  # only «Удалить»


def test_a_part_without_a_count_and_nothing_out_does_not_overlap_the_next_one(tracker, shikimori, session_factory):
    shikimori.by_id["61987"].update(episodes=0, episodesAired=0, nextEpisodeAt=None, status="anons")

    add(tracker, KUSURIYA)

    firsts = [p[1] for p in stored_parts(session_factory)]
    assert firsts[2] < firsts[3]  # the two parts of season 3 start at different episodes


def test_marking_every_released_season_makes_the_title_wait_for_the_next_one(tracker):
    title = add(tracker, JJK).title_id

    for number in (1, 2, 3):
        run(tracker.set_season_watched(title, number, True))

    assert tracker.title_card(title).status == "waiting"
    assert "Просмотрены сезоны: 1, 2, 3" in format_card(tracker.title_card(title))


def test_some_seasons_marked_make_the_anime_in_progress(tracker):
    title = add(tracker, KUSURIYA).title_id

    run(tracker.set_season_watched(title, 1, True))
    run(tracker.set_season_watched(title, 2, True))

    assert tracker.title_card(title).status == "in_progress"  # season 3 is on air and not watched


def test_the_mark_belongs_to_the_season_and_covers_its_parts(tracker):
    title = add(tracker, KUSURIYA).title_id

    run(tracker.set_season_watched(title, 3, True))

    assert [(s.number, s.watched) for s in tracker.watchable_seasons(title)] == [(1, False), (2, False), (3, True)]
