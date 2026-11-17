"""Bot side of the list: «Мои тайтлы» (the titles as buttons) and «Удалить несколько» (the selection and its question).

`register_list_handlers` puts them on the owner router of `tracker_handlers`. The text «📚 Мои тайтлы» is taken only in
chat mode (in link mode the list is in the app and `tracker_handlers` answers the text with a link); the buttons
(`tcard:`, `tdm:`) work in both modes, so a message sent before keeps its buttons alive. The open selections live in
memory and are lost on restart (the old buttons then say so).
"""

import logging
import secrets
from collections.abc import Sequence

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.tracker.core import TitleSummary, Tracker, UnknownTitle
from app.tracker.kinds import KINDS

MY_TITLES_BUTTON = "📚 Мои тайтлы"
DELETE_BULK_BUTTON = "🗑 Удалить несколько"
MAX_LIST_BUTTONS = 50
EMPTY_LIST = "Список пуст. Перешлите мне пост о фильме, сериале, аниме или игре или напишите название."
CARD_PREFIX = "tcard:"  # tcard:<title id>: the card of a title of the list
_BULK_PREFIX = "tdm:"  # tdm:open starts a selection; tdm:<selection id>:t:<title id> | go | yes | no work on it
_BULK_OPEN, _BULK_TOGGLE, _BULK_GO, _BULK_YES, _BULK_NO = "open", "t", "go", "yes", "no"
_STALE_SELECTION = "Эта кнопка больше не работает, откройте список заново."


def title_button_text(name: str, year: int | None) -> str:
    return f"{name} ({year})" if year else name


def delete_question(names: Sequence[str]) -> str:
    quoted = ", ".join(f"«{name}»" for name in names)
    return f"Удалить {quoted} из списка? Сезоны, отметки и накопленные события тоже сотрутся. Вернуть нельзя."


def confirm_markup(yes: str, no: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Да, удалить", callback_data=yes)],
            [InlineKeyboardButton(text="Отмена", callback_data=no)],
        ]
    )


async def drop_buttons(callback: CallbackQuery) -> None:
    """A pressed button is spent: take the keyboard off its message (the list's buttons and those of `tracker_handlers`)."""
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception as exc:  # an old or missing message: the answer to the press matters more
        logging.debug("could not remove buttons: %s", repr(exc))


def _selection_markup(selection_id: str, titles: Sequence[TitleSummary], chosen: set[int]) -> InlineKeyboardMarkup:
    """The titles with a mark on the chosen ones, then the delete button (with the count) and the cancel button."""
    rows = [
        [
            InlineKeyboardButton(
                text=f"{'✅' if t.id in chosen else KINDS[t.kind].icon} {title_button_text(t.name, t.year)}",
                callback_data=f"{_BULK_PREFIX}{selection_id}:{_BULK_TOGGLE}:{t.id}",
            )
        ]
        for t in titles
    ]
    go = f"{_BULK_PREFIX}{selection_id}:{_BULK_GO}"
    rows.append([InlineKeyboardButton(text=f"Удалить выбранные ({len(chosen)})", callback_data=go)])
    rows.append([InlineKeyboardButton(text="Отмена", callback_data=f"{_BULK_PREFIX}{selection_id}:{_BULK_NO}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def register_list_handlers(router: Router, tracker: Tracker, *, chat_mode: bool) -> None:
    """«Мои тайтлы» (only in chat mode) and the buttons of the list and of the selection (always) on `router`."""
    selections: dict[int, tuple[str, set[int]]] = {}  # owner id -> (id of the open selection, chosen ids); lost on restart

    # --- «Мои тайтлы» ---------------------------------------------------------------------------

    async def show_my_titles(message: Message) -> None:
        titles = await tracker.list_titles()
        if not titles:
            await message.answer(EMPTY_LIST)
            return
        rows = [
            [
                InlineKeyboardButton(
                    text=f"{KINDS[t.kind].icon} {title_button_text(t.name, t.year)}",
                    callback_data=f"{CARD_PREFIX}{t.id}",
                )
            ]
            for t in titles[:MAX_LIST_BUTTONS]
        ]
        rows.append([InlineKeyboardButton(text=DELETE_BULK_BUTTON, callback_data=f"{_BULK_PREFIX}{_BULK_OPEN}")])
        header = "Ваши тайтлы. Нажмите на название, чтобы открыть карточку:"
        if len(titles) > MAX_LIST_BUTTONS:
            header += f"\nПоказаны первые {MAX_LIST_BUTTONS} из {len(titles)}."
        await message.answer(header, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

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
                delete_question(names),
                reply_markup=confirm_markup(
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

    if chat_mode:
        router.message.register(show_my_titles, F.text == MY_TITLES_BUTTON)
    router.callback_query.register(press_selection, F.data.startswith(_BULK_PREFIX))
