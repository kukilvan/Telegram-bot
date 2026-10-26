"""«🗑 Удалить» in the bot: one title from its card, several from «Мои тайтлы». Owner only, through a real Dispatcher.

Telegram itself is replaced by capturing what the bot would say; the tracker core is real.
"""

import asyncio
from datetime import date, datetime, timezone

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from sqlalchemy import func, select

from app.bot.access import AccessMiddleware
from app.bot.tracker_handlers import MY_TITLES_BUTTON, register_tracker_handlers
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import Event
from app.tracker.sources.tmdb_movies import MovieSnapshot

OWNER, STRANGER = 42, 7
NAMES = {"1": "Дюна", "2": "Дюна: Часть вторая", "3": "Дюна: Часть третья"}
STALE = "Эта кнопка больше не работает, откройте список заново."


def movie(external_id):
    return MovieSnapshot(
        external_id=external_id,
        name=NAMES[external_id],
        original_name=NAMES[external_id],
        year=2021,
        genres=[],
        theatrical_date=date(2027, 1, 1),
    )


class FakeMovieSource:
    source_key = "tmdb_movie"

    async def suggest(self, query):
        return []

    async def snapshot(self, external_id):
        return movie(external_id) if external_id in NAMES else None


class FakeSender:
    async def send(self, message, actions=()):
        pass


@pytest.fixture
def tracker():
    return Tracker(
        create_session_factory("sqlite://"),
        clock=lambda: datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc),
        sender=FakeSender(),
        sources={"movie": FakeMovieSource()},
    )


class Said(list):
    """The bot's replies in order; `dropped` holds keyboards taken off messages, `edited` keyboards put in their place."""

    def __init__(self):
        super().__init__()
        self.dropped = []
        self.edited = []


@pytest.fixture
def replies(monkeypatch):
    said = Said()

    async def message_answer(self, text=None, **kwargs):
        markup = kwargs.get("reply_markup")
        rows = getattr(markup, "inline_keyboard", []) if markup else []
        said.append(("message", text, [b for row in rows for b in row]))

    async def callback_answer(self, text=None, **kwargs):
        said.append(("callback", text, None))

    async def edit_markup(self, **kwargs):
        markup = kwargs.get("reply_markup")
        if markup is None:
            said.dropped.append(None)
        else:
            said.edited.append([b for row in markup.inline_keyboard for b in row])

    monkeypatch.setattr(Message, "answer", message_answer)
    monkeypatch.setattr(CallbackQuery, "answer", callback_answer)
    monkeypatch.setattr(Message, "edit_reply_markup", edit_markup)
    return said


class Chat_:
    """One conversation with the bot through a real Dispatcher; a new one is a bot that has just been restarted."""

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
        return Message(message_id=1, date=0, chat=Chat(id=self.uid, type="private"), from_user=self._user(), text=text)

    def say(self, text):
        self._feed(message=self._message(text))

    def press(self, data):
        self._feed(
            callback_query=CallbackQuery(
                id="1", from_user=self._user(), chat_instance="c", data=data, message=self._message("menu")
            )
        )


def run(coro):
    return asyncio.run(coro)


def add(tracker, external_id="1"):
    return run(tracker.add_title("movie", external_id)).title_id


def labels(buttons):
    return [b.text for b in buttons]


def callback_of(buttons, label_part):
    return next(b.callback_data for b in buttons if label_part in b.text)


def last_message(replies):
    return [r for r in replies if r[0] == "message"][-1]


def callbacks(replies):
    return [r[1] for r in replies if r[0] == "callback"]


def names(tracker):
    return [t.name for t in run(tracker.list_titles())]


def ask_to_delete(chat, tracker, replies, title_id):
    chat.press(f"tact:delete:{title_id}")
    return last_message(replies)[2]


# --- from the card -------------------------------------------------------------------------------


def test_the_card_of_a_title_has_a_delete_button(tracker, replies):
    title_id = add(tracker)

    Chat_(tracker).press(f"tcard:{title_id}")

    assert "🗑 Удалить" in labels(last_message(replies)[2])


def test_pressing_delete_asks_first_and_erases_nothing(tracker, replies):
    title_id = add(tracker)

    buttons = ask_to_delete(Chat_(tracker), tracker, replies, title_id)

    assert last_message(replies)[1] == (
        "Удалить «Дюна» из списка? Сезоны, отметки и накопленные события тоже сотрутся. Вернуть нельзя."
    )
    assert labels(buttons) == ["Да, удалить", "Отмена"]
    assert names(tracker) == ["Дюна"]


def test_confirming_erases_the_title_and_takes_the_buttons_off(tracker, replies):
    title_id = add(tracker)
    chat = Chat_(tracker)
    buttons = ask_to_delete(chat, tracker, replies, title_id)

    chat.press(callback_of(buttons, "Да, удалить"))

    assert names(tracker) == []
    assert last_message(replies)[1] == "🗑 Удалено: Дюна"
    assert replies.dropped == [None]


def test_cancelling_erases_nothing(tracker, replies):
    title_id = add(tracker)
    chat = Chat_(tracker)
    buttons = ask_to_delete(chat, tracker, replies, title_id)

    chat.press(callback_of(buttons, "Отмена"))

    assert names(tracker) == ["Дюна"]
    assert replies.dropped == [None]
    assert callbacks(replies)[-1] == "Отменено, тайтл остался в списке."


def test_the_events_of_the_deleted_title_go_too(tracker, replies):
    title_id = add(tracker)
    run(tracker.record_event("movie_released", {"text": "x"}, "k", title_id=title_id))
    chat = Chat_(tracker)

    chat.press(callback_of(ask_to_delete(chat, tracker, replies, title_id), "Да, удалить"))

    with tracker.session_factory() as s:
        assert s.scalar(select(func.count()).select_from(Event)) == 0


def test_confirming_twice_says_the_title_is_gone(tracker, replies):
    title_id = add(tracker)
    chat = Chat_(tracker)
    yes = callback_of(ask_to_delete(chat, tracker, replies, title_id), "Да, удалить")
    chat.press(yes)
    replies.clear()

    chat.press(yes)

    assert replies == [("callback", "Этого тайтла больше нет в списке.", None)]


def test_asking_to_delete_a_title_that_is_gone_says_so(tracker, replies):
    Chat_(tracker).press("tact:delete:999")

    assert replies == [("callback", "Этого тайтла больше нет в списке.", None)]


def test_the_old_buttons_of_a_deleted_title_say_it_is_gone(tracker, replies):
    title_id = add(tracker)
    chat = Chat_(tracker)
    chat.press(callback_of(ask_to_delete(chat, tracker, replies, title_id), "Да, удалить"))
    replies.clear()

    for data in (f"tact:watched:{title_id}", f"tact:card:{title_id}", f"tact:seasons:{title_id}", f"tsea:{title_id}:1"):
        chat.press(data)

    assert callbacks(replies) == ["Этого тайтла больше нет в списке."] * 4


def test_a_stranger_cannot_delete_anything(tracker, replies):
    title_id = add(tracker)
    chat = Chat_(tracker, uid=STRANGER)

    for data in (f"tact:delete:{title_id}", f"tdel:y:{title_id}", f"tdel:n:{title_id}", "tdm:open"):
        chat.press(data)

    assert replies == []
    assert names(tracker) == ["Дюна"]


def test_a_broken_confirmation_button_is_answered_not_crashed(tracker, replies):
    add(tracker)
    chat = Chat_(tracker)

    chat.press("tdel:y:abc")
    chat.press("tdel:what:1")

    assert callbacks(replies) == ["Эта кнопка больше не работает."] * 2
    assert names(tracker) == ["Дюна"]


# --- several at once -----------------------------------------------------------------------------


def open_selection(chat, tracker, replies):
    chat.say(MY_TITLES_BUTTON)
    chat.press(callback_of(last_message(replies)[2], "Удалить несколько"))
    return last_message(replies)[2]


def test_my_titles_offers_to_delete_several(tracker, replies):
    add(tracker, "1")

    Chat_(tracker).say(MY_TITLES_BUTTON)

    assert labels(last_message(replies)[2])[-1] == "🗑 Удалить несколько"


def test_the_selection_lists_every_title_with_a_counter_and_a_cancel_button(tracker, replies):
    add(tracker, "1")
    add(tracker, "2")

    buttons = open_selection(Chat_(tracker), tracker, replies)

    assert labels(buttons) == ["🎬 Дюна (2021)", "🎬 Дюна: Часть вторая (2021)", "Удалить выбранные (0)", "Отмена"]


def test_pressing_a_title_marks_it_and_pressing_again_unmarks_it(tracker, replies):
    add(tracker, "1")
    add(tracker, "2")
    chat = Chat_(tracker)
    buttons = open_selection(chat, tracker, replies)

    chat.press(callback_of(buttons, "Часть вторая"))
    chat.press(callback_of(buttons, "Часть вторая"))

    assert labels(replies.edited[0]) == ["🎬 Дюна (2021)", "✅ Дюна: Часть вторая (2021)", "Удалить выбранные (1)", "Отмена"]
    assert labels(replies.edited[1])[-2] == "Удалить выбранные (0)"
    assert names(tracker) == ["Дюна", "Дюна: Часть вторая"]


def test_an_empty_selection_deletes_nothing_and_says_so(tracker, replies):
    add(tracker, "1")
    chat = Chat_(tracker)
    buttons = open_selection(chat, tracker, replies)
    replies.clear()

    chat.press(callback_of(buttons, "Удалить выбранные"))

    assert replies == [("callback", "Ничего не выбрано, удалять нечего.", None)]
    assert names(tracker) == ["Дюна"]


def test_the_chosen_titles_are_confirmed_by_name_and_then_deleted(tracker, replies):
    add(tracker, "1")
    add(tracker, "2")
    add(tracker, "3")
    chat = Chat_(tracker)
    buttons = open_selection(chat, tracker, replies)
    chat.press(callback_of(buttons, "Дюна (2021)"))
    chat.press(callback_of(buttons, "Часть третья"))

    chat.press(callback_of(buttons, "Удалить выбранные"))

    text, confirm = last_message(replies)[1:]
    assert text == (
        "Удалить «Дюна», «Дюна: Часть третья» из списка? "
        "Сезоны, отметки и накопленные события тоже сотрутся. Вернуть нельзя."
    )
    assert labels(confirm) == ["Да, удалить", "Отмена"]
    assert len(names(tracker)) == 3

    chat.press(callback_of(confirm, "Да, удалить"))

    assert names(tracker) == ["Дюна: Часть вторая"]
    assert last_message(replies)[1] == "🗑 Удалено: Дюна, Дюна: Часть третья"
    assert replies.dropped == [None]


def test_cancelling_the_confirmation_of_several_erases_nothing(tracker, replies):
    add(tracker, "1")
    chat = Chat_(tracker)
    buttons = open_selection(chat, tracker, replies)
    chat.press(callback_of(buttons, "Дюна (2021)"))
    chat.press(callback_of(buttons, "Удалить выбранные"))

    chat.press(callback_of(last_message(replies)[2], "Отмена"))

    assert names(tracker) == ["Дюна"]
    assert callbacks(replies)[-1] == "Отменено, ничего не удалено."


def test_cancelling_the_selection_erases_nothing_and_ends_it(tracker, replies):
    add(tracker, "1")
    chat = Chat_(tracker)
    buttons = open_selection(chat, tracker, replies)
    chat.press(callback_of(buttons, "Дюна (2021)"))

    chat.press(callback_of(buttons, "Отмена"))
    chat.press(callback_of(buttons, "Дюна (2021)"))

    assert names(tracker) == ["Дюна"]
    assert callbacks(replies)[-2:] == ["Отменено, ничего не удалено.", STALE]


def test_after_a_restart_an_old_selection_button_asks_to_open_the_list_again(tracker, replies):
    add(tracker, "1")
    buttons = open_selection(Chat_(tracker), tracker, replies)
    restarted = Chat_(tracker)
    replies.clear()

    for label in ("Дюна (2021)", "Удалить выбранные", "Отмена"):
        restarted.press(callback_of(buttons, label))

    assert callbacks(replies) == [STALE] * 3
    assert names(tracker) == ["Дюна"]


def test_the_buttons_of_an_older_selection_stop_working_when_a_new_one_is_opened(tracker, replies):
    add(tracker, "1")
    chat = Chat_(tracker)
    old = open_selection(chat, tracker, replies)
    open_selection(chat, tracker, replies)
    replies.clear()

    chat.press(callback_of(old, "Дюна (2021)"))

    assert callbacks(replies) == [STALE]


def test_a_title_deleted_meanwhile_does_not_break_deleting_the_rest(tracker, replies):
    first = add(tracker, "1")
    add(tracker, "2")
    chat = Chat_(tracker)
    buttons = open_selection(chat, tracker, replies)
    chat.press(callback_of(buttons, "Дюна (2021)"))
    chat.press(callback_of(buttons, "Часть вторая"))
    chat.press(callback_of(buttons, "Удалить выбранные"))
    confirm = last_message(replies)[2]
    run(tracker.delete_title(first))  # removed from its own card while the question was open

    chat.press(callback_of(confirm, "Да, удалить"))

    assert names(tracker) == []
    assert last_message(replies)[1] == "🗑 Удалено: Дюна: Часть вторая"


def test_if_every_chosen_title_is_already_gone_the_bot_says_so(tracker, replies):
    first = add(tracker, "1")
    chat = Chat_(tracker)
    buttons = open_selection(chat, tracker, replies)
    chat.press(callback_of(buttons, "Дюна (2021)"))
    chat.press(callback_of(buttons, "Удалить выбранные"))
    confirm = last_message(replies)[2]
    run(tracker.delete_title(first))

    chat.press(callback_of(confirm, "Да, удалить"))

    assert last_message(replies)[1] == "Этих тайтлов уже нет в списке."


def test_the_list_is_up_to_date_after_deleting_and_adding_again_works(tracker, replies):
    title_id = add(tracker, "1")
    chat = Chat_(tracker)
    chat.press(callback_of(ask_to_delete(chat, tracker, replies, title_id), "Да, удалить"))

    chat.say(MY_TITLES_BUTTON)
    assert last_message(replies)[1].startswith("Список пуст")

    again = run(tracker.add_title("movie", "1"))
    assert again.created is True
    assert names(tracker) == ["Дюна"]


def test_a_title_marked_after_the_question_is_not_deleted_by_the_answer(tracker, replies):
    add(tracker, "1")
    add(tracker, "2")
    chat = Chat_(tracker)
    buttons = open_selection(chat, tracker, replies)
    chat.press(callback_of(buttons, "Дюна (2021)"))
    chat.press(callback_of(buttons, "Удалить выбранные"))
    confirm = last_message(replies)[2]
    replies.clear()

    chat.press(callback_of(buttons, "Часть вторая"))  # the old selection buttons no longer work
    chat.press(callback_of(confirm, "Да, удалить"))

    assert callbacks(replies)[0] == STALE
    assert names(tracker) == ["Дюна: Часть вторая"]


def test_a_failed_deletion_keeps_the_question_so_the_press_can_be_repeated(tracker, replies, monkeypatch):
    title_id = add(tracker)
    chat = Chat_(tracker)
    yes = callback_of(ask_to_delete(chat, tracker, replies, title_id), "Да, удалить")
    original = tracker._titles._delete_title

    def broken(_title_id):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(tracker._titles, "_delete_title", broken)
    chat.press(yes)
    assert callbacks(replies)[-1] == "Не удалось удалить. Попробуйте ещё раз."
    assert replies.dropped == []
    assert names(tracker) == ["Дюна"]

    monkeypatch.setattr(tracker._titles, "_delete_title", original)
    chat.press(yes)

    assert names(tracker) == []


def test_a_title_that_could_not_be_deleted_is_named_in_the_answer(tracker, replies, monkeypatch):
    add(tracker, "1")
    add(tracker, "2")
    chat = Chat_(tracker)
    buttons = open_selection(chat, tracker, replies)
    chat.press(callback_of(buttons, "Дюна (2021)"))
    chat.press(callback_of(buttons, "Часть вторая"))
    chat.press(callback_of(buttons, "Удалить выбранные"))
    confirm = last_message(replies)[2]
    original = tracker._titles._delete_title

    def broken_for_the_first(title_id):
        if title_id == 1:
            raise RuntimeError("database is locked")
        return original(title_id)

    monkeypatch.setattr(tracker._titles, "_delete_title", broken_for_the_first)
    chat.press(callback_of(confirm, "Да, удалить"))

    assert last_message(replies)[1] == (
        "🗑 Удалено: Дюна: Часть вторая\nНе удалось удалить: Дюна. Откройте список и попробуйте ещё раз."
    )
    assert names(tracker) == ["Дюна"]
