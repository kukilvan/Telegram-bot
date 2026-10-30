"""What the list and the archive share (ticket 01 of part 5.4): the filters read from the address, the row of links, the
empty sentences, the macro of a row of filters, the orders of the list, the one handling of «Следить» and the names of
the helpers of `pages.py`. On the real core (rows put straight into the database)."""

import asyncio
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.runtime import Health
from app.tracker.core import ListOrder, SourceFailed, TitleNotFound, Tracker, UnknownKind
from app.tracker.db import create_session_factory
from app.tracker.models import ARCHIVE_STATUSES, Title, TitleKind, TitleStatus
from app.web import create_web_app, filters

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "app" / "web"
PASSWORD = "correct horse battery"
T0 = datetime(2026, 10, 24, 12, 0)
HTMX = {"HX-Request": "true"}


class FakeSender:
    async def send(self, message, actions=()):
        pass


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def tracker(session_factory):
    return Tracker(session_factory, clock=lambda: T0.replace(tzinfo=timezone.utc), sender=FakeSender())


@pytest.fixture
def client(tracker, tmp_path):
    health = Health()
    health.bot_running = health.scheduler_running = True
    health.scheduler_mark = health.clock()
    app = create_web_app(health=health.report, password=PASSWORD, secret_file=tmp_path / "web_secret", tracker=tracker)
    client = TestClient(app, follow_redirects=False)
    assert client.post("/login", data={"password": PASSWORD}).status_code == 303
    return client


def put(session_factory, name, status=TitleStatus.WANT, *, minutes=0, score=None, kind=TitleKind.MOVIE):
    with session_factory() as session:
        title = Title(
            kind=kind, name=name, original_name=name, genres=[], status=status, tracking_enabled=True,
            added_at=T0 + timedelta(minutes=minutes), status_changed_at=T0 + timedelta(minutes=minutes), score=score,
        )
        session.add(title)
        session.commit()
        return title.id


def shown(html):
    return re.findall(r'<span class="title-name"><span aria-hidden="true">[^<]*</span> ([^<]*)</span>', html)


def current(html):
    return re.findall(r'<a href="[^"]*" aria-current="true">([^<]*)</a>', html)


# ---- a value from the address ------------------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("movie", TitleKind.MOVIE), ("anime", TitleKind.ANIME), ("", None), ("game", None), ("MOVIE", None), (" movie", None),
])
def test_a_kind_from_the_address_is_the_kind_or_none(raw, expected):
    assert filters.parse_choice(TitleKind, raw) is expected


def test_a_value_outside_the_allowed_ones_counts_as_none_or_the_default():
    assert filters.parse_choice(TitleStatus, "want", allowed=ARCHIVE_STATUSES) is None
    assert filters.parse_choice(TitleStatus, "dropped", allowed=ARCHIVE_STATUSES) is TitleStatus.DROPPED
    assert filters.parse_choice(ListOrder, "score", allowed=[ListOrder.ADDED], default=ListOrder.ADDED) is ListOrder.ADDED
    assert filters.parse_choice(ListOrder, "", allowed=[ListOrder.ADDED], default=ListOrder.ADDED) is ListOrder.ADDED
    assert filters.parse_choice(ListOrder, "added", allowed=[ListOrder.ADDED], default=ListOrder.NAME) is ListOrder.ADDED


def test_the_row_of_kinds_has_all_then_every_kind_with_the_chosen_one_marked():
    links = filters.kind_links(TitleKind.SERIES, lambda kind: f"/x?kind={kind.value if kind else ''}")

    assert [link.label for link in links] == ["Все", "Фильмы", "Сериалы", "Аниме"]
    assert [link.address for link in links] == ["/x?kind=", "/x?kind=movie", "/x?kind=series", "/x?kind=anime"]
    assert [link.current for link in links] == [False, False, True, False]
    assert filters.kind_links(None, lambda kind: "/")[0].current is True


# ---- the sentence of an empty page -------------------------------------------------------------------------------

def phrase(*, query="", unfiltered=False, has_rows=False):
    """The sentence and how many times the page was asked whether it has rows without the filter."""
    calls = []

    async def anything():
        calls.append(1)
        return has_rows

    text = asyncio.run(filters.empty_phrase(query=query, unfiltered=unfiltered, anything=anything, nothing_at_all="ПУСТО"))
    return text, len(calls)


def test_a_search_that_found_nothing_says_so_and_asks_nothing_more():
    assert phrase(query="дюн", unfiltered=False, has_rows=True) == (filters.NOTHING_FOUND, 0)


def test_with_no_filter_the_page_is_empty_and_nothing_is_asked():
    assert phrase(unfiltered=True) == ("ПУСТО", 0)


def test_a_filter_nothing_fits_is_told_apart_from_a_page_with_nothing_at_all():
    assert phrase(unfiltered=False, has_rows=True) == (filters.NOTHING_FITS, 1)
    assert phrase(unfiltered=False, has_rows=False) == ("ПУСТО", 1)


# ---- the macro of a row of filters --------------------------------------------------------------------------------

def test_a_row_of_filters_is_written_in_one_place_the_macro():
    for path in sorted((WEB / "templates").glob("*.html")):
        text = path.read_text(encoding="utf-8")
        assert ('<nav class="filters"' in text) == (path.name == "macros.html"), path.name
    assert (WEB / "templates" / "macros.html").read_text(encoding="utf-8").count('<nav class="filters"') == 1


def test_the_macro_marks_the_chosen_link_and_escapes_the_label(client, session_factory):
    put(session_factory, "Дюна")

    html = client.get("/list?kind=movie").text

    assert re.search(r'<nav class="filters" aria-label="Тип">\s*<a href="/list">Все</a><a href="/list\?kind=movie" aria-current="true">Фильмы</a>', html)
    assert current(html) == ["Фильмы", "Без архива", "Сначала новые"]


# ---- the orders of the list ----------------------------------------------------------------------------------------

@pytest.fixture
def scored(session_factory):
    """Three watched films: the best score was added first, the worst last."""
    put(session_factory, "Первый", TitleStatus.WATCHED, minutes=0, score=30)
    put(session_factory, "Второй", TitleStatus.WATCHED, minutes=1, score=15)
    put(session_factory, "Третий", TitleStatus.WATCHED, minutes=2, score=3)


@pytest.mark.parametrize("order", ["score", "archived"])
def test_an_order_of_the_archive_in_the_address_of_the_list_is_the_order_of_the_list(client, scored, order):
    by_default = client.get("/list?status=all")
    by_hand = client.get(f"/list?status=all&order={order}")

    assert shown(by_default.text) == ["Третий", "Второй", "Первый"]  # newest first
    assert shown(by_hand.text) == shown(by_default.text)
    assert "Сначала новые" in current(by_hand.text) and "По названию" not in current(by_hand.text)
    assert "order=" not in re.search(r'<a href="([^"]*)"[^>]*>Весь список', by_hand.text).group(1)


def test_the_list_has_its_two_orders_and_the_archive_keeps_its_three(client, scored):
    page = client.get("/list").text
    archive = client.get("/archive?order=archived").text

    assert re.findall(r'aria-label="Порядок">(.*?)</nav>', page, re.S)[0].count("<a ") == 2
    assert re.findall(r'aria-label="Порядок">(.*?)</nav>', archive, re.S)[0].count("<a ") == 3
    assert "Сначала недавние" in current(archive)
    assert shown(client.get("/archive").text) == ["Первый", "Второй", "Третий"]  # by the score, the default
    assert "По названию" in current(client.get("/archive?order=name").text)


def test_the_result_fragments_of_both_pages_still_push_their_addresses(client, scored):
    listing = client.get("/list/results", params={"status": "all", "q": "Пер"}, headers=HTMX)
    archive = client.get("/archive/results", params={"q": "Вто"}, headers=HTMX)

    assert listing.headers["HX-Push-Url"] == "/list?status=all&q=%D0%9F%D0%B5%D1%80"
    assert archive.headers["HX-Push-Url"] == "/archive?q=%D0%92%D1%82%D0%BE"
    assert client.get("/list/results?q=x").headers["location"] == "/list?q=x"
    assert client.get("/archive/results?q=x").headers["location"] == "/archive?q=x"


# ---- «Следить» is one handling -----------------------------------------------------------------------------------

def test_the_handling_of_follow_is_in_pages_and_nowhere_else():
    users = [path.name for path in sorted(WEB.glob("*.py")) if "follow_sequel_of(" in path.read_text(encoding="utf-8")]

    assert users == ["pages.py"]


@pytest.mark.parametrize("error, phrase_of_it", [
    (UnknownKind("game"), "Такого типа нет"),
    (KeyError("game"), "Такого типа нет"),
    (TitleNotFound("9"), "TMDb больше не знает этот тайтл. Поищите заново"),
    (SourceFailed("down"), "Не удалось связаться с TMDb. Попробуйте чуть позже"),
])
def test_the_card_and_the_feed_say_the_same_sentence_for_each_error(client, session_factory, monkeypatch, error, phrase_of_it):
    film = put(session_factory, "Дюна", TitleStatus.WATCHED)

    async def refuse(self, kind, sequel_id):
        raise error

    monkeypatch.setattr(Tracker, "follow_sequel_of", refuse)

    # a film without a look at its sequels has no block for the line: without HTMX the line crosses to the card page
    pressed = client.post(f"/titles/{film}/sequels", data={"kind": "movie", "sequel_id": "9"})
    on_card = client.get(pressed.headers["location"])
    on_feed = client.post("/feed/sequels", data={"kind": "movie", "sequel_id": "9"}, headers=HTMX)

    assert phrase_of_it in on_card.text and phrase_of_it in on_feed.text


# ---- the names ---------------------------------------------------------------------------------------------------

def test_the_helpers_of_pages_say_what_they_do():
    old_names = [r"\bsource_failed\b", r"\b_net\b"]
    for path in [*sorted((ROOT / "app").rglob("*.py")), *sorted((ROOT / "tests").glob("*.py"))]:
        if path.name == Path(__file__).name:
            continue
        text = path.read_text(encoding="utf-8")
        for name in old_names:
            assert not re.search(name, text), (path.name, name)
    from app.web import pages

    assert callable(pages.report_source_failure) and callable(pages.try_follow_sequel) and callable(pages._under_net)
