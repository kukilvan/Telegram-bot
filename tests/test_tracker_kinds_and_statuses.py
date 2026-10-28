"""Kind and statuses are enums, a kind's properties live in one table, and nothing in `app/` spells them as raw strings."""

import ast
import pathlib
from datetime import datetime

import pytest
from sqlalchemy import select, text

from app.tracker import anime_events, cards, movie_events, series_events
from app.tracker.actions import card_actions
from app.tracker.db import create_session_factory
from app.tracker.kinds import KINDS, is_seasonal, seasonal_kinds
from app.tracker.models import ARCHIVE_STATUSES, DeliveryItem, DeliveryStatus, Title, TitleKind, TitleStatus

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
# "watched" is left out: it is also the name of the «Посмотрел» button action (`actions.WATCHED`), which is no status
RAW_WORDS = {"movie", "series", "anime", "pending", "delivered", "want", "in_progress", "waiting", "to_finish", "dropped"}
# the enums themselves may spell the words (migrations are skipped by the test: they wrote the data)
ALLOWED_FILES = {pathlib.PurePath("tracker/models.py")}
# words of Shikimori's own response, not kinds of title of ours: the `kind` of a catalogue entry and the `anime` field of a relation
SHIKIMORI_WORDS = {(pathlib.PurePath("tracker/sources/shikimori_anime.py"), word) for word in ("movie", "anime")}


def test_the_enums_keep_the_values_the_database_already_holds():
    assert [k.value for k in TitleKind] == ["movie", "series", "anime"]
    assert [s.value for s in TitleStatus] == ["want", "in_progress", "waiting", "to_finish", "watched", "dropped"]
    assert [s.value for s in DeliveryStatus] == ["pending", "delivered"]


@pytest.mark.parametrize("kind", list(TitleKind))
def test_every_kind_has_every_property_filled(kind):
    info = KINDS[kind]
    assert info.label and info.plural and info.icon and info.ask_name and info.source_name
    assert isinstance(info.seasonal, bool)


def test_the_table_has_no_kind_that_does_not_exist():
    assert set(KINDS) == set(TitleKind)


@pytest.mark.parametrize("status", list(TitleStatus))
def test_every_status_has_a_label(status):
    assert cards.STATUS_LABELS[status]


def test_the_table_of_status_labels_has_no_status_that_does_not_exist():
    assert set(cards.STATUS_LABELS) == set(TitleStatus)


def test_seasonal_kinds_are_series_and_anime():
    assert seasonal_kinds() == (TitleKind.SERIES, TitleKind.ANIME)
    assert is_seasonal(TitleKind.ANIME) and not is_seasonal(TitleKind.MOVIE)


def test_the_icon_of_the_messages_is_the_icon_of_the_kind():
    assert movie_events.message_released("Дюна").startswith(KINDS[TitleKind.MOVIE].icon)
    assert series_events.SERIES.icon == KINDS[TitleKind.SERIES].icon
    assert anime_events.flavor(None).icon == KINDS[TitleKind.ANIME].icon


def test_the_key_prefixes_of_the_events_are_the_kinds_so_stored_keys_stay_valid():
    assert series_events.SERIES.key_prefix == "series"
    assert anime_events.flavor(None).key_prefix == "anime"


def test_the_card_header_comes_from_the_table():
    card = cards.TitleCard(1, TitleKind.ANIME, "Название", "", None, [], TitleStatus.WAITING, seasons=None)
    assert cards.format_card(card).splitlines()[0] == f"{KINDS[TitleKind.ANIME].icon} {KINDS[TitleKind.ANIME].label} · Жду"


def test_a_watched_movie_card_offers_only_delete_and_a_wanted_one_also_watched():
    watched = cards.TitleCard(1, TitleKind.MOVIE, "Ф", "", None, [], TitleStatus.WATCHED)
    wanted = cards.TitleCard(1, TitleKind.MOVIE, "Ф", "", None, [], TitleStatus.WANT)
    assert [a.name for a in card_actions(watched)] == ["delete"]
    assert [a.name for a in card_actions(wanted)] == ["watched", "delete"]


def test_a_card_of_a_seasonal_kind_has_no_watched_button_for_the_whole_title():
    series = cards.TitleCard(1, TitleKind.SERIES, "С", "", None, [], TitleStatus.WANT)
    assert [a.name for a in card_actions(series)] == ["delete"]  # no seasons yet: nothing to mark


def test_the_archive_is_the_final_statuses():
    assert ARCHIVE_STATUSES == {TitleStatus.WATCHED, TitleStatus.DROPPED}


def test_dropped_is_a_status_the_season_marks_never_rewrite():
    from app.tracker import progress

    assert TitleStatus.DROPPED not in progress.AUTOMATIC_STATUSES


def test_a_dropped_card_in_the_bot_offers_no_watched_button():
    movie = cards.TitleCard(1, TitleKind.MOVIE, "Ф", "", None, [], TitleStatus.DROPPED)
    assert [a.name for a in card_actions(movie)] == ["delete"]
    assert cards.format_card(movie).splitlines()[0].endswith("· Бросил")


def test_columns_hand_out_enum_members():
    assert Title.__table__.c.kind.type.python_type is TitleKind
    assert Title.__table__.c.status.type.python_type is TitleStatus
    assert DeliveryItem.__table__.c.status.type.python_type is DeliveryStatus


def _raw_words_in(path: pathlib.Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in RAW_WORDS:
            yield node.lineno, node.value


def test_no_raw_kind_or_queue_status_strings_outside_the_enums_and_migrations():
    offenders = []
    for path in APP.rglob("*.py"):
        relative = path.relative_to(APP)
        if "migrations" in relative.parts or relative in ALLOWED_FILES:
            continue
        for line, word in _raw_words_in(path):
            if (relative, word) not in SHIKIMORI_WORDS:
                offenders.append(f"{relative}:{line}: {word!r}")
    assert offenders == []


def test_the_database_keeps_plain_text_and_hands_back_members():
    factory = create_session_factory("sqlite://")
    now = datetime(2026, 1, 1)
    with factory() as session:
        session.execute(
            text(
                "INSERT INTO titles (kind, name, original_name, genres, status, tracking_enabled, added_at, status_changed_at)"
                " VALUES ('series', 'С', 'S', '[]', 'in_progress', 1, :now, :now)"
            ),
            {"now": now},
        )
        session.commit()
        title = session.scalars(select(Title)).one()
        assert (title.kind, title.status) == (TitleKind.SERIES, TitleStatus.IN_PROGRESS)
        assert type(title.kind) is TitleKind
        title.kind, title.status = TitleKind.ANIME, TitleStatus.TO_FINISH
        session.commit()
        assert session.execute(text("SELECT kind, status FROM titles")).one() == ("anime", "to_finish")


def test_a_button_naming_no_kind_is_not_a_kind():
    from app.bot.tracker_handlers import _kind_of

    assert _kind_of("anime") is TitleKind.ANIME
    assert _kind_of("game") is None and _kind_of("") is None


def test_following_a_sequel_of_an_unknown_kind_says_so():
    import asyncio

    from app.tracker.core import Tracker, UnknownKind

    tracker = Tracker(create_session_factory("sqlite://"), clock=lambda: datetime(2026, 1, 1), sender=None, sources={})
    for kind in ("game", "series"):  # no such kind / a kind with no sequel source
        with pytest.raises(UnknownKind):
            asyncio.run(tracker.follow_sequel_of(kind, "1"))


def test_the_table_says_what_the_owner_has_always_read():
    assert [(k.label, k.icon, k.source_name) for k in KINDS.values()] == [
        ("Фильм", "🎬", "TMDb"),
        ("Сериал", "📺", "TMDb"),
        ("Аниме", "🎌", "Shikimori"),
    ]
    assert KINDS[TitleKind.ANIME].ask_name == "Напишите название аниме (можно по-русски или по-английски)."
    assert [cards.STATUS_LABELS[s] for s in TitleStatus] == ["Хочу", "В процессе", "Жду", "Досмотреть", "Просмотрено", "Бросил"]
