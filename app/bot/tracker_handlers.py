"""Bot side of the tracker core: the menu («Добавить», «Мои тайтлы», «Сводка сейчас», «Тестовое событие»; the
delivery-rules check is the last item of the test-event list), the buttons under messages and cards
(«Посмотрел», «Следить», «Карточка», «Удалить») and the Telegram sender.

Handlers talk to the core only through the `Tracker` facade. They live on one router with the owner filter on it;
a handler never checks the owner itself. «Добавить» is a temporary way to fill the
list until the web app (it goes away when the web app arrives).
"""

import logging
import secrets
from collections.abc import Sequence
from datetime import timezone

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from app.tracker import delivery
from app.tracker.actions import CARD, DELETE, FOLLOW, SEASONS, WATCHED, Action, card_actions
from app.tracker.cards import TitleCard, format_card, format_when
from app.tracker.core import (
    TitleNotFound,
    TitleSummary,
    Tracker,
    UnknownEvent,
    UnknownKind,
    UnknownSeason,
    UnknownTitle,
    WatchableSeason,
)
from app.tracker.kinds import KINDS
from app.tracker.models import TitleKind
from app.tracker.series_events import SAMPLE_EPISODES_ID

TEST_EVENT_BUTTON = "🧪 Тестовое событие"
ADD_BUTTON = "➕ Добавить"
MY_TITLES_BUTTON = "📚 Мои тайтлы"
SUMMARY_BUTTON = "📋 Сводка сейчас"
RULES_CHECK_BUTTON = "🕒 Проверить правила доставки"  # the last item of the test-event list
RULES_CHECK_CALLBACK = "tchk:open"
_SAMPLE_PREFIX = "tev:"
_CHECK_PREFIX = "twin:"  # twin:<delivery check id>: a test event as if it were queued at that moment of the week (sent buttons keep it)
_ADD_KIND_PREFIX = "tadd:"
_PICK_PREFIX = "tpick:"
_CARD_PREFIX = "tcard:"
_ACTION_PREFIX = "tact:"  # tact:<action name>:<number>, see app.tracker.actions
_SEASON_PREFIX = "tsea:"  # tsea:<title id>:<season number> flips a mark, tsea:<title id>:done closes the choice
_DONE = "done"
_DELETE_PREFIX = "tdel:"  # tdel:y:<title id> deletes after the question, tdel:n:<title id> drops it
_BULK_PREFIX = "tdm:"  # tdm:open starts a selection; tdm:<selection id>:t:<title id> | go | yes | no work on it
_YES, _NO = "y", "n"
_BULK_OPEN, _BULK_TOGGLE, _BULK_GO, _BULK_YES, _BULK_NO = "open", "t", "go", "yes", "no"

MAX_SUGGESTIONS = 10
MAX_LIST_BUTTONS = 50
_NO_SUCH_KIND = f"Такого типа больше нет, нажмите «{ADD_BUTTON}» заново."
SUMMARY_COMMAND = "summary"
BOT_COMMANDS = [BotCommand(command=SUMMARY_COMMAND, description="Сводка сейчас")]  # shown in Telegram's «/» menu
START_TEXT = (
    "👋 Бот работает. Кнопки меню внизу: «Добавить» и «Мои тайтлы» ведут список, «Сводка сейчас» присылает "
    "накопленные события, «Тестовое событие» показывает, как выглядят сообщения, и проверяет правила доставки."
)
DELETE_BULK_BUTTON = "🗑 Удалить несколько"
_NOT_IN_LIST = "Этого тайтла больше нет в списке."
_DEAD_BUTTON = "Эта кнопка больше не работает."
_STALE_SELECTION = "Эта кнопка больше не работает, откройте список заново."
_ASK_SEASONS = (
    "Какие сезоны вы уже посмотрели? Нажмите на сезон, чтобы отметить его; "
    "повторное нажатие снимает отметку. Когда закончите, нажмите «Готово»."
)


def actions_markup(actions: Sequence[Action]) -> InlineKeyboardMarkup | None:
    """One button per row under a message; None when there is nothing to press."""
    if not actions:
        return None
    rows = [
        [InlineKeyboardButton(text=a.label, callback_data=f"{_ACTION_PREFIX}{a.name}:{a.arg}")] for a in actions
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


class TelegramSender:
    """Delivers tracker messages to the owner's chat."""

    def __init__(self, bot: Bot, chat_id: int) -> None:
        self._bot = bot
        self._chat_id = chat_id

    async def send(self, message: str, actions: Sequence[Action] = ()) -> None:
        await self._bot.send_message(chat_id=self._chat_id, text=message, reply_markup=actions_markup(actions))


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=ADD_BUTTON), KeyboardButton(text=MY_TITLES_BUTTON)],
            [KeyboardButton(text=SUMMARY_BUTTON)],
            [KeyboardButton(text=TEST_EVENT_BUTTON)],
        ],
        resize_keyboard=True,
    )


def seasons_markup(title_id: int, seasons: Sequence[WatchableSeason]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{'✅ ' if s.watched else ''}Сезон {s.number}",
                callback_data=f"{_SEASON_PREFIX}{title_id}:{s.number}",
            )
        ]
        for s in seasons
    ]
    rows.append([InlineKeyboardButton(text="Готово", callback_data=f"{_SEASON_PREFIX}{title_id}:{_DONE}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _title_button_text(name: str, year: int | None) -> str:
    return f"{name} ({year})" if year else name


def _delete_question(names: Sequence[str]) -> str:
    quoted = ", ".join(f"«{name}»" for name in names)
    return f"Удалить {quoted} из списка? Сезоны, отметки и накопленные события тоже сотрутся. Вернуть нельзя."


def _kind_of(raw: str) -> TitleKind | None:
    """The kind a button names; None for text that is no kind (a button of an older version of the bot)."""
    try:
        return TitleKind(raw)
    except ValueError:
        return None


def _confirm_markup(yes: str, no: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Да, удалить", callback_data=yes)],
            [InlineKeyboardButton(text="Отмена", callback_data=no)],
        ]
    )


def _selection_markup(selection_id: str, titles: Sequence[TitleSummary], chosen: set[int]) -> InlineKeyboardMarkup:
    """The titles with a mark on the chosen ones, then the delete button (with the count) and the cancel button."""
    rows = [
        [
            InlineKeyboardButton(
                text=f"{'✅' if t.id in chosen else KINDS[t.kind].icon} {_title_button_text(t.name, t.year)}",
                callback_data=f"{_BULK_PREFIX}{selection_id}:{_BULK_TOGGLE}:{t.id}",
            )
        ]
        for t in titles
    ]
    go = f"{_BULK_PREFIX}{selection_id}:{_BULK_GO}"
    rows.append([InlineKeyboardButton(text=f"Удалить выбранные ({len(chosen)})", callback_data=go)])
    rows.append([InlineKeyboardButton(text="Отмена", callback_data=f"{_BULK_PREFIX}{selection_id}:{_BULK_NO}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def register_tracker_handlers(dp: Dispatcher, tracker: Tracker, allowed_user_ids: list[int]) -> Router:
    """Put every tracker handler on one router behind the owner filter and include it in `dp`.

    The filter is the second line of defence behind `AccessMiddleware`: an update from anyone else, or from nobody
    (no sender), matches no handler. A new handler goes on this router and never checks the owner itself.
    """
    router = Router(name="tracker")
    owner = F.from_user.id.in_(frozenset(allowed_user_ids))
    router.message.filter(owner)
    router.callback_query.filter(owner)
    awaiting_name: dict[int, TitleKind] = {}  # owner id -> kind whose name the next text message is
    selections: dict[int, tuple[str, set[int]]] = {}  # owner id -> (id of the open selection, chosen ids); lost on restart

    def forget_pending(user) -> None:
        awaiting_name.pop(getattr(user, "id", None), None)

    async def start(message: Message) -> None:
        forget_pending(message.from_user)
        await message.answer(START_TEXT, reply_markup=main_keyboard())

    async def show_menu(message: Message) -> None:
        forget_pending(message.from_user)
        rows = [
            [InlineKeyboardButton(text=sample.label, callback_data=f"{_SAMPLE_PREFIX}{sample.id}")]
            for sample in tracker.test_samples()
        ]
        rows.append([InlineKeyboardButton(text=RULES_CHECK_BUTTON, callback_data=RULES_CHECK_CALLBACK)])
        await message.answer(
            "Какое тестовое событие отправить?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )

    async def send_test_event(callback: CallbackQuery) -> None:
        sample_id = callback.data.removeprefix(_SAMPLE_PREFIX)
        try:
            result = await tracker.send_test_event(sample_id)
        except KeyError:
            await callback.answer("Такого события больше нет, откройте меню заново.")
            return
        if result.delivered:
            await callback.answer("Отправлено")
        else:
            await callback.answer("Не удалось отправить, событие осталось в очереди и придёт позже.")

    # --- «Сводка сейчас» и проверка правил доставки ---------------------------------------------

    async def send_summary_now(message: Message) -> None:
        forget_pending(message.from_user)
        try:
            result = await tracker.summary_now()
        except Exception as exc:  # the queue is read from the database: tell the owner, keep the bot alive
            logging.warning("summary now failed: %s", repr(exc))
            await message.answer("Не удалось собрать сводку. Попробуйте ещё раз.")
            return
        if result.events == 0:
            await message.answer("Накопленных событий нет — присылать нечего.")
        elif not result.delivered:
            await message.answer("Не удалось отправить сводку. События остались в очереди и придут позже.")

    async def show_rules_check(callback: CallbackQuery) -> None:
        rows = [
            [InlineKeyboardButton(text=c.label, callback_data=f"{_CHECK_PREFIX}{c.id}")]
            for c in delivery.DELIVERY_CHECKS
        ]
        await callback.answer()
        if callback.message is None:
            return
        await callback.message.answer(
            "Какой момент недели подставить? Я отправлю тестовое событие «Сериал: две серии подряд» "
            "так, как будто оно появилось именно тогда, и покажу, что с ним сделают правила доставки.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )

    async def run_rules_check(callback: CallbackQuery) -> None:
        check = delivery.delivery_check_by_id(callback.data.removeprefix(_CHECK_PREFIX))
        if check is None:
            await callback.answer("Такого момента больше нет, откройте меню заново.")
            return
        try:
            moment = await tracker.delivery_check_moment(check)
            tz = (await tracker.delivery_rules()).tz
            result = await tracker.send_test_event(SAMPLE_EPISODES_ID, at=moment)
        except Exception as exc:
            logging.warning("delivery rules check failed: %s", repr(exc))
            await callback.answer("Не удалось выполнить проверку. Попробуйте ещё раз.")
            return
        await callback.answer()

        def when(value) -> str:
            return format_when(value.astimezone(timezone.utc).replace(tzinfo=None), tz)

        if result.delivered_at_once:
            text = f"Как будто сейчас {when(moment)}: сообщения пришли сразу, правила их не задерживают."
        elif result.delivered and result.held_until is not None:
            text = (
                f"Как будто сейчас {when(moment)}: в этот момент ничего не пришло, события копились. "
                f"Выше — сводка, которая уйдёт {when(result.held_until)}."
            )
        else:
            text = "Не удалось отправить, события остались в очереди и придут позже."
        if callback.message is not None:
            await callback.message.answer(text)

    # --- «Добавить» -----------------------------------------------------------------------------

    async def show_add_menu(message: Message) -> None:
        forget_pending(message.from_user)
        rows = [
            [InlineKeyboardButton(text=KINDS[kind].label, callback_data=f"{_ADD_KIND_PREFIX}{kind.value}")]
            for kind in tracker.sources
        ]
        await message.answer("Что добавить?", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

    async def ask_name(callback: CallbackQuery) -> None:
        kind = _kind_of(callback.data.removeprefix(_ADD_KIND_PREFIX))
        if kind is None or kind not in tracker.sources:
            await callback.answer(_NO_SUCH_KIND)
            return
        awaiting_name[callback.from_user.id] = kind
        await callback.answer()
        if callback.message is not None:
            await callback.message.answer(KINDS[kind].ask_name)

    def is_name_for_search(message: Message) -> bool:
        text = message.text or ""
        return bool(text) and not text.startswith("/") and getattr(message.from_user, "id", None) in awaiting_name

    async def search_by_name(message: Message) -> None:
        kind = awaiting_name.pop(message.from_user.id)  # one press of «Добавить» = one search
        query = (message.text or "").strip()
        try:
            suggestions = await tracker.search(kind, query)
        except Exception as exc:  # the source is a network client: tell the owner, keep the bot alive
            logging.warning("title search failed: %s", repr(exc))
            await message.answer(f"Не удалось связаться с {KINDS[kind].source_name}. Попробуйте чуть позже.")
            return
        if not suggestions:
            await message.answer(
                f"Ничего не нашлось по запросу «{query}». Нажмите «{ADD_BUTTON}» и попробуйте другое название."
            )
            return
        rows = [
            [
                InlineKeyboardButton(
                    text=_title_button_text(s.name, s.year), callback_data=f"{_PICK_PREFIX}{kind.value}:{s.external_id}"
                )
            ]
            for s in suggestions[:MAX_SUGGESTIONS]
        ]
        await message.answer(
            f"Нашлось по запросу «{query}». Выберите:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
        )

    async def add_picked(callback: CallbackQuery) -> None:
        raw_kind, _, external_id = callback.data.removeprefix(_PICK_PREFIX).partition(":")
        kind = _kind_of(raw_kind)
        if kind is None:
            await callback.answer(_NO_SUCH_KIND)
            return
        try:
            result = await tracker.add_title(kind, external_id)
        except KeyError:
            await callback.answer(_NO_SUCH_KIND)
            return
        except TitleNotFound:
            await callback.answer(f"Не нашёл такой тайтл в {KINDS[kind].source_name}, попробуйте поискать заново.")
            return
        except Exception as exc:
            logging.warning("adding a title failed: %s", repr(exc))
            await callback.answer(f"Не удалось получить данные из {KINDS[kind].source_name}. Попробуйте чуть позже.")
            return
        await callback.answer()
        heading = "✅ Добавлено в список" if result.created else "Уже в списке"
        await send_card(callback, await tracker.title_card(result.title_id), heading)
        if result.created:
            await ask_watched_seasons(callback, result.title_id)

    async def ask_watched_seasons(callback: CallbackQuery, title_id: int) -> bool:
        """Offer the seasons with released episodes for marking. False: a movie or nothing is out yet."""
        seasons = await tracker.watchable_seasons(title_id)
        if not seasons or callback.message is None:
            return False
        await callback.message.answer(_ASK_SEASONS, reply_markup=seasons_markup(title_id, seasons))
        return True

    async def send_card(callback: CallbackQuery, card: TitleCard | None, heading: str | None = None) -> None:
        if card is None or callback.message is None:
            return
        text = format_card(card) if heading is None else f"{heading}\n\n{format_card(card)}"
        await callback.message.answer(text, reply_markup=actions_markup(card_actions(card)))

    # --- «Мои тайтлы» ---------------------------------------------------------------------------

    async def show_my_titles(message: Message) -> None:
        forget_pending(message.from_user)
        titles = await tracker.list_titles()
        if not titles:
            await message.answer(f"Список пуст. Нажмите «{ADD_BUTTON}», чтобы добавить первый фильм.")
            return
        rows = [
            [
                InlineKeyboardButton(
                    text=f"{KINDS[t.kind].icon} {_title_button_text(t.name, t.year)}",
                    callback_data=f"{_CARD_PREFIX}{t.id}",
                )
            ]
            for t in titles[:MAX_LIST_BUTTONS]
        ]
        rows.append([InlineKeyboardButton(text=DELETE_BULK_BUTTON, callback_data=f"{_BULK_PREFIX}{_BULK_OPEN}")])
        header = "Ваши тайтлы. Нажмите на название, чтобы открыть карточку:"
        if len(titles) > MAX_LIST_BUTTONS:
            header += f"\nПоказаны первые {MAX_LIST_BUTTONS} из {len(titles)}."
        await message.answer(header, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

    async def show_card_of(callback: CallbackQuery, title_id: int) -> None:
        card = await tracker.title_card(title_id)
        if card is None:
            await callback.answer(_NOT_IN_LIST)
            return
        await callback.answer()
        await send_card(callback, card)

    async def show_card(callback: CallbackQuery) -> None:
        try:
            title_id = int(callback.data.removeprefix(_CARD_PREFIX))
        except ValueError:
            title_id = -1
        await show_card_of(callback, title_id)

    # --- buttons under messages and cards -------------------------------------------------------

    async def drop_buttons(callback: CallbackQuery) -> None:
        """A pressed button is spent: take the keyboard off its message."""
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception as exc:  # an old or missing message: the answer to the press matters more
            logging.debug("could not remove buttons: %s", repr(exc))

    async def mark_watched(callback: CallbackQuery, title_id: int) -> None:
        try:
            result = await tracker.mark_watched(title_id)
        except UnknownTitle:
            await callback.answer(_NOT_IN_LIST)
            return
        except Exception as exc:
            logging.warning("marking a title watched failed: %s", repr(exc))
            await callback.answer("Не удалось сохранить. Попробуйте ещё раз.")
            return
        await drop_buttons(callback)
        if not result.changed:
            await callback.answer("Уже отмечено как просмотренное.")
            return
        await callback.answer("Отмечено как просмотренное")
        card = await tracker.title_card(title_id)
        if callback.message is not None and card is not None:
            await callback.message.answer(
                f"✅ Просмотрено: {card.name}\nФильм в архиве. Раз в неделю я проверю, не анонсировано ли продолжение."
            )

    async def follow_sequel(callback: CallbackQuery, raw: str) -> None:
        """`raw` is "<kind>:<id>" on a button of the current kind, or the number of the announcement on an old one."""
        kind, _, sequel_id = raw.partition(":")
        try:
            if raw.isascii() and raw.isdigit():
                result = await tracker.follow_sequel(int(raw))
            elif kind and sequel_id:
                result = await tracker.follow_sequel_of(kind, sequel_id)
            else:
                raise UnknownKind(raw)
        except UnknownEvent:
            await callback.answer("Это объявление больше недоступно.")
            return
        except UnknownKind:
            await callback.answer(_DEAD_BUTTON)
            return
        except TitleNotFound:
            await callback.answer("Не нашёл это продолжение в TMDb. Попробуйте чуть позже.")
            return
        except Exception as exc:
            logging.warning("following a sequel failed: %s", repr(exc))
            await callback.answer("Не удалось получить данные из TMDb. Попробуйте чуть позже.")
            return
        await drop_buttons(callback)
        await callback.answer()
        heading = "✅ Продолжение добавлено в список" if result.created else "Уже в списке"
        await send_card(callback, await tracker.title_card(result.title_id), heading)

    async def open_seasons_choice(callback: CallbackQuery, title_id: int) -> None:
        if await tracker.title_card(title_id) is None:
            await callback.answer(_NOT_IN_LIST)
            return
        if not await ask_watched_seasons(callback, title_id):
            await callback.answer("Пока нет вышедших сезонов, отмечать нечего.")
            return
        await callback.answer()

    async def flip_season(callback: CallbackQuery) -> None:
        raw_id, _, raw_number = callback.data.removeprefix(_SEASON_PREFIX).partition(":")
        if not (raw_id.isascii() and raw_id.isdigit()):
            await callback.answer("Эта кнопка больше не работает.")
            return
        title_id = int(raw_id)
        if await tracker.title_card(title_id) is None:
            await callback.answer(_NOT_IN_LIST)
            return
        if raw_number == _DONE:
            await drop_buttons(callback)
            await callback.answer("Готово")
            await send_card(callback, await tracker.title_card(title_id))
            return
        if not (raw_number.isascii() and raw_number.isdigit()):
            await callback.answer("Эта кнопка больше не работает.")
            return
        number = int(raw_number)
        marks = {s.number: s.watched for s in await tracker.watchable_seasons(title_id)}
        try:
            if number not in marks:
                raise UnknownSeason(f"{title_id}:{number}")
            await tracker.set_season_watched(title_id, number, not marks[number])
        except UnknownTitle:
            await callback.answer(_NOT_IN_LIST)
            return
        except UnknownSeason:
            await callback.answer("Такого сезона нет или он ещё не вышел.")
            return
        except Exception as exc:
            logging.warning("marking a season failed: %s", repr(exc))
            await callback.answer("Не удалось сохранить. Попробуйте ещё раз.")
            return
        await callback.answer()
        try:
            await callback.message.edit_reply_markup(
                reply_markup=seasons_markup(title_id, await tracker.watchable_seasons(title_id))
            )
        except Exception as exc:  # the marks are saved; a stale message only keeps its old look
            logging.debug("could not refresh the season buttons: %s", repr(exc))

    # --- «Удалить» ------------------------------------------------------------------------------

    async def ask_delete(callback: CallbackQuery, title_id: int) -> None:
        card = await tracker.title_card(title_id)
        if card is None:
            await callback.answer(_NOT_IN_LIST)
            return
        await callback.answer()
        if callback.message is not None:
            await callback.message.answer(
                _delete_question([card.name]),
                reply_markup=_confirm_markup(f"{_DELETE_PREFIX}{_YES}:{title_id}", f"{_DELETE_PREFIX}{_NO}:{title_id}"),
            )

    async def answer_delete(callback: CallbackQuery) -> None:
        answer, _, raw_id = callback.data.removeprefix(_DELETE_PREFIX).partition(":")
        if answer not in (_YES, _NO) or not (raw_id.isascii() and raw_id.isdigit()):
            await callback.answer("Эта кнопка больше не работает.")
            return
        if answer == _NO:
            await drop_buttons(callback)
            await callback.answer("Отменено, тайтл остался в списке.")
            return
        try:
            result = await tracker.delete_title(int(raw_id))
        except UnknownTitle:
            await drop_buttons(callback)
            await callback.answer(_NOT_IN_LIST)
            return
        except Exception as exc:  # the question stays, so the press can be repeated
            logging.warning("deleting a title failed: %s", repr(exc))
            await callback.answer("Не удалось удалить. Попробуйте ещё раз.")
            return
        await drop_buttons(callback)
        await callback.answer()
        if callback.message is not None:
            await callback.message.answer(f"🗑 Удалено: {result.name}")

    # --- «Удалить несколько» --------------------------------------------------------------------

    async def open_selection(callback: CallbackQuery) -> None:
        titles = (await tracker.list_titles())[:MAX_LIST_BUTTONS]
        if not titles:
            await callback.answer("Список пуст, удалять нечего.")
            return
        selection_id = secrets.token_hex(3)  # told apart from the selections of earlier runs and of earlier presses
        selections[callback.from_user.id] = (selection_id, set())
        await callback.answer()
        if callback.message is not None:
            await callback.message.answer(
                "Отметьте тайтлы, которые нужно удалить. Повторное нажатие снимает отметку.",
                reply_markup=_selection_markup(selection_id, titles, set()),
            )

    async def press_selection(callback: CallbackQuery) -> None:
        rest = callback.data.removeprefix(_BULK_PREFIX)
        if rest == _BULK_OPEN:
            await open_selection(callback)
            return
        selection_id, _, action = rest.partition(":")
        current = selections.get(callback.from_user.id)
        if current is None or current[0] != selection_id:  # after a restart, or after a newer selection was opened
            await callback.answer(_STALE_SELECTION)
            return
        chosen = current[1]
        verb, _, raw = action.partition(":")
        if verb == _BULK_TOGGLE and raw.isascii() and raw.isdigit():
            chosen.symmetric_difference_update({int(raw)})
            await callback.answer()
            if callback.message is None:
                return
            try:
                await callback.message.edit_reply_markup(
                    reply_markup=_selection_markup(selection_id, (await tracker.list_titles())[:MAX_LIST_BUTTONS], chosen)
                )
            except Exception as exc:  # the marks are kept; a stale message only keeps its old look
                logging.debug("could not refresh the selection buttons: %s", repr(exc))
        elif verb == _BULK_GO:
            await ask_delete_selected(callback, selection_id, chosen)
        elif verb == _BULK_YES:
            await delete_selected(callback, chosen)
        elif verb == _BULK_NO:
            selections.pop(callback.from_user.id, None)
            await drop_buttons(callback)
            await callback.answer("Отменено, ничего не удалено.")
        else:
            await callback.answer("Эта кнопка больше не работает.")

    async def ask_delete_selected(callback: CallbackQuery, selection_id: str, chosen: set[int]) -> None:
        names = [t.name for t in await tracker.list_titles() if t.id in chosen]
        if not names:
            await callback.answer("Ничего не выбрано, удалять нечего.")
            return
        # the question is about exactly these titles: the selection moves under a new id, so the old buttons go stale
        # and a title marked after the question cannot be deleted by the answer to it
        asked_id = secrets.token_hex(3)
        selections[callback.from_user.id] = (asked_id, set(chosen))
        await callback.answer()
        if callback.message is not None:
            await callback.message.answer(
                _delete_question(names),
                reply_markup=_confirm_markup(
                    f"{_BULK_PREFIX}{asked_id}:{_BULK_YES}", f"{_BULK_PREFIX}{asked_id}:{_BULK_NO}"
                ),
            )

    async def delete_selected(callback: CallbackQuery, chosen: set[int]) -> None:
        selections.pop(callback.from_user.id, None)  # one question, one answer
        await drop_buttons(callback)
        names = {t.id: t.name for t in await tracker.list_titles()}
        removed: list[str] = []
        failed: list[str] = []
        for title_id in sorted(chosen):
            try:
                removed.append((await tracker.delete_title(title_id)).name)
            except UnknownTitle:
                continue  # already removed from its own card
            except Exception as exc:
                logging.warning("deleting a title failed: %s", repr(exc))
                failed.append(names.get(title_id, str(title_id)))
        await callback.answer()
        if callback.message is None:
            return
        lines = [f"🗑 Удалено: {', '.join(removed)}"] if removed else []
        if failed:
            lines.append(f"Не удалось удалить: {', '.join(failed)}. Откройте список и попробуйте ещё раз.")
        await callback.message.answer("\n".join(lines) if lines else "Этих тайтлов уже нет в списке.")

    async def press_action(callback: CallbackQuery) -> None:
        name, _, raw = callback.data.removeprefix(_ACTION_PREFIX).partition(":")
        number = int(raw) if raw.isascii() and raw.isdigit() else None
        if name == FOLLOW:
            await follow_sequel(callback, raw)
        elif number is not None and name == WATCHED:
            await mark_watched(callback, number)
        elif number is not None and name == SEASONS:
            await open_seasons_choice(callback, number)
        elif number is not None and name == CARD:
            await show_card_of(callback, number)
        elif number is not None and name == DELETE:
            await ask_delete(callback, number)
        else:
            await callback.answer(_DEAD_BUTTON)

    router.message.register(start, CommandStart())
    router.message.register(show_menu, F.text == TEST_EVENT_BUTTON)
    router.callback_query.register(send_test_event, F.data.startswith(_SAMPLE_PREFIX))

    router.message.register(send_summary_now, Command(SUMMARY_COMMAND))
    router.message.register(send_summary_now, F.text == SUMMARY_BUTTON)
    router.callback_query.register(show_rules_check, F.data == RULES_CHECK_CALLBACK)
    router.callback_query.register(run_rules_check, F.data.startswith(_CHECK_PREFIX))

    router.message.register(show_add_menu, F.text == ADD_BUTTON)
    router.message.register(show_my_titles, F.text == MY_TITLES_BUTTON)
    router.message.register(search_by_name, is_name_for_search)  # after the menu buttons: a button is never a title name
    router.callback_query.register(ask_name, F.data.startswith(_ADD_KIND_PREFIX))
    router.callback_query.register(add_picked, F.data.startswith(_PICK_PREFIX))
    router.callback_query.register(show_card, F.data.startswith(_CARD_PREFIX))
    router.callback_query.register(press_action, F.data.startswith(_ACTION_PREFIX))
    router.callback_query.register(answer_delete, F.data.startswith(_DELETE_PREFIX))
    router.callback_query.register(press_selection, F.data.startswith(_BULK_PREFIX))
    router.callback_query.register(flip_season, F.data.startswith(_SEASON_PREFIX))

    dp.include_router(router)
    return router
