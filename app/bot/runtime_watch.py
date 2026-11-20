"""What the runtime watches in the bot: the updates being handled (the stop waits for them) and the answers to getUpdates.

`RunningUpdates` is an outer middleware of `dp.update` (KI-9): aiogram runs each update as a task of its own and
`stop_polling` does not wait for them, so the stop waits here. `GetUpdatesWatch` is a request middleware of the bot's
session (KI-33): aiogram retries a failed getUpdates inside its polling and raises nothing, so the line «Бот не подключён
к Telegram» follows the answers to getUpdates themselves. Other requests (sending) do not touch it.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.client.session.middlewares.base import BaseRequestMiddleware, NextRequestMiddlewareType
from aiogram.methods import GetUpdates, TelegramMethod
from aiogram.types import TelegramObject


class RunningUpdates(BaseMiddleware):
    """Keeps the task of every update while it is handled; `wait` lets the stop give them time to finish."""

    def __init__(self) -> None:
        self.tasks: set[asyncio.Task] = set()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        task = asyncio.current_task()
        self.tasks.add(task)
        try:
            return await handler(event, data)
        finally:
            self.tasks.discard(task)

    async def wait(self, timeout: float) -> int:
        """Wait up to `timeout` seconds for the updates being handled; the number still running then (they are left
        to end by themselves)."""
        running = set(self.tasks)
        if not running:
            return 0
        _, left = await asyncio.wait(running, timeout=timeout)
        return len(left)


class GetUpdatesWatch(BaseRequestMiddleware):
    """Tells `down(True)` when getUpdates fails (no network, Telegram's error, a second instance) and `down(False)`
    when it is answered."""

    def __init__(self, down: Callable[[bool], None]) -> None:
        self._down = down

    async def __call__(self, make_request: NextRequestMiddlewareType, bot: Any, method: TelegramMethod) -> Any:
        if not isinstance(method, GetUpdates):
            return await make_request(bot, method)
        try:
            response = await make_request(bot, method)
        except Exception:
            self._down(True)
            raise
        self._down(False)
        return response
