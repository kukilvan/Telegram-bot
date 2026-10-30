"""Install on a PC and an iPhone (ticket 04 of part 5.4): the file that describes the app and the icons are served without
a sign-in, the lines of the `<head>` are on every page (also the sign-in and the «not configured» ones), the
`Content-Security-Policy` is as it was, and «← Назад» in the card leads back to the page the card was opened from."""

import asyncio
import json
import re
import struct
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.runtime import Health
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.sources.tmdb_movies import MovieSnapshot
from app.web import create_web_app
from app.web.menu import OPEN_ADDRESSES, OpenAddress

PASSWORD = "correct horse battery"
T0 = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
WEB = Path(__file__).resolve().parent.parent / "app" / "web"
HEAD_LINES = [
    '<link rel="manifest" href="/static/manifest.webmanifest">',
    '<link rel="icon" href="/static/icons/icon.svg" type="image/svg+xml">',
    '<link rel="icon" href="/static/icons/favicon-32.png" sizes="32x32" type="image/png">',
    '<link rel="apple-touch-icon" href="/static/icons/apple-touch-icon.png">',
    '<meta name="theme-color" content="#f6f6f4" media="(prefers-color-scheme: light)">',
    '<meta name="theme-color" content="#161615" media="(prefers-color-scheme: dark)">',
    '<meta name="mobile-web-app-capable" content="yes">',
    '<meta name="apple-mobile-web-app-capable" content="yes">',
    '<meta name="apple-mobile-web-app-title" content="Трекер">',
    '<meta name="apple-mobile-web-app-status-bar-style" content="default">',
]
ICON_SIZES = {
    "icon-192.png": 192, "icon-512.png": 512, "icon-maskable-512.png": 512, "apple-touch-icon.png": 180,
    "favicon-32.png": 32,
}
FILM = MovieSnapshot(external_id="1", name="Дюна", original_name="Dune", year=2021, genres=[])


class FakeSender:
    async def send(self, message, actions=()):
        pass


class FakeSource:
    source_key = "tmdb_movie"

    async def suggest(self, query):
        return []

    async def snapshot(self, external_id):
        return FILM


@pytest.fixture
def tracker():
    return Tracker(create_session_factory("sqlite://"), clock=lambda: T0, sender=FakeSender(), sources={"movie": FakeSource()})


def make_client(tmp_path, *, tracker=None, password=PASSWORD, sign_in=True):
    health = Health()
    health.bot_running = health.scheduler_running = True
    health.scheduler_mark = health.clock()
    app = create_web_app(health=health.report, password=password, secret_file=tmp_path / "web_secret", tracker=tracker)
    client = TestClient(app, follow_redirects=False)
    if sign_in:
        assert client.post("/login", data={"password": PASSWORD}).status_code == 303
    return client


@pytest.fixture
def client(tracker, tmp_path):
    return make_client(tmp_path, tracker=tracker)


@pytest.fixture
def stranger(tmp_path):
    """A browser that is not signed in: the installer of an app takes the manifest and the icons without cookies."""
    return make_client(tmp_path, sign_in=False)


def png_size(content):
    assert content[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", content[16:24])


# ---- the files ------------------------------------------------------------------------------------------------

def test_the_manifest_is_served_without_a_sign_in_as_a_manifest(stranger):
    answer = stranger.get("/static/manifest.webmanifest")

    assert answer.status_code == 200
    assert answer.headers["content-type"].startswith("application/manifest+json")
    assert "no-store" not in answer.headers.get("cache-control", "")
    manifest = json.loads(answer.content)
    assert manifest["id"] == manifest["start_url"] == manifest["scope"] == "/"
    assert manifest["name"] == "Трекер релизов" and manifest["short_name"] == "Трекер"
    assert manifest["display"] == "standalone"
    assert manifest["background_color"] == manifest["theme_color"] == "#f6f6f4"
    assert [(i["sizes"], i["purpose"]) for i in manifest["icons"]] == [
        ("192x192", "any"), ("512x512", "any"), ("512x512", "maskable"),
    ]


def test_every_icon_of_the_manifest_is_a_png_of_its_size_served_without_a_sign_in(stranger):
    manifest = json.loads(stranger.get("/static/manifest.webmanifest").content)

    for icon in manifest["icons"]:
        answer = stranger.get(icon["src"])
        side = int(icon["sizes"].split("x")[0])
        assert answer.status_code == 200 and answer.headers["content-type"] == "image/png", icon["src"]
        assert png_size(answer.content) == (side, side), icon["src"]


@pytest.mark.parametrize("name, side", ICON_SIZES.items())
def test_every_icon_is_a_png_of_its_size(stranger, name, side):
    answer = stranger.get(f"/static/icons/{name}")

    assert answer.status_code == 200
    assert png_size(answer.content) == (side, side)


def test_the_vector_icon_is_served_as_svg(stranger):
    answer = stranger.get("/static/icons/icon.svg")

    assert answer.status_code == 200
    assert answer.headers["content-type"].startswith("image/svg+xml")
    assert b"<svg" in answer.content


def test_the_manifest_and_the_icons_of_the_head_exist_as_files():
    head = (WEB / "templates" / "base.html").read_text(encoding="utf-8")

    for address in re.findall(r'href="(/static/(?:manifest|icons)/[^"]+)"', head):
        assert (WEB / address.removeprefix("/")).is_file(), address
    for icon in json.loads((WEB / "static" / "manifest.webmanifest").read_text(encoding="utf-8"))["icons"]:
        assert (WEB / icon["src"].removeprefix("/")).is_file(), icon["src"]


# ---- the head -------------------------------------------------------------------------------------------------

def test_the_head_of_every_page_has_the_lines_of_the_install(client, stranger, tracker):
    pages = {
        "behind the sign-in": client.get("/list").text,
        "the sign-in": stranger.get("/login").text,
    }

    for name, html in pages.items():
        head = html.split("</head>")[0]
        for line in HEAD_LINES:
            assert line in head, f"{name}: {line}"


def test_the_page_of_an_unset_password_has_them_too_and_the_files_are_served(tmp_path):
    client = make_client(tmp_path, password="", sign_in=False)

    page = client.get("/login")

    assert "не настроен" in page.text
    for line in HEAD_LINES:
        assert line in page.text.split("</head>")[0], line
    assert client.get("/static/manifest.webmanifest").status_code == 200
    assert client.get("/static/icons/icon-192.png").status_code == 200


def test_the_security_policy_has_no_manifest_source_of_its_own(client):
    policy = client.get("/list").headers["content-security-policy"]

    assert "manifest-src" not in policy
    assert "default-src 'self'" in policy
    assert re.search(r'<link rel="manifest" href="/static/[^"/]+">', client.get("/list").text)


def test_the_addresses_open_without_a_sign_in_are_the_same(client):
    assert OPEN_ADDRESSES == (
        OpenAddress("/health", True), OpenAddress("/static/", True), OpenAddress("/login", False),
        OpenAddress("/logout", False),
    )


# ---- «← Назад» ------------------------------------------------------------------------------------------------

def back_of(html):
    """The link above the card (outside `#card`): its address and its caption."""
    found = re.search(r'<p class="back"><a href="([^"]*)">([^<]+)</a></p>', html)
    assert found, "no back link"
    assert html.index('class="back"') < html.index('id="card"')
    return found.group(1), found.group(2)


@pytest.mark.parametrize("referer", [
    "/", "/list", "/list?status=all&order=name", "/archive?kind=movie&genre=%D0%B4%D1%80%D0%B0%D0%BC%D0%B0", "/search?q=%D0%B4%D1%8E%D0%BD%D0%B0",
])
def test_the_back_link_leads_to_the_page_the_card_was_opened_from(tracker, client, referer):
    film = asyncio.run(tracker.add_title("movie", "1")).title_id

    page = client.get(f"/titles/{film}", headers={"Referer": f"http://testserver{referer}"})

    assert back_of(page.text) == (referer.replace("&", "&amp;"), "← Назад")


@pytest.mark.parametrize("referer", [
    None, "", "http://other.example/list", "http://testserver/titles/2", "http://testserver/settings",
    "http://testserver//evil.example/list", "http://testserver//", "javascript:alert(1)", "http://testserver/list/x",
])
def test_the_back_link_without_a_good_referer_leads_to_the_list(tracker, client, referer):
    film = asyncio.run(tracker.add_title("movie", "1")).title_id
    headers = {} if referer is None else {"Referer": referer}

    page = client.get(f"/titles/{film}", headers=headers)

    assert back_of(page.text) == ("/list", "← Список")


def test_the_back_link_of_a_title_in_the_archive_leads_to_the_archive(tracker, client):
    film = asyncio.run(tracker.add_title("movie", "1")).title_id
    asyncio.run(tracker.mark_watched(film))

    page = client.get(f"/titles/{film}", headers={"Referer": "http://testserver/settings"})

    assert back_of(page.text) == ("/archive", "← Архив")


def test_the_query_of_the_referer_is_escaped_in_the_back_link(tracker, client):
    film = asyncio.run(tracker.add_title("movie", "1")).title_id

    page = client.get(f"/titles/{film}", headers={"Referer": 'http://testserver/list?q="><script>x</script>'})

    assert "<script>x" not in page.text
    assert back_of(page.text)[1] == "← Назад"


def test_a_press_on_the_card_does_not_carry_the_link(tracker, client):
    film = asyncio.run(tracker.add_title("movie", "1")).title_id

    answer = client.post(f"/titles/{film}/watched", headers={"HX-Request": "true"})

    assert answer.status_code == 200
    assert 'class="back"' not in answer.text
