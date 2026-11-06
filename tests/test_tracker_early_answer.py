"""A press that goes to the network is answered first: «answer → work → tell» (rule 8 in docs/coding-standards.md).

Telegram takes one answer per press and drops it ("query is too old") if it comes late. The fake Telegram here
rejects an answer that arrives after a source has started, like the real one does for a slow source.
"""

import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import AnswerCallbackQuery
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from app.bot.access import AccessMiddleware
from app.bot.tracker_handlers import register_tracker_handlers
from app.tracker.core import IncomingMessage, Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import TitleKind
from app.tracker.seasons import Episode, Season
from app.tracker.sources.tmdb_movies import MovieSnapshot
from app.tracker.sources.tmdb_sequels import CollectionPart, SequelSnapshot
from app.tracker.sources.tmdb_series import SeriesSnapshot
from test_tracker_game_follow_ups import FakeFollowUps, MadeUpGames, game

OWNER = 42
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
ADDING = "Добавляю…"
SILO, DUNE_3, DUNE = "125988", "1170608", "438631"


def run(coro):
    return asyncio.run(coro)


class Journal(list):
    """What happened, in order: ("answer", text), ("source", id) and ("message", text, buttons)."""

    def of(self, what):
        return [entry for entry in self if entry[0] == what]

    @property
    def started(self):
        return bool(self.of("source"))


class SlowSource:
    """A source that takes its time (a series with dozens of seasons) and can fail."""

    def __init__(self, source_key, journal, snapshots):
        self.source_key = source_key
        self.journal = journal
        self.by_id = snapshots
        self.failing = False

    async def suggest(self, query):
        return []

    async def snapshot(self, external_id):
        self.journal.append(("source", external_id))
        await asyncio.sleep(0.02)
        if self.failing:
            raise ConnectionError("tmdb is down")
        return self.by_id.get(external_id)


class FakeSequelSource:
    source_key = "tmdb_sequels"

    async def snapshot(self, external_id):
        return SequelSnapshot(own_date=date(2021, 9, 15), parts=[CollectionPart(DUNE_3, "Дюна: Часть третья", date(2026, 12, 15))])


class SlowGames(MadeUpGames):
    """The game source of IGDB: slow to answer, can fail."""

    def __init__(self, journal):
        super().__init__()
        self.journal = journal
        self.failing = False

    async def snapshot_to_add(self, external_id):
        self.journal.append(("source", external_id))
        await asyncio.sleep(0.02)
        if self.failing:
            raise ConnectionError("igdb is down")
        return self.by_id.get(external_id)


class FakeSender:
    async def send(self, message, actions=()):
        pass


def silo():
    episodes = tuple(Episode(n + 1, datetime(2023, 5, 4) + timedelta(weeks=n)) for n in range(10))
    return SeriesSnapshot(
        external_id=SILO, name="Укрытие", original_name="Silo", year=2023, genres=["драма"],
        seasons=[Season(1, "Сезон 1", 10, episodes)],
    )


def movie(external_id, name):
    return MovieSnapshot(
        external_id=external_id, name=name, original_name=name, year=2026, genres=[], theatrical_date=date(2026, 12, 15)
    )


@pytest.fixture
def journal():
    return Journal()


@pytest.fixture
def series(journal):
    return SlowSource("tmdb_tv", journal, {SILO: silo()})


@pytest.fixture
def movies(journal):
    return SlowSource("tmdb_movie", journal, {DUNE_3: movie(DUNE_3, "Дюна: Часть третья"), DUNE: movie(DUNE, "Дюна")})


@pytest.fixture
def tracker(series, movies):
    return Tracker(
        create_session_factory("sqlite://"),
        clock=lambda: NOW,
        sender=FakeSender(),
        sources={"series": series, "movie": movies},
        sequel_sources={"movie": FakeSequelSource()},
    )


@pytest.fixture
def games(journal):
    source = SlowGames(journal)
    source.put("3", game(), "Elden Ring: Shadow of the Erdtree")
    return source


@pytest.fixture
def game_tracker(games):
    return Tracker(
        create_session_factory("sqlite://"), clock=lambda: NOW, sender=FakeSender(), sources={TitleKind.GAME: games},
        follow_up_source=FakeFollowUps(),
    )


@pytest.fixture
def telegram(monkeypatch, journal):
    """The bot's side of Telegram: one answer per press, rejected when a source has already started."""
    answered = []

    async def callback_answer(self, text=None, **kwargs):
        if answered:
            raise AssertionError(f"the press was answered twice: {answered[-1]!r}, then {text!r}")
        if journal.started:
            raise TelegramBadRequest(
                method=AnswerCallbackQuery(callback_query_id="1"), message="query is too old and response timeout expired"
            )
        answered.append(text)
        journal.append(("answer", text))

    async def message_answer(self, text=None, **kwargs):
        markup = kwargs.get("reply_markup")
        rows = getattr(markup, "inline_keyboard", []) if markup else []
        journal.append(("message", text, [b for row in rows for b in row]))

    async def edit_markup(self, **kwargs):
        pass

    monkeypatch.setattr(CallbackQuery, "answer", callback_answer)
    monkeypatch.setattr(Message, "answer", message_answer)
    monkeypatch.setattr(Message, "edit_reply_markup", edit_markup)
    return journal


def press(tracker, data, with_message=True):
    dp = Dispatcher()
    dp.update.outer_middleware(AccessMiddleware([OWNER]))
    register_tracker_handlers(dp, tracker, [OWNER])
    user = User(id=OWNER, is_bot=False, first_name="x")
    message = Message(message_id=1, date=0, chat=Chat(id=OWNER, type="private"), from_user=user, text="m")
    callback = CallbackQuery(
        id="1", from_user=user, chat_instance="c", data=data, message=message if with_message else None
    )
    run(dp.feed_update(Bot(token="123456:TEST"), Update(update_id=1, callback_query=callback)))


def texts(journal):
    return [entry[1] for entry in journal.of("message")]


# --- the kind of an inbox item («Что это?») --------------------------------------------------------------


@pytest.fixture
def watched_answers(tracker, journal, monkeypatch):
    """`answer_kind` is where the analysis goes to the sources (ticket 04 of stage 6.4): it counts as a source here."""
    real = tracker.answer_kind

    async def answer_kind(item_id, kind):
        journal.append(("source", f"inbox:{item_id}"))
        return await real(item_id, kind)

    monkeypatch.setattr(tracker, "answer_kind", answer_kind)
    return tracker


def test_a_kind_answers_the_press_before_the_work(watched_answers, telegram):
    item = run(watched_answers.take_in(IncomingMessage(text="Дюна"))).item_id

    press(watched_answers, f"inb:{item}:k:movie")

    assert [entry[0] for entry in telegram][:2] == ["answer", "source"]
    assert telegram.of("answer") == [("answer", "Ищу…")]
    assert texts(telegram) == ["Тип запомнил — сохранил во «Входящие»."]


def test_a_kind_of_an_item_removed_meanwhile_comes_as_a_message(watched_answers, telegram, monkeypatch):
    item = run(watched_answers.take_in(IncomingMessage(text="Дюна"))).item_id
    real = watched_answers.answer_kind

    async def removed_first(item_id, kind):
        await watched_answers.forget_inbox_item(item_id)  # «Убрать» on the web between the check and the work
        return await real(item_id, kind)

    monkeypatch.setattr(watched_answers, "answer_kind", removed_first)

    press(watched_answers, f"inb:{item}:k:movie")

    assert telegram.of("answer") == [("answer", "Ищу…")]
    assert texts(telegram) == ["Эта запись уже разобрана."]


@pytest.mark.parametrize("data", ["inb:1:k:movie", "inb:1:k:book", "inb:x:k:movie", "inb:1:q"])
def test_a_dead_inbox_button_is_a_popup_and_never_reaches_the_work(watched_answers, telegram, data):
    press(watched_answers, data)

    [(what, text)] = list(telegram)
    assert what == "answer" and text in ("Эта запись уже разобрана.", "Эта кнопка больше не работает.")


# --- «Следить» -----------------------------------------------------------------------------------------


def test_following_answers_the_press_before_the_source_is_asked(tracker, telegram):
    press(tracker, f"tact:follow:movie:{DUNE_3}")

    assert [entry[0] for entry in telegram][:2] == ["answer", "source"]
    assert telegram.of("answer") == [("answer", ADDING)]
    [card] = texts(telegram)
    assert card.startswith("✅ Добавлено в список") and "Дюна: Часть третья" in card


def test_a_source_failure_while_following_comes_as_a_message(tracker, movies, telegram):
    movies.failing = True

    press(tracker, f"tact:follow:movie:{DUNE_3}")

    assert telegram.of("answer") == [("answer", ADDING)]
    assert texts(telegram) == ["Не удалось получить данные из TMDb. Попробуйте чуть позже."]
    assert run(tracker.list_titles()) == []


def test_a_sequel_the_source_does_not_know_comes_as_a_message(tracker, telegram):
    press(tracker, "tact:follow:movie:1")

    assert telegram.of("answer") == [("answer", ADDING)]
    assert texts(telegram) == ["Не нашёл это в TMDb. Попробуйте чуть позже."]


def test_an_old_button_without_its_announcement_comes_as_a_message(tracker, telegram):
    press(tracker, "tact:follow:999")

    assert telegram.of("answer") == [("answer", ADDING)]
    assert texts(telegram) == ["Это объявление больше недоступно."]
    assert not telegram.started


def test_a_kind_without_sequels_comes_as_a_message(tracker, telegram):
    press(tracker, f"tact:follow:series:{SILO}")  # a real kind, but only films have sequels

    assert telegram.of("answer") == [("answer", ADDING)]
    assert texts(telegram) == ["Эта кнопка больше не работает."]
    assert not telegram.started


@pytest.mark.parametrize("data", ["tact:follow:book:1", "tact:follow:movie:", "tact:follow::1", "tact:follow:x"])
def test_a_dead_follow_button_is_a_popup_and_never_reaches_a_source(tracker, telegram, data):
    press(tracker, data)

    assert list(telegram) == [("answer", "Эта кнопка больше не работает.")]


def test_following_without_a_message_goes_to_the_log_only(tracker, movies, telegram, caplog):
    movies.failing = True

    press(tracker, f"tact:follow:movie:{DUNE_3}", with_message=False)

    assert telegram.of("answer") == [("answer", ADDING)]
    assert texts(telegram) == []
    assert any("following a title failed" in r.getMessage() and "tmdb is down" in r.getMessage() for r in caplog.records)


# --- «Следить» under the announcement of a game ---------------------------------------------------------


def test_following_a_game_answers_first_adds_it_and_shows_its_card(game_tracker, telegram):
    press(game_tracker, "tact:follow:game:3")

    assert [entry[0] for entry in telegram][:2] == ["answer", "source"]
    assert telegram.of("answer") == [("answer", ADDING)]
    [card] = texts(telegram)
    assert card.startswith("✅ Добавлено в список") and "Elden Ring: Shadow of the Erdtree" in card
    assert [t.name for t in run(game_tracker.list_titles())] == ["Elden Ring: Shadow of the Erdtree"]


def test_following_a_game_that_is_in_the_list_says_so(game_tracker, telegram):
    run(game_tracker.add_title(TitleKind.GAME, "3"))  # the owner followed it from the card meanwhile
    telegram.clear()

    press(game_tracker, "tact:follow:game:3")

    assert telegram.of("answer") == [("answer", ADDING)]
    [card] = texts(telegram)
    assert card.startswith("Уже в списке") and len(run(game_tracker.list_titles())) == 1


def test_a_game_the_source_does_not_know_names_igdb(game_tracker, telegram):
    press(game_tracker, "tact:follow:game:99")

    assert telegram.of("answer") == [("answer", ADDING)]
    assert texts(telegram) == ["Не нашёл это в IGDB. Попробуйте чуть позже."]


def test_a_failure_of_igdb_while_following_names_igdb(game_tracker, games, telegram):
    games.failing = True

    press(game_tracker, "tact:follow:game:3")

    assert telegram.of("answer") == [("answer", ADDING)]
    assert texts(telegram) == ["Не удалось получить данные из IGDB. Попробуйте чуть позже."]
    assert run(game_tracker.list_titles()) == []


def test_an_old_button_with_a_number_still_names_tmdb(tracker, telegram):
    press(tracker, "tact:follow:999")  # no such announcement: the failure names the source of a film's sequel

    assert texts(telegram) == ["Это объявление больше недоступно."]
