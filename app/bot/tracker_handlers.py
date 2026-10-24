"""Bot side of the tracker core: «Тестовое событие», «Добавить», «Мои тайтлы», the buttons under messages
(«Посмотрел», «Следить») and the Telegram sender.

Handlers talk to the core only through the `Tracker` facade. «Добавить» is a temporary way to fill the
list until the web app (it is removed together with the other old bot flows).
"""

import logging
from collections.abc import Sequence

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from app.tracker.actions import FOLLOW, SEASONS, WATCHED, Action, card_actions
from app.tracker.cards import KIND_ICONS, KIND_LABELS, TitleCard, format_card
from app.tracker.core import Tracker, TitleNotFound, UnknownEvent, UnknownSeason, UnknownTitle, WatchableSeason
from app.utils.secrets_mask import mask_secrets

TEST_EVENT_BUTTON = "🧪 Тестовое событие"
ADD_BUTTON = "➕ Добавить"
MY_TITLES_BUTTON = "📚 Мои тайтлы"
_KIND_PREFIX = "tev:"
_ADD_KIND_PREFIX = "tadd:"
_PICK_PREFIX = "tpick:"
_CARD_PREFIX = "tcard:"
_ACTION_PREFIX = "tact:"  # tact:<action name>:<number>, see app.tracker.actions
_SEASON_PREFIX = "tsea:"  # tsea:<title id>:<season number> flips a mark, tsea:<title id>:done closes the choice
_DONE = "done"

MAX_SUGGESTIONS = 10
MAX_LIST_BUTTONS = 50
_ASK_NAME = {
    "movie": "Напишите название фильма (можно по-русски или по-английски).",
    "series": "Напишите название сериала (можно по-русски или по-английски).",
}
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


def owner_chat_id(configured: str, allowed_user_ids: list[int]) -> int:
    """OWNER_CHAT_ID if it is a number, otherwise the first allowed user (a private chat id equals the user id)."""
    try:
        return int(configured)
    except ValueError:
        if configured:
            logging.warning("OWNER_CHAT_ID is not a number; sending tracker messages to the first allowed user")
        return allowed_user_ids[0]


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=ADD_BUTTON), KeyboardButton(text=MY_TITLES_BUTTON)],
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


def register_tracker_handlers(dp: Dispatcher, tracker: Tracker, allowed_user_ids: list[int]) -> None:
    """Register on `dp` itself (not a sub-router) so these win over the catch-all text handler."""
    allowed = frozenset(allowed_user_ids)
    awaiting_name: dict[int, str] = {}  # owner id -> kind whose name the next text message is

    def is_owner(user) -> bool:  # second line of defence behind AccessMiddleware
        return getattr(user, "id", None) in allowed

    def forget_pending(user) -> None:
        awaiting_name.pop(getattr(user, "id", None), None)

    async def show_menu(message: Message) -> None:
        if not is_owner(message.from_user):
            return
        forget_pending(message.from_user)
        rows = [
            [InlineKeyboardButton(text=kind.label, callback_data=f"{_KIND_PREFIX}{kind.id}")]
            for kind in tracker.test_event_kinds()
        ]
        await message.answer(
            "Какое тестовое событие отправить?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )

    async def send_test_event(callback: CallbackQuery) -> None:
        if not is_owner(callback.from_user):
            return
        kind_id = callback.data.removeprefix(_KIND_PREFIX)
        try:
            result = await tracker.send_test_event(kind_id)
        except KeyError:
            await callback.answer("Такого события больше нет, откройте меню заново.")
            return
        if result.delivered:
            await callback.answer("Отправлено")
        else:
            await callback.answer("Не удалось отправить, событие осталось в очереди и придёт позже.")

    # --- «Добавить» -----------------------------------------------------------------------------

    async def show_add_menu(message: Message) -> None:
        if not is_owner(message.from_user):
            return
        forget_pending(message.from_user)
        rows = [
            [InlineKeyboardButton(text=KIND_LABELS.get(kind, kind), callback_data=f"{_ADD_KIND_PREFIX}{kind}")]
            for kind in tracker.sources
        ]
        await message.answer("Что добавить?", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

    async def ask_name(callback: CallbackQuery) -> None:
        if not is_owner(callback.from_user):
            return
        kind = callback.data.removeprefix(_ADD_KIND_PREFIX)
        if kind not in tracker.sources:
            await callback.answer(f"Такого типа больше нет, нажмите «{ADD_BUTTON}» заново.")
            return
        awaiting_name[callback.from_user.id] = kind
        await callback.answer()
        if callback.message is not None:
            await callback.message.answer(_ASK_NAME.get(kind, "Напишите название."))

    def is_name_for_search(message: Message) -> bool:
        text = message.text or ""
        return bool(text) and not text.startswith("/") and getattr(message.from_user, "id", None) in awaiting_name

    async def search_by_name(message: Message) -> None:
        if not is_owner(message.from_user):
            return
        kind = awaiting_name.pop(message.from_user.id)  # one press of «Добавить» = one search
        query = (message.text or "").strip()
        try:
            suggestions = await tracker.search(kind, query)
        except Exception as exc:  # the source is a network client: tell the owner, keep the bot alive
            logging.warning("title search failed: %s", mask_secrets(repr(exc)))
            await message.answer("Не удалось связаться с TMDb. Попробуйте чуть позже.")
            return
        if not suggestions:
            await message.answer(
                f"Ничего не нашлось по запросу «{query}». Нажмите «{ADD_BUTTON}» и попробуйте другое название."
            )
            return
        rows = [
            [
                InlineKeyboardButton(
                    text=_title_button_text(s.title, s.year), callback_data=f"{_PICK_PREFIX}{kind}:{s.external_id}"
                )
            ]
            for s in suggestions[:MAX_SUGGESTIONS]
        ]
        await message.answer(
            f"Нашлось по запросу «{query}». Выберите:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
        )

    async def add_picked(callback: CallbackQuery) -> None:
        if not is_owner(callback.from_user):
            return
        kind, _, external_id = callback.data.removeprefix(_PICK_PREFIX).partition(":")
        try:
            result = await tracker.add_title(kind, external_id)
        except KeyError:
            await callback.answer(f"Такого типа больше нет, нажмите «{ADD_BUTTON}» заново.")
            return
        except TitleNotFound:
            await callback.answer("Не нашёл такой тайтл в TMDb, попробуйте поискать заново.")
            return
        except Exception as exc:
            logging.warning("adding a title failed: %s", mask_secrets(repr(exc)))
            await callback.answer("Не удалось получить данные из TMDb. Попробуйте чуть позже.")
            return
        await callback.answer()
        heading = "✅ Добавлено в список" if result.created else "Уже в списке"
        await send_card(callback, tracker.title_card(result.title_id), heading)
        if result.created:
            await ask_watched_seasons(callback, result.title_id)

    async def ask_watched_seasons(callback: CallbackQuery, title_id: int) -> bool:
        """Offer the seasons with released episodes for marking. False: a movie or nothing is out yet."""
        seasons = tracker.watchable_seasons(title_id)
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
        if not is_owner(message.from_user):
            return
        forget_pending(message.from_user)
        titles = tracker.list_titles()
        if not titles:
            await message.answer(f"Список пуст. Нажмите «{ADD_BUTTON}», чтобы добавить первый фильм.")
            return
        rows = [
            [
                InlineKeyboardButton(
                    text=f"{KIND_ICONS.get(t.kind, '🎞')} {_title_button_text(t.name, t.year)}",
                    callback_data=f"{_CARD_PREFIX}{t.id}",
                )
            ]
            for t in titles[:MAX_LIST_BUTTONS]
        ]
        header = "Ваши тайтлы. Нажмите на название, чтобы открыть карточку:"
        if len(titles) > MAX_LIST_BUTTONS:
            header += f"\nПоказаны первые {MAX_LIST_BUTTONS} из {len(titles)}."
        await message.answer(header, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

    async def show_card(callback: CallbackQuery) -> None:
        if not is_owner(callback.from_user):
            return
        try:
            title_id = int(callback.data.removeprefix(_CARD_PREFIX))
        except ValueError:
            title_id = -1
        card = tracker.title_card(title_id)
        if card is None:
            await callback.answer("Этого тайтла больше нет в списке.")
            return
        await callback.answer()
        await send_card(callback, card)

    # --- buttons under messages and cards -------------------------------------------------------

    async def drop_buttons(callback: CallbackQuery) -> None:
        """A pressed button is spent: take the keyboard off its message."""
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception as exc:  # an old or missing message: the answer to the press matters more
            logging.debug("could not remove buttons: %s", mask_secrets(repr(exc)))

    async def mark_watched(callback: CallbackQuery, title_id: int) -> None:
        try:
            result = await tracker.mark_watched(title_id)
        except UnknownTitle:
            await callback.answer("Этого тайтла больше нет в списке.")
            return
        except Exception as exc:
            logging.warning("marking a title watched failed: %s", mask_secrets(repr(exc)))
            await callback.answer("Не удалось сохранить. Попробуйте ещё раз.")
            return
        await drop_buttons(callback)
        if not result.changed:
            await callback.answer("Уже отмечено как просмотренное.")
            return
        await callback.answer("Отмечено как просмотренное")
        card = tracker.title_card(title_id)
        if callback.message is not None and card is not None:
            await callback.message.answer(
                f"✅ Просмотрено: {card.title}\nФильм в архиве. Раз в неделю я проверю, не анонсировано ли продолжение."
            )

    async def follow_sequel(callback: CallbackQuery, event_id: int) -> None:
        try:
            result = await tracker.follow_sequel(event_id)
        except UnknownEvent:
            await callback.answer("Это объявление больше недоступно.")
            return
        except TitleNotFound:
            await callback.answer("Не нашёл это продолжение в TMDb. Попробуйте чуть позже.")
            return
        except Exception as exc:
            logging.warning("following a sequel failed: %s", mask_secrets(repr(exc)))
            await callback.answer("Не удалось получить данные из TMDb. Попробуйте чуть позже.")
            return
        await drop_buttons(callback)
        await callback.answer()
        heading = "✅ Продолжение добавлено в список" if result.created else "Уже в списке"
        await send_card(callback, tracker.title_card(result.title_id), heading)

    async def open_seasons_choice(callback: CallbackQuery, title_id: int) -> None:
        if not await ask_watched_seasons(callback, title_id):
            await callback.answer("Пока нет вышедших сезонов, отмечать нечего.")
            return
        await callback.answer()

    async def flip_season(callback: CallbackQuery) -> None:
        if not is_owner(callback.from_user):
            return
        raw_id, _, raw_number = callback.data.removeprefix(_SEASON_PREFIX).partition(":")
        if not (raw_id.isascii() and raw_id.isdigit()):
            await callback.answer("Эта кнопка больше не работает.")
            return
        title_id = int(raw_id)
        if raw_number == _DONE:
            await drop_buttons(callback)
            await callback.answer("Готово")
            await send_card(callback, tracker.title_card(title_id))
            return
        if not (raw_number.isascii() and raw_number.isdigit()):
            await callback.answer("Эта кнопка больше не работает.")
            return
        number = int(raw_number)
        marks = {s.number: s.watched for s in tracker.watchable_seasons(title_id)}
        try:
            if number not in marks:
                raise UnknownSeason(f"{title_id}:{number}")
            await tracker.set_season_watched(title_id, number, not marks[number])
        except UnknownTitle:
            await callback.answer("Этого тайтла больше нет в списке.")
            return
        except UnknownSeason:
            await callback.answer("Такого сезона нет или он ещё не вышел.")
            return
        except Exception as exc:
            logging.warning("marking a season failed: %s", mask_secrets(repr(exc)))
            await callback.answer("Не удалось сохранить. Попробуйте ещё раз.")
            return
        await callback.answer()
        try:
            await callback.message.edit_reply_markup(
                reply_markup=seasons_markup(title_id, tracker.watchable_seasons(title_id))
            )
        except Exception as exc:  # the marks are saved; a stale message only keeps its old look
            logging.debug("could not refresh the season buttons: %s", mask_secrets(repr(exc)))

    async def press_action(callback: CallbackQuery) -> None:
        if not is_owner(callback.from_user):
            return
        name, _, raw = callback.data.removeprefix(_ACTION_PREFIX).partition(":")
        number = int(raw) if raw.isascii() and raw.isdigit() else None
        if number is not None and name == WATCHED:
            await mark_watched(callback, number)
        elif number is not None and name == FOLLOW:
            await follow_sequel(callback, number)
        elif number is not None and name == SEASONS:
            await open_seasons_choice(callback, number)
        else:
            await callback.answer("Эта кнопка больше не работает.")

    dp.message.register(show_menu, Command("test_event"))
    dp.message.register(show_menu, F.text == TEST_EVENT_BUTTON)
    dp.callback_query.register(send_test_event, F.data.startswith(_KIND_PREFIX))

    dp.message.register(show_add_menu, F.text == ADD_BUTTON)
    dp.message.register(show_my_titles, F.text == MY_TITLES_BUTTON)
    dp.message.register(search_by_name, is_name_for_search)  # after the menu buttons: a button is never a title name
    dp.callback_query.register(ask_name, F.data.startswith(_ADD_KIND_PREFIX))
    dp.callback_query.register(add_picked, F.data.startswith(_PICK_PREFIX))
    dp.callback_query.register(show_card, F.data.startswith(_CARD_PREFIX))
    dp.callback_query.register(press_action, F.data.startswith(_ACTION_PREFIX))
    dp.callback_query.register(flip_season, F.data.startswith(_SEASON_PREFIX))
