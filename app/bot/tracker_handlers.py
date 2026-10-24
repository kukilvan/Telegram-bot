"""Bot side of the tracker core: «Тестовое событие» and the Telegram sender.

Handlers talk to the core only through the `Tracker` facade.
"""

import logging

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

from app.tracker.core import Tracker

TEST_EVENT_BUTTON = "🧪 Тестовое событие"
_KIND_PREFIX = "tev:"


class TelegramSender:
    """Delivers tracker messages to the owner's chat."""

    def __init__(self, bot: Bot, chat_id: int) -> None:
        self._bot = bot
        self._chat_id = chat_id

    async def send(self, message: str) -> None:
        await self._bot.send_message(chat_id=self._chat_id, text=message)


def owner_chat_id(configured: str, allowed_user_ids: list[int]) -> int:
    """OWNER_CHAT_ID if it is a number, otherwise the first allowed user (a private chat id equals the user id)."""
    try:
        return int(configured)
    except ValueError:
        if configured:
            logging.warning("OWNER_CHAT_ID is not a number; sending tracker messages to the first allowed user")
        return allowed_user_ids[0]


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=TEST_EVENT_BUTTON)]], resize_keyboard=True)


def register_tracker_handlers(dp: Dispatcher, tracker: Tracker, allowed_user_ids: list[int]) -> None:
    """Register on `dp` itself (not a sub-router) so these win over the catch-all text handler."""
    allowed = frozenset(allowed_user_ids)

    def is_owner(user) -> bool:  # second line of defence behind AccessMiddleware
        return getattr(user, "id", None) in allowed

    async def show_menu(message: Message) -> None:
        if not is_owner(message.from_user):
            return
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

    dp.message.register(show_menu, Command("test_event"))
    dp.message.register(show_menu, F.text == TEST_EVENT_BUTTON)
    dp.callback_query.register(send_test_event, F.data.startswith(_KIND_PREFIX))
