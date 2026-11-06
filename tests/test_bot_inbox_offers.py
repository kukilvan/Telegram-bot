"""Offers of «Входящие» in the bot (spec 2.3, 6, 7.3 of stage 6.4) through a real aiogram Dispatcher, the real core and
the fakes of the sources on the saved answers: the offer card with its poster and «✅ Да» / «❌ Нет», every result of the
analysis, «Да» (a game, a series with its seasons), «Нет» to the end, «Уже в списке», links without a question, the
buttons of an item in «Входящие» and of a gone one."""

import asyncio

import pytest
from aiogram.types import CallbackQuery, Message

from app.bot import inbox_handlers
from app.tracker.core import InboxReason, InboxState
from app.tracker.models import TitleKind
from inbox_fakes import Clients, samples, tracker_on
from test_bot_inbox import Conversation

PAUSE = 0.15
NOT_FOUND = "Не нашёл — сохранил во «Входящие». Разберите в веб-приложении."
SEASONS_QUESTION = "Какие сезоны вы уже посмотрели?"


@pytest.fixture(autouse=True)
def short_pause(monkeypatch):
    monkeypatch.setattr(inbox_handlers, "PAUSE_SECONDS", PAUSE)


@pytest.fixture
def clients():
    return Clients()


@pytest.fixture
def tracker(clients):
    return tracker_on(clients)


class Said(list):
    """("message", text, rows, preview), ("popup", text), ("edit", rows)."""

    def messages(self):
        return [entry for entry in self if entry[0] == "message"]

    def texts(self):
        return [entry[1] for entry in self.messages()]


@pytest.fixture
def telegram(monkeypatch):
    said = Said()

    def rows_of(markup):
        return [[(b.text, b.callback_data) for b in row] for row in getattr(markup, "inline_keyboard", [])] if markup else []

    async def message_answer(self, text=None, **kwargs):
        said.append(("message", text, rows_of(kwargs.get("reply_markup")), kwargs.get("link_preview_options")))

    async def callback_answer(self, text=None, **kwargs):
        said.append(("popup", text))

    async def edit_reply_markup(self, reply_markup=None, **kwargs):
        said.append(("edit", rows_of(reply_markup)))

    monkeypatch.setattr(Message, "answer", message_answer)
    monkeypatch.setattr(CallbackQuery, "answer", callback_answer)
    monkeypatch.setattr(Message, "edit_reply_markup", edit_reply_markup)
    return said


def talk(tracker, *steps):
    """Each step: a text to send (then the pause runs out) or a button to press."""
    async def go():
        chat = Conversation(tracker)
        for step in steps:
            if step.startswith("inb:"):
                await chat.press(step)
            else:
                await chat.say(step)
                await asyncio.sleep(PAUSE * 3)

    asyncio.run(go())


def offered(tracker, telegram, text, kind):
    """`text` sent and its kind pressed; what the bot said is forgotten."""
    talk(tracker, text, f"inb:1:k:{kind}")
    telegram.clear()


def item(tracker, item_id=1):
    return asyncio.run(tracker.inbox_item(item_id))


# --- the card ----------------------------------------------------------------------------------------------


def test_a_kind_press_sends_the_offer_card_with_the_poster_above_and_yes_no(tracker, telegram):
    talk(tracker, samples()[10], "inb:1:k:game")

    _, text, rows, preview = telegram.messages()[-1]
    assert text == "Это оно?\n\n🎮 The Wolf Among Us Remastered\n2026 · ПК, PS5, Xbox One, Switch"
    assert rows == [[("✅ Да", "inb:1:y:0"), ("❌ Нет", "inb:1:n:0")]]
    assert preview.url.startswith("https://images.igdb.com/igdb/image/upload/t_cover_big_2x/")
    assert preview.show_above_text and preview.prefer_large_media
    assert item(tracker).state == InboxState.WAITING


def test_an_offer_without_a_poster_is_a_text_card():
    tracker = tracker_on(Clients(extra={"game:Без обложки": [{"id": 1, "name": "Без обложки", "game_type": 0}]}))

    async def go(said):
        chat = Conversation(tracker)
        await chat.say("Без обложки")
        await asyncio.sleep(PAUSE * 3)
        await chat.press("inb:1:k:game")

    said = []

    async def message_answer(self, text=None, **kwargs):
        said.append(kwargs.get("link_preview_options"))

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Message, "answer", message_answer)
        patch.setattr(CallbackQuery, "answer", lambda self, text=None, **kw: asyncio.sleep(0))
        patch.setattr(Message, "edit_reply_markup", lambda self, **kw: asyncio.sleep(0))
        asyncio.run(go(said))

    assert said[-1].is_disabled


def test_nothing_found_the_source_failed_and_games_not_connected_are_said_and_kept(clients, telegram):
    tracker = tracker_on(clients)
    talk(tracker, samples()[12], "inb:1:k:game")
    assert telegram.texts()[-1] == NOT_FOUND

    clients.tmdb.fail_from = 1
    talk(tracker, "Дюна", "inb:2:k:movie")
    assert telegram.texts()[-1] == "Не удалось связаться с TMDb — сохранил во «Входящие»."
    assert item(tracker, 2).reason == InboxReason.SOURCE_FAILED

    unconnected = tracker_on(Clients(igdb_keys=False))
    talk(unconnected, "Hades 2", "inb:1:k:game")
    assert telegram.texts()[-1] == "Игры не подключены: нет ключей IGDB в .env — сохранил во «Входящие»."


# --- «Да» ----------------------------------------------------------------------------------------------------


def test_yes_on_a_game_adds_it_and_shows_its_card(tracker, telegram):
    offered(tracker, telegram, samples()[5], "game")

    talk(tracker, "inb:1:y:0")

    assert telegram[0] == ("popup", "Добавляю…")
    assert ("edit", []) in telegram
    [(_, text, rows, preview)] = telegram.messages()  # no seasons question for a game
    assert text.startswith("✅ Добавлено в список\n\n🎮 Игра · Хочу\nPhantom Blade Zero")
    assert [label for row in rows for label, _ in row] == ["🗑 Удалить"]  # a game moves between statuses on the web
    assert preview.url and item(tracker) is None


def test_yes_on_a_series_asks_the_watched_seasons(tracker, telegram):
    offered(tracker, telegram, samples()[2], "series")

    talk(tracker, "inb:1:y:0")

    first, second = telegram.texts()
    assert first.startswith("✅ Добавлено в список\n\n📺 Сериал")
    assert second.startswith(SEASONS_QUESTION)


def test_yes_when_the_source_fails_keeps_the_buttons(tracker, clients, telegram):
    offered(tracker, telegram, samples()[5], "game")
    clients.igdb.fail_from = 1

    talk(tracker, "inb:1:y:0")

    assert telegram == [("popup", "Добавляю…"), (
        "message", "Не удалось получить данные из IGDB. Нажмите «Да» ещё раз чуть позже.", [], None,
    )]


def test_a_title_in_the_list_says_so_with_its_card_and_resolves_the_item(tracker, telegram):
    asyncio.run(tracker.add_title(TitleKind.GAME, "250618"))

    talk(tracker, samples()[15], "inb:1:k:game")

    _, text, _, _ = telegram.messages()[-1]
    assert text.startswith("Уже в списке\n\n🎮 Игра · Хочу\nPhantom Blade Zero")
    assert item(tracker) is None


# --- «Нет» ---------------------------------------------------------------------------------------------------


def test_no_goes_through_the_offers_to_the_inbox(tracker, telegram):
    offered(tracker, telegram, samples()[5], "game")

    talk(tracker, "inb:1:n:0", "inb:1:n:1", "inb:1:n:2")

    assert telegram[:2] == [("popup", None), ("edit", [])]
    cards = [entry for entry in telegram.messages() if entry[2]]
    assert [rows[0][0][1] for _, _, rows, _ in cards] == ["inb:1:y:1", "inb:1:y:2"]
    assert "Black Myth: Wukong" in cards[0][1] and "Elden Ring" in cards[1][1]
    assert telegram.texts()[-1] == NOT_FOUND
    assert (item(tracker).state, item(tracker).reason) == (InboxState.INBOX, InboxReason.NOT_FOUND)


def test_gone_and_dead_numbers_are_popups(tracker, telegram):
    offered(tracker, telegram, samples()[11], "game")  # two offers

    talk(tracker, "inb:1:y:2", "inb:1:n:7")
    assert telegram == [("popup", "Эта кнопка больше не работает."), ("popup", "Эта кнопка больше не работает.")]

    asyncio.run(tracker.forget_inbox_item(1))
    telegram.clear()
    talk(tracker, "inb:1:y:0", "inb:1:n:0")
    assert telegram == [("popup", "Эта запись уже разобрана."), ("popup", "Эта запись уже разобрана.")]


# --- links and «Входящие» --------------------------------------------------------------------------------


def test_a_steam_link_gets_the_card_at_once_without_a_question(tracker, telegram):
    talk(tracker, "https://store.steampowered.com/app/1245620/")

    [(_, text, rows, _)] = telegram.messages()
    assert text.startswith("Это оно?\n\n🎮 Elden Ring")
    assert rows == [[("✅ Да", "inb:1:y:0"), ("❌ Нет", "inb:1:n:0")]]


def test_the_first_card_of_a_new_item_says_the_previous_one_went_to_the_inbox(tracker, telegram):
    talk(tracker, "Привет", "https://store.steampowered.com/app/1245620/")

    assert telegram.texts()[-1].startswith("Предыдущий пост без ответа ушёл во «Входящие».\n\nЭто оно?")


def test_the_buttons_of_an_item_in_the_inbox_still_work_and_it_stays_there(tracker, telegram):
    talk(tracker, samples()[10], "Второй пост", "inb:1:k:game")

    assert telegram.texts()[-1].startswith("Это оно?\n\n🎮 The Wolf Among Us Remastered")
    assert item(tracker, 1).state == InboxState.INBOX and item(tracker, 2).state == InboxState.WAITING

    talk(tracker, "inb:1:y:0")
    assert telegram.texts()[-1].startswith("✅ Добавлено в список") and item(tracker, 1) is None
