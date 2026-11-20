"""Stage 9.1a, ticket 01: rare input that used to break the core (spec 3.1, 3.2, 6.2).

The five delivery and part settings spoiled by hand in the database read as their defaults with one log line (KI-41);
a number of a title that is no number of any source is a `BadExternalId` before any source is asked (KI-42); an unknown
sample or moment of «Тестовое событие» are errors of their own (F4). Driven through the facade on in-memory SQLite, the
web on a `TestClient`.
"""

import asyncio
import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.runtime import Health
from app.tracker import delivery
from app.tracker.core import BadExternalId, InboxOutcome, TitleNotFound, Tracker, UnknownCheck, UnknownSample
from app.tracker.db import create_session_factory
from app.tracker.models import ExternalId, InboxRecord, SettingRecord, Title, TitleKind, TitleStatus
from app.tracker.settings_store import DEFAULT_PART_GAP_WEEKS
from app.web import create_web_app
from app.web.pages import NO_SUCH_NUMBER
from inbox_fakes import Clients, samples, tracker_on

JERUSALEM = ZoneInfo("Asia/Jerusalem")
NOW = datetime(2026, 10, 29, 20, 10, tzinfo=timezone.utc)  # Thursday 22:10 in Jerusalem
PASSWORD = "correct horse battery"
HTMX = {"HX-Request": "true"}
SPOILED_NUMBERS = ["abc", "007", "-5", " 5", "5 ", "+5", "", "1" * 19, "٥", "5\n", "1.5", "0"]


class FakeSender:
    async def send(self, message, actions=()):
        pass


class CountingSource:
    """A source of titles that counts what it is asked: a bad number must never reach it."""

    def __init__(self, source_key):
        self.source_key = source_key
        self.asked = []

    async def snapshot(self, external_id):
        self.asked.append(external_id)
        return None

    async def snapshot_to_add(self, external_id):
        return await self.snapshot(external_id)

    async def suggest(self, query):
        return []


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def source():
    return CountingSource("tmdb_movie")


@pytest.fixture
def games():
    return CountingSource("igdb")


@pytest.fixture
def tracker(session_factory, source, games):
    return Tracker(
        session_factory,
        clock=lambda: NOW,
        sender=FakeSender(),
        sources={TitleKind.MOVIE: source, TitleKind.GAME: games},
        follow_up_source=object(),  # only says that games announce titles to follow: nothing is asked of it here
        default_tz=JERUSALEM,
    )


def spoil(session_factory, key, value):
    with session_factory() as session:
        session.add(SettingRecord(key=key, value=value))
        session.commit()


def warnings_about(caplog, key):
    return [r for r in caplog.records if r.levelno == logging.WARNING and f"stored {key}" in r.getMessage()]


# --- settings spoiled by hand (3.1) ----------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["abc", 0, 53, -1, 2.5, [8], None, True, ""])
def test_a_spoiled_part_gap_reads_as_the_default_and_logs_once(tracker, session_factory, caplog, value):
    spoil(session_factory, "part_gap_weeks", value)

    with caplog.at_level(logging.WARNING):
        weeks = [run(tracker.part_gap_weeks()) for _ in range(3)] + [run(tracker.settings()).part_gap_weeks]

    assert weeks == [DEFAULT_PART_GAP_WEEKS] * 4
    assert len(warnings_about(caplog, "part_gap_weeks")) == 1
    assert "the default works" in warnings_about(caplog, "part_gap_weeks")[0].getMessage()


@pytest.mark.parametrize("value", ["1,2", "abc", [7], [0, 0, "x"], [-1], None, 5, {"a": 1}])
def test_spoiled_workdays_read_as_sunday_to_thursday_and_log_once(tracker, session_factory, caplog, value):
    spoil(session_factory, "workdays", value)

    with caplog.at_level(logging.WARNING):
        rules = [run(tracker.delivery_rules()) for _ in range(3)]

    assert all(r.workdays == delivery.DEFAULT_WORKDAYS for r in rules)
    assert len(warnings_about(caplog, "workdays")) == 1


@pytest.mark.parametrize("key", ["summary_at", "quiet_from", "quiet_until"])
@pytest.mark.parametrize("value", ["25:99", "abc", 5, None, "16:5", ["15:00"]])
def test_a_spoiled_clock_reads_as_its_default_and_logs_once(tracker, session_factory, caplog, key, value):
    default = {
        "summary_at": delivery.DEFAULT_SUMMARY_AT,  # (the quiet hours of the tests are set by `conftest.py`)
        "quiet_from": delivery.DEFAULT_QUIET_FROM,
        "quiet_until": delivery.DEFAULT_QUIET_UNTIL,
    }[key]
    spoil(session_factory, key, value)

    with caplog.at_level(logging.WARNING):
        rules = [run(tracker.delivery_rules()) for _ in range(3)]

    assert all(getattr(r, key) == default for r in rules)
    assert len(warnings_about(caplog, key)) == 1


def test_each_field_is_checked_alone_so_a_good_one_stays(tracker, session_factory):
    spoil(session_factory, "summary_at", "25:99")
    spoil(session_factory, "quiet_from", "22:00")
    spoil(session_factory, "workdays", [0, 1])

    rules = run(tracker.delivery_rules())

    assert (rules.summary_at, rules.quiet_from, rules.quiet_until) == (
        delivery.DEFAULT_SUMMARY_AT, time(22, 0), delivery.DEFAULT_QUIET_UNTIL
    )
    assert rules.workdays == frozenset({0, 1})


def test_a_second_spoiled_value_is_told_again_but_the_same_one_is_not(tracker, session_factory, caplog):
    spoil(session_factory, "summary_at", "25:99")
    with caplog.at_level(logging.WARNING):
        run(tracker.delivery_rules())
        with session_factory() as session:
            session.get(SettingRecord, "summary_at").value = "99:99"
            session.commit()
        run(tracker.delivery_rules())
        run(tracker.delivery_rules())

    assert len(warnings_about(caplog, "summary_at")) == 2


def test_the_feed_and_the_delivery_rules_work_on_spoiled_settings(tracker, session_factory):
    for key, value in (
        ("part_gap_weeks", "abc"), ("workdays", "x"), ("summary_at", "25:99"), ("quiet_from", 5), ("quiet_until", None)
    ):
        spoil(session_factory, key, value)

    feed = run(tracker.feed())
    report = run(tracker.deliver_pending())
    view = run(tracker.settings())

    assert feed is not None and report is not None
    assert (view.summary_at, view.quiet_from, view.quiet_until) == tuple(
        delivery.format_time(at)
        for at in (delivery.DEFAULT_SUMMARY_AT, delivery.DEFAULT_QUIET_FROM, delivery.DEFAULT_QUIET_UNTIL)
    )
    assert view.part_gap_weeks == DEFAULT_PART_GAP_WEEKS and view.workdays == delivery.DEFAULT_WORKDAYS


def test_the_part_gap_methods_belong_to_the_instance(tracker, session_factory):
    spoil(session_factory, "part_gap_weeks", "abc")

    with session_factory() as session:
        assert tracker._settings.part_gap_weeks_in(session) == DEFAULT_PART_GAP_WEEKS
        assert tracker._settings.part_gap(session) == timedelta(weeks=DEFAULT_PART_GAP_WEEKS)


# --- a number that is no number (3.2) --------------------------------------------------------------------------


@pytest.mark.parametrize("number", SPOILED_NUMBERS)
def test_a_bad_number_is_refused_before_any_source_is_asked_and_nothing_is_stored(
    tracker, source, session_factory, number
):
    with pytest.raises(BadExternalId):
        run(tracker.add_title(TitleKind.MOVIE, number))

    assert source.asked == []
    with session_factory() as session:
        assert session.scalars(select(Title)).all() == [] and session.scalars(select(ExternalId)).all() == []


@pytest.mark.parametrize("number", ["abc", "007"])
def test_follow_refuses_a_bad_number_the_same_way(tracker, games, number):
    with pytest.raises(BadExternalId):
        run(tracker.follow("game", number))

    assert games.asked == []


def test_a_bad_external_id_is_a_title_not_found():
    assert issubclass(BadExternalId, TitleNotFound)


@pytest.mark.parametrize("number", ["1", "7", "693134", "9" * 18])
def test_a_plain_number_goes_on_to_the_source(tracker, source, number):
    with pytest.raises(TitleNotFound) as caught:
        run(tracker.add_title(TitleKind.MOVIE, number))

    assert not isinstance(caught.value, BadExternalId) and source.asked == [number]


def test_the_yes_of_an_offer_with_a_bad_number_goes_to_the_next_offer():
    clients = Clients()
    tracker = tracker_on(clients)
    item = run(tracker.take_in(_message(samples()[5]))).item_id
    run(tracker.answer_kind(item, TitleKind.GAME))  # three offers
    with tracker.session_factory() as session:
        record = session.get(InboxRecord, item)
        record.offers = [{**record.offers[0], "external_id": "007"}, *record.offers[1:]]
        session.commit()

    reply = run(tracker.answer_offer(item, 0, True))

    assert reply.outcome == InboxOutcome.OFFER and reply.offer.number == 1
    with tracker.session_factory() as session:
        assert session.scalars(select(Title)).all() == []


def _message(text):
    from app.tracker.core import IncomingMessage

    return IncomingMessage(text=text, forwarded=True, links=())


# --- the web says it ------------------------------------------------------------------------------------------


@pytest.fixture
def client(tracker, tmp_path):
    health = Health()
    health.bot_running = health.scheduler_running = True
    health.scheduler_mark = health.clock()
    app = create_web_app(health=health.report, password=PASSWORD, secret_file=tmp_path / "web_secret", tracker=tracker)
    client = TestClient(app, follow_redirects=False)
    assert client.post("/login", data={"password": PASSWORD}).status_code == 303
    return client


def test_the_line_of_the_web_is_the_one_of_the_ticket():
    assert NO_SUCH_NUMBER == "Такого номера тайтла не бывает. Поищите заново"


@pytest.mark.parametrize("number", ["abc", "007", "-5"])
def test_the_web_add_says_there_is_no_such_number(client, source, number):
    response = client.post("/titles", data={"kind": "movie", "external_id": number}, headers=HTMX)

    assert response.status_code == 200 and "HX-Redirect" not in response.headers
    assert response.text.strip() == f'<p class="error" role="alert">{NO_SUCH_NUMBER}</p>'
    assert source.asked == []


def test_the_web_add_without_htmx_goes_back_to_the_search_with_the_line(client, source):
    response = client.post("/titles", data={"kind": "movie", "external_id": "007", "q": "дюна"})

    assert response.status_code == 303 and response.headers["location"].startswith("/search?kind=movie")
    assert NO_SUCH_NUMBER in client.get("/search").text and source.asked == []


def test_the_web_follow_says_there_is_no_such_number(client, games, session_factory):
    now = NOW.replace(tzinfo=None)
    with session_factory() as session:
        title = Title(
            kind=TitleKind.MOVIE, name="Дюна", original_name="Dune", genres=[], status=TitleStatus.WATCHED, tracking_enabled=False, added_at=now,
            status_changed_at=now,
        )
        session.add(title)
        session.commit()
        title_id = title.id

    feed = client.post("/feed/follow", data={"kind": "game", "external_id": "007"}, headers=HTMX)
    card = client.post(
        f"/titles/{title_id}/follow", data={"kind": "game", "external_id": "abc", "block": "sequels"}, headers=HTMX
    )

    assert NO_SUCH_NUMBER in feed.text and NO_SUCH_NUMBER in card.text
    assert games.asked == []


# --- unknown sample and unknown moment (6.2) --------------------------------------------------------------------


def test_an_unknown_sample_is_an_unknown_sample_and_nothing_is_sent(tracker):
    with pytest.raises(UnknownSample):
        run(tracker.send_test_event("no-such-sample"))


def test_an_unknown_moment_is_an_unknown_check(tracker):
    with pytest.raises(UnknownCheck):
        run(tracker.delivery_check("no-such-moment"))


def test_the_new_errors_are_not_key_errors(tracker):
    assert not issubclass(UnknownSample, KeyError) and not issubclass(UnknownCheck, KeyError)
