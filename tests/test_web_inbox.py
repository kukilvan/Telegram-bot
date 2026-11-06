"""The web tab «Входящие» (stage 6.4, ticket 05): the number in the menu, the page, «Найти» and the search that comes from
it, «Убрать» with and without HTMX. Real core on a database in memory with items written straight into the table; the
sources are fakes."""

import asyncio
import logging
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.runtime import Health
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import InboxReason, InboxRecord, InboxState, TitleKind
from app.tracker.sources.tmdb_movies import MovieSnapshot, Suggestion
from app.web import create_web_app
from app.web.inbox import MAX_CHARS, shorten, when_text

PASSWORD = "correct horse battery"
HTMX = {"HX-Request": "true"}
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
MOSCOW = ZoneInfo("Europe/Moscow")
EMPTY = "Здесь пусто: всё, что вы присылали боту, разобрано."
SEARCH_LINE = "Из «Входящих»: добавленный тайтл уберёт эту запись."


class Sender:
    async def send(self, *args, **kwargs):
        return None


class Movies:
    source_key = "tmdb_movie"

    async def suggest(self, query):
        return [Suggestion(TitleKind.MOVIE, "1", "Дюна", "Dune", 2021)]

    async def snapshot(self, external_id):
        return MovieSnapshot(external_id=external_id, name="Дюна", original_name="Dune", year=2021)


def make_tracker(session_factory=None):
    return Tracker(
        session_factory or create_session_factory("sqlite://"), clock=lambda: NOW, sender=Sender(),
        sources={"movie": Movies()}, default_tz=MOSCOW,
    )


def put(tracker, *, text="", state=InboxState.INBOX, reason=InboxReason.NOT_FOUND, kind=None, media=None,
        post_url=None, query="", received=datetime(2026, 11, 6, 9, 0)):
    """An item straight into the table (naive UTC `received`); returns its number."""
    with tracker.session_factory() as session:
        item = InboxRecord(
            state=state, reason=reason if state == InboxState.INBOX else None, kind=kind, text=text, media=media,
            bold=[], links=[], post_url=post_url, forwarded=False, query=query, offers=[], received_at=received,
            last_message_at=received, moved_at=received if state == InboxState.INBOX else None,
        )
        session.add(item)
        session.commit()
        return item.id


def make_client(tracker, tmp_path, *, signed_in=True):
    app = create_web_app(
        health=Health().report, password=PASSWORD, secret_file=tmp_path / "web_secret", tracker=tracker, now=lambda: NOW
    )
    client = TestClient(app, follow_redirects=False)
    if signed_in:
        assert client.post("/login", data={"password": PASSWORD}).status_code == 303
    return client


def ids_in_page(html):
    return [int(n) for n in re.findall(r'<li class="inbox-item" id="inbox-(\d+)">', html)]


def left(tracker):
    return [item.id for item in asyncio.run(tracker.inbox_items())]


# ---- the menu -------------------------------------------------------------------------------------------------

def test_the_menu_has_the_inbox_between_search_and_settings_and_no_number_while_it_is_empty(tmp_path):
    html = make_client(make_tracker(), tmp_path).get("/search").text

    assert re.findall(r'<a href="(/[a-z]*)"[^>]*>([^<]+)</a>', html.split('<nav', 1)[1].split('</nav>')[0]) == [
        ("/", "Лента"), ("/list", "Список"), ("/archive", "Архив"), ("/search", "Поиск"), ("/inbox", "Входящие"),
        ("/settings", "Настройки"),
    ]


def test_the_number_counts_the_items_in_the_inbox_and_not_the_one_that_waits(tmp_path):
    tracker = make_tracker()
    put(tracker)
    put(tracker)
    put(tracker, state=InboxState.WAITING)

    html = make_client(tracker, tmp_path).get("/list").text

    assert '<a href="/inbox">Входящие (2)</a>' in html


def test_the_menu_without_the_count_is_bare_and_the_page_still_opens(tmp_path, caplog):
    tracker = make_tracker()

    async def broken():
        raise RuntimeError("database is locked")

    tracker.inbox_count = broken
    with caplog.at_level(logging.WARNING):
        response = make_client(tracker, tmp_path).get("/search")

    assert response.status_code == 200 and '<a href="/inbox">Входящие</a>' in response.text
    assert "no number of «Входящие»" in caplog.text


def test_the_inbox_is_marked_in_the_menu_on_its_own_page(tmp_path):
    html = make_client(make_tracker(), tmp_path).get("/inbox").text

    assert '<a href="/inbox" aria-current="page">Входящие</a>' in html and "<h1>Входящие</h1>" in html


# ---- the page -------------------------------------------------------------------------------------------------

def test_an_empty_inbox_says_so(tmp_path):
    html = make_client(make_tracker(), tmp_path).get("/inbox").text

    assert EMPTY in html and 'class="inbox-item"' not in html


def test_the_items_come_newest_first_and_the_one_that_waits_is_not_shown(tmp_path):
    tracker = make_tracker()
    old = put(tracker, text="старое", received=datetime(2026, 11, 1, 9, 0))
    waiting = put(tracker, text="ждёт", state=InboxState.WAITING)
    new = put(tracker, text="новое", received=datetime(2026, 11, 6, 9, 0))
    middle = put(tracker, text="среднее", received=datetime(2026, 11, 3, 9, 0))

    html = make_client(tracker, tmp_path).get("/inbox").text

    assert ids_in_page(html) == [new, middle, old] and waiting not in ids_in_page(html) and EMPTY not in html


def test_every_reason_is_said_in_words(tmp_path):
    tracker = make_tracker()
    for reason in InboxReason:
        put(tracker, text="текст", reason=reason)

    html = make_client(tracker, tmp_path).get("/inbox").text

    for words in ("не нашёл", "без ответа", "нет текста", "источник не ответил", "игры не подключены"):
        assert f"<span>{words}</span>" in html


def test_the_kind_has_its_icon_and_no_kind_says_so(tmp_path):
    tracker = make_tracker()
    put(tracker, text="игра", kind=TitleKind.GAME)
    put(tracker, text="без типа")

    html = make_client(tracker, tmp_path).get("/inbox").text

    assert "<span>🎮 Игра</span>" in html and "<span>тип не выбран</span>" in html


def test_the_dates_are_on_the_owners_clock_in_four_forms(tmp_path):
    tracker = make_tracker()  # Moscow, UTC+3; now is 6 November 15:00 there
    put(tracker, text="a", received=datetime(2026, 11, 6, 11, 20))  # 14:20 today
    put(tracker, text="b", received=datetime(2026, 11, 5, 19, 41))  # 22:41 yesterday
    put(tracker, text="c", received=datetime(2026, 11, 3, 6, 12))  # 09:12 on 3 November
    put(tracker, text="d", received=datetime(2025, 11, 3, 6, 12))  # another year

    html = make_client(tracker, tmp_path).get("/inbox").text

    assert re.findall(r'<span class="inbox-when">([^<]+)</span>', html) == [
        "Сегодня, 14:20", "Вчера, 22:41", "3 ноября, 09:12", "3 ноября 2025, 09:12",
    ]


def test_a_long_text_is_cut_at_a_word_and_the_whole_one_waits_under_show_all(tmp_path):
    tracker = make_tracker()
    put(tracker, text="слово " * 100)
    put(tracker, text="коротко")

    html = make_client(tracker, tmp_path).get("/inbox").text

    assert html.count("показать всё") == 1
    shown = re.search(r'<p class="inbox-text">(слово[^<]*)</p>', html).group(1)
    assert shown.endswith("слово…") and len(shown) <= MAX_CHARS + 1
    assert "<details" in html and "<script" not in html.split("</nav>")[1]


def test_an_item_without_text_says_what_came_and_has_no_find_button(tmp_path):
    tracker = make_tracker()
    put(tracker, media="sticker", reason=InboxReason.NO_TEXT)
    put(tracker, media="photo", reason=InboxReason.NO_TEXT)

    html = make_client(tracker, tmp_path).get("/inbox").text

    assert "(стикер без подписи)" in html and "(картинка без подписи)" in html
    assert ">Найти<" not in html and html.count(">Убрать<") == 2


def test_an_item_without_text_but_with_a_kind_can_be_searched(tmp_path):
    tracker = make_tracker()
    number = put(tracker, media="photo", kind=TitleKind.MOVIE, reason=InboxReason.NOT_FOUND)

    html = make_client(tracker, tmp_path).get("/inbox").text

    assert f'href="/search?kind=movie&amp;inbox={number}"' in html


def test_the_post_link_opens_in_a_new_tab_without_the_opener(tmp_path):
    tracker = make_tracker()
    put(tracker, text="пост", post_url="https://t.me/games/12")
    put(tracker, text="без поста")

    html = make_client(tracker, tmp_path).get("/inbox").text

    assert html.count("Открыть пост ↗") == 1
    assert '<a href="https://t.me/games/12" target="_blank" rel="noopener">Открыть пост ↗</a>' in html


def test_find_is_a_link_to_the_search_with_the_kind_the_query_and_the_item(tmp_path):
    tracker = make_tracker()
    with_kind = put(tracker, text="Новая игра Hades II", kind=TitleKind.GAME, query="Hades II")
    no_kind = put(tracker, text="Дюна & «Часть»", query="Дюна & «Часть»")

    html = make_client(tracker, tmp_path).get("/inbox").text

    assert f'href="/search?kind=game&amp;q=Hades+II&amp;inbox={with_kind}"' in html
    assert f'href="/search?q=%D0%94%D1%8E%D0%BD%D0%B0+%26+%C2%AB%D0%A7%D0%B0%D1%81%D1%82%D1%8C%C2%BB&amp;inbox={no_kind}"' in html


def test_the_text_of_an_item_is_escaped(tmp_path):
    tracker = make_tracker()
    put(tracker, text='<script>alert("x")</script>')

    html = make_client(tracker, tmp_path).get("/inbox").text

    assert "<script>alert" not in html and "&lt;script&gt;alert" in html


def test_a_core_that_cannot_list_gives_the_common_failure_with_a_reload_link(tmp_path):
    tracker = make_tracker()

    async def broken():
        raise RuntimeError("boom")

    tracker.inbox_items = broken
    response = make_client(tracker, tmp_path).get("/inbox")

    assert response.status_code == 500 and 'href="/inbox"' in response.text and "Не получилось" in response.text


# ---- the pure parts -------------------------------------------------------------------------------------------

def test_a_short_text_is_kept_as_it_is_but_blank_lines_go():
    assert shorten("Дюна\n\n\nвышла") == ("Дюна\nвышла", False)


def test_more_than_four_lines_are_cut_with_the_dots():
    assert shorten("1\n2\n3\n4\n5") == ("1\n2\n3\n4…", True)
    assert shorten("1\n2\n3\n4") == ("1\n2\n3\n4", False)


def test_the_characters_are_cut_at_a_word_and_a_word_longer_than_the_limit_is_cut_hard():
    text = "слово " * 60
    cut, was_cut = shorten(text)
    assert was_cut and cut.endswith("слово…") and len(cut) <= MAX_CHARS + 1
    hard, was_cut = shorten("я" * 400)
    assert was_cut and hard == "я" * MAX_CHARS + "…"


def test_a_text_of_exactly_the_limit_is_not_cut():
    assert shorten("я" * MAX_CHARS) == ("я" * MAX_CHARS, False)


@pytest.mark.parametrize(
    ("received", "expected"),
    [
        (datetime(2026, 11, 5, 21, 30), "Сегодня, 00:30"),  # 00:30 on 6 November in Moscow
        (datetime(2026, 11, 5, 20, 59), "Вчера, 23:59"),
        (datetime(2026, 1, 9, 6, 5), "9 января, 09:05"),
        (datetime(2025, 12, 31, 22, 0), "1 января, 01:00"),
    ],
)
def test_when_text_counts_the_day_on_the_owners_clock(received, expected):
    assert when_text(received, MOSCOW, NOW) == expected


def test_when_text_without_a_zone_uses_utc():
    assert when_text(datetime(2026, 11, 6, 9, 0), None, NOW) == "Сегодня, 09:00"


# ---- «Убрать» -------------------------------------------------------------------------------------------------

def test_remove_with_htmx_empties_the_row_and_renews_the_menu_out_of_band(tmp_path):
    tracker = make_tracker()
    first, second = put(tracker, text="a"), put(tracker, text="b")
    client = make_client(tracker, tmp_path)

    response = client.post(f"/inbox/{first}/remove", headers=HTMX)

    assert response.status_code == 200 and left(tracker) == [second]
    assert 'hx-swap-oob="true"' in response.text and "Входящие (1)" in response.text and EMPTY not in response.text
    assert "inbox-item" not in response.text


def test_the_last_one_removed_brings_the_empty_sentence_and_a_bare_menu(tmp_path):
    tracker = make_tracker()
    only = put(tracker, text="a")
    client = make_client(tracker, tmp_path)

    response = client.post(f"/inbox/{only}/remove", headers=HTMX)

    assert left(tracker) == []
    assert '<a href="/inbox" aria-current="page">Входящие</a>' in response.text
    assert f'<div id="inbox-empty" hx-swap-oob="true"><p class="hint">{EMPTY}</p></div>' in response.text


def test_remove_without_htmx_goes_back_to_the_page(tmp_path):
    tracker = make_tracker()
    number = put(tracker, text="a")
    client = make_client(tracker, tmp_path)

    response = client.post(f"/inbox/{number}/remove")

    assert response.status_code == 303 and response.headers["location"] == "/inbox" and left(tracker) == []


def test_a_second_press_and_an_item_that_never_was_answer_the_same(tmp_path):
    tracker = make_tracker()
    number = put(tracker, text="a")
    keep = put(tracker, text="b")
    client = make_client(tracker, tmp_path)
    client.post(f"/inbox/{number}/remove", headers=HTMX)

    again = client.post(f"/inbox/{number}/remove", headers=HTMX)
    never = client.post("/inbox/999/remove", headers=HTMX)
    huge = client.post(f"/inbox/{10 ** 30}/remove")

    assert again.status_code == never.status_code == 200 and huge.status_code == 303 and left(tracker) == [keep]
    assert "Входящие (1)" in again.text


def test_the_form_of_every_row_posts_to_its_own_item_and_hands_the_row_to_htmx(tmp_path):
    tracker = make_tracker()
    number = put(tracker, text="a")

    html = make_client(tracker, tmp_path).get("/inbox").text

    assert f'action="/inbox/{number}/remove" hx-post="/inbox/{number}/remove" hx-target="#inbox-{number}" hx-swap="outerHTML"' in html


def test_nothing_of_the_inbox_opens_without_a_sign_in(tmp_path):
    tracker = make_tracker()
    number = put(tracker, text="a")
    anonymous = make_client(tracker, tmp_path, signed_in=False)

    page = anonymous.get("/inbox")
    press = anonymous.post(f"/inbox/{number}/remove")
    pressed_with_htmx = anonymous.post(f"/inbox/{number}/remove", headers=HTMX)

    assert page.status_code == 303 and page.headers["location"].startswith("/login")
    assert press.status_code == 303 and pressed_with_htmx.status_code == 401
    assert left(tracker) == [number]


# ---- the search that comes from «Найти» -------------------------------------------------------------------------

def test_the_search_of_an_item_says_that_adding_removes_it_and_carries_its_number(tmp_path):
    tracker = make_tracker()
    number = put(tracker, text="Дюна", query="Дюна")
    client = make_client(tracker, tmp_path)

    html = client.get("/search", params={"kind": "movie", "q": "Дюна", "inbox": number}).text

    assert SEARCH_LINE in html and f'<input type="hidden" name="inbox" value="{number}">' in html
    assert re.findall(r'name="external_id" value="1">\s*<input type="hidden" name="q" value="[^"]*">\s*<input type="hidden" name="inbox" value="(\d+)">', html) == [str(number)]


def test_the_suggestions_for_htmx_carry_the_number_to_the_add_form(tmp_path):
    tracker = make_tracker()
    number = put(tracker, text="Дюна")
    client = make_client(tracker, tmp_path)

    html = client.get("/search/suggestions", params={"kind": "movie", "q": "Дюна", "inbox": number}, headers=HTMX).text

    assert f'<input type="hidden" name="inbox" value="{number}">' in html and SEARCH_LINE not in html


@pytest.mark.parametrize("garbage", ["abc", "-1", "1.5", " 1", "١", "9" * 40, ""])
def test_a_garbage_number_changes_nothing(tmp_path, garbage):
    tracker = make_tracker()
    put(tracker, text="Дюна")
    client = make_client(tracker, tmp_path)

    page = client.get("/search", params={"kind": "movie", "q": "Дюна", "inbox": garbage}).text
    suggestions = client.get("/search/suggestions", params={"kind": "movie", "q": "Дюна", "inbox": garbage}, headers=HTMX).text

    assert SEARCH_LINE not in page and 'name="inbox"' not in page and 'name="inbox"' not in suggestions


def test_a_number_of_an_item_that_is_gone_is_ignored_by_the_page(tmp_path):
    html = make_client(make_tracker(), tmp_path).get("/search", params={"q": "Дюна", "inbox": "77"}).text

    assert SEARCH_LINE not in html and 'name="inbox"' not in html


def test_adding_a_new_title_deletes_the_item_it_was_searched_for(tmp_path):
    tracker = make_tracker()
    number = put(tracker, text="Дюна")
    other = put(tracker, text="другое")
    client = make_client(tracker, tmp_path)

    response = client.post("/titles", data={"kind": "movie", "external_id": "1", "q": "Дюна", "inbox": str(number)}, headers=HTMX)

    assert response.headers["HX-Redirect"] == "/titles/1" and left(tracker) == [other]


def test_a_title_that_was_in_the_list_already_deletes_the_item_too(tmp_path):
    tracker = make_tracker()
    client = make_client(tracker, tmp_path)
    client.post("/titles", data={"kind": "movie", "external_id": "1"})
    number = put(tracker, text="Дюна")

    response = client.post("/titles", data={"kind": "movie", "external_id": "1", "inbox": str(number)})

    assert response.status_code == 303 and left(tracker) == []
    assert "Этот тайтл уже в списке" in client.get(response.headers["location"]).text


def test_a_garbage_number_or_a_gone_item_does_not_stop_adding_and_deletes_nothing(tmp_path):
    tracker = make_tracker()
    number = put(tracker, text="Дюна")
    client = make_client(tracker, tmp_path)

    garbage = client.post("/titles", data={"kind": "movie", "external_id": "1", "inbox": "x1"})
    gone = client.post("/titles", data={"kind": "movie", "external_id": "1", "inbox": "999"})

    assert garbage.status_code == gone.status_code == 303 and left(tracker) == [number]


def test_an_add_that_fails_keeps_the_item(tmp_path):
    tracker = make_tracker()
    number = put(tracker, text="Дюна")
    client = make_client(tracker, tmp_path)

    response = client.post("/titles", data={"kind": "robot", "external_id": "1", "inbox": str(number)}, headers=HTMX)

    assert response.status_code == 200 and left(tracker) == [number]


def test_the_title_is_added_even_when_the_item_could_not_be_deleted(tmp_path, caplog):
    tracker = make_tracker()
    number = put(tracker, text="Дюна")

    async def broken(item_id):
        raise RuntimeError("database is locked")

    tracker.resolve_inbox = broken
    with caplog.at_level(logging.WARNING):
        response = make_client(tracker, tmp_path).post("/titles", data={"kind": "movie", "external_id": "1", "inbox": str(number)})

    assert response.status_code == 303 and response.headers["location"] == "/titles/1"
    assert "could not delete the item" in caplog.text and left(tracker) == [number]


def test_the_way_back_after_a_refusal_keeps_the_number(tmp_path):
    tracker = make_tracker()
    number = put(tracker, text="Дюна")
    client = make_client(tracker, tmp_path)

    response = client.post("/titles", data={"kind": "robot", "external_id": "1", "q": "Дюна", "inbox": str(number)})

    assert response.status_code == 303 and response.headers["location"].endswith(f"&inbox={number}")
