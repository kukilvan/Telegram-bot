"""The export through the core (spec 3 of stage 7.1): the CSV list and the JSON of everything on a prepared database, the
pure formats of `export_rows` (BOM, `;`, `\\r\\n`, quoting, the `'` guard, the dates on the owner's clock), the parts left
out on purpose, an empty database, and one read session for each file."""

import asyncio
import dataclasses
import json
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.tracker import export_rows
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.export_rows import ListLine
from app.tracker.models import (
    DeliveryItem, EpisodeRecord, Event, ExternalId, GamePlatformRecord, InboxReason, InboxRecord, InboxState,
    MovieRecord, PartRecord, PriceRecord, SeasonRecord, SettingRecord, SourceSnapshot, Title, TitleKind, TitleStatus,
)

MOSCOW = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 10, 29, 22, 30, tzinfo=timezone.utc)  # Moscow is already on the 30th: 01:30
BOM = b"\xef\xbb\xbf"


def run(coroutine):
    return asyncio.run(coroutine)


class FakeSender:
    async def send(self, message, actions=()):
        pass


@pytest.fixture
def session_factory(tmp_path):
    return create_session_factory(f"sqlite:///{(tmp_path / 'tracker.db').as_posix()}")


@pytest.fixture
def tracker(session_factory):
    return Tracker(session_factory, clock=lambda: NOW, sender=FakeSender(), default_tz=MOSCOW)


def title(kind, name, status=TitleStatus.WANT, *, original=None, year=None, score=None, added=None, changed=None, **more):
    moment = added or datetime(2026, 10, 1, 12, 0)
    return Title(
        kind=kind, name=name, original_name=original if original is not None else name, year=year, genres=more.pop("genres", []),
        poster_path=more.pop("poster_path", None), overview=more.pop("overview", None), status=status, tracking_enabled=True,
        added_at=moment, status_changed_at=changed or moment, score=score, **more,
    )


def lines(content: bytes) -> list[str]:
    assert content.startswith(BOM)
    return content[len(BOM):].decode("utf-8").split("\r\n")


# --- the pure formats ----------------------------------------------------------------------------------------


def line(**changes) -> ListLine:
    base = ListLine("Дюна", "Dune", "Фильм", "Хочу", None, 2021, datetime(2026, 10, 29, 22, 30), None)
    return base._replace(**changes)


def test_csv_has_bom_separator_line_ends_and_the_header():
    content = export_rows.csv_bytes([line()], MOSCOW)
    assert content.startswith(BOM)
    text = content[len(BOM):].decode("utf-8")
    assert text == (
        "Название;Оригинальное название;Тип;Статус;Оценка;Год;Добавлен;Завершён\r\n"
        "Дюна;Dune;Фильм;Хочу;;2021;30.10.2026;\r\n"
    )


def test_an_empty_list_is_the_header_only():
    assert lines(export_rows.csv_bytes([], MOSCOW)) == [
        "Название;Оригинальное название;Тип;Статус;Оценка;Год;Добавлен;Завершён", "",
    ]


def test_the_original_name_is_empty_when_equal_and_the_year_when_unknown():
    row = lines(export_rows.csv_bytes([line(original_name="Дюна", year=None)], MOSCOW))[1]
    assert row == "Дюна;;Фильм;Хочу;;;30.10.2026;"


def test_quoting_of_separator_quote_and_line_break():
    row = export_rows.csv_bytes([line(name='А;Б "В"\nГ')], MOSCOW)[len(BOM):].decode("utf-8")
    assert '"А;Б ""В""\nГ";Dune;' in row


@pytest.mark.parametrize("start", ["=", "+", "-", "@", "\t", "\r"])
def test_a_cell_that_may_be_a_formula_gets_a_quote(start):
    assert export_rows.guard(f"{start}1+1") == f"'{start}1+1"
    content = export_rows.csv_bytes([line(name=f"{start}cmd", original_name=f"{start}orig")], MOSCOW).decode("utf-8-sig")
    assert f"'{start}cmd" in content and f"'{start}orig" in content


def test_ordinary_cells_are_not_guarded():
    assert export_rows.guard("Дюна 2") == "Дюна 2"
    assert export_rows.guard("8+") == "8+" and export_rows.guard("7−") == "7−"  # the minus sign of a score is U+2212


def test_the_dates_are_on_the_owner_clock():
    # 22:30 UTC on the 29th is the 30th in Moscow
    row = lines(export_rows.csv_bytes([line(finished_at=datetime(2026, 12, 31, 21, 30))], MOSCOW))[1]
    assert row.endswith(";30.10.2026;01.01.2027")


def test_json_values_are_iso_with_the_offset_and_days():
    assert export_rows.moment_text(datetime(2026, 11, 7, 13, 21, 5), MOSCOW) == "2026-11-07T16:21:05+03:00"
    assert export_rows.moment_text(None, MOSCOW) is None
    assert export_rows.day_text(date(2026, 11, 7)) == "2026-11-07" and export_rows.day_text(None) is None
    assert export_rows.zone_name(MOSCOW) == "Europe/Moscow" and export_rows.zone_name(timezone.utc) == "UTC"


def test_json_bytes_are_utf8_without_bom_and_readable():
    content = export_rows.json_bytes({"имя": "Одни из нас"})
    assert not content.startswith(BOM)
    assert "Одни из нас".encode("utf-8") in content and b"\n  " in content


# --- the CSV list through the core ---------------------------------------------------------------------------


def test_csv_lists_every_title_in_the_order_of_the_list_archive_included(tracker, session_factory):
    with session_factory() as session:
        session.add_all([
            title(TitleKind.MOVIE, "яблоко", original="Apple", year=2020),
            title(TitleKind.MOVIE, "Ёж", status=TitleStatus.WATCHED, original="Hedgehog", score=28,
                  changed=datetime(2026, 10, 20, 9, 0)),
            title(TitleKind.GAME, "Арбуз", status=TitleStatus.COMPLETED, score=30, changed=datetime(2026, 10, 25, 21, 30)),
            title(TitleKind.ANIME, "Бросил", status=TitleStatus.DROPPED, changed=datetime(2026, 10, 26, 9, 0)),
            title(TitleKind.SERIES, "Ждём", status=TitleStatus.WAITING, score=12, changed=datetime(2026, 10, 27, 9, 0)),
        ])
        session.commit()
    file = run(tracker.export_list())
    assert file.name == "tracker-list-2026-10-30.csv" and file.media_type == "text/csv; charset=utf-8"
    rows = lines(file.content)[1:-1]
    # «по названию»: case and «ё» do not matter, Cyrillic in alphabetical order
    assert [row.split(";")[0] for row in rows] == ["Арбуз", "Бросил", "Ёж", "Ждём", "яблоко"]
    by_name = {row.split(";")[0]: row.split(";") for row in rows}
    assert by_name["Арбуз"][2:] == ["Игра", "Пройдено", "10", "", "01.10.2026", "26.10.2026"]  # 21:30 UTC is past midnight in Moscow
    assert by_name["Бросил"][2:] == ["Аниме", "Бросил", "", "", "01.10.2026", "26.10.2026"]
    assert by_name["Ёж"][1:] == ["Hedgehog", "Фильм", "Просмотрено", "9+", "", "01.10.2026", "20.10.2026"]
    # a series that is waiting has no marked season: its score is not shown and it has no finish date
    assert by_name["Ждём"][2:] == ["Сериал", "Жду", "", "", "01.10.2026", ""]
    assert by_name["яблоко"][1:] == ["Apple", "Фильм", "Хочу", "", "2020", "01.10.2026", ""]


def test_csv_shows_the_average_of_the_seasons_as_the_card_does(tracker, session_factory):
    with session_factory() as session:
        show = title(TitleKind.SERIES, "Сериал", status=TitleStatus.IN_PROGRESS)
        session.add(show)
        session.flush()
        session.add_all([
            SeasonRecord(title_id=show.id, number=1, name="Сезон 1", episode_count=2, watched=True, score=27),
            SeasonRecord(title_id=show.id, number=2, name="Сезон 2", episode_count=2, watched=True, score=24),
            SeasonRecord(title_id=show.id, number=3, name="Сезон 3", episode_count=2, watched=False, score=3),
        ])
        session.commit()
    row = lines((run(tracker.export_list())).content)[1].split(";")
    assert row[4] == "9−" or row[4] == "8+"  # (27 + 24) / 2 = 25.5: the higher step, 26 = «9−»
    assert row[4] == "9−"
    assert row[7] == ""  # «В процессе» is no final status


def test_an_empty_database_gives_the_header_and_empty_lists(tracker):
    assert lines((run(tracker.export_list())).content) == [
        "Название;Оригинальное название;Тип;Статус;Оценка;Год;Добавлен;Завершён", "",
    ]
    document = json.loads((run(tracker.export_all())).content)
    assert document["titles"] == [] and document["inbox"] == [] and document["settings"] == {}
    assert document["format"] == "release-tracker-export" and document["version"] == 1


# --- the JSON through the core -------------------------------------------------------------------------------


def prepared(session_factory):
    """A movie, a series with a part, an anime with parts and a franchise movie, a game with platforms, an expansion of
    it and a price history, the working state that must stay out, the settings and the inbox."""
    with session_factory() as session:
        movie = title(TitleKind.MOVIE, "Дюна", status=TitleStatus.WATCHED, original="Dune", year=2021, score=28,
                      genres=["Фантастика"], overview="Песок.", poster_path="/dune.jpg",
                      added=datetime(2026, 10, 20, 16, 2, 11), changed=datetime(2026, 10, 28, 18, 40))
        series = title(TitleKind.SERIES, "Одни из нас", status=TitleStatus.IN_PROGRESS, original="The Last of Us",
                       year=2023, genres=["Драма"], restored_at=datetime(2026, 10, 30, 6, 0), failure_notified_at=datetime(2026, 10, 31, 6, 0))
        anime = title(TitleKind.ANIME, "Магическая битва", original="Jujutsu Kaisen", year=2020)
        base = title(TitleKind.GAME, "Ведьмак 3", original="The Witcher 3", year=2015)
        expansion = title(TitleKind.GAME, "Кровь и вино", original="Blood and Wine", year=2016)
        orphan = title(TitleKind.GAME, "Дополнение без игры", original="Orphan")
        session.add_all([movie, series, anime, base, expansion, orphan])
        session.flush()
        session.add_all([
            ExternalId(title_id=movie.id, source="tmdb_movie", external_id="438631", role="primary"),
            ExternalId(title_id=series.id, source="tmdb_tv", external_id="100088", role="primary"),
            ExternalId(title_id=anime.id, source="shikimori", external_id="40748", role="primary"),
            ExternalId(title_id=base.id, source="igdb", external_id="1942", role="primary"),
            ExternalId(title_id=expansion.id, source="igdb", external_id="2000", role="primary"),
            ExternalId(title_id=orphan.id, source="igdb", external_id="2001", role="primary"),
        ])
        s1 = SeasonRecord(title_id=series.id, number=1, name="Сезон 1", episode_count=2, watched=True, score=24)
        a1 = SeasonRecord(title_id=anime.id, number=1, name="Сезон 1", episode_count=24, watched=False, score=None)
        session.add_all([s1, a1])
        session.flush()
        session.add_all([
            EpisodeRecord(season_id=s1.id, number=2, air_at=datetime(2023, 1, 23, 1, 0)),
            EpisodeRecord(season_id=s1.id, number=1, air_at=datetime(2023, 1, 15, 1, 0)),
            EpisodeRecord(season_id=a1.id, number=1, air_at=None),
            PartRecord(title_id=anime.id, season_id=a1.id, number=1, first_episode=1, episode_count=12,
                       shikimori_id="40748", mal_id="40748", anilist_id="113415"),
            PartRecord(title_id=anime.id, season_id=a1.id, number=2, first_episode=13, episode_count=12,
                       shikimori_id="51009", mal_id=None, anilist_id=None),
            MovieRecord(title_id=anime.id, name="Фильм 0", aired_on=date(2021, 12, 24), released=True,
                        shikimori_id="48561", mal_id=None, anilist_id=None),
            GamePlatformRecord(title_id=base.id, platform="pc", playing=True),
            GamePlatformRecord(title_id=base.id, platform="ps5", playing=False),
            PriceRecord(title_id=base.id, seen_at=datetime(2026, 10, 2, 9, 0), appid="292030", country="RU", currency="{} руб.",
                        final=79900, original=None, pct=0),
            PriceRecord(title_id=base.id, seen_at=datetime(2026, 10, 9, 9, 0), appid="292030", country="RU", currency="{} руб.",
                        final=39900, original=79900, pct=50),
            # the working state that is not exported
            SourceSnapshot(title_id=expansion.id, source="igdb", observed_at=datetime(2026, 10, 3, 9, 0),
                           state={"expansion": "expansion", "parent": {"id": "1942", "name": "The Witcher 3: Wild Hunt"}}),
            SourceSnapshot(title_id=orphan.id, source="igdb", observed_at=datetime(2026, 10, 3, 9, 0),
                           state={"expansion": "standalone", "parent": {"id": "999", "name": "Game IGDB Knows"}}),
            SourceSnapshot(title_id=movie.id, source="tmdb_movie", observed_at=datetime(2026, 10, 3, 9, 0),
                           state={"secret_working_state": 1}),
            SettingRecord(key="summary_at", value="15:00"),
            SettingRecord(key="workdays", value=[0, 1, 2]),
        ])
        event = Event(type="movie_released", title_id=movie.id, payload={"text": "event text"}, dedup_key="k1",
                      detected_at=datetime(2026, 10, 4, 9, 0))
        session.add(event)
        session.flush()
        session.add(DeliveryItem(event_id=event.id, status="pending", attempts=0, created_at=datetime(2026, 10, 4, 9, 0)))
        session.add_all([
            InboxRecord(state=InboxState.INBOX, reason=InboxReason.NOT_FOUND, kind=None, text="старый пост", media=None,
                        bold=["Старый"], links=[], post_url=None, forwarded=True, media_group_id="g1", query="Старый",
                        offers=[{"x": 1}], received_at=datetime(2026, 11, 5, 7, 12), last_message_at=datetime(2026, 11, 5, 7, 13),
                        moved_at=datetime(2026, 11, 5, 19, 12)),
            InboxRecord(state=InboxState.WAITING, reason=None, kind=TitleKind.MOVIE, text="новый пост", bold=[],
                        links=["https://example.test/a"], post_url="https://t.me/c/1", forwarded=False, media_group_id=None,
                        query="", offers=[], received_at=datetime(2026, 11, 6, 7, 12), last_message_at=datetime(2026, 11, 6, 7, 12),
                        moved_at=None),
        ])
        session.commit()


def test_json_has_the_shape_of_version_one(tracker, session_factory):
    prepared(session_factory)
    file = run(tracker.export_all())
    assert file.name == "tracker-all-2026-10-30.json" and file.media_type == "application/json"
    assert not file.content.startswith(BOM) and "Одни из нас".encode("utf-8") in file.content  # not \u-escaped
    doc = json.loads(file.content)
    assert list(doc) == ["format", "version", "exported_at", "time_zone", "database_revision", "titles", "settings", "inbox"]
    assert doc["exported_at"] == "2026-10-30T01:30:00+03:00" and doc["time_zone"] == "Europe/Moscow"
    assert doc["database_revision"] == "0014"
    assert [t["name"] for t in doc["titles"]] == ["Дюна", "Одни из нас", "Магическая битва", "Ведьмак 3", "Кровь и вино", "Дополнение без игры"]
    movie, series, anime, base, expansion, orphan = doc["titles"]
    assert list(movie) == [
        "id", "kind", "name", "original_name", "year", "genres", "overview", "poster", "status", "status_label", "score",
        "tracking", "added_at", "status_changed_at", "restored_at", "sources", "seasons", "franchise_movies", "platforms",
        "expansion_of", "price_history",
    ]
    assert movie["kind"] == "movie" and movie["status"] == "watched" and movie["status_label"] == "Просмотрено"
    assert movie["score"] == "9+" and movie["genres"] == ["Фантастика"] and movie["poster"] == "/dune.jpg"
    assert movie["added_at"] == "2026-10-20T19:02:11+03:00" and movie["status_changed_at"] == "2026-10-28T21:40:00+03:00"
    assert movie["restored_at"] is None and movie["tracking"] is True
    assert movie["sources"] == [{"source": "tmdb_movie", "id": "438631"}]
    assert movie["seasons"] == [] and movie["platforms"] == [] and movie["price_history"] == [] and movie["expansion_of"] is None
    assert series["restored_at"] == "2026-10-30T09:00:00+03:00" and series["score"] is None
    assert series["seasons"] == [{
        "number": 1, "name": "Сезон 1", "episode_count": 2, "watched": True, "score": "8",
        "episodes": [{"number": 1, "air_at": "2023-01-15T04:00:00+03:00"}, {"number": 2, "air_at": "2023-01-23T04:00:00+03:00"}],
        "parts": [],
    }]
    assert anime["seasons"][0]["episodes"] == [{"number": 1, "air_at": None}]
    assert anime["seasons"][0]["parts"] == [
        {"number": 1, "first_episode": 1, "episode_count": 12}, {"number": 2, "first_episode": 13, "episode_count": 12},
    ]
    assert anime["franchise_movies"] == [{"name": "Фильм 0", "aired_on": "2021-12-24", "released": True}]
    assert base["platforms"] == [{"platform": "pc", "playing": True}, {"platform": "ps5", "playing": False}]
    assert base["price_history"] == [
        {"seen_at": "2026-10-02T12:00:00+03:00", "country": "RU", "currency": "{} руб.", "final": 79900, "original": None, "pct": 0},
        {"seen_at": "2026-10-09T12:00:00+03:00", "country": "RU", "currency": "{} руб.", "final": 39900, "original": 79900, "pct": 50},
    ]
    # the base game is in the list: its name there, as the card shows it; one the list lacks keeps the IGDB name
    assert expansion["expansion_of"] == "Ведьмак 3" and orphan["expansion_of"] == "Game IGDB Knows" and base["expansion_of"] is None
    assert doc["settings"] == {"summary_at": "15:00", "workdays": [0, 1, 2]}


def test_json_leaves_out_the_working_state(tracker, session_factory):
    prepared(session_factory)
    text = (run(tracker.export_all())).content.decode("utf-8")
    for left_out in ("secret_working_state", "event text", "movie_released", "delivery", "failure_notified", "observed_at",
                     "next_check_at", "shikimori_id", "mal_id", "anilist_id", "TELEGRAM", "TMDB_API_KEY"):
        assert left_out not in text
    doc = json.loads(text)
    assert not {"events", "delivery_queue", "source_snapshots"} & set(doc)
    assert not {"failure_notified_at", "state", "snapshots"} & set(doc["titles"][0])


def test_the_inbox_is_newest_first_without_the_internal_fields(tracker, session_factory):
    prepared(session_factory)
    inbox = json.loads((run(tracker.export_all())).content)["inbox"]
    assert [item["text"] for item in inbox] == ["новый пост", "старый пост"]
    assert inbox[0] == {
        "id": 2, "state": "waiting", "reason": None, "kind": "movie", "text": "новый пост", "links": ["https://example.test/a"],
        "post_url": "https://t.me/c/1", "received_at": "2026-11-06T10:12:00+03:00", "moved_at": None,
    }
    assert inbox[1]["state"] == "inbox" and inbox[1]["reason"] == "not_found" and inbox[1]["moved_at"] == "2026-11-05T22:12:00+03:00"
    for item in inbox:
        assert not {"bold", "media", "media_group_id", "forwarded", "query", "offers", "last_message_at"} & set(item)


def test_the_zone_of_settings_decides_the_clock(tracker, session_factory):
    with session_factory() as session:
        session.add(title(TitleKind.MOVIE, "Дюна", added=datetime(2026, 10, 29, 22, 30)))
        session.add(SettingRecord(key="timezone", value="Asia/Vladivostok"))
        session.commit()
    csv_file = run(tracker.export_list())
    assert csv_file.name == "tracker-list-2026-10-30.csv" and lines(csv_file.content)[1].split(";")[6] == "30.10.2026"
    doc = json.loads((run(tracker.export_all())).content)
    assert doc["time_zone"] == "Asia/Vladivostok" and doc["titles"][0]["added_at"] == "2026-10-30T08:30:00+10:00"


# --- one read session ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["export_list", "export_all"])
def test_each_file_is_read_in_one_session(tracker, session_factory, method):
    prepared(session_factory)
    opened = []
    ctx = tracker._exports.ctx

    def counting():
        session = session_factory()
        opened.append(session)
        return session

    tracker._exports.ctx = dataclasses.replace(ctx, session_factory=counting)
    run(getattr(tracker, method)())
    assert len(opened) == 1


def test_the_picture_does_not_change_while_a_file_is_built(tracker, session_factory):
    """Something committed by another writer after the export began reading does not show in the rest of the same file."""
    prepared(session_factory)
    from app.tracker import export_all

    real = export_all._inbox

    def inbox_after_a_change(session, tz):
        with session_factory() as other:  # another writer, between two reads of the export
            other.add(InboxRecord(state=InboxState.INBOX, reason=InboxReason.NOT_FOUND, text="после начала", bold=[], links=[],
                                  forwarded=False, query="", offers=[], received_at=datetime(2026, 11, 7, 7, 0),
                                  last_message_at=datetime(2026, 11, 7, 7, 0)))
            other.commit()
        return real(session, tz)

    export_all._inbox = inbox_after_a_change
    try:
        during = json.loads((run(tracker.export_all())).content)["inbox"]
    finally:
        export_all._inbox = real
    assert [item["text"] for item in during] == ["новый пост", "старый пост"]
    assert "после начала" in [item["text"] for item in json.loads((run(tracker.export_all())).content)["inbox"]]
