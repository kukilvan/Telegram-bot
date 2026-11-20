"""«Тестовое событие» and «Проверка правил доставки» in Settings (ticket 02 of stage 7.2): `Tracker.delivery_check` (every
outcome of the eight moments), the two forms of the page (the lists, each outcome with HTMX as a fragment and without it as
the notice after a `303`, an unknown id), and the one logic behind the bot's check and the web's (the same outcome for the
same moment). On the real core; the clock stands on Sunday 1 Nov 2026 10:00 in Asia/Jerusalem (a working morning, UTC+2)."""

import asyncio
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from fastapi.testclient import TestClient

from app.bot.access import AccessMiddleware
from app.bot.tracker_handlers import TelegramSender, register_tracker_handlers
from app.runtime import Health
from app.tracker.core import CheckOutcome, Tracker, UnknownCheck
from app.tracker.db import create_session_factory
from app.tracker.test_samples import DELIVERY_CHECKS
from app.web import create_web_app
from app.web import settings_test_event as texts

PASSWORD = "correct horse battery"
OWNER = 42
JERUSALEM = ZoneInfo("Asia/Jerusalem")
HELD = {"work-morning", "night-before-day-off", "night-before-workday", "quiet-ends"}  # the rules hold these; the rest go at once
HTMX = {"HX-Request": "true"}


class Sender:
    def __init__(self):
        self.messages = []
        self.failing = False

    async def send(self, message, actions=()):
        if self.failing:
            raise ConnectionError("telegram is down")
        self.messages.append(message)


def run(coro):
    return asyncio.run(coro)


def make_tracker(sender):
    clock = lambda: datetime(2026, 11, 1, 10, 0, tzinfo=JERUSALEM).astimezone(timezone.utc)  # noqa: E731
    tracker = Tracker(create_session_factory("sqlite://"), clock=clock, sender=sender, sources={})
    run(
        tracker.set_delivery_rules(
            tz_name="Asia/Jerusalem", workdays=[6, 0, 1, 2, 3], summary_at="15:00", quiet_from="21:00", quiet_until="07:30"
        )
    )
    return tracker


@pytest.fixture
def sender():
    return Sender()


@pytest.fixture
def tracker(sender):
    return make_tracker(sender)


@pytest.fixture
def client(tracker, tmp_path):
    health = Health()
    health.bot_running = health.scheduler_running = True
    health.scheduler_mark = health.clock()
    app = create_web_app(health=health.report, password=PASSWORD, secret_file=tmp_path / "web_secret", tracker=tracker)
    client = TestClient(app, follow_redirects=False)
    assert client.post("/login", data={"password": PASSWORD}).status_code == 303
    return client


# --- Tracker.delivery_check -----------------------------------------------------------------------


@pytest.mark.parametrize("check", DELIVERY_CHECKS, ids=lambda c: c.id)
def test_every_moment_ends_as_the_rules_say(tracker, sender, check):
    result = run(tracker.delivery_check(check.id))

    assert result.outcome is (CheckOutcome.HELD if check.id in HELD else CheckOutcome.AT_ONCE)
    assert result.moment
    assert bool(result.release) is (check.id in HELD)
    assert sender.messages  # the sample reached the owner either way


def test_the_moment_and_the_release_are_written_on_the_owners_clock(tracker):
    held = run(tracker.delivery_check("work-morning"))

    assert held.moment == "вс, 8 ноя в 10:00" and held.release == "вс, 8 ноя в 15:00"


def test_a_failing_sender_is_not_delivered_and_not_held(tracker, sender):
    sender.failing = True

    result = run(tracker.delivery_check("friday"))

    assert result.outcome is CheckOutcome.NOT_DELIVERED and result.release == ""


def test_an_unknown_moment_is_an_unknown_check(tracker):
    with pytest.raises(UnknownCheck):
        run(tracker.delivery_check("gone"))


def test_the_core_hands_out_the_eight_moments():
    from app.tracker import core

    assert core.DELIVERY_CHECKS is DELIVERY_CHECKS and len(DELIVERY_CHECKS) == 8


# --- the forms on the page ------------------------------------------------------------------------


def options(html, select_name):
    block = re.search(rf'<select name="{select_name}"[^>]*>(.*?)</select>', html, re.S).group(1)
    return re.findall(r'<option value="([^"]*)"( selected)?>([^<]*)</option>', block)


def test_the_page_has_both_forms_with_the_lists_of_the_core_the_first_line_chosen(client, tracker):
    html = client.get("/settings").text

    assert "<h3>Тестовое событие</h3>" in html and "<h3>Проверка правил доставки</h3>" in html
    assert "Пришлёт в Telegram пример сообщения — посмотреть, как оно выглядит." in html
    assert "и покажет, что сделали правила доставки (рабочие дни, тихие часы, сводка)." in html
    samples = options(html, "sample")
    assert [(v, label) for v, _, label in samples] == [(s.id, s.label) for s in tracker.test_samples()]
    assert [chosen for _, chosen, _ in samples] == [" selected"] + [""] * (len(samples) - 1)
    checks = options(html, "check")
    assert [(v, label) for v, _, label in checks] == [(c.id, c.label) for c in DELIVERY_CHECKS]
    assert checks[0][1] == " selected"
    assert '<button type="submit">Прислать</button>' in html and '<button type="submit">Проверить</button>' in html


def test_the_forms_are_htmx_forms_with_a_plain_post_behind_them(client):
    html = client.get("/settings").text

    for address, target in (("/settings/test-event", "test-event-answer"), ("/settings/delivery-check", "delivery-check-answer")):
        assert f'method="post" action="{address}" hx-post="{address}" hx-target="#{target}" hx-swap="innerHTML"' in html
        assert f'<div id="{target}"' in html


def test_a_sample_is_delivered_with_htmx_as_a_fragment_and_the_page_stays(client, sender):
    response = client.post("/settings/test-event", data={"sample": "ping"}, headers=HTMX)

    assert response.status_code == 200
    assert response.text.strip() == f"<p>{texts.SAMPLE_SENT}</p>" and "<html" not in response.text
    assert len(sender.messages) == 1 and "Проверка связи" in sender.messages[0]


def test_a_sample_without_htmx_goes_back_to_settings_with_the_notice_once(client, sender):
    response = client.post("/settings/test-event", data={"sample": "ping"})

    assert response.status_code == 303 and response.headers["location"] == "/settings"
    assert texts.SAMPLE_SENT in client.get("/settings").text
    assert texts.SAMPLE_SENT not in client.get("/settings").text
    assert len(sender.messages) == 1


def test_the_sample_goes_at_once_whatever_the_hour(tracker, sender, client):
    run(tracker.set_delivery_rules(tz_name="Asia/Jerusalem", workdays=[6], summary_at="15:00", quiet_from="09:00", quiet_until="11:00"))

    client.post("/settings/test-event", data={"sample": "ping"}, headers=HTMX)

    assert len(sender.messages) == 1  # the clock stands in the quiet hours and a work day before the summary


def test_a_bot_that_is_not_connected_leaves_the_event_in_the_queue_and_says_so(client, sender):
    sender.failing = True

    html = client.post("/settings/test-event", data={"sample": "ping"}, headers=HTMX).text
    sender.failing = False

    assert texts.SAMPLE_NOT_SENT in html and 'class="error"' in html


def test_a_failed_sample_comes_later_with_the_next_delivery(tracker, client, sender):
    sender.failing = True
    client.post("/settings/test-event", data={"sample": "ping"}, headers=HTMX)
    sender.failing = False

    run(tracker.deliver_pending(force=True))

    assert any("Проверка связи" in m for m in sender.messages)


def test_two_presses_make_two_events(client, sender):
    client.post("/settings/test-event", data={"sample": "ping"}, headers=HTMX)
    client.post("/settings/test-event", data={"sample": "ping"}, headers=HTMX)

    assert len(sender.messages) == 2


def test_an_unknown_sample_is_a_400_with_its_sentence_and_a_fragment_for_htmx(client, sender):
    plain = client.post("/settings/test-event", data={"sample": "gone"})
    htmx = client.post("/settings/test-event", data={"sample": "gone"}, headers=HTMX)
    empty = client.post("/settings/test-event", data={})

    assert plain.status_code == empty.status_code == 400 and texts.NO_SUCH_SAMPLE in plain.text
    assert htmx.status_code == 200 and texts.NO_SUCH_SAMPLE in htmx.text and "<html" not in htmx.text
    assert sender.messages == []


def test_an_unexpected_error_is_the_common_sentence_with_refresh(client, tracker, monkeypatch):
    async def broken(sample_id, at=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(tracker, "send_test_event", broken)

    fragment = client.post("/settings/test-event", data={"sample": "ping"}, headers=HTMX)
    page = client.post("/settings/test-event", data={"sample": "ping"})

    assert "Не получилось" in fragment.text and 'href="/settings"' in fragment.text and "Обновить" in fragment.text
    assert page.status_code == 500 and "Обновить" in page.text


def test_a_key_error_inside_a_send_is_not_no_such_sample(client, tracker, monkeypatch):
    async def broken(sample_id, at=None):
        raise KeyError("inside")

    monkeypatch.setattr(tracker, "send_test_event", broken)

    fragment = client.post("/settings/test-event", data={"sample": "ping"}, headers=HTMX)
    page = client.post("/settings/test-event", data={"sample": "ping"})

    assert texts.NO_SUCH_SAMPLE not in fragment.text and texts.NO_SUCH_SAMPLE not in page.text
    assert "Не получилось" in fragment.text and page.status_code == 500


def test_a_key_error_inside_a_check_is_not_no_such_moment(client, tracker, monkeypatch):
    async def broken(check_id):
        raise KeyError("inside")

    monkeypatch.setattr(tracker, "delivery_check", broken)

    fragment = client.post("/settings/delivery-check", data={"check": "friday"}, headers=HTMX)
    page = client.post("/settings/delivery-check", data={"check": "friday"})

    assert texts.NO_SUCH_CHECK not in fragment.text and texts.NO_SUCH_CHECK not in page.text
    assert "Не получилось" in fragment.text and page.status_code == 500


@pytest.mark.parametrize("check", DELIVERY_CHECKS, ids=lambda c: c.id)
def test_every_moment_of_the_page_shows_its_sentence_with_htmx(client, check):
    html = client.post("/settings/delivery-check", data={"check": check.id}, headers=HTMX).text

    assert "<html" not in html
    if check.id in HELD:
        assert "Как будто сейчас " in html and "в этот момент ничего не пришло, события копились." in html
        assert "В Telegram пришла сводка, которая уйдёт " in html and "{" not in html
    else:
        assert "сообщения пришли сразу, правила их не задерживают." in html


def test_a_held_moment_without_htmx_is_the_notice_after_a_303(client, sender):
    response = client.post("/settings/delivery-check", data={"check": "work-morning"})

    assert response.status_code == 303 and response.headers["location"] == "/settings"
    page = client.get("/settings").text
    assert "Как будто сейчас вс, 8 ноя в 10:00: в этот момент ничего не пришло, события копились. " in page
    assert "В Telegram пришла сводка, которая уйдёт вс, 8 ноя в 15:00." in page
    assert any(m.startswith("📋 Сводка") for m in sender.messages)


def test_a_check_with_a_failing_sender_says_the_events_stay_in_the_queue(client, sender):
    sender.failing = True

    html = client.post("/settings/delivery-check", data={"check": "friday"}, headers=HTMX).text

    assert texts.CHECK_NOT_SENT in html and 'class="error"' in html


def test_an_unknown_moment_is_a_400_with_its_sentence(client, sender):
    plain = client.post("/settings/delivery-check", data={"check": "gone"})
    htmx = client.post("/settings/delivery-check", data={"check": "gone"}, headers=HTMX)

    assert plain.status_code == 400 and texts.NO_SUCH_CHECK in plain.text
    assert htmx.status_code == 200 and texts.NO_SUCH_CHECK in htmx.text
    assert sender.messages == []


def test_both_routes_are_closed_without_a_sign_in(tracker, tmp_path):
    app = create_web_app(health=Health().report, password=PASSWORD, secret_file=tmp_path / "s", tracker=tracker)
    anonymous = TestClient(app, follow_redirects=False)

    assert anonymous.post("/settings/test-event", data={"sample": "ping"}).status_code == 303
    assert anonymous.post("/settings/delivery-check", data={"check": "friday"}).status_code == 303


# --- one logic for the bot and the web ------------------------------------------------------------


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append(text)


def bot_says(check_id, monkeypatch):
    """What the bot's check answers for this moment, on a core of its own (the delivered messages included)."""
    said, bot = [], FakeBot()
    tracker = make_tracker(TelegramSender(bot, OWNER))

    async def message_answer(self, text=None, **kwargs):
        said.append(text)

    async def callback_answer(self, text=None, **kwargs):
        pass

    monkeypatch.setattr(Message, "answer", message_answer)
    monkeypatch.setattr(CallbackQuery, "answer", callback_answer)
    dp = Dispatcher()
    dp.update.outer_middleware(AccessMiddleware([OWNER]))
    register_tracker_handlers(dp, tracker, [OWNER])
    user = User(id=OWNER, is_bot=False, first_name="x")
    message = Message(message_id=1, date=0, chat=Chat(id=OWNER, type="private"), from_user=user, text="m")
    callback = CallbackQuery(id="1", from_user=user, chat_instance="c", data=f"twin:{check_id}", message=message)
    asyncio.run(dp.feed_update(Bot(token="123456:TEST"), Update(update_id=2, callback_query=callback)))
    return said[-1], bot.sent


@pytest.mark.parametrize("check", DELIVERY_CHECKS, ids=lambda c: c.id)
def test_the_bot_and_the_web_give_the_same_outcome_for_the_same_moment(client, tracker, check, monkeypatch):
    core = run(make_tracker(Sender()).delivery_check(check.id))  # what the core says: the one source of both
    bot_text, bot_sent = bot_says(check.id, monkeypatch)
    web_text = client.post("/settings/delivery-check", data={"check": check.id}, headers=HTMX).text

    assert f"Как будто сейчас {core.moment}:" in bot_text and f"Как будто сейчас {core.moment}:" in web_text
    for text in (bot_text, web_text):
        if core.outcome is CheckOutcome.HELD:
            assert "ничего не пришло" in text and core.release in text
        else:
            assert "сообщения пришли сразу" in text
    assert any(m.startswith("📋") for m in bot_sent) is (core.outcome is CheckOutcome.HELD)
