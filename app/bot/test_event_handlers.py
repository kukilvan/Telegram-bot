"""Bot side of «Тестовое событие»: the list of samples, the delivery-rules check and their buttons.

`register_test_event_handlers` puts them on the owner router of `tracker_handlers`. The menu text «🧪 Тестовое событие»
is taken only in chat mode (in link mode the test event is in Settings of the app and `tracker_handlers` answers the
text with a link); the buttons (`tev:`, `tchk:`, `twin:`) work in both modes, so a message sent before keeps its buttons
alive. The last item of the list is «🕒 Проверить правила доставки», which asks for a moment of the week and shows what
the delivery rules do with an event at that moment (the logic is `Tracker.delivery_check`; the bot words the answer).
"""

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.tracker.core import CheckOutcome, Tracker, UnknownCheck, UnknownSample
from app.tracker.test_samples import DELIVERY_CHECKS

TEST_EVENT_BUTTON = "🧪 Тестовое событие"
RULES_CHECK_BUTTON = "🕒 Проверить правила доставки"  # the last item of the test-event list
RULES_CHECK_CALLBACK = "tchk:open"
_SAMPLE_PREFIX = "tev:"
_CHECK_PREFIX = "twin:"  # twin:<delivery check id>: a test event as if it were queued at that moment of the week (sent buttons keep it)


def register_test_event_handlers(router: Router, tracker: Tracker, *, chat_mode: bool) -> None:
    """«Тестовое событие» (only in chat mode) and the buttons of the samples and of the check (always) on `router`."""

    async def show_menu(message: Message) -> None:
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
        except UnknownSample:
            await callback.answer("Такого события больше нет, откройте меню заново.")
            return
        except Exception as exc:  # not the send (a failed send is `delivered` False): whether it was queued is unknown
            logging.warning("sending the test event %s failed: %r", sample_id, exc)
            await callback.answer("Не удалось отправить тестовое событие. Попробуйте ещё раз.")
            return
        if result.delivered:
            await callback.answer("Отправлено")
        else:
            await callback.answer("Не удалось отправить, событие осталось в очереди и придёт позже.")

    async def show_rules_check(callback: CallbackQuery) -> None:
        rows = [
            [InlineKeyboardButton(text=c.label, callback_data=f"{_CHECK_PREFIX}{c.id}")]
            for c in DELIVERY_CHECKS
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
        try:
            result = await tracker.delivery_check(callback.data.removeprefix(_CHECK_PREFIX))
        except UnknownCheck:
            await callback.answer("Такого момента больше нет, откройте меню заново.")
            return
        except Exception as exc:
            logging.warning("delivery rules check failed: %s", repr(exc))
            await callback.answer("Не удалось выполнить проверку. Попробуйте ещё раз.")
            return
        await callback.answer()

        if result.outcome is CheckOutcome.AT_ONCE:
            text = f"Как будто сейчас {result.moment}: сообщения пришли сразу, правила их не задерживают."
        elif result.outcome is CheckOutcome.HELD:
            text = (
                f"Как будто сейчас {result.moment}: в этот момент ничего не пришло, события копились. "
                f"Выше — сводка, которая уйдёт {result.release}."
            )
        else:
            text = "Не удалось отправить, события остались в очереди и придут позже."
        if callback.message is not None:
            await callback.message.answer(text)

    if chat_mode:
        router.message.register(show_menu, F.text == TEST_EVENT_BUTTON)
    router.callback_query.register(send_test_event, F.data.startswith(_SAMPLE_PREFIX))
    router.callback_query.register(show_rules_check, F.data == RULES_CHECK_CALLBACK)
    router.callback_query.register(run_rules_check, F.data.startswith(_CHECK_PREFIX))
