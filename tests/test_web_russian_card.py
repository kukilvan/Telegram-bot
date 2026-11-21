"""Russian in the browser (spec 5.3 of stage 9.1b, ticket 04): the block «Русский язык» after «Платформы» and before
«Steam», with the line «Русский: …» and the hints of every state that exists without ZoG — not checked yet, the source
and its moment, «(ПК)», «нет данных» with and without a Steam page, another status; no block for a game in another
status without data, nor without the source of languages; the template compares no kind and no status.

The real core on in-memory SQLite with a stand-in clock, a made-up game source, a fake source of price looks and a fake
source of Steam's languages; the web is the real app on a `TestClient`.
"""

import re
from pathlib import Path

import pytest

from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import TitleKind
from app.tracker.platforms import Platform
from app.tracker.russian import Support
from test_tracker_game_prices import T0, FakeClock, FakePrices, FakeSender, MadeUpGames, run
from test_tracker_russian_check import CYBERPUNK, STRAY, FakeLanguages, add, game
from test_web_card import make_client

WEB = Path(__file__).resolve().parent.parent / "app" / "web"


@pytest.fixture
def igdb():
    return MadeUpGames()


@pytest.fixture
def steam():
    return FakeLanguages()


@pytest.fixture
def tracker(igdb, steam):
    return Tracker(
        create_session_factory("sqlite://"), clock=FakeClock(T0), sender=FakeSender(), sources={TitleKind.GAME: igdb},
        price_source=FakePrices(), language_source=steam,
    )


@pytest.fixture
def client(tracker, tmp_path):
    return make_client(tracker, tmp_path)


def section(html, name):
    found = re.search(rf'<section class="{name}".*?</section>', html, re.S)
    return found.group(0) if found else ""


def text_of(html):
    return re.sub(r"[ \t\r\n]+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def russian_block(client, title_id):
    return section(client.get(f"/titles/{title_id}").text, "russian")


def test_the_block_stands_after_the_platforms_and_before_steam(tracker, igdb, steam, client):
    steam.support[CYBERPUNK] = Support(True, True)
    title_id = add(tracker, igdb, game(steam_id=CYBERPUNK), name="Cyberpunk 2077")
    run(tracker.poll_due())

    html = client.get(f"/titles/{title_id}").text

    assert html.index('<section class="platforms"') < html.index('<section class="russian"') < html.index('<section class="steam"')
    block = section(html, "russian")
    assert '<h2 id="russian-heading">Русский язык</h2>' in block
    assert "<b>Русский:</b> текст и озвучка — официально" in block
    assert text_of(block) == "Русский язык Русский: текст и озвучка — официально Steam — проверено сегодня в 12:00"


def test_before_the_first_check_the_line_reads_by_igdb_and_says_it_comes_soon(tracker, igdb, client):
    title_id = add(tracker, igdb, game(russian=Support(True, False)))

    assert text_of(russian_block(client, title_id)) == (
        "Русский язык Русский: текст — официально Ещё не проверяли — строка появится через минуту-другую"
    )


def test_the_pc_mark_and_its_hint(tracker, igdb, steam, client):
    steam.support[STRAY] = Support(True, False)
    title_id = add(tracker, igdb, game(platforms=(Platform.PC, Platform.PS5)))
    run(tracker.poll_due())

    assert text_of(russian_block(client, title_id)) == (
        "Русский язык Русский: текст — официально (ПК) Steam — проверено сегодня в 12:00 "
        "(ПК) — данные о версии для ПК, а вы играете ещё и на другой платформе"
    )


@pytest.mark.parametrize(
    "steam_id, hint",
    [
        (STRAY, "Steam — проверено сегодня в 12:00 Языки ещё не объявлены. Проверяю: Steam — каждые 6 часов, ZoG — раз в неделю"),
        (None, "IGDB — проверено сегодня в 12:00 Языки ещё не объявлены. Проверяю: IGDB — вместе с датами игры, ZoG — раз в неделю"),
    ],
)
def test_no_data_after_a_check(steam_id, hint, tracker, igdb, client):
    title_id = add(tracker, igdb, game(steam_id=steam_id, russian=None))
    run(tracker.poll_due())

    assert text_of(russian_block(client, title_id)) == f"Русский язык Русский: нет данных {hint}"


def test_another_status_keeps_the_last_line_with_its_hint_and_hides_a_block_without_data(tracker, igdb, steam, client):
    steam.support[STRAY] = Support(False, False)
    with_data = add(tracker, igdb)
    without = add(tracker, igdb, game(steam_id=None, russian=None), external_id="2", name="Без данных")
    run(tracker.poll_due())
    run(tracker.mark_watched(with_data))
    run(tracker.mark_dropped(without))

    assert text_of(russian_block(client, with_data)) == (
        "Русский язык Русский: официально нет Steam — проверено сегодня в 12:00 "
        "Игра не в «Хочу» и не «В процессе» — русский язык больше не проверяется"
    )
    assert russian_block(client, without) == ""


def test_no_block_without_the_source_of_languages(igdb, tmp_path):
    tracker = Tracker(
        create_session_factory("sqlite://"), clock=FakeClock(T0), sender=FakeSender(), sources={TitleKind.GAME: igdb}
    )
    title_id = add(tracker, igdb, game(russian=Support(True, True)))

    assert russian_block(make_client(tracker, tmp_path), title_id) == ""


def test_the_template_of_the_block_compares_no_kind_and_no_status():
    template = (WEB / "templates" / "card_body.html").read_text(encoding="utf-8")
    block = template[template.index("{% if russian %}"):template.index("{% if steam %}")]

    assert "kind" not in block and "status" not in block
