"""The two downloads of the Settings block (spec 3 of stage 7.1): both addresses are behind the sign-in, the headers
(`attachment`, the name with the owner's date, the types), the bytes the core built, the buttons and the hint on the page,
and a failed export giving the page of an unexpected error and an error line in the log. On the real core."""

import html
import json
import logging
from datetime import datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.runtime import Health
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import Title, TitleKind, TitleStatus
from app.web import create_web_app

PASSWORD = "correct horse battery"
MOSCOW = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 10, 29, 22, 30, tzinfo=timezone.utc)  # the 30th in Moscow
HINT = (
    "CSV открывается в Excel: один тайтл — одна строка. JSON — все данные целиком, на память или для переноса. "
    "Загрузить выгрузку обратно нельзя: данные возвращают из копии базы."
)


class FakeSender:
    async def send(self, message, actions=()):
        pass


@pytest.fixture
def tracker(tmp_path):
    factory = create_session_factory(f"sqlite:///{(tmp_path / 'tracker.db').as_posix()}")
    with factory() as session:
        session.add(Title(
            kind=TitleKind.MOVIE, name="Дюна", original_name="Dune", year=2021, genres=[], poster_path=None, overview=None,
            status=TitleStatus.WANT, tracking_enabled=True, added_at=datetime(2026, 10, 1, 12, 0),
            status_changed_at=datetime(2026, 10, 1, 12, 0), score=None,
        ))
        session.commit()
    return Tracker(factory, clock=lambda: NOW, sender=FakeSender(), default_tz=MOSCOW)


def make_client(tracker, tmp_path, **options):
    health = Health()
    health.bot_running = health.scheduler_running = True
    health.scheduler_mark = health.clock()
    app = create_web_app(health=health.report, password=PASSWORD, secret_file=tmp_path / "web_secret", tracker=tracker)
    return TestClient(app, follow_redirects=False, **options)


@pytest.fixture
def client(tracker, tmp_path):
    client = make_client(tracker, tmp_path)
    assert client.post("/login", data={"password": PASSWORD}).status_code == 303
    return client


@pytest.mark.parametrize("address", ["/settings/export.csv", "/settings/export.json"])
def test_the_downloads_need_the_sign_in(tracker, tmp_path, address):
    response = make_client(tracker, tmp_path).get(address)
    assert response.status_code == 303 and response.headers["location"].startswith("/login")
    assert "Дюна" not in response.text


def test_the_csv_is_an_attachment_with_the_owners_date(client):
    response = client.get("/settings/export.csv")
    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="tracker-list-2026-10-30.csv"'
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert response.content.decode("utf-8-sig").split("\r\n")[1] == "Дюна;Dune;Фильм;Хочу;;2021;01.10.2026;"


def test_the_json_is_an_attachment_with_the_owners_date(client):
    response = client.get("/settings/export.json")
    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="tracker-all-2026-10-30.json"'
    assert response.headers["content-type"] == "application/json"
    document = json.loads(response.content)
    assert document["format"] == "release-tracker-export" and document["titles"][0]["name"] == "Дюна"


def test_the_page_has_the_buttons_and_the_hint(client):
    page = html.unescape(client.get("/settings").text)
    assert 'href="/settings/export.csv"' in page and "Скачать список (CSV)" in page
    assert 'href="/settings/export.json"' in page and "Скачать всё (JSON)" in page
    assert HINT in page
    assert page.index("Сделать копию сейчас") < page.index("Скачать список (CSV)") < page.index(HINT)


@pytest.mark.parametrize(
    ("address", "method"), [("/settings/export.csv", "export_list"), ("/settings/export.json", "export_all")]
)
def test_a_failed_export_gives_the_error_page_and_a_log_line(client, tracker, caplog, address, method):
    async def broken():
        raise RuntimeError("the database went away")

    with patch.object(tracker, method, broken), caplog.at_level(logging.ERROR):
        response = client.get(address)
    assert response.status_code == 500 and "attachment" not in response.headers.get("content-disposition", "")
    assert "Не получилось" in response.text
    assert any(
        record.levelno == logging.ERROR and "unexpected error" in record.getMessage() and address in record.getMessage()
        for record in caplog.records
    )
