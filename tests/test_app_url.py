"""`APP_URL` (stage 7.2, ticket 01, spec 1.1–1.2): the pure reading of the address (each rule fails on its own value with its
own reason, valid values come out in the one form), `Settings` reading it from the environment, the line of Settings
about it with its two hints, the log lines of the start."""

import logging
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.bot.app_links import AppLinks
from app.config import AppUrl, Settings, parse_app_url
from app.main import app_links
from app.runtime import Health
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.web import create_web_app
from app.web.address_line import address_note

NO_SCHEME = "нужно http:// или https:// в начале"
NO_HOST = "нет адреса ПК или имени сайта"
TELEGRAM = (
    "Telegram не открывает такие ссылки — укажите адрес ПК в сети (например, http://192.168.1.124:8080) "
    "или имя сайта с точкой"
)
BAD_PORT = "порт должен быть числом от 1 до 65535"
EXTRA = "после адреса не должно быть ничего лишнего: только http(s)://адрес[:порт]"
IDNA_REFUSED = "имя сайта записано с ошибкой — проверьте буквы и точки"
PASSWORD = "correct horse battery"


# --- the rules of 1.1 ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("192.168.1.124:8080", NO_SCHEME),
        ("ftp://192.168.1.124", NO_SCHEME),
        ("//tracker.example.com", NO_SCHEME),
        ("http://", NO_HOST),
        ("https:///titles", NO_HOST),
        ("http://:8080", NO_HOST),
        ("http://localhost:8080", TELEGRAM),
        ("http://LOCALHOST", TELEGRAM),
        ("http://tracker.localhost", TELEGRAM),
        ("http://tracker", TELEGRAM),
        ("http://.example.com", TELEGRAM),
        ("http://example.com.", TELEGRAM),
        ("http://a..b", TELEGRAM),
        ("http://tracker .example.com", TELEGRAM),
        ("http://[not-an-address]", TELEGRAM),
        ("http://[::1", TELEGRAM),
        ("http://192.168.1.124:0", BAD_PORT),
        ("http://192.168.1.124:65536", BAD_PORT),
        ("http://192.168.1.124:http", BAD_PORT),
        ("http://192.168.1.124:", BAD_PORT),
        ("http://[::1]:abc", BAD_PORT),
        ("http://192.168.1.124/app", EXTRA),
        ("http://192.168.1.124:8080//", EXTRA),
        ("https://tracker.example.com?x=1", EXTRA),
        ("https://tracker.example.com#top", EXTRA),
        ("https://owner@tracker.example.com", EXTRA),
        ("http://[::1]x", EXTRA),
    ],
)
def test_a_broken_rule_gives_no_address_and_its_own_reason(raw, reason):
    result = parse_app_url(raw)

    assert result == AppUrl(address=None, reason=reason, host=None)


def test_the_first_broken_rule_is_the_reason_when_several_are_broken():
    assert parse_app_url("ftp://localhost:99999/x").reason == NO_SCHEME
    assert parse_app_url("http://localhost:99999/x").reason == TELEGRAM
    assert parse_app_url("http://tracker.example.com:99999/x").reason == BAD_PORT


@pytest.mark.parametrize(
    ("raw", "address"),
    [
        ("http://192.168.1.124:8080", "http://192.168.1.124:8080"),
        ("  http://192.168.1.124:8080  ", "http://192.168.1.124:8080"),
        ("http://127.0.0.1:8080", "http://127.0.0.1:8080"),
        ("HTTP://Tracker.Example.com/", "http://tracker.example.com"),
        ("https://tracker.example.com", "https://tracker.example.com"),
        ("HTTPS://TRACKER.EXAMPLE.COM:8443/", "https://tracker.example.com:8443"),
        ("http://my-pc.lan:08080", "http://my-pc.lan:08080"),  # the port as written
        ("http://[::1]:8080", "http://[::1]:8080"),
        ("http://[FD00::1]/", "http://[fd00::1]"),
    ],
)
def test_a_valid_address_comes_out_in_the_one_form(raw, address):
    result = parse_app_url(raw)

    assert result.address == address and result.reason is None


def test_the_host_of_an_address_is_kept_without_brackets_and_in_lower_case():
    assert parse_app_url("http://192.168.1.124:8080").host == "192.168.1.124"
    assert parse_app_url("https://Tracker.Example.com").host == "tracker.example.com"
    assert parse_app_url("http://[::1]:80").host == "::1"


@pytest.mark.parametrize("raw", ["", " ", "\t"])
def test_an_empty_line_is_no_address_and_no_reason(raw):
    assert parse_app_url(raw) == AppUrl()


# --- Settings and the start -------------------------------------------------------------------------------------------


def settings_with(monkeypatch, **env):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TEST")
    monkeypatch.setenv("TMDB_API_KEY", "key")
    for name in ("APP_URL",):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return Settings(_env_file=None)


def test_settings_read_app_url_from_the_environment(monkeypatch):
    settings = settings_with(monkeypatch, APP_URL=" HTTP://192.168.1.124:8080/ ")

    assert settings.app_url_reading.address == "http://192.168.1.124:8080"


def test_settings_without_app_url_have_no_address(monkeypatch):
    assert settings_with(monkeypatch).app_url_reading == AppUrl()


def test_a_valid_address_turns_link_mode_on_and_the_log_says_so_without_the_address(caplog):
    with caplog.at_level(logging.INFO):
        links = app_links(parse_app_url("http://192.168.1.124:8080"))

    assert links == AppLinks("http://192.168.1.124:8080")
    assert [r.getMessage() for r in caplog.records] == ["APP_URL: ссылки бота ведут в приложение"]
    assert "192.168" not in caplog.text


def test_a_malformed_address_keeps_chat_mode_and_warns_with_the_reason(caplog):
    with caplog.at_level(logging.INFO):
        links = app_links(parse_app_url("http://localhost:8080"))

    assert links is None
    (record,) = caplog.records
    assert record.levelno == logging.WARNING
    assert record.getMessage() == f"APP_URL: {TELEGRAM} — адрес не используется, кнопки «Карточка» показывают карточку в чате"


def test_no_address_keeps_chat_mode_quietly(caplog):
    with caplog.at_level(logging.INFO):
        assert app_links(parse_app_url("")) is None

    assert caplog.records == []


# --- the line of Settings (1.2) ---------------------------------------------------------------------------------------

ADDRESS_LINE = "Адрес приложения: {}. Кнопки «Карточка» в сообщениях бота открывают его."
NO_ADDRESS_LINE = "Адрес приложения не задан (строка APP_URL в .env): кнопки «Карточка» показывают карточку в чате."
HINT_NETWORK = (
    "Адрес — в домашней сети, а приложение открыто только этому ПК: "
    "добавьте в .env строку WEB_HOST=0.0.0.0 и запустите .\\start-bot.ps1."
)
HINT_LOOPBACK = "Адрес 127.0.0.1 открывается только на этом ПК: на телефоне кнопки не откроются."


def test_the_three_states_have_their_lines_and_no_hint():
    ok = address_note(parse_app_url("https://tracker.example.com"), "")
    none = address_note(parse_app_url(""), "")
    bad = address_note(parse_app_url("http://tracker"), "")

    assert ok == (ADDRESS_LINE.format("https://tracker.example.com"), "")
    assert none == (NO_ADDRESS_LINE, "")
    assert bad == (
        f"Адрес приложения в .env (APP_URL) записан с ошибкой: {TELEGRAM}. "
        "Пока кнопки «Карточка» показывают карточку в чате.",
        "",
    )


@pytest.mark.parametrize("host", ["10.0.0.5", "172.16.0.1", "172.31.255.1", "192.168.1.124"])
def test_a_private_address_with_the_web_closed_to_the_network_gets_the_hint(host):
    note = address_note(parse_app_url(f"http://{host}:8080"), "127.0.0.1")

    assert note.hint == HINT_NETWORK
    assert address_note(parse_app_url(f"http://{host}:8080"), "").hint == HINT_NETWORK  # WEB_HOST not set at all


def test_the_hint_goes_when_the_web_is_open_to_the_network():
    assert address_note(parse_app_url("http://192.168.1.124:8080"), "0.0.0.0").hint == ""
    assert address_note(parse_app_url("http://192.168.1.124:8080"), " 0.0.0.0 ").hint == ""


@pytest.mark.parametrize("host", ["172.15.0.1", "172.32.0.1", "11.0.0.1", "8.8.8.8", "tracker.example.com"])
def test_an_address_outside_the_private_networks_gets_no_network_hint(host):
    assert address_note(parse_app_url(f"http://{host}"), "").hint == ""


def test_the_loopback_address_gets_its_own_hint_whatever_web_host_says():
    assert address_note(parse_app_url("http://127.0.0.1:8080"), "").hint == HINT_LOOPBACK
    assert address_note(parse_app_url("http://127.0.0.1:8080"), "0.0.0.0").hint == HINT_LOOPBACK


# --- the page --------------------------------------------------------------------------------------------------------


class FakeSender:
    async def send(self, message, actions=()):
        pass


@pytest.fixture
def tracker():
    return Tracker(
        create_session_factory("sqlite://"), clock=lambda: datetime(2026, 10, 29, 19, 10, tzinfo=timezone.utc),
        sender=FakeSender(), sources={}, default_tz=ZoneInfo("Europe/Moscow"),
    )


def settings_page(tracker, tmp_path, **kwargs):
    health = Health()
    health.bot_running = health.scheduler_running = True
    health.scheduler_mark = health.clock()
    app = create_web_app(
        health=health.report, password=PASSWORD, secret_file=tmp_path / "web_secret", tracker=tracker, **kwargs
    )
    client = TestClient(app, follow_redirects=False)
    assert client.post("/login", data={"password": PASSWORD}).status_code == 303
    page = client.get("/settings")
    assert page.status_code == 200
    return page.text


def lines_under_telegram(html):
    block = html.split("<h2>Бот в Telegram</h2>")[1].split("<h3>")[0]  # the lines of the state; the test forms follow
    return re.findall(r'<p class="([^"]*)">([^<]*)</p>', block)


def test_the_page_shows_the_address_line_under_the_state_of_the_bot(tracker, tmp_path):
    html = settings_page(
        tracker, tmp_path, app_url=parse_app_url("http://192.168.1.124:8080"), web_host="0.0.0.0"
    )

    assert lines_under_telegram(html) == [
        ("telegram-state", "Подключён"), ("app-address", ADDRESS_LINE.format("http://192.168.1.124:8080")),
    ]


def test_the_page_shows_the_hint_under_the_line_when_one_applies(tracker, tmp_path):
    html = settings_page(tracker, tmp_path, app_url=parse_app_url("http://192.168.1.124:8080"), web_host="")

    assert lines_under_telegram(html)[-1] == ("hint app-address-hint", HINT_NETWORK.replace("&", "&amp;"))


def test_the_page_says_no_address_without_the_line_of_env(tracker, tmp_path):
    html = settings_page(tracker, tmp_path)

    assert ("app-address", NO_ADDRESS_LINE) in lines_under_telegram(html)


def test_a_malformed_address_never_breaks_the_page(tracker, tmp_path):
    html = settings_page(tracker, tmp_path, app_url=parse_app_url("http://localhost:8080"))

    assert "записан с ошибкой: Telegram не открывает такие ссылки" in html


# --- a Cyrillic name (KI-76) ---------------------------------------------------------------------------------------------


def test_a_cyrillic_name_is_taken_in_its_ascii_form_and_shown_as_written_in_lower_case():
    url = parse_app_url("https://Трекер.РФ")

    assert url == AppUrl(
        address="https://xn--e1aaowdh.xn--p1ai", host="xn--e1aaowdh.xn--p1ai", shown="https://трекер.рф"
    )


def test_a_cyrillic_name_with_a_port_keeps_the_port_and_a_slash_at_the_end_goes():
    url = parse_app_url("https://ТРЕКЕР.РФ:8443/")

    assert (url.address, url.shown) == ("https://xn--e1aaowdh.xn--p1ai:8443", "https://трекер.рф:8443")


def test_the_name_the_live_telegram_check_used_comes_out_as_it_was_sent():
    # `answers/telegram-xn-button-2026-11-22.json`: Telegram took exactly this address
    assert parse_app_url("https://пример-трекера.рф").address == "https://xn----8sbnbaormzkdbdx.xn--p1ai"


def test_a_name_with_latin_and_cyrillic_labels_works():
    url = parse_app_url("https://tracker.РФ.example.com")

    assert (url.address, url.shown) == ("https://tracker.xn--p1ai.example.com", "https://tracker.рф.example.com")


def test_an_ascii_address_is_its_own_shown_form():
    url = parse_app_url("HTTPS://Tracker.Example.COM:8443")

    assert url.shown == url.address == "https://tracker.example.com:8443"


def test_a_cyrillic_name_without_a_dot_has_the_reason_of_a_latin_one():
    assert parse_app_url("https://трекер") == AppUrl(reason=TELEGRAM)
    assert parse_app_url("https://трекер.") == AppUrl(reason=TELEGRAM)


@pytest.mark.parametrize("raw", ["https://" + "а" * 64 + ".рф", "https://трекер!.рф", "https://тре кер.рф", "https://трекер..рф"])
def test_a_name_idna_refuses_is_malformed_with_its_own_reason(raw):
    assert parse_app_url(raw) == AppUrl(reason=IDNA_REFUSED)


def test_the_settings_line_shows_the_address_as_written_and_the_bot_gets_the_ascii_one():
    url = parse_app_url("https://трекер.рф")

    assert address_note(url, "") == (ADDRESS_LINE.format("https://трекер.рф"), "")
    assert app_links(url) == AppLinks("https://xn--e1aaowdh.xn--p1ai")


def test_the_web_answers_under_the_ascii_host_of_a_cyrillic_name(tracker, tmp_path):
    health = Health()
    health.bot_running = health.scheduler_running = True
    health.scheduler_mark = health.clock()
    app = create_web_app(
        health=health.report, password=PASSWORD, secret_file=tmp_path / "web_secret", tracker=tracker,
        app_url=parse_app_url("https://Трекер.РФ"),
    )
    client = TestClient(app, follow_redirects=False)

    assert client.get("/health", headers={"host": "xn--e1aaowdh.xn--p1ai"}).status_code == 200
    assert client.get("/health", headers={"host": "xn--other.xn--p1ai"}).status_code == 400


def test_the_page_shows_a_cyrillic_address_as_written(tracker, tmp_path):
    html = settings_page(tracker, tmp_path, app_url=parse_app_url("https://трекер.рф"))

    assert ("app-address", ADDRESS_LINE.format("https://трекер.рф")) in lines_under_telegram(html)
