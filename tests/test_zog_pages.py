"""ZoG pages and the client (spec 5.6, 5.7 of stage 9.1b, ticket 05): every saved page read into its fan support,
«Ошибка» and an unreadable layout told apart, the entry rules (another platform, «текстуры», «для Phantom Liberty», other
languages), the year; the addresses and their variants, the match key and the year rule, `page_of`; the client on a
fake transport (a `windows-1251` body, a redirect, a timeout, 500, the `User-Agent`).
"""

import asyncio
from pathlib import Path

import httpx
import pytest

from app.providers.zog import USER_AGENT, ZogError, ZogProvider
from app.tracker.russian import Support
from app.tracker.sources import zog_pages
from app.tracker.sources.zog_pages import GamePage, UnreadablePage, addresses, matches, page_of, read_page

PAGES = Path(__file__).parent / "fixtures" / "zog"
BOTH = Support(True, True)
TEXT = Support(True, False)
VOICE = Support(False, True)
NO = Support(False, False)


def saved(name: str) -> str:
    return (PAGES / f"{name}.html").read_bytes().decode("windows-1251")


# --- the saved pages ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "page, name, year, support",
    [
        ("baldurs_gate_3", "Baldur’s Gate 3", 2023, BOTH),  # PC text «исправление официального», neural voice
        ("hades_2", "Hades 2", 2025, VOICE),
        ("lorelei_and_the_laser_eyes", "Lorelei and the Laser Eyes", 2024, TEXT),  # its Switch entry not counted
        ("split_fiction", "Split Fiction", 2025, BOTH),  # «текст и звук»
        ("lies_of_p", "Lies of P", 2023, VOICE),  # «текстуры» not counted
        ("disco_elysium", "Disco Elysium", 2019, VOICE),
        ("cyberpunk_2077", "Cyberpunk 2077", 2020, VOICE),  # «для Phantom Liberty»
        ("prey", "Prey", 2006, BOTH),  # no platform named
        ("stray", "Stray", 2022, NO),  # only «Українізатор»
        ("astro_bot", "Astro Bot", 2024, NO),  # no «Переводы:»
    ],
)
def test_every_saved_page_gives_its_support(page, name, year, support):
    assert read_page(saved(page)) == GamePage(name, year, support)


def test_the_error_page_is_no_page():
    assert read_page(saved("the_witcher_3_wild_hunt")) is None


@pytest.mark.parametrize(
    "text",
    [
        "<html><title>Zone of Games — главная</title></html>",
        "<html><body>no title at all</body></html>",
        "<title> | Игровой архив на Zone of Games</title>",
    ],
)
def test_another_title_is_an_unreadable_layout(text):
    with pytest.raises(UnreadablePage):
        read_page(text)


def page_with(entries: str, year: str = '<a href="/games/year/2024.html">1 мая 2024</a>') -> str:
    return (
        "<title>Some &amp; Game | Игровой архив на Zone of Games</title>"
        f"<td>В официальной продаже с {year}</td>"
        f"<table><tr><td><b>Переводы:</b></td></tr>{entries}</table>"
        "<table><tr><td><a href='/games/other/files/1.html'>Русификатор (текст)</a></td></tr></table>"
    )


def entry(text: str, number: int = 1) -> str:
    return f"<tr><td><a href='/games/some_game/files/{number}.html'>{text}</a></td></tr>"


def test_translations_without_an_entry_link_are_unreadable_and_the_name_opens_entities():
    page = read_page(page_with("<tr><td>nothing here</td></tr>"))

    assert page == GamePage("Some & Game", 2024, None)


def test_the_entries_end_at_the_table_and_the_year_may_be_missing():
    page = read_page(page_with(entry("Українізатор (текст)"), year="скоро"))

    assert page == GamePage("Some & Game", None, NO)  # the entry of the next table is not read


@pytest.mark.parametrize(
    "text, parts",
    [
        ("Русификатор (текст) - для ПК-версии", TEXT),
        ("Русификатор (звук) - озвучено нейросетью", VOICE),
        ("Русификатор (текст и звук) - для ПК-версии (Mechanics VoiceOver)", BOTH),
        ("Русификатор (звук) - для Phantom Liberty (DreamVoice)", VOICE),
        ("Русификатор (текст) - оригинальный", TEXT),
        ("Русификатор (текст) - для Switch-версии", None),
        ("Русификатор (звук) - для Mac-версии", None),
        ("Русификатор (текст) - для PS4-версии", None),
        # a platform of two words or two platforms (review 9.1b, F1): another platform unless ПК is one of them
        ("Русификатор (текст) - для Xbox 360-версии", None),
        ("Русификатор (текст) - для Nintendo Switch-версии", None),
        ("Русификатор (звук) - для PS Vita-версии (GamesVoice)", None),
        ("Русификатор (текст) - для PS4- и PS5-версий", None),
        ("Русификатор (текст) - для ПК- и Switch-версий", TEXT),
        ("Русификатор (текстуры) - для ПК-версии", None),
        ("Русификатор (видео)", None),
        ("Українізатор (текст) - для ПК-версии", None),
        ("Беларусізатар (текст) - для ПК-версии", None),
        ("Русификатор текст", None),
    ],
)
def test_the_entry_rules(text, parts):
    assert zog_pages.entry_parts(text) == parts


def test_entries_add_up_and_another_platform_adds_nothing():
    entries = entry("Русификатор (текст) - для Switch-версии", 1) + entry("Русификатор (звук) - для ПК-версии", 2)

    assert read_page(page_with(entries)).support == VOICE


# --- addresses and the match ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Baldur's Gate III", ["baldurs_gate_iii", "baldurs_gate_3"]),
        ("Hades II", ["hades_ii", "hades_2"]),
        ("The Witcher 3: Wild Hunt", ["the_witcher_3_wild_hunt", "the_witcher_iii_wild_hunt", "the_witcher_3", "the_witcher_iii"]),
        ("Prey", ["prey"]),
        ("Cyberpunk 2077", ["cyberpunk_2077"]),  # 2077 is no number word
        ("Pokémon Legends – Z-A", ["pokemon_legends_z_a", "pokemon_legends"]),
        ("Baldur’s Gate 3 - Edition", ["baldurs_gate_3_edition", "baldurs_gate_iii_edition", "baldurs_gate_3", "baldurs_gate_iii"]),
        ("Ведьмак", []),  # no Latin letter: nothing to ask
    ],
)
def test_the_addresses_in_order_each_once_at_most_four(name, expected):
    assert addresses(name) == expected


def test_the_address_of_a_name():
    assert zog_pages.address_of("S.T.A.L.K.E.R. 2: Heart of Chornobyl") == "stalker_2_heart_of_chornobyl"
    assert zog_pages.address_of("  Mount & Blade  ") == "mount_blade"


@pytest.mark.parametrize(
    "zog_name, names, expected",
    [
        ("S.T.A.L.K.E.R. 2: Heart of Chornobyl*", ("S.T.A.L.K.E.R. 2: Heart of Chornobyl",), True),
        ("Hades 2", ("Hades II",), True),
        ("Baldur’s Gate 3", ("Baldur's Gate 3",), True),
        ("The Witcher 3", ("The Witcher 3: Wild Hunt",), True),  # the name before its «:»
        ("Ведьмак 3", ("The Witcher 3: Wild Hunt", "Ведьмак 3: Дикая Охота"), True),  # the Russian name
        ("Ёлки", ("Елки",), True),
        ("Pokemon", ("Pokémon",), True),
        ("Hades", ("Hades II",), False),
        ("Stray Souls", ("Stray",), False),
    ],
)
def test_the_match_key(zog_name, names, expected):
    assert matches(GamePage(zog_name, None, NO), names, 2024) is expected


@pytest.mark.parametrize(
    "page_year, game_year, expected",
    [(2006, 2017, False), (2016, 2017, True), (2017, 2017, True), (2020, 2017, True), (None, 2017, True), (2006, None, True)],
)
def test_the_year_rule(page_year, game_year, expected):
    assert matches(GamePage("Prey", page_year, BOTH), ("Prey",), game_year) is expected


@pytest.mark.parametrize(
    "link, page",
    [
        ("https://www.zoneofgames.ru/games/baldurs_gate_3/", "baldurs_gate_3"),
        ("http://zoneofgames.ru/games/hades_2", "hades_2"),
        ("https://www.zoneofgames.ru/games/baldurs_gate_3/files/9371.html", "baldurs_gate_3"),
        ("https://www.zoneofgames.ru/games/Split_Fiction/?page=2#files", "split_fiction"),
        ("  HTTPS://WWW.ZONEOFGAMES.RU/games/stray/  ", "stray"),
        ("https://www.zoneofgames.ru/forum/index.php", None),
        ("https://www.zoneofgames.ru/games/", None),
        ("https://evil.example/games/stray/", None),
        ("https://zoneofgames.ru.evil.example/games/stray/", None),
        ("ftp://www.zoneofgames.ru/games/stray/", None),
        ("baldurs_gate_3", None),
        ("", None),
    ],
)
def test_the_page_of_a_link(link, page):
    assert page_of(link) == page


def test_the_page_url():
    assert zog_pages.page_url("baldurs_gate_3") == "https://www.zoneofgames.ru/games/baldurs_gate_3/"


# --- the client -----------------------------------------------------------------------------------------------------


def run(coroutine):
    return asyncio.run(coroutine)


def client(handler) -> ZogProvider:
    return ZogProvider(transport=httpx.MockTransport(handler))


def test_the_client_decodes_windows_1251_and_names_itself():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content="<title>Ошибка</title>".encode("windows-1251"))

    assert run(client(handler).page("baldurs_gate_3")) == "<title>Ошибка</title>"
    assert str(seen[0].url) == "https://www.zoneofgames.ru/games/baldurs_gate_3/"
    assert seen[0].headers["user-agent"] == USER_AGENT == "release-tracker (personal game tracker; one page per game a week)"


@pytest.mark.parametrize("status", [301, 302, 404, 500, 503])
def test_any_answer_but_200_is_a_failure_and_a_redirect_is_not_followed(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers={"location": "https://www.zoneofgames.ru/"})

    with pytest.raises(ZogError) as failure:
        run(client(handler).page("hades_2"))
    assert failure.value.status == status
    assert len(calls) == 1


def test_a_timeout_is_a_failure():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ZogError) as failure:
        run(client(handler).page("hades_2"))
    assert isinstance(failure.value.cause, httpx.ReadTimeout)


def test_a_page_that_is_no_address_is_not_asked():
    with pytest.raises(ValueError):
        run(client(lambda request: httpx.Response(200)).page("../admin"))
