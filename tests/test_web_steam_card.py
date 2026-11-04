"""The Steam prices in the browser (spec 6.2, 6.3 and 6.6 of part 6.2, ticket 05): the block «Steam» of the card after
«Платформы», the hint of the platforms, the mark «−30 %» of the rows of the list, the line under «Страна магазинов».

The real core on in-memory SQLite with a stand-in clock, a made-up game source and a fake source of price looks (as in
`test_tracker_game_prices`); the web is the real app on a `TestClient`.
"""

import re
from pathlib import Path

import pytest

from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import TitleKind
from test_tracker_game_prices import HADES, T0, FakeClock, FakePrices, FakeSender, MadeUpGames, add, game, run
from test_web_card import make_client

WEB = Path(__file__).resolve().parent.parent / "app" / "web"
MINUS_30 = "−30 %"


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def igdb():
    return MadeUpGames()


@pytest.fixture
def prices():
    return FakePrices()


@pytest.fixture
def tracker(session_factory, igdb, prices):
    return Tracker(
        session_factory, clock=FakeClock(T0), sender=FakeSender(), sources={TitleKind.GAME: igdb}, price_source=prices
    )


@pytest.fixture
def client(tracker, tmp_path):
    return make_client(tracker, tmp_path)


def on_sale(prices):
    prices.final[HADES] = 19530
    prices.discount[HADES] = (27900, 30)


def steam_section(html):
    found = re.search(r'<section class="steam".*?</section>', html, re.S)
    return found.group(0) if found else ""


def text_of(html):
    return re.sub(r"[ \t\r\n]+", " ", re.sub(r"<[^>]+>", " ", html)).strip()  # a no-break space stays one


def test_the_card_has_the_steam_block_after_the_platforms_with_its_lines(tracker, igdb, prices, client):
    title_id = add(tracker, igdb)
    on_sale(prices)
    run(tracker.poll_due())

    html = client.get(f"/titles/{title_id}").text

    assert html.index('<section class="platforms"') < html.index('<section class="steam"')
    section = steam_section(html)
    assert "<h2 id=\"steam-heading\">Steam</h2>" in section
    assert text_of(section) == f"Steam Цены для страны «Израиль» · проверено в 12:00 Скидка {MINUS_30}: ₪279 → ₪195,30"
    assert "Открыть в Steam" in html.split('<section class="steam"')[0]  # the link stays in «Платформы»
    assert "Открыть в Steam" not in section


def test_the_block_before_the_first_check_says_the_price_comes_soon(tracker, igdb, client):
    title_id = add(tracker, igdb)
    section = steam_section(client.get(f"/titles/{title_id}").text)
    assert text_of(section) == "Steam Цены для страны «Израиль» Цену ещё не проверяли — она появится через минуту-другую"


def test_the_block_lists_the_bundles_under_their_own_heading(tracker, igdb, prices, client, session_factory):
    from sqlalchemy import select

    from app.tracker.models import SourceSnapshot
    from app.tracker.prices import PRICE, Bundle, Price, PriceLook

    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    bundles = tuple(Bundle(f"bundle:{n}", f"Pack {n}", 2, 25000) for n in range(1, 8))
    with session_factory() as session:
        session.scalar(select(SourceSnapshot).where(SourceSnapshot.source == "steam")).state = PriceLook(
            HADES, "il", PRICE, "₪{}", Price(11095), bundles
        ).state()
        session.commit()

    section = steam_section(client.get(f"/titles/{title_id}").text)

    assert "<h3>Бандлы</h3>" in section
    assert re.findall(r"<li[^>]*>([^<]+)</li>", section) == [f"«Pack {n}» (2 игры) — ₪250" for n in range(1, 6)] + ["и ещё 2"]


def test_a_game_that_prices_are_not_told_about_has_no_block_and_no_stale_one(tracker, igdb, prices, client):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    assert steam_section(client.get(f"/titles/{title_id}").text)
    run(tracker.set_platform_playing(title_id, "pc", False))  # the snapshot is still there until the next minute
    assert steam_section(client.get(f"/titles/{title_id}").text) == ""
    run(tracker.set_platform_playing(title_id, "pc", True))
    assert steam_section(client.get(f"/titles/{title_id}").text)
    run(tracker.mark_started(title_id))
    assert steam_section(client.get(f"/titles/{title_id}").text) == ""


def test_the_press_of_the_mark_gives_the_card_with_or_without_the_block(tracker, igdb, prices, client):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    htmx = {"HX-Request": "true"}
    off = client.post(f"/titles/{title_id}/platforms/pc", data={}, headers=htmx)  # an unchecked box sends nothing
    assert off.status_code == 200 and steam_section(off.text) == ""
    on = client.post(f"/titles/{title_id}/platforms/pc", data={"playing": "1"}, headers=htmx)
    assert steam_section(on.text) != ""


def test_a_film_card_has_no_block(client, tracker, session_factory):
    from app.tracker.models import Title, TitleStatus
    from test_tracker_steam_card import naive

    with session_factory() as session:
        session.add(Title(kind=TitleKind.MOVIE, name="Дюна", original_name="Dune", year=2021, genres=[],
                          status=TitleStatus.WANT, tracking_enabled=True, added_at=naive(T0), status_changed_at=naive(T0)))
        session.commit()
    assert steam_section(client.get("/titles/1").text) == ""


def test_the_hint_of_the_platforms_mentions_steam(tracker, igdb, client):
    title_id = add(tracker, igdb)
    html = client.get(f"/titles/{title_id}").text
    assert "Галочка — «играю здесь»: о выходе на отмеченных платформах придёт сообщение; у ПК — ещё цены и скидки Steam" in html


def test_the_template_of_the_block_compares_no_kind_and_no_status():
    template = (WEB / "templates" / "card_body.html").read_text(encoding="utf-8")
    block = re.search(r'<section class="steam".*?</section>', template, re.S).group(0)
    opener = re.search(r"\{% if (\w+) %\}\s*<section class=\"steam\"", template).group(1)
    assert opener == "steam"  # it is there when the core gave it
    assert not re.search(r"kind|status|==|!=", block)


# --- the list and the settings ----------------------------------------------------------------------------------------


def rows_of(html):
    """The rows of the list: (name, the mark or empty, the status)."""
    found = []
    for row in re.findall(r'<li class="title-row">(.*?)</li>', html, re.S):
        name = re.search(r'class="title-name"><span[^>]*>[^<]*</span>\s*([^<]+)<', row).group(1).strip()
        mark = re.search(r'<span class="row-mark">([^<]+)</span>', row)
        found.append((name, mark.group(1) if mark else "", re.search(r'row-status">([^<]+)<', row).group(1)))
    return found


def test_the_row_of_a_game_with_a_discount_has_the_mark_before_the_status(tracker, igdb, prices, client):
    on_sale(prices)
    add(tracker, igdb, game(), "1", "Hades II")
    add(tracker, igdb, game(steam_id="2"), "2", "Elden Ring")
    run(tracker.poll_due())

    html = client.get("/list").text

    assert sorted(rows_of(html)) == [("Elden Ring", "", "Хочу"), ("Hades II", MINUS_30, "Хочу")]
    assert re.search(r'<span class="row-mark">[^<]+</span><span class="row-status">', html)


def test_the_archive_has_no_marks(tracker, igdb, prices, client):
    title_id = add(tracker, igdb)
    on_sale(prices)
    run(tracker.poll_due())
    run(tracker.mark_dropped(title_id))
    assert "row-mark" not in client.get("/archive").text and "row-mark" not in client.get("/list?status=all").text


def test_the_country_of_the_stores_says_the_prices_are_in_its_currency(client):
    html = client.get("/settings").text
    assert "Ссылка на PlayStation Store ведёт в магазин этой страны, даты выхода — для её региона, цены Steam — в её валюте" in html
