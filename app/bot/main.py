"""Minimal aiogram bot entry point. Phase 1 skeleton."""

import asyncio
import logging

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart

from app.config import get_settings


async def main() -> None:
    settings = get_settings()
    logging.info("Starting bot...")

    dp = Dispatcher()

    async with Bot(token=settings.telegram_bot_token) as bot:
        me = await bot.get_me()
        logging.info(f"Bot started as @{me.username}")

        @dp.message(CommandStart())
        async def start_handler(message: types.Message):
            await message.answer("👋 Бот запущен. Phase 1 skeleton works.")

        # Long polling (for VPS deployment without webhook setup)
        await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
