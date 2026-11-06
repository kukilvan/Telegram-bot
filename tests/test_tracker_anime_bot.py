"""The card of an anime in the bot and marking its watched seasons: owner only, through a real aiogram Dispatcher.

Telegram itself is replaced by capturing what the bot would say; the tracker core and the Shikimori adapter are
real, on the saved real answers (tests/fixtures/shikimori).
"""

import asyncio
from datetime import datetime, timezone

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from anime_fakes import FakeAniList, FakeShikimori
from app.bot.access import AccessMiddleware
from app.bot.tracker_handlers import register_tracker_handlers
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import TitleKind
from app.tracker.sources.shikimori_anime import ShikimoriAnimeSource

OWNER = 42
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


def run(coro):
    return asyncio.run(coro)


class FakeSender:
    async def send(self, message, actions=()):
        pass


@pytest.fixture
def shikimori():
    return FakeShikimori()


@pytest.fixture
def tracker(shikimori):
    return Tracker(
        create_session_factory("sqlite://"),
        clock=lambda: NOW,
        sender=FakeSender(),
        sources={"anime": ShikimoriAnimeSource(shikimori, FakeAniList())},
    )


@pytest.fixture
def replies(monkeypatch):
    """What the bot said: ("message", text, buttons), ("callback", text, None) or ("edit", None, buttons)."""
    said = []

    def buttons_of(markup):
        return [b for row in getattr(markup, "inline_keyboard", []) for b in row] if markup else []

    async def message_answer(self, text=None, **kwargs):
        said.append(("message", text, buttons_of(kwargs.get("reply_markup"))))

    async def callback_answer(self, text=None, **kwargs):
        said.append(("callback", text, None))

    async def edit_reply_markup(self, reply_markup=None, **kwargs):
        said.append(("edit", None, buttons_of(reply_markup)))

    monkeypatch.setattr(Message, "answer", message_answer)
    monkeypatch.setattr(CallbackQuery, "answer", callback_answer)
    monkeypatch.setattr(Message, "edit_reply_markup", edit_reply_markup)
    return said


class Chat_:
    def __init__(self, tracker, uid=OWNER):
        self.uid = uid
        self.dp = Dispatcher()
        self.dp.update.outer_middleware(AccessMiddleware([OWNER]))
        register_tracker_handlers(self.dp, tracker, [OWNER])
        self._update_id = 0

    def _feed(self, **update):
        self._update_id += 1
        asyncio.run(self.dp.feed_update(Bot(token="123456:TEST"), Update(update_id=self._update_id, **update)))

    def _user(self):
        return User(id=self.uid, is_bot=False, first_name="x")

    def _message(self, text=None):
        return Message(
            message_id=1, date=0, chat=Chat(id=self.uid, type="private"), from_user=self._user(), text=text
        )

    def say(self, text):
        self._feed(message=self._message(text))

    def press(self, data):
        self._feed(
            callback_query=CallbackQuery(
                id="1", from_user=self._user(), chat_instance="c", data=data, message=self._message("menu")
            )
        )


def labels(buttons):
    return [b.text for b in buttons]


def callback_of(buttons, label_part):
    return next(b.callback_data for b in buttons if label_part in b.text)


def last_message(replies):
    return next(r for r in reversed(replies) if r[0] == "message")


JUJUTSU = "40748"  # «Магическая битва», the first season of the franchise


def add_anime(tracker, external_id=JUJUTSU):
    """Into the list as the core adds it (the bot adds by «Да» on an offer, ticket 04 of stage 6.4)."""
    return run(tracker.add_title(TitleKind.ANIME, external_id))


def test_the_card_of_an_added_anime_shows_the_seasons_and_the_films(tracker, replies):
    add_anime(tracker)
    Chat_(tracker).press("tcard:1")

    card = last_message(replies)[1]
    assert "🎌 Аниме · Хочу" in card
    assert "Магическая битва · Jujutsu Kaisen" in card
    assert "Сезон 3: вышло 12 из 12" in card
    assert "Сезон 4 анонсирован" in card
    assert "Фильмы франшизы: Магическая битва 0. Фильм (2021)" in card
    [entry] = run(tracker.list_titles())
    assert (entry.kind, entry.status) == ("anime", "want")


def test_the_seasons_button_asks_which_seasons_are_watched(tracker, replies):
    add_anime(tracker)
    Chat_(tracker).press("tact:seasons:1")

    _, text, buttons = last_message(replies)
    assert "сезоны" in text.lower() and "посмотрел" in text.lower()
    assert labels(buttons) == ["Сезон 1", "Сезон 2", "Сезон 3", "Готово"]  # the announced season 4 is not offered


def test_marking_all_released_seasons_makes_the_anime_wait(tracker, replies):
    add_anime(tracker)
    chat = Chat_(tracker)
    chat.press("tact:seasons:1")
    buttons = last_message(replies)[2]
    for season in ("Сезон 1", "Сезон 2", "Сезон 3"):
        chat.press(callback_of(buttons, season))
    chat.press(callback_of(buttons, "Готово"))

    card = last_message(replies)[1]
    assert "🎌 Аниме · Жду" in card
    assert "Просмотрены сезоны: 1, 2, 3" in card


def test_the_card_of_a_listed_anime_has_the_seasons_button(tracker, replies):
    add_anime(tracker)
    Chat_(tracker).press("tcard:1")

    assert labels(last_message(replies)[2]) == ["📺 Просмотренные сезоны", "🗑 Удалить"]


def test_adding_the_franchise_through_another_entry_opens_the_same_title(tracker):
    add_anime(tracker)

    result = add_anime(tracker, "48561")  # the prequel film of the same franchise

    assert not result.created
    assert len(run(tracker.list_titles())) == 1
