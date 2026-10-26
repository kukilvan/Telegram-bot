"""Tracker core: the owner is told when a title could not be checked — once a day per title, one message per source.

Driven through the facade only: fake clock, fake sources that fail on demand, fake sender, in-memory SQLite.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import select

from app.providers.shikimori import ShikimoriError
from app.providers.tmdb import TmdbHttpError
from app.tracker import failures
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import DeliveryItem, Event, ExternalId, SourceSnapshot, Title
from app.tracker.sources.tmdb_movies import MovieSnapshot

T0 = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
JERUSALEM = ZoneInfo("Asia/Jerusalem")
REQUEST = httpx.Request("GET", "https://api.themoviedb.org/3/movie/1?api_key=SECRET-KEY")


def run(coro):
    return asyncio.run(coro)


class FakeClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, **delta):
        self.now += timedelta(**delta)


class FakeSender:
    def __init__(self):
        self.sent = []  # (message, actions)
        self.failing = False

    @property
    def messages(self):
        return [m for m, _ in self.sent]

    async def send(self, message, actions=()):
        if self.failing:
            raise ConnectionError("telegram is down")
        self.sent.append((message, list(actions)))


class FakeSource:
    """A source that returns a movie, or raises what it was told to for an id."""

    def __init__(self, source_key="tmdb_movie"):
        self.source_key = source_key
        self.errors: dict[str, Exception] = {}
        self.unknown: set[str] = set()
        self.calls: list[str] = []

    async def suggest(self, query):
        return []

    async def snapshot(self, external_id):
        self.calls.append(external_id)
        if external_id in self.errors:
            raise self.errors[external_id]
        if external_id in self.unknown:
            return None
        return movie(external_id)


def movie(external_id, name=None):
    return MovieSnapshot(
        external_id=external_id,
        title=name or f"Фильм {external_id}",
        original_title=name or f"Movie {external_id}",
        year=2026,
        genres=[],
        poster_path=None,
        overview=None,
        theatrical_date=None,
        digital_date=None,
    )


@pytest.fixture
def clock():
    return FakeClock(T0)


@pytest.fixture
def sender():
    return FakeSender()


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def source():
    return FakeSource()


@pytest.fixture
def tracker(session_factory, clock, sender, source):
    return Tracker(session_factory, clock=clock, sender=sender, sources={"movie": source})


def add_movie(tracker, external_id, name=None):
    source = tracker.sources["movie"]
    source.snapshot_name = name
    result = run(tracker.add_title("movie", external_id))
    if name:
        with tracker.session_factory() as s:
            s.get(Title, result.title_id).title = name
            s.commit()
    return result.title_id


def add_anime_row(session_factory, external_id, name, now=T0):
    """An anime title as it sits in the list, without going through the anime source."""
    naive = now.replace(tzinfo=None)
    with session_factory() as s:
        title = Title(
            kind="anime", title=name, original_title=name, year=2026, genres=[], status="want",
            tracking_enabled=True, added_at=naive, status_changed_at=naive,
        )
        s.add(title)
        s.flush()
        s.add(ExternalId(title_id=title.id, source="shikimori", external_id=external_id, role="primary"))
        s.add(SourceSnapshot(title_id=title.id, source="shikimori", state={}, observed_at=naive, next_check_at=naive))
        s.commit()
        return title.id


def poll(tracker, clock, **advance):
    clock.advance(**advance)
    report = run(tracker.poll_due())
    run(tracker.deliver_pending())
    return report


def make_due(session_factory, title_id, now):
    """The check of the title is due at `now` (aware): a title is added with its first check a day away."""
    with session_factory() as s:
        snapshot = s.scalar(select(SourceSnapshot).where(SourceSnapshot.title_id == title_id))
        snapshot.next_check_at = now.replace(tzinfo=None)
        s.commit()


def notices(sender):
    return [m for m in sender.messages if m.startswith("⚠️")]


# --- why a check failed, in the owner's words ----------------------------------------------------


@pytest.mark.parametrize(
    "error, expected",
    [
        (httpx.ReadTimeout("slow", request=REQUEST), "не ответил вовремя"),
        (httpx.ConnectTimeout("slow", request=REQUEST), "не ответил вовремя"),
        (TimeoutError("slow"), "не ответил вовремя"),
        (httpx.ConnectError("no route", request=REQUEST), "не удалось подключиться"),
        (ConnectionError("reset"), "не удалось подключиться"),
        (TmdbHttpError("TMDb is rate-limiting requests (HTTP 429)", 429), "просит подождать, слишком много запросов"),
        (TmdbHttpError("x (HTTP 401)", 401), "не принял ключ — проверьте ключ в настройках"),
        (TmdbHttpError("x (HTTP 403)", 403), "не принял ключ — проверьте ключ в настройках"),
        (TmdbHttpError("x (HTTP 503)", 503), "у него сейчас сбой"),
        (ShikimoriError("entries request failed", status=502), "у него сейчас сбой"),
        (ShikimoriError("entries request failed", cause=httpx.ReadTimeout("slow")), "не ответил вовремя"),
        (failures.TitleGone("tmdb 1"), "больше не знает этого тайтла"),
        (RuntimeError("something odd"), "неизвестная ошибка, подробности в журнале"),
        (ShikimoriError("entries request failed"), "неизвестная ошибка, подробности в журнале"),
        (KeyError("movie"), "неизвестная ошибка, подробности в журнале"),
    ],
)
def test_every_reason_has_its_own_text(error, expected):
    text = failures.message_one("Дюна", "TMDb", failures.reason_of(error))

    assert expected in text
    assert text.startswith("⚠️ Не удалось проверить «Дюна»: ")
    assert text.endswith("Повторю через 30 мин.")


def test_the_reasons_are_all_different():
    texts = {failures.message_one("Дюна", "TMDb", reason) for reason in (
        failures.TIMEOUT, failures.CONNECTION, failures.RATE_LIMIT, failures.KEY_REJECTED,
        failures.SOURCE_DOWN, failures.GONE, failures.UNKNOWN,
    )}

    assert len(texts) == 7


def test_the_message_for_one_title_reads_as_promised():
    assert failures.message_one("Дюна", "TMDb", failures.TIMEOUT) == (
        "⚠️ Не удалось проверить «Дюна»: TMDb не ответил вовремя. Повторю через 30 мин."
    )


def test_the_message_for_several_titles_names_the_first_ones():
    titles = ["Дюна", "Укрытие", "А", "Б", "В", "Г", "Д", "Е", "Ж", "З", "И", "К"]

    text = failures.message_many("TMDb", failures.TIMEOUT, titles)

    assert text == (
        "⚠️ Не удалось проверить 12 тайтлов: TMDb не ответил вовремя. Дюна, Укрытие, А, Б, В, … Повторю через 30 мин."
    )


def test_the_message_for_several_titles_gives_the_real_reason():
    text = failures.message_many("TMDb", failures.KEY_REJECTED, ["Дюна", "Укрытие"])

    assert "TMDb не принял ключ — проверьте ключ в настройках" in text
    assert "не отвечает" not in text


@pytest.mark.parametrize("many", [False, True])
def test_an_unknown_error_names_the_source(many):
    text = (
        failures.message_many("TMDb", failures.UNKNOWN, ["Дюна", "Укрытие"])
        if many
        else failures.message_one("Дюна", "TMDb", failures.UNKNOWN)
    )

    assert "у TMDb неизвестная ошибка, подробности в журнале" in text


@pytest.mark.parametrize(
    "count, word", [(2, "тайтла"), (3, "тайтла"), (5, "тайтлов"), (11, "тайтлов"), (12, "тайтлов"), (21, "тайтл"), (22, "тайтла")]
)
def test_the_count_agrees_with_the_word(count, word):
    text = failures.message_many("TMDb", failures.TIMEOUT, [f"Т{i}" for i in range(count)])

    assert f"проверить {count} {word}:" in text


@pytest.mark.parametrize(
    "key, name",
    [("tmdb_movie", "TMDb"), ("tmdb_tv", "TMDb"), ("tmdb_sequels", "TMDb"), ("shikimori", "Shikimori")],
)
def test_the_source_is_named_by_its_key(key, name):
    assert failures.source_name(key) == name


# --- one notice per failure, once a day per title ------------------------------------------------


def test_a_failed_check_gives_one_message(tracker, source, clock, sender):
    add_movie(tracker, "1", "Дюна")
    source.errors["1"] = httpx.ReadTimeout("slow", request=REQUEST)

    report = poll(tracker, clock, days=2)

    assert notices(sender) == ["⚠️ Не удалось проверить «Дюна»: TMDb не ответил вовремя. Повторю через 30 мин."]
    assert (report.failed, report.notices) == (1, 1)


def test_the_first_failure_is_reported_without_waiting_for_more(tracker, source, clock, sender):
    add_movie(tracker, "1")
    source.errors["1"] = ConnectionError("down")

    poll(tracker, clock, days=2)

    assert len(notices(sender)) == 1


def test_the_same_title_failing_again_within_a_day_is_silent(tracker, source, clock, sender):
    add_movie(tracker, "1")
    source.errors["1"] = ConnectionError("down")
    poll(tracker, clock, days=2)

    for _ in range(5):  # a retry every 31 minutes, five of them
        poll(tracker, clock, minutes=31)

    assert len(notices(sender)) == 1


def test_a_day_later_the_title_is_reported_again(tracker, source, clock, sender):
    add_movie(tracker, "1")
    source.errors["1"] = ConnectionError("down")
    poll(tracker, clock, days=2)

    for _ in range(46):  # a retry every 31 minutes for 23 hours and 46 minutes
        poll(tracker, clock, minutes=31)
    assert len(notices(sender)) == 1

    for _ in range(3):  # the retries that fall after the 24th hour
        poll(tracker, clock, minutes=31)
    assert len(notices(sender)) == 2


def test_the_cooldown_ends_exactly_after_24_hours(tracker, source, clock, sender, session_factory):
    title_id = add_movie(tracker, "1")
    source.errors["1"] = ConnectionError("down")
    poll(tracker, clock, days=2)
    told_at = clock.now

    make_due(session_factory, title_id, told_at + timedelta(hours=24) - timedelta(seconds=1))
    poll(tracker, clock, hours=24, seconds=-1)
    assert len(notices(sender)) == 1

    make_due(session_factory, title_id, told_at + timedelta(hours=24))
    poll(tracker, clock, seconds=1)
    assert len(notices(sender)) == 2


def test_the_time_of_the_last_notice_survives_a_restart(session_factory, clock, sender, source):
    first = Tracker(session_factory, clock=clock, sender=sender, sources={"movie": source})
    add_movie(first, "1")
    source.errors["1"] = ConnectionError("down")
    poll(first, clock, days=2)

    restarted = Tracker(session_factory, clock=clock, sender=sender, sources={"movie": source})
    poll(restarted, clock, hours=2)
    poll(restarted, clock, hours=2)

    assert len(notices(sender)) == 1
    with session_factory() as s:
        assert s.scalar(select(Title.failure_notified_at)) is not None


def test_a_title_that_recovered_creates_no_more_messages(tracker, source, clock, sender):
    add_movie(tracker, "1")
    source.errors["1"] = ConnectionError("down")
    poll(tracker, clock, days=2)
    del source.errors["1"]

    report = poll(tracker, clock, minutes=31)
    poll(tracker, clock, days=3)

    assert report.failed == 0
    assert len(sender.sent) == 1


def test_a_title_the_source_no_longer_knows_is_reported(tracker, source, clock, sender):
    add_movie(tracker, "1", "Дюна")
    source.unknown.add("1")

    poll(tracker, clock, days=2)

    assert notices(sender) == ["⚠️ Не удалось проверить «Дюна»: TMDb больше не знает этого тайтла. Повторю через 30 мин."]


def test_the_failed_title_is_still_postponed_by_thirty_minutes(tracker, source, clock, sender, session_factory):
    title_id = add_movie(tracker, "1")
    source.errors["1"] = ConnectionError("down")

    poll(tracker, clock, days=2)

    with session_factory() as s:
        due = s.scalar(select(SourceSnapshot.next_check_at).where(SourceSnapshot.title_id == title_id))
    assert due == clock.now.replace(tzinfo=None) + timedelta(minutes=30)


# --- one message per source in a pass ------------------------------------------------------------


def test_many_titles_of_one_source_give_one_message(tracker, source, clock, sender):
    for number, name in enumerate(["Дюна", "Укрытие", "Аркейн"], start=1):
        add_movie(tracker, str(number), name)
        source.errors[str(number)] = httpx.ConnectError("no route", request=REQUEST)

    report = poll(tracker, clock, days=2)

    assert notices(sender) == [
        "⚠️ Не удалось проверить 3 тайтла: не удалось подключиться к TMDb. Дюна, Укрытие, Аркейн. Повторю через 30 мин."
    ]
    assert report.notices == 3  # one event per title; delivery folds them


def test_different_reasons_of_one_source_give_a_message_each(tracker, source, clock, sender):
    for number, name in enumerate(["Дюна", "Укрытие", "Аркейн"], start=1):
        add_movie(tracker, str(number), name)
    source.errors["1"] = httpx.ReadTimeout("slow", request=REQUEST)
    source.errors["2"] = httpx.ReadTimeout("slow", request=REQUEST)
    source.errors["3"] = TmdbHttpError("x (HTTP 401)", 401)

    poll(tracker, clock, days=2)

    assert sorted(notices(sender)) == sorted([
        "⚠️ Не удалось проверить 2 тайтла: TMDb не ответил вовремя. Дюна, Укрытие. Повторю через 30 мин.",
        "⚠️ Не удалось проверить «Аркейн»: TMDb не принял ключ — проверьте ключ в настройках. Повторю через 30 мин.",
    ])
    cards = [a for message, actions in sender.sent for a in actions if "Аркейн" in message]
    assert [a.name for a in cards] == ["card"]


def test_titles_the_source_no_longer_knows_are_never_folded(tracker, source, clock, sender):
    for number, name in enumerate(["Дюна", "Укрытие"], start=1):
        add_movie(tracker, str(number), name)
        source.unknown.add(str(number))

    poll(tracker, clock, days=2)

    assert sorted(notices(sender)) == [
        "⚠️ Не удалось проверить «Дюна»: TMDb больше не знает этого тайтла. Повторю через 30 мин.",
        "⚠️ Не удалось проверить «Укрытие»: TMDb больше не знает этого тайтла. Повторю через 30 мин.",
    ]
    assert all([a.name for a in actions] == ["card"] for _, actions in sender.sent)


def test_the_event_is_one_per_title_with_the_pass_stamp(tracker, source, clock, session_factory):
    ids = [add_movie(tracker, str(n), f"Т{n}") for n in (1, 2, 3)]
    for n in (1, 2, 3):
        source.errors[str(n)] = ConnectionError("down")

    poll(tracker, clock, days=2)

    with session_factory() as s:
        events = s.scalars(select(Event).where(Event.type == failures.SOURCE_FAILED).order_by(Event.id)).all()
    assert [e.title_id for e in events] == ids
    assert {e.payload["pass"] for e in events} == {"20261026T120000"}
    assert {(e.payload["source"], e.payload["reason"]) for e in events} == {("TMDb", failures.CONNECTION)}
    assert [e.payload["title_name"] for e in events] == ["Т1", "Т2", "Т3"]


def test_an_old_common_event_is_delivered_by_its_own_text(tracker, sender):
    run(tracker.record_event(
        failures.SOURCE_FAILED,
        {"text": "⚠️ TMDb не отвечает. Не удалось проверить 2 тайтла: А, Б. Повторю через 30 мин.", "source": "TMDb", "titles": ["А", "Б"]},
        "failure:TMDb:old:1,2",
    ))
    run(tracker.deliver_pending())

    assert sender.messages == ["⚠️ TMDb не отвечает. Не удалось проверить 2 тайтла: А, Б. Повторю через 30 мин."]


def test_two_broken_sources_give_two_messages(session_factory, clock, sender):
    tmdb, shikimori = FakeSource("tmdb_movie"), FakeSource("shikimori")
    tracker = Tracker(session_factory, clock=clock, sender=sender, sources={"movie": tmdb, "anime": shikimori})
    add_movie(tracker, "1", "Дюна")
    add_anime_row(session_factory, "10", "Монолог фармацевта")
    tmdb.errors["1"] = TmdbHttpError("TMDb is rate-limiting requests (HTTP 429)", 429)
    shikimori.errors["10"] = ShikimoriError("entries request failed", status=503)

    poll(tracker, clock, days=2)

    assert sorted(notices(sender)) == sorted([
        "⚠️ Не удалось проверить «Дюна»: TMDb просит подождать, слишком много запросов. Повторю через 30 мин.",
        "⚠️ Не удалось проверить «Монолог фармацевта»: Shikimori недоступен — у него сейчас сбой. Повторю через 30 мин.",
    ])


def test_titles_told_about_today_do_not_join_a_later_group(tracker, source, clock, sender):
    add_movie(tracker, "1", "Дюна")
    source.errors["1"] = ConnectionError("down")
    poll(tracker, clock, days=2)
    second = add_movie(tracker, "2", "Укрытие")
    source.errors["2"] = ConnectionError("down")
    make_due(tracker.session_factory, second, clock.now + timedelta(minutes=31))
    sender.sent.clear()

    poll(tracker, clock, minutes=31)

    assert notices(sender) == ["⚠️ Не удалось проверить «Укрытие»: не удалось подключиться к TMDb. Повторю через 30 мин."]


# --- what the message may not contain ------------------------------------------------------------


def test_addresses_keys_and_exception_names_stay_in_the_log(tracker, source, clock, sender, caplog):
    add_movie(tracker, "1", "Дюна")
    source.errors["1"] = RuntimeError("GET https://api.themoviedb.org/3/movie/1?api_key=SECRET-KEY failed: ReadTimeout")

    poll(tracker, clock, days=2)

    (text,) = notices(sender)
    for leak in ("SECRET-KEY", "https://", "api_key", "RuntimeError", "ReadTimeout", "Traceback"):
        assert leak not in text
    assert "SECRET-KEY" not in caplog.text


# --- delivery ------------------------------------------------------------------------------------


def test_a_notice_about_one_title_has_the_card_button(tracker, source, clock, sender):
    title_id = add_movie(tracker, "1")
    source.errors["1"] = ConnectionError("down")

    poll(tracker, clock, days=2)

    ((_, actions),) = sender.sent
    assert [(a.label, a.name, a.arg) for a in actions] == [("📄 Карточка", "card", title_id)]


def test_a_notice_about_many_titles_has_no_buttons(tracker, source, clock, sender):
    for number in (1, 2):
        add_movie(tracker, str(number))
        source.errors[str(number)] = ConnectionError("down")

    poll(tracker, clock, days=2)

    ((_, actions),) = sender.sent
    assert actions == []


def test_a_notice_that_could_not_be_sent_stays_in_the_queue(tracker, source, clock, sender, session_factory):
    add_movie(tracker, "1", "Дюна")
    source.errors["1"] = ConnectionError("down")
    sender.failing = True

    poll(tracker, clock, days=2)

    assert sender.sent == []
    with session_factory() as s:
        assert s.scalars(select(DeliveryItem.status)).all() == ["pending"]
    sender.failing = False
    run(tracker.deliver_pending())
    assert len(notices(sender)) == 1
    poll(tracker, clock, minutes=31)  # and the failed delivery is not a reason for another notice
    assert len(notices(sender)) == 1


def test_the_dedup_key_holds_the_title_and_the_start_of_the_day_window(tracker, source, clock, session_factory):
    title_id = add_movie(tracker, "1")
    source.errors["1"] = ConnectionError("down")

    poll(tracker, clock, days=2)

    with session_factory() as s:
        event = s.scalars(select(Event).where(Event.type == failures.SOURCE_FAILED)).one()
    assert event.dedup_key == f"failure:{title_id}:20261026T120000"
    assert event.title_id == title_id


RULES = dict(tz_name="Asia/Jerusalem", workdays=[6, 0, 1, 2, 3], digest_at="15:00", quiet_from="21:00", quiet_until="07:30")


def local(day, hour, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=JERUSALEM).astimezone(timezone.utc)


def test_in_the_quiet_hours_the_notice_waits_and_comes_in_the_morning_summary(session_factory, sender, source):
    clock = FakeClock(local(5, 20))  # Thursday evening, a working day
    tracker = Tracker(session_factory, clock=clock, sender=sender, sources={"movie": source})
    run(tracker.set_delivery_rules(**RULES))
    add_movie(tracker, "1", "Дюна")
    source.errors["1"] = ConnectionError("down")

    clock.now = local(5, 22)  # quiet hours
    make_due(session_factory, 1, clock.now)
    run(tracker.poll_due())
    run(tracker.deliver_pending())
    assert sender.sent == []

    clock.now = local(6, 7, 29)
    run(tracker.deliver_pending())
    assert sender.sent == []

    clock.now = local(6, 7, 30)  # Friday is a day off
    run(tracker.deliver_pending())
    (message,) = sender.messages
    assert message.startswith("📋 Сводка")
    assert "Не удалось проверить «Дюна»: не удалось подключиться к TMDb. Повторю через 30 мин." in message


def test_on_a_working_morning_the_notice_is_one_line_of_the_summary(session_factory, sender, source):
    clock = FakeClock(local(1, 9))  # Sunday morning
    tracker = Tracker(session_factory, clock=clock, sender=sender, sources={"movie": source})
    run(tracker.set_delivery_rules(**RULES))
    add_movie(tracker, "1", "Дюна")
    source.errors["1"] = httpx.ReadTimeout("slow", request=REQUEST)

    clock.now = local(1, 10)
    make_due(session_factory, 1, clock.now)
    run(tracker.poll_due())
    run(tracker.deliver_pending())
    assert sender.sent == []

    clock.now = local(1, 15)
    run(tracker.deliver_pending())

    (message,) = sender.messages
    lines = message.split("\n")
    assert lines[0].startswith("📋 Сводка")
    assert lines[1] == "⚠️ Не удалось проверить «Дюна»: TMDb не ответил вовремя. Повторю через 30 мин."
    assert len(lines) == 2
    ((_, actions),) = sender.sent
    assert [a.name for a in actions] == ["card"] and "Дюна" in actions[0].label


def test_on_a_day_off_the_notice_comes_at_once(session_factory, sender, source):
    clock = FakeClock(local(6, 12))  # Friday noon
    tracker = Tracker(session_factory, clock=clock, sender=sender, sources={"movie": source})
    run(tracker.set_delivery_rules(**RULES))
    add_movie(tracker, "1", "Дюна")
    source.errors["1"] = ConnectionError("down")

    clock.now = local(6, 13)
    make_due(session_factory, 1, clock.now)
    run(tracker.poll_due())
    run(tracker.deliver_pending())

    assert len(notices(sender)) == 1


# --- the test event ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind_id, label, text",
    [
        (
            "failure-one", "Сбой источника: один тайтл",
            "⚠️ Не удалось проверить «Дюна»: TMDb не ответил вовремя. Повторю через 30 мин.",
        ),
        (
            "failure-many", "Сбой источника: несколько тайтлов",
            "⚠️ Не удалось проверить 6 тайтлов: TMDb не ответил вовремя. Дюна, Укрытие, Аркейн, Оппенгеймер, Барби, …",
        ),
    ],
)
def test_the_samples_are_in_the_test_event_menu(tracker, sender, kind_id, label, text):
    assert label in [kind.label for kind in tracker.test_event_kinds()]

    result = run(tracker.send_test_event(kind_id))

    assert result.delivered
    assert text in sender.messages[0]


# --- a title deleted while the common message waits ---------------------------------------------


def three_waiting_failures(session_factory, sender, source):
    clock = FakeClock(local(5, 20))  # Thursday evening
    tracker = Tracker(session_factory, clock=clock, sender=sender, sources={"movie": source})
    run(tracker.set_delivery_rules(**RULES))
    ids = [add_movie(tracker, str(n), name) for n, name in enumerate(["Дюна", "Укрытие", "Аркейн"], start=1)]
    for n in (1, 2, 3):
        source.errors[str(n)] = httpx.ReadTimeout("slow", request=REQUEST)
    clock.now = local(5, 22)  # quiet hours
    for title_id in ids:
        make_due(session_factory, title_id, clock.now)
    run(tracker.poll_due())
    run(tracker.deliver_pending())
    assert sender.sent == []
    clock.now = local(6, 7, 30)
    return tracker, ids


def test_a_deleted_title_is_not_named_in_the_morning_summary(session_factory, sender, source):
    tracker, ids = three_waiting_failures(session_factory, sender, source)
    run(tracker.delete_title(ids[1]))

    run(tracker.deliver_pending())

    (message,) = sender.messages
    assert "Не удалось проверить 2 тайтла: TMDb не ответил вовремя. Дюна, Аркейн." in message
    assert "Укрытие" not in message


def test_when_one_of_three_is_left_it_comes_as_a_single_message(session_factory, sender, source):
    tracker, ids = three_waiting_failures(session_factory, sender, source)
    run(tracker.delete_title(ids[0]))
    run(tracker.delete_title(ids[1]))

    run(tracker.deliver_pending())

    (message,) = sender.messages
    assert "⚠️ Не удалось проверить «Аркейн»: TMDb не ответил вовремя. Повторю через 30 мин." in message
    ((_, actions),) = sender.sent
    assert [a.name for a in actions] == ["card"]


def test_when_all_are_deleted_nothing_comes(session_factory, sender, source):
    tracker, ids = three_waiting_failures(session_factory, sender, source)
    for title_id in ids:
        run(tracker.delete_title(title_id))

    run(tracker.deliver_pending())

    assert sender.sent == []
