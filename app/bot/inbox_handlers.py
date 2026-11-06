"""Bot side of «Входящие»: taking in every other message of the owner, the pause after it, «Что это?» and its buttons.

A message that no other handler took (not a command, not a menu button) is written as an inbox item at once
(`Tracker.take_in`), before anything is answered. Two seconds after the last message of an item (a message that joins
it — an album, a forward after its comment — starts the pause again) the bot asks «Что это?», or says that a message
without text went to «Входящие». The pause lives in memory: after a restart in the middle of it the item waits without
the question until the next post or 12 hours (KI-57). Presses follow rule 8: a dead button is a popup, a live one is
answered «Ищу…» at once, the rest comes as messages. The handlers live on the owner router of `tracker_handlers`.
"""

import asyncio
import logging
from collections.abc import Collection
from dataclasses import dataclass

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.inbox_message import incoming
from app.tracker.core import PauseOutcome, Tracker, UnknownInboxItem
from app.tracker.kinds import KINDS
from app.tracker.models import TitleKind

PAUSE_SECONDS = 2.0  # after the last message of an item, before the bot answers (spec 1.3 of stage 6.4)
PREFIX = "inb:"  # inb:<item id>:k:<kind> — the kind chosen; inb:<item id>:x — «Не сохранять»
_KIND, _FORGET = "k", "x"
QUESTION = "Что это?"
FORGET_BUTTON = "🗑 Не сохранять"
NO_TEXT = "В сообщении нет текста — сохранил во «Входящие»."
PREVIOUS_MOVED = "Предыдущий пост без ответа ушёл во «Входящие»."
KIND_KEPT = "Тип запомнил — сохранил во «Входящие»."  # until the analysis of ticket 04 of stage 6.4
SEARCHING = "Ищу…"
NOT_SAVING = "Не сохраняю."
ALREADY_DONE = "Эта запись уже разобрана."
DEAD_BUTTON = "Эта кнопка больше не работает."
_NOT_TAKEN = "Не удалось сохранить сообщение — пришлите его ещё раз."
_ANSWER_FAILED = "Не удалось сохранить ответ. Попробуйте ещё раз."


def question_markup(item_id: int) -> InlineKeyboardMarkup:
    """The kinds two in a row («Фильм» «Сериал» / «Аниме» «Игра»), then «🗑 Не сохранять»."""
    buttons = [
        InlineKeyboardButton(text=KINDS[kind].label, callback_data=f"{PREFIX}{item_id}:{_KIND}:{kind.value}")
        for kind in TitleKind
    ]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(text=FORGET_BUTTON, callback_data=f"{PREFIX}{item_id}:{_FORGET}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def read_press(data: str) -> tuple[int, TitleKind | None] | None:
    """(item id, the kind chosen — None for «Не сохранять») of a button; None for data the bot cannot read."""
    raw_id, _, rest = data.removeprefix(PREFIX).partition(":")
    if not (raw_id.isascii() and raw_id.isdigit()):
        return None
    if rest == _FORGET:
        return int(raw_id), None
    action, _, raw_kind = rest.partition(":")
    if action != _KIND:
        return None
    try:
        return int(raw_id), TitleKind(raw_kind)
    except ValueError:
        return None


@dataclass
class _Pause:
    task: asyncio.Task
    moved: bool  # waiting items went to «Входящие» when the item came: its first message says so
    answering: bool = False  # the pause is over and the bot is answering: a joined message no longer cancels it


def register_inbox_handlers(router: Router, tracker: Tracker, not_taken_in: Collection[str]) -> None:
    """Put the taking-in handler and the `inb:` presses on the owner router. Call it after every other message
    handler: the taking in takes whatever is left, except commands and the texts of `not_taken_in` (menu buttons)."""
    pauses: dict[int, _Pause] = {}  # item id -> its latest pause, until it has answered
    running: set[asyncio.Task] = set()  # every pause task until it ends, so none is collected half-way

    def is_taken_in(message: Message) -> bool:
        text = message.text
        return text is None or not (text.startswith("/") or text in not_taken_in)

    async def take_in(message: Message) -> None:
        try:
            result = await tracker.take_in(incoming(message))
        except Exception as exc:  # the database: tell the owner, keep the bot alive
            logging.warning("taking in a message failed: %r", exc)
            await message.answer(_NOT_TAKEN)
            return
        if result.joined:
            previous = pauses.get(result.item_id)
            moved = previous is not None and previous.moved
            if previous is not None and not previous.answering:
                previous.task.cancel()
        else:
            moved = result.moved > 0
            for pause in pauses.values():  # those items went to «Входящие» without their question
                if not pause.answering:
                    pause.task.cancel()
            pauses.clear()
        pause = _Pause(asyncio.create_task(after_pause(result.item_id, message, moved)), moved)
        pauses[result.item_id] = pause
        running.add(pause.task)
        pause.task.add_done_callback(running.discard)

    async def after_pause(item_id: int, message: Message, moved: bool) -> None:
        await asyncio.sleep(PAUSE_SECONDS)
        mine = pauses.get(item_id)
        if mine is not None and mine.task is not asyncio.current_task():
            mine = None
        if mine is not None:
            mine.answering = True
        try:
            outcome = await tracker.inbox_pause_over(item_id)
            if outcome == PauseOutcome.NOTHING:
                return
            first = f"{PREVIOUS_MOVED}\n\n" if moved else ""
            if outcome == PauseOutcome.NO_TEXT:
                await message.answer(first + NO_TEXT)
            else:
                await message.answer(first + QUESTION, reply_markup=question_markup(item_id))
        except Exception as exc:  # a task of its own: nobody above it would see the error
            logging.warning("answering an inbox item failed: %r", exc)
        finally:
            if mine is not None and pauses.get(item_id) is mine:
                del pauses[item_id]

    async def drop_buttons(callback: CallbackQuery) -> None:
        if callback.message is None:
            return
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception as exc:  # an old or missing message: the answer to the press matters more
            logging.debug("could not remove the buttons of an inbox item: %r", exc)

    async def tell(callback: CallbackQuery, text: str) -> None:
        """After the early answer the press has no popup left: the rest goes to the chat as a message."""
        if callback.message is None:
            logging.warning("no message to tell the owner: %s", text)
            return
        await callback.message.answer(text)

    async def press(callback: CallbackQuery) -> None:
        pressed = read_press(callback.data)
        if pressed is None:
            await callback.answer(DEAD_BUTTON)
            return
        item_id, kind = pressed
        if kind is None:
            forgotten = await tracker.forget_inbox_item(item_id)
            await drop_buttons(callback)
            await callback.answer(NOT_SAVING if forgotten else ALREADY_DONE)
            return
        if await tracker.inbox_item(item_id) is None:
            await callback.answer(ALREADY_DONE)
            return
        await callback.answer(SEARCHING)  # the analysis goes to the sources (ticket 04): answer before it
        await drop_buttons(callback)
        try:
            await tracker.answer_kind(item_id, kind)
        except UnknownInboxItem:  # removed in the web meanwhile
            await tell(callback, ALREADY_DONE)
            return
        except Exception as exc:
            logging.warning("answering the kind of an inbox item failed: %r", exc)
            await tell(callback, _ANSWER_FAILED)
            return
        await tell(callback, KIND_KEPT)

    router.message.register(take_in, is_taken_in)
    router.callback_query.register(press, F.data.startswith(PREFIX))
