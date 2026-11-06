"""Bot side of «Входящие»: taking in every other message of the owner, the pause after it, «Что это?», the offer cards
and their buttons.

A message that no other handler took (not a command, not a menu button) is written as an inbox item at once
(`Tracker.take_in`), before anything is answered. Two seconds after the last message of an item (a message that joins
it — an album, a forward after its comment — starts the pause again) the core is asked what comes: the offers of its
links of sources, «Что это?», or that a message without text went to «Входящие». The pause lives in memory: after a
restart in the middle of it the item waits without the question until the next post or 12 hours (KI-57).

A kind press runs the analysis of the core; its answer is an offer card «Это оно?» with the poster above the text
(through `card_message`, as every card) and «✅ Да» / «❌ Нет», «Уже в списке» with the card of the title, or the
sentence that the item went to «Входящие». «Да» adds the title as the web does; «Нет» shows the next offer. Presses
follow rule 8: a dead button is a popup, a live one is answered at once («Ищу…», «Добавляю…»), the rest comes as
messages. The handlers live on the owner router of `tracker_handlers`, which shows the cards of the titles.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.card_message import send_card_message
from app.bot.inbox_message import incoming
from app.tracker.core import CARD_SIZE, InboxOutcome, InboxReply, Tracker, UnknownInboxItem, poster_url
from app.tracker.kinds import KINDS
from app.tracker.models import TitleKind

PAUSE_SECONDS = 2.0  # after the last message of an item, before the bot answers (spec 1.3 of stage 6.4)
PREFIX = "inb:"  # inb:<item>:k:<kind> the kind chosen; inb:<item>:x «Не сохранять»; inb:<item>:y|n:<offer> «Да» / «Нет»
_KIND, _FORGET, _YES, _NO = "k", "x", "y", "n"
QUESTION = "Что это?"
FORGET_BUTTON = "🗑 Не сохранять"
YES_BUTTON, NO_BUTTON = "✅ Да", "❌ Нет"
NO_TEXT = "В сообщении нет текста — сохранил во «Входящие»."
PREVIOUS_MOVED = "Предыдущий пост без ответа ушёл во «Входящие»."
SEARCHING = "Ищу…"
ADDING = "Добавляю…"
NOT_SAVING = "Не сохраняю."
ALREADY_DONE = "Эта запись уже разобрана."
DEAD_BUTTON = "Эта кнопка больше не работает."
ADDED = "✅ Добавлено в список"
IN_LIST = "Уже в списке"
NOT_FOUND = "Не нашёл — сохранил во «Входящие». Разберите в веб-приложении."
SOURCE_FAILED = "Не удалось связаться с {source} — сохранил во «Входящие»."
NOT_CONNECTED = "Игры не подключены: нет ключей IGDB в .env — сохранил во «Входящие»."
ADD_FAILED = "Не удалось получить данные из {source}. Нажмите «Да» ещё раз чуть позже."
ADD_NOT_CONNECTED = "Игры не подключены: нет ключей IGDB в .env."
_NOT_TAKEN = "Не удалось сохранить сообщение — пришлите его ещё раз."
_ANSWER_FAILED = "Не удалось обработать ответ. Попробуйте ещё раз."
_BUTTONS_STAY = (InboxOutcome.ADD_FAILED, InboxOutcome.ADD_NOT_CONNECTED, InboxOutcome.DEAD)  # «Да» can be pressed again


@dataclass(frozen=True)
class TitleCards:
    """How the tracker handlers show a title of the list: its card after a heading, and the question about the watched
    seasons of a series or an anime (False: nothing to ask)."""

    show: Callable[[Message, int, str], Awaitable[None]]
    ask_seasons: Callable[[Message, int], Awaitable[bool]]


@dataclass(frozen=True)
class Press:
    """A button of an inbox item as the bot reads it."""

    item_id: int
    action: str  # `_KIND`, `_FORGET`, `_YES`, `_NO`
    kind: TitleKind | None = None
    number: int | None = None  # of the offer


def question_markup(item_id: int) -> InlineKeyboardMarkup:
    """The kinds two in a row («Фильм» «Сериал» / «Аниме» «Игра»), then «🗑 Не сохранять»."""
    buttons = [
        InlineKeyboardButton(text=KINDS[kind].label, callback_data=f"{PREFIX}{item_id}:{_KIND}:{kind.value}")
        for kind in TitleKind
    ]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(text=FORGET_BUTTON, callback_data=f"{PREFIX}{item_id}:{_FORGET}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def offer_markup(item_id: int, number: int) -> InlineKeyboardMarkup:
    """«✅ Да» and «❌ Нет» of offer `number` in one row."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=YES_BUTTON, callback_data=f"{PREFIX}{item_id}:{_YES}:{number}"),
        InlineKeyboardButton(text=NO_BUTTON, callback_data=f"{PREFIX}{item_id}:{_NO}:{number}"),
    ]])


def _number(raw: str) -> int | None:
    return int(raw) if raw.isascii() and raw.isdigit() else None


def read_press(data: str) -> Press | None:
    """The button pressed; None for data the bot cannot read."""
    raw_id, _, rest = data.removeprefix(PREFIX).partition(":")
    item_id = _number(raw_id)
    if item_id is None:
        return None
    if rest == _FORGET:
        return Press(item_id, _FORGET)
    action, _, value = rest.partition(":")
    if action == _KIND:
        try:
            return Press(item_id, _KIND, kind=TitleKind(value))
        except ValueError:
            return None
    number = _number(value)
    if action in (_YES, _NO) and number is not None:
        return Press(item_id, action, number=number)
    return None


@dataclass
class _Pause:
    task: asyncio.Task
    moved: bool  # waiting items went to «Входящие» when the item came: its first message says so
    answering: bool = False  # the pause is over and the bot is answering: a joined message no longer cancels it


def register_inbox_handlers(
    router: Router, tracker: Tracker, not_taken_in: Collection[str], titles: TitleCards
) -> None:
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
            reply = await tracker.inbox_pause_over(item_id)
            await say(message, item_id, reply, f"{PREVIOUS_MOVED}\n\n" if moved else "")
        except Exception as exc:  # a task of its own: nobody above it would see the error
            logging.warning("answering an inbox item failed: %r", exc)
        finally:
            if mine is not None and pauses.get(item_id) is mine:
                del pauses[item_id]

    async def say(message: Message, item_id: int, reply: InboxReply, first: str = "") -> None:
        """What the core answered, as messages; `first` starts the first of them (the line «Предыдущий…»)."""
        outcome = reply.outcome
        source = KINDS[reply.kind].source_name if reply.kind is not None else ""
        if outcome == InboxOutcome.NOTHING:
            return
        if outcome == InboxOutcome.ASK:
            await message.answer(first + QUESTION, reply_markup=question_markup(item_id))
        elif outcome == InboxOutcome.OFFER:
            card = reply.offer
            markup = offer_markup(card.item_id, card.number)
            await send_card_message(message, first + card.text, poster_url(card.poster, CARD_SIZE), markup)
        elif outcome in (InboxOutcome.IN_LIST, InboxOutcome.ADDED):
            heading = ADDED if outcome == InboxOutcome.ADDED else IN_LIST
            await titles.show(message, reply.title_id, first + heading)
            if outcome == InboxOutcome.ADDED:
                await titles.ask_seasons(message, reply.title_id)
        else:
            texts = {
                InboxOutcome.NO_TEXT: NO_TEXT,
                InboxOutcome.NOT_FOUND: NOT_FOUND,
                InboxOutcome.SOURCE_FAILED: SOURCE_FAILED.format(source=source),
                InboxOutcome.NOT_CONNECTED: NOT_CONNECTED,
                InboxOutcome.ADD_FAILED: ADD_FAILED.format(source=source),
                InboxOutcome.ADD_NOT_CONNECTED: ADD_NOT_CONNECTED,
                InboxOutcome.DEAD: DEAD_BUTTON,
            }
            await message.answer(first + texts[outcome])

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
        if pressed.action == _FORGET:
            forgotten = await tracker.forget_inbox_item(pressed.item_id)
            await drop_buttons(callback)
            await callback.answer(NOT_SAVING if forgotten else ALREADY_DONE)
            return
        item = await tracker.inbox_item(pressed.item_id)
        if item is None:
            await callback.answer(ALREADY_DONE)
            return
        if pressed.number is not None and pressed.number >= item.offer_count:
            await callback.answer(DEAD_BUTTON)
            return
        # the analysis and «Да» go to the sources: answer before them (rule 8); «Нет» answers without a popup
        await callback.answer({_KIND: SEARCHING, _YES: ADDING}.get(pressed.action))
        if pressed.action != _YES:
            await drop_buttons(callback)
        try:
            if pressed.action == _KIND:
                reply = await tracker.answer_kind(pressed.item_id, pressed.kind)
            else:
                reply = await tracker.answer_offer(pressed.item_id, pressed.number, pressed.action == _YES)
        except UnknownInboxItem:  # removed on the web meanwhile
            await tell(callback, ALREADY_DONE)
            return
        except Exception as exc:
            logging.warning("answering an inbox item failed: %r", exc)
            await tell(callback, _ANSWER_FAILED)
            return
        if pressed.action == _YES and reply.outcome not in _BUTTONS_STAY:
            await drop_buttons(callback)
        if callback.message is None:
            logging.warning("no message to answer an inbox item in: %s", reply.outcome)
            return
        await say(callback.message, pressed.item_id, reply)

    router.message.register(take_in, is_taken_in)
    router.callback_query.register(press, F.data.startswith(PREFIX))
