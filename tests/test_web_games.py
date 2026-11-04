"""Games in the browser (spec 9.2, 10, 4.6 and 14 of part 6.1): the search «Игра» with the line of the platforms, the card
of a game with «Платформы» and their marks «играю здесь», the links to the stores, the buttons of each status, the list
and the archive with «Игры» and «Пройдено», and the covers of IGDB in the size of their place.

The real core on in-memory SQLite with a stand-in clock; the game source is the real IGDB adapter on the saved answers of
IGDB and Steam (no network), the film one a fake.
"""

import copy
import re
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.providers.igdb import IgdbError
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.games import GameState
from app.tracker.models import GamePlatformRecord, SettingRecord, SourceSnapshot, TitleStatus
from app.tracker.settings_store import MY_PLATFORMS_SETTING
from app.tracker.sources.igdb_games import IgdbGameSource
from app.tracker.sources.tmdb_movies import MovieSnapshot
from test_igdb_game_source import FakeIgdb, FakeSteam, game, steam
from test_web_card import GONE, HTMX, FakeSender, FakeSource, buttons, make_client, run

WEB = Path(__file__).resolve().parent.parent / "app" / "web"
T0 = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
WITCHER, BLOODBORNE, HADES, NOWHERE, NASTY = "1942", "7334", "228525", "990001", "990002"
IGDB = "https://images.igdb.com/igdb/image/upload"
NOT_CONNECTED = "Игры не подключены: в файле настроек запуска (.env) нет ключей IGDB — IGDB_CLIENT_ID и IGDB_CLIENT_SECRET"
PLATFORM_GONE = "Этой платформы у игры больше нет — карточка обновлена"

FILM = MovieSnapshot(
    external_id="1", name="Дюна", original_name="Dune", year=2021, genres=["приключения", "драма"],
    poster_path="/dune.jpg", overview="Пол Атрейдес едет на Арракис.", theatrical_date=date(2027, 3, 12), digital_date=None,
)


def made_up(number, **changes):
    """Bloodborne under another number with some fields changed: a game only on the Mac, a name with markup."""
    raw = copy.deepcopy(game("bloodborne")) | {"id": int(number)} | changes
    return [raw]


class Games(FakeIgdb):
    """The saved answers of IGDB, two made-up games, and a failure when asked for one."""

    def __init__(self, enabled=True, search="search-vedmak-filtered.json"):
        super().__init__(enabled, search)
        self.failing = False

    async def games(self, body, *, at_once=False):
        if self.failing:
            raise IgdbError("IGDB answered 503", status=503)
        if body.rstrip(" ;").endswith(NOWHERE):  # only on the Mac: no platform of the tracker
            return made_up(NOWHERE, platforms=[14], release_dates=[])
        if body.rstrip(" ;").endswith(NASTY):
            return made_up(NASTY, name='<script>alert("x")</script>', alternative_names=[])
        return await super().games(body, at_once=at_once)


@pytest.fixture
def igdb():
    return Games()


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def tracker(session_factory, igdb):
    return Tracker(
        session_factory, clock=lambda: T0, sender=FakeSender(),
        sources={
            "movie": FakeSource("tmdb_movie", FILM),
            "game": IgdbGameSource(igdb, FakeSteam({292030: steam(292030), 1145350: steam(1145350)})),
        },
    )


@pytest.fixture
def client(tracker, tmp_path):
    return make_client(tracker, tmp_path)


def add(tracker, external_id, kind="game"):
    return run(tracker.add_title(kind, external_id)).title_id


def marks(html):
    """The rows of the platforms: (text, checked, where the mark goes)."""
    found = re.findall(
        r'<form method="post" action="([^"]*/platforms/[^"]*)"[^>]*>\s*<label class="check"><input type="checkbox" '
        r'name="playing" value="1"( checked)?> <span>([^<]+)</span>',
        html,
    )
    return [(text, bool(checked), address) for address, checked, text in found]


def playing(session_factory, title_id):
    """The marks of ПК and PS5 as stored (the game has a row for every platform of the tracker it is on)."""
    with session_factory() as session:
        rows = session.query(GamePlatformRecord).filter_by(title_id=title_id)
        return {row.platform: row.playing for row in rows if row.platform in ("pc", "ps5")}


def set_my_platforms(session_factory, *values):
    with session_factory() as session:
        session.merge(SettingRecord(key=MY_PLATFORMS_SETTING, value=list(values)))
        session.commit()


def status_of(tracker, title_id):
    return run(tracker.title_card(title_id)).status


# ---- the search ----------------------------------------------------------------------------------------------------


def test_the_switch_has_the_four_kinds_in_their_order_and_the_note_of_a_game(client):
    html = client.get("/search?kind=game").text

    assert re.findall(r'name="kind" value="([a-z]+)"', html) == ["movie", "series", "anime", "game"]
    assert re.findall(r'value="[a-z]+"(?: checked)?> <span>([^<]+)</span>', html) == ["Фильм", "Сериал", "Аниме", "Игра"]
    assert 'value="game" checked' in html
    assert "Игры лучше искать по-английски: по-русски IGDB находит не всё" in html


def test_the_suggestions_of_a_game_have_the_line_of_the_platforms_and_the_cover(client):
    html = client.get("/search/suggestions?kind=game&q=ведьмак", headers=HTMX).text

    names = re.findall(r'<span class="title-name"><span aria-hidden="true">🎮</span> ([^<]+)</span>', html)
    assert len(names) == 5 and "Ведьмак 3: Дикая охота" in names
    assert '<span class="title-details">ПК, PS5, PS4, Xbox Series X|S, Xbox One, Switch 2, Switch</span>' in html
    assert f'src="{IGDB}/t_cover_big/coaarl.jpg"' in html
    assert html.count('name="kind" value="game"') == 5


def test_the_witcher_3_gives_one_suggestion(client, igdb):
    igdb.search = "search-the-witcher-3-filtered.json"

    html = client.get("/search/suggestions?kind=game&q=the witcher 3", headers=HTMX).text

    assert re.findall(r'name="external_id" value="(\d+)"', html) == [WITCHER]


def test_the_suggestions_of_a_film_have_no_line_of_details(client):
    html = client.get("/search?kind=movie").text

    assert "title-details" not in html


def test_without_the_keys_of_igdb_the_search_says_the_games_are_not_connected(client, igdb):
    igdb.enabled = False

    html = client.get("/search/suggestions?kind=game&q=ведьмак", headers=HTMX).text

    assert NOT_CONNECTED in html and 'role="alert"' not in html and "title-row" not in html


def test_a_failure_of_igdb_names_it(client, igdb):
    igdb.failing = True

    html = client.get("/search/suggestions?kind=game&q=ведьмак", headers=HTMX).text

    assert "Не удалось связаться с IGDB" in html and 'role="alert"' in html


def test_add_leads_to_the_card_with_the_line_and_the_game_is_then_in_the_list(client):
    answer = client.post("/titles", data={"kind": "game", "external_id": WITCHER, "q": "ведьмак"})

    assert answer.status_code == 303
    card = client.get(answer.headers["location"]).text
    assert "Добавлено в список" in card and "Отметьте сезоны" not in card
    assert "<h1>Ведьмак 3: Дикая охота</h1>" in card
    again = client.get("/search/suggestions?kind=game&q=ведьмак", headers=HTMX).text
    assert re.search(rf'<a class="row-action button-link" href="{answer.headers["location"]}">В списке</a>', again)


# ---- the card ------------------------------------------------------------------------------------------------------


def test_the_card_of_a_game_has_its_facts_its_platforms_and_its_stores(tracker, client):
    witcher = add(tracker, WITCHER)

    html = client.get(f"/titles/{witcher}").text

    assert "<h1>Ведьмак 3: Дикая охота</h1>" in html and "The Witcher 3: Wild Hunt" in html
    assert "🎮 Игра · 2015 · Ролевая, Приключения" in html and "Статус:</span> Хочу" in html
    assert f'src="{IGDB}/t_cover_big_2x/coaarl.jpg"' in html
    assert "<h2 id=\"platforms-heading\">Платформы</h2>" in html
    assert "Галочка — «играю здесь»: о выходе на отмеченных платформах придёт сообщение; у ПК — ещё цены и скидки Steam" in html
    assert marks(html) == [
        ("ПК — 19 мая 2015", True, f"/titles/{witcher}/platforms/pc"),
        ("PS5 — 19 мая 2015 (версия для PS4)", True, f"/titles/{witcher}/platforms/ps5"),
    ]
    assert re.findall(r'<a class="button-link" href="([^"]+)" target="_blank" rel="noopener">([^<]+)</a>', html) == [
        ("https://store.steampowered.com/app/292030/", "Открыть в Steam"),
        ("https://store.playstation.com/en-il/concept/204794", "Открыть в PlayStation Store"),
    ]
    assert "Премьера в кино" not in html and "Цифровой релиз" not in html and "Сезоны" not in html
    assert "Оценка" not in html  # not in the archive


def test_a_mark_goes_off_without_a_reload_and_a_repeat_changes_nothing(tracker, client, session_factory):
    witcher = add(tracker, WITCHER)

    answer = client.post(f"/titles/{witcher}/platforms/ps5", headers=HTMX)

    assert answer.status_code == 200 and "<html" not in answer.text and 'id="card"' in answer.text
    assert playing(session_factory, witcher) == {"pc": True, "ps5": False}
    assert [(text, checked) for text, checked, _ in marks(answer.text)] == [
        ("ПК — 19 мая 2015", True), ("PS5 — 19 мая 2015 (версия для PS4)", False),
    ]
    again = client.post(f"/titles/{witcher}/platforms/ps5", headers=HTMX)
    assert again.status_code == 200 and playing(session_factory, witcher) == {"pc": True, "ps5": False}
    assert PLATFORM_GONE not in again.text
    back = client.post(f"/titles/{witcher}/platforms/ps5", data={"playing": "1"}, headers=HTMX)
    assert playing(session_factory, witcher) == {"pc": True, "ps5": True} and marks(back.text)[1][1] is True
    assert marks(client.get(f"/titles/{witcher}").text)[1][1] is True  # a reload shows what was saved


def test_a_mark_without_htmx_is_a_303_to_the_card(tracker, client, session_factory):
    witcher = add(tracker, WITCHER)

    answer = client.post(f"/titles/{witcher}/platforms/pc")

    assert answer.status_code == 303 and answer.headers["location"] == f"/titles/{witcher}"
    assert playing(session_factory, witcher)["pc"] is False


@pytest.mark.parametrize("platform", ["ps4", "abc", "PS5"])
def test_a_platform_the_game_does_not_have_is_the_fresh_card_with_a_line(tracker, client, session_factory, platform):
    witcher = add(tracker, WITCHER)

    answer = client.post(f"/titles/{witcher}/platforms/{platform}", headers=HTMX)

    assert answer.status_code == 200 and PLATFORM_GONE in answer.text and 'id="card"' in answer.text
    assert playing(session_factory, witcher) == {"pc": True, "ps5": True}


def test_a_platform_igdb_took_away_is_the_fresh_card_with_a_line_and_keeps_its_row(
    tracker, client, session_factory
):
    witcher = add(tracker, WITCHER)
    with session_factory() as session:  # IGDB no longer lists PS4 and PS5; the row of PS5 stays
        stored = session.scalars(select(SourceSnapshot)).one()
        before = GameState.from_state(stored.state)
        stored.state = replace(
            before,
            platforms=tuple(p for p in before.platforms if p not in (48, 167)),
            releases=tuple(r for r in before.releases if r.platform not in (48, 167)),
        ).state()
        session.commit()

    answer = client.post(f"/titles/{witcher}/platforms/ps5", headers=HTMX)

    assert answer.status_code == 200 and PLATFORM_GONE in answer.text and 'id="card"' in answer.text
    assert playing(session_factory, witcher) == {"pc": True, "ps5": True}


def test_a_platform_of_a_film_is_a_platform_that_is_gone(tracker, client):
    film = add(tracker, "1", "movie")

    answer = client.post(f"/titles/{film}/platforms/pc", data={"playing": "1"}, headers=HTMX)

    assert PLATFORM_GONE in answer.text and "Премьера в кино: 12 марта 2027" in answer.text


def test_a_platform_gone_without_htmx_shows_the_line_once_on_the_card(tracker, client):
    witcher = add(tracker, WITCHER)

    answer = client.post(f"/titles/{witcher}/platforms/ps4")

    assert answer.status_code == 303
    assert client.get(f"/titles/{witcher}").text.count(PLATFORM_GONE) == 1
    assert PLATFORM_GONE not in client.get(f"/titles/{witcher}").text


def test_a_mark_of_a_deleted_game_is_the_gone_fragment(tracker, client):
    witcher = add(tracker, WITCHER)
    run(tracker.delete_title(witcher))

    answer = client.post(f"/titles/{witcher}/platforms/pc", headers=HTMX)

    assert answer.status_code == 200 and GONE in answer.text


def test_a_number_too_long_does_not_reach_the_core(tracker, client, monkeypatch):
    asked = []
    monkeypatch.setattr(Tracker, "set_platform_playing", lambda self, *args: asked.append(args))
    monkeypatch.setattr(Tracker, "mark_started", lambda self, *args: asked.append(args))

    for path in ("/titles/1234567890123/platforms/pc", "/titles/1234567890123/started"):
        assert GONE in client.post(path, headers=HTMX).text
    assert asked == []


def test_a_game_on_none_of_the_tracker_platforms_says_so(tracker, client):
    lonely = add(tracker, NOWHERE)

    html = client.get(f"/titles/{lonely}").text

    assert '<p class="platform-note">Платформы пока не объявлены</p>' in html
    assert marks(html) == [] and "Галочка — «играю здесь»" not in html and "store-links" not in html


def test_a_game_on_none_of_my_platforms_links_the_word_to_the_settings(tracker, client, session_factory):
    bloodborne = add(tracker, BLOODBORNE)
    set_my_platforms(session_factory, "xbox_series")

    html = client.get(f"/titles/{bloodborne}").text

    assert (
        '<p class="platform-note">Игры нет на ваших платформах — выбрать платформы можно в <a href="/settings">Настройках</a></p>'
    ) in html
    assert marks(html) == [] and "store-links" not in html


def test_without_the_platform_of_a_store_its_link_is_not_there(tracker, client, session_factory):
    witcher = add(tracker, WITCHER)
    set_my_platforms(session_factory, "pc")

    html = client.get(f"/titles/{witcher}").text

    assert [text for text, _, _ in marks(html)] == ["ПК — 19 мая 2015"]
    assert "Открыть в Steam" in html and "Открыть в PlayStation Store" not in html


def test_a_game_without_a_steam_number_has_only_playstation_store(tracker, client):
    html = client.get(f"/titles/{add(tracker, BLOODBORNE)}").text

    assert "Открыть в Steam" not in html
    assert 'href="https://store.playstation.com/en-il/concept/200520" target="_blank" rel="noopener"' in html


def test_the_buttons_of_a_game_in_each_status(tracker, client):
    witcher = add(tracker, WITCHER)
    card = f"/titles/{witcher}"

    assert buttons(client.get(card).text) == ["Начал играть", "Прошёл", "Бросил", "Да, удалить", "Удалить"]

    html = client.post(f"{card}/started", headers=HTMX).text
    assert status_of(tracker, witcher) == TitleStatus.IN_PROGRESS and "Статус:</span> В процессе" in html
    assert buttons(html) == ["Прошёл", "Бросил", "Да, удалить", "Удалить"]

    html = client.post(f"{card}/watched", headers=HTMX).text
    assert status_of(tracker, witcher) == TitleStatus.COMPLETED and "Статус:</span> Пройдено" in html
    assert buttons(html) == ["Вернуть в список", "Да, удалить", "Удалить"]
    assert re.search(r'<select name="score">\s*<option value="" selected>—</option>', html)
    assert len(re.findall(r"<option ", html)) == 29  # «—» and the 28 steps, as a film has
    assert marks(html)  # the platforms stay on the card

    html = client.post(f"{card}/restore", headers=HTMX).text
    assert status_of(tracker, witcher) == TitleStatus.WANT
    assert buttons(html) == ["Начал играть", "Прошёл", "Бросил", "Да, удалить", "Удалить"]

    html = client.post(f"{card}/dropped", headers=HTMX).text
    assert status_of(tracker, witcher) == TitleStatus.DROPPED and "Статус:</span> Бросил" in html
    assert buttons(html) == ["Вернуть в список", "Да, удалить", "Удалить"]


def test_finished_straight_from_want_and_the_score_of_the_archive(tracker, client):
    hades = add(tracker, HADES)

    client.post(f"/titles/{hades}/watched", headers=HTMX)
    html = client.post(f"/titles/{hades}/score", data={"score": "28"}, headers=HTMX).text

    assert status_of(tracker, hades) == TitleStatus.COMPLETED
    assert re.search(r'<option value="28" selected>', html)


def test_started_twice_and_started_after_finishing_change_nothing(tracker, client):
    witcher = add(tracker, WITCHER)
    client.post(f"/titles/{witcher}/started", headers=HTMX)

    again = client.post(f"/titles/{witcher}/started", headers=HTMX)

    assert again.status_code == 200 and status_of(tracker, witcher) == TitleStatus.IN_PROGRESS
    client.post(f"/titles/{witcher}/watched", headers=HTMX)
    client.post(f"/titles/{witcher}/started", headers=HTMX)
    assert status_of(tracker, witcher) == TitleStatus.COMPLETED


def test_started_on_a_film_changes_nothing_and_answers_with_the_fresh_card(tracker, client):
    film = add(tracker, "1", "movie")

    answer = client.post(f"/titles/{film}/started", headers=HTMX)

    assert answer.status_code == 200 and 'id="card"' in answer.text
    assert status_of(tracker, film) == TitleStatus.WANT
    assert buttons(answer.text) == ["Посмотрел", "Бросил", "Да, удалить", "Удалить"]


def test_the_buttons_of_a_film_did_not_change(tracker, client):
    film = add(tracker, "1", "movie")

    assert buttons(client.get(f"/titles/{film}").text) == ["Посмотрел", "Бросил", "Да, удалить", "Удалить"]
    html = client.post(f"/titles/{film}/watched", headers=HTMX).text
    assert buttons(html) == ["Вернуть в список", "Да, удалить", "Удалить"]
    assert "Платформы" not in html and "platform-note" not in html


def test_started_without_htmx_is_a_303_to_the_card(tracker, client):
    witcher = add(tracker, WITCHER)

    answer = client.post(f"/titles/{witcher}/started")

    assert answer.status_code == 303 and answer.headers["location"] == f"/titles/{witcher}"


def test_a_name_with_markup_is_text_on_the_card_and_in_the_search(tracker, client):
    nasty = add(tracker, NASTY)

    html = client.get(f"/titles/{nasty}").text

    assert "<script>alert" not in html and "&lt;script&gt;alert(&#34;x&#34;)&lt;/script&gt;" in html


def test_the_card_template_compares_no_kind_and_no_status():
    for name in ("card.html", "card_body.html"):
        source = (WEB / "templates" / name).read_text(encoding="utf-8")
        statements = re.findall(r"\{%(.*?)%\}", source, re.S)
        assert [s for s in statements if re.search(r"\b(kind|status)\b", s)] == [], name


# ---- the list and the archive --------------------------------------------------------------------------------------


def row_names(html):
    return re.findall(r'<span class="title-name"><span aria-hidden="true">[^<]*</span> ([^<]*)</span>', html)


def filter_labels(html, label):
    row = re.search(rf'<nav class="filters" aria-label="{label}">(.*?)</nav>', html, re.S).group(1)
    return re.findall(r">([^<]+)</a>", row)


def test_the_list_has_games_and_completed(tracker, client):
    witcher = add(tracker, WITCHER)
    add(tracker, "1", "movie")

    html = client.get("/list").text

    assert filter_labels(html, "Тип") == ["Все", "Фильмы", "Сериалы", "Аниме", "Игры"]
    statuses = filter_labels(html, "Статус")
    assert statuses.index("Пройдено") == statuses.index("Просмотрено") + 1
    assert f'src="{IGDB}/t_cover_big/coaarl.jpg"' in html
    assert row_names(client.get("/list?kind=game").text) == ["Ведьмак 3: Дикая охота"]
    client.post(f"/titles/{witcher}/watched", headers=HTMX)
    assert row_names(client.get("/list?status=completed").text) == ["Ведьмак 3: Дикая охота"]
    assert row_names(client.get("/list").text) == ["Дюна"]


def test_the_archive_has_games_completed_their_genres_and_their_score(tracker, client):
    witcher, film = add(tracker, WITCHER), add(tracker, "1", "movie")
    client.post(f"/titles/{witcher}/watched", headers=HTMX)
    client.post(f"/titles/{witcher}/score", data={"score": "30"}, headers=HTMX)
    client.post(f"/titles/{film}/watched", headers=HTMX)

    html = client.get("/archive").text

    assert filter_labels(html, "Тип") == ["Все", "Фильмы", "Сериалы", "Аниме", "Игры"]
    assert filter_labels(html, "Статус") == ["Весь архив", "Просмотрено", "Пройдено", "Бросил"]
    genres = filter_labels(html, "Жанр")
    assert [g.casefold() for g in genres].count("приключения") == 1  # one genre of TMDb and of IGDB
    assert "Ролевая" in genres
    assert row_names(client.get("/archive?kind=game").text) == ["Ведьмак 3: Дикая охота"]
    assert row_names(client.get("/archive?status=completed").text) == ["Ведьмак 3: Дикая охота"]
    assert re.search(r'row-score">10<', client.get("/archive?kind=game").text)
    assert filter_labels(client.get("/archive?kind=game").text, "Жанр") == ["Все жанры", "Приключения", "Ролевая"]


def test_an_empty_archive_says_completed_gets_there_too(client):
    assert "В архиве пока ничего нет. Сюда попадает просмотренное, пройденное и брошенное" in client.get("/archive").text


# ---- the covers and the header -------------------------------------------------------------------------------------


def test_img_src_has_igdb(client):
    policy = client.get("/").headers["Content-Security-Policy"]

    assert re.search(r"img-src 'self' https://image\.tmdb\.org https://images\.igdb\.com https://shikimori\.io", policy)
