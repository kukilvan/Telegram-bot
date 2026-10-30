"""The settings page in the browser (ticket 03 of part 5.4): what it shows, the save (the form as the core gets it, the
foreign values of the days dropped, «Сохранено» once), a refused form (one sentence, the field marked, everything as typed,
nothing stored), the unexpected error, the line about Telegram, the rule of the web (the page is closed without a sign-in,
reaches the core through the facade only, has no script and no `style=`). On the real core with the clock fixed."""

import ast
import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.runtime import Health
from app.tracker.core import SettingsChange, SettingsView, Tracker, ZoneOption
from app.tracker.db import create_session_factory
from app.web import create_web_app
from app.web.status_line import TELEGRAM_DOWN

PASSWORD = "correct horse battery"
MOSCOW = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 10, 29, 19, 10, tzinfo=timezone.utc)  # Thursday 22:10 in Moscow
WEB = Path(__file__).resolve().parent.parent / "app" / "web"
CLASH = "Час сводки 22:00 попадает в тихие часы 21:00–07:30 — сводка не придёт. Сдвиньте час сводки или тихие часы"
FORM = {
    "timezone": "Asia/Tokyo", "workday": ["1", "2"], "summary_at": "16:00", "quiet_from": "22:00", "quiet_until": "06:00",
    "part_gap_weeks": "8",
}


class FakeSender:
    async def send(self, message, actions=()):
        pass


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def tracker():
    return Tracker(create_session_factory("sqlite://"), clock=lambda: NOW, sender=FakeSender(), sources={}, default_tz=MOSCOW)


def make_client(tracker, tmp_path, **kwargs):
    health = Health()
    health.bot_running = health.scheduler_running = True
    health.scheduler_mark = health.clock()
    app = create_web_app(
        health=health.report, password=PASSWORD, secret_file=tmp_path / "web_secret", tracker=tracker, **kwargs
    )
    client = TestClient(app, follow_redirects=False)
    assert client.post("/login", data={"password": PASSWORD}).status_code == 303
    return client


@pytest.fixture
def client(tracker, tmp_path):
    return make_client(tracker, tmp_path)


def field(html, name):
    """The tag of the field with this id."""
    found = re.search(rf'<(?:input|select) id="{name}"[^>]*>', html)
    assert found, name
    return found.group(0)


def checked_days(html):
    return sorted(int(m.group(1)) for m in re.finditer(r'name="workday" value="(\d)" checked', html))


def selected_zone(html):
    return re.search(r'<option value="([^"]*)" selected>', html).group(1)


def invalid_fields(html):
    return sorted(re.findall(r'<(?:input|select) id="(\w+)"[^>]*aria-invalid="true"', html))


# ---- what the page shows --------------------------------------------------

def test_the_page_shows_the_defaults_the_zone_of_the_launch_file_first_and_the_line_now(client, tracker):
    view = run(tracker.settings())

    page = client.get("/settings")

    html = page.text
    assert page.status_code == 200 and "<h1>Настройки</h1>" in html and "Скоро будет" not in html
    assert '<a href="/settings" aria-current="page">Настройки</a>' in html and html.count('aria-current="page"') == 1
    assert selected_zone(html) == "" and f'<option value="" selected>{view.default_label}</option>' in html
    assert view.default_label == "Как в файле настроек запуска: Europe/Moscow (UTC+3)"
    assert checked_days(html) == sorted(view.workdays)
    assert f'value="{view.summary_at}"' in field(html, "summary_at")
    assert f'value="{view.quiet_from}"' in field(html, "quiet_from") and f'value="{view.quiet_until}"' in field(html, "quiet_until")
    assert f'value="{view.part_gap_weeks}"' in field(html, "part_gap_weeks")
    assert 'min="1"' in field(html, "part_gap_weeks") and 'max="52"' in field(html, "part_gap_weeks")
    assert view.now_line.startswith("Сейчас чт, 29 окт, 22:10") and f'<p class="now-line">{view.now_line}</p>' in html
    assert "Журнал бота пишет время" not in html
    assert '<p class="telegram-state">Подключён</p>' in html
    assert invalid_fields(html) == [] and 'role="alert"' not in html


def test_the_form_is_a_plain_post_with_a_label_for_every_field_and_the_seven_days(client):
    html = client.get("/settings").text

    assert '<form class="settings-form" method="post" action="/settings">' in html and "hx-" not in html.split("<main>")[1]
    for name in ("timezone", "summary_at", "quiet_from", "quiet_until", "part_gap_weeks"):
        assert f'<label for="{name}">' in html, name
    assert re.findall(r'name="workday" value="(\d)"', html) == list("0123456")
    for day in ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"):
        assert f"> {day}</label>" in html
    assert '<button type="submit">Сохранить</button>' in html
    assert "Новые правила действуют сразу, в том числе для того, что уже ждёт отправки" in html
    assert 'type="time" name="summary_at"' in html and 'type="number" name="part_gap_weeks"' in html


def test_the_page_shows_what_is_stored_and_says_the_log_keeps_the_zone_of_the_launch_file(client, tracker):
    run(tracker.save_settings(SettingsChange("Asia/Tokyo", [0, 4], "16:00", "22:00", "06:00", "8")))

    html = client.get("/settings").text

    assert selected_zone(html) == "Asia/Tokyo" and '<option value="Asia/Tokyo" selected>Asia/Tokyo (UTC+9)</option>' in html
    assert checked_days(html) == [0, 4]
    assert 'value="16:00"' in field(html, "summary_at") and 'value="22:00"' in field(html, "quiet_from")
    assert 'value="06:00"' in field(html, "quiet_until") and 'value="8"' in field(html, "part_gap_weeks")
    assert "Журнал бота пишет время по поясу из файла настроек запуска (Europe/Moscow)" in html
    assert "Сейчас пт, 30 окт, 04:10" in html  # Thursday 22:10 in Moscow is Friday 04:10 in Tokyo


def test_the_zone_of_the_launch_file_chosen_by_name_needs_no_note_on_the_log(client, tracker):
    run(tracker.save_settings(SettingsChange("Europe/Moscow", [0], "15:00", "21:00", "07:30", "6")))

    html = client.get("/settings").text

    assert selected_zone(html) == "Europe/Moscow" and "Журнал бота пишет время" not in html


class FakeCore:
    """Only what the page asks: a view with a zone nobody would write in a form."""

    def __init__(self, view):
        self.view = view

    async def settings(self):
        return self.view

    async def overview(self):
        raise RuntimeError("not needed")


def test_a_zone_from_the_database_is_text_on_the_page_not_markup(tmp_path):
    evil = "<script>alert(1)</script>"
    view = SettingsView(
        tz_name=evil, default_tz_name="Europe/Moscow", zones=(ZoneOption(evil, f"{evil} (UTC+0)"),),
        default_label="Как в файле настроек запуска: Europe/Moscow (UTC+3)", workdays=frozenset({0}), summary_at="15:00",
        quiet_from="21:00", quiet_until="07:30", part_gap_weeks=6, now_line="Сейчас",
    )
    client = make_client(FakeCore(view), tmp_path)

    html = client.get("/settings").text

    assert "<script>alert(1)" not in html and "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert len(re.findall(r"<script", html)) == 1  # only the page's own htmx tag


# ---- saving ---------------------------------------------------------------

class Spy:
    """Remembers what the page gave the core to store, then lets the core do it."""

    def __init__(self, tracker, monkeypatch):
        self.changes = []
        real = tracker.save_settings

        async def save_settings(change):
            self.changes.append(change)
            await real(change)

        monkeypatch.setattr(tracker, "save_settings", save_settings)


def test_saving_goes_back_to_the_page_says_saved_once_and_the_core_got_the_form_as_it_is(client, tracker, monkeypatch):
    spy = Spy(tracker, monkeypatch)

    response = client.post("/settings", data=FORM)

    assert response.status_code == 303 and response.headers["location"] == "/settings"
    assert spy.changes == [SettingsChange("Asia/Tokyo", [1, 2], "16:00", "22:00", "06:00", "8")]
    first = client.get("/settings")
    assert '<p class="notice" role="status">Сохранено</p>' in first.text and first.text.count("Сохранено") == 1
    assert "Сохранено" not in client.get("/settings").text  # shown once
    view = run(tracker.settings())
    assert (view.tz_name, sorted(view.workdays), view.summary_at, view.quiet_from, view.quiet_until, view.part_gap_weeks) == (
        "Asia/Tokyo", [1, 2], "16:00", "22:00", "06:00", 8)


def test_a_value_that_is_no_day_is_dropped_by_the_page_and_no_box_is_no_working_day(client, tracker, monkeypatch):
    spy = Spy(tracker, monkeypatch)

    client.post("/settings", data={**FORM, "workday": ["3", "7", "x", "", "-1", "3", "1"]})
    client.post("/settings", data={k: v for k, v in FORM.items() if k != "workday"})

    assert [change.workdays for change in spy.changes] == [[1, 3], []]
    assert run(tracker.settings()).workdays == frozenset()  # they are all days off


def test_saving_what_is_stored_changes_nothing_and_still_says_saved(client, tracker):
    before = run(tracker.settings())
    html = client.get("/settings").text
    same = {
        "timezone": selected_zone(html), "workday": [str(day) for day in checked_days(html)],
        "summary_at": before.summary_at, "quiet_from": before.quiet_from, "quiet_until": before.quiet_until,
        "part_gap_weeks": str(before.part_gap_weeks),
    }

    response = client.post("/settings", data=same)

    assert response.status_code == 303 and "Сохранено" in client.get("/settings").text
    assert run(tracker.settings()) == before


def test_the_first_line_of_the_list_clears_a_zone_chosen_before(client, tracker):
    client.post("/settings", data=FORM)
    assert run(tracker.settings()).tz_name == "Asia/Tokyo"

    client.post("/settings", data={**FORM, "timezone": ""})

    assert run(tracker.settings()).tz_name is None
    assert selected_zone(client.get("/settings").text) == ""


# ---- a refused form -------------------------------------------------------

def refused_page(client, **override):
    return client.post("/settings", data={**FORM, **override})


def test_a_refused_form_is_the_page_with_a_400_one_sentence_on_top_and_nothing_stored(client, tracker):
    before = run(tracker.settings())

    response = refused_page(client, summary_at="22:00", quiet_from="21:00", quiet_until="07:30")

    html = response.text
    assert response.status_code == 400
    assert f'<p class="error" role="alert">{CLASH}</p>' in html
    assert html.index(CLASH) < html.index('<form class="settings-form"')
    assert "Сохранено" not in html
    assert run(tracker.settings()) == before


def test_everything_the_owner_typed_stays_in_a_refused_form_not_what_was_stored(client, tracker):
    response = refused_page(client, summary_at="22:00", quiet_from="21:00", quiet_until="07:30")

    html = response.text
    assert selected_zone(html) == "Asia/Tokyo" and checked_days(html) == [1, 2]
    assert 'value="22:00"' in field(html, "summary_at") and 'value="21:00"' in field(html, "quiet_from")
    assert 'value="07:30"' in field(html, "quiet_until") and 'value="8"' in field(html, "part_gap_weeks")
    # «Сейчас» and the note on the log come from what is stored, not from what was typed
    stored = run(tracker.settings())
    assert stored.now_line in html and stored.tz_name is None and "Журнал бота пишет время" not in html


@pytest.mark.parametrize("override, marked, sentence", [
    ({"timezone": "Mars/Base"}, ["timezone"], "Такого часового пояса нет"),
    ({"summary_at": "25:00"}, ["summary_at"], "Час сводки: время пишется так — 15:00"),
    ({"summary_at": ""}, ["summary_at"], "Час сводки: время пишется так — 15:00"),
    ({"quiet_from": "abc"}, ["quiet_from", "quiet_until"], "Тихие часы: время пишется так — 21:00"),
    ({"part_gap_weeks": "53"}, ["part_gap_weeks"], "Части сезона: число недель — целое, от 1 до 52"),
    ({"part_gap_weeks": "2.5"}, ["part_gap_weeks"], "Части сезона: число недель — целое, от 1 до 52"),
    ({"summary_at": "22:00", "quiet_from": "21:00", "quiet_until": "07:30"}, ["summary_at"], CLASH),
])
def test_the_field_the_core_names_is_marked_and_the_others_are_not(client, override, marked, sentence):
    response = refused_page(client, **override)

    assert response.status_code == 400 and sentence in response.text
    assert invalid_fields(response.text) == sorted(marked)
    assert response.text.count('role="alert"') == 1


def test_the_first_error_is_the_one_the_page_names(client):
    html = refused_page(client, summary_at="25:00", part_gap_weeks="99").text

    assert "Час сводки: время пишется так" in html and "Части сезона" not in html


def test_a_form_with_no_fields_at_all_is_refused_by_the_core_not_dropped_by_the_page(client, tracker):
    before = run(tracker.settings())

    response = client.post("/settings", data={})

    assert response.status_code == 400 and "Час сводки: время пишется так" in response.text
    assert run(tracker.settings()) == before


# ---- the net ----------------------------------------------------------------

def test_an_unexpected_error_is_a_sentence_with_a_link_to_refresh_the_page(client, tracker, monkeypatch, caplog):
    async def broken(*args):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(tracker, "settings", broken)
    monkeypatch.setattr(tracker, "save_settings", broken)

    page = client.get("/settings")
    save = client.post("/settings", data=FORM)

    for response in (page, save):
        assert response.status_code == 500 and "Не получилось" in response.text
        assert 'href="/settings">Обновить</a>' in response.text
    assert any("unexpected error" in record.getMessage() for record in caplog.records)


# ---- the line about Telegram -------------------------------------------------

def test_while_the_bot_is_not_connected_the_sentence_stands_under_the_status_line_on_every_page(tracker, tmp_path):
    down = [True]
    client = make_client(tracker, tmp_path, telegram_down=lambda: down[0])

    on_page = client.get("/settings").text
    on_other = client.get("/nowhere").text
    fragment = client.get("/status-line")

    for html in (on_page, on_other, fragment.text):
        assert TELEGRAM_DOWN in html
    assert '<p class="telegram-state">Подключён</p>' not in on_page
    assert f'<p class="telegram-state">{TELEGRAM_DOWN}</p>' in on_page
    assert 'id="status-line"' in fragment.text and 'hx-trigger="every 60s"' in fragment.text and "<html" not in fragment.text
    assert 'role="alert"' not in re.search(r'<div id="status-line".*?</div>', on_other, re.S).group(0)
    down[0] = False  # the bot connected: the next refresh of the line drops the sentence
    assert TELEGRAM_DOWN not in client.get("/status-line").text and TELEGRAM_DOWN not in client.get("/settings").text


def test_without_the_trouble_there_is_no_sentence(client):
    assert TELEGRAM_DOWN not in client.get("/settings").text and TELEGRAM_DOWN not in client.get("/status-line").text


def test_the_login_page_never_shows_the_sentence(tracker, tmp_path):
    app = create_web_app(
        health=Health().report, password=PASSWORD, secret_file=tmp_path / "s", tracker=tracker, telegram_down=lambda: True
    )
    anonymous = TestClient(app, follow_redirects=False)

    assert TELEGRAM_DOWN not in anonymous.get("/login").text
    assert TELEGRAM_DOWN not in anonymous.post("/login", data={"password": "wrong password"}).text


def test_the_sentence_does_not_wait_for_the_core(tmp_path):
    client = make_client(None, tmp_path, telegram_down=lambda: True)  # no tracker: the status line has no data

    html = client.get("/nowhere").text

    assert "нет данных из базы" in html and TELEGRAM_DOWN in html


# ---- rule 10 and the shape of the page -------------------------------------

def test_the_page_is_closed_without_a_sign_in_and_a_foreign_origin_cannot_save(client, tracker, tmp_path):
    anonymous = TestClient(
        create_web_app(health=Health().report, password=PASSWORD, secret_file=tmp_path / "s2", tracker=tracker),
        follow_redirects=False,
    )

    assert anonymous.get("/settings").status_code == 303
    assert anonymous.post("/settings", data=FORM).status_code == 303
    before = run(tracker.settings())
    foreign = client.post("/settings", data=FORM, headers={"Origin": "http://evil.example"})
    assert foreign.status_code == 403 and run(tracker.settings()) == before


def test_the_page_reaches_the_core_through_the_facade_only_and_the_templates_have_no_script_or_style():
    tree = ast.parse((WEB / "settings.py").read_text(encoding="utf-8"))
    from_core = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app.tracker")]
    assert from_core == ["app.tracker.core"]
    for name in ("settings.html", "status_line.html"):
        text = (WEB / "templates" / name).read_text(encoding="utf-8")
        assert "<script" not in text and "style=" not in text and "onclick" not in text, name
    assert not (WEB / "templates" / "section.html").exists()
