"""The bot part on stop and the line «Бот не подключён к Telegram» (spec 9.1a 2.1, 2.2, 2.4; KI-5, 9, 33).

`TelegramPart.close` waits for the sends before it closes the session; `TelegramPart.stop` waits for the started presses
(`RunningUpdates`, the outermost middleware of `dp.update`); `GetUpdatesWatch` follows the answers to getUpdates only.
"""

import asyncio
import logging
from datetime import datetime, timezone

import pytest
from aiogram import Bot, Dispatcher
from aiogram.methods import GetUpdates, SendMessage
from aiogram.types import Chat, Message, Update, User

import app.main as app_main
from app.bot.access import AccessMiddleware
from app.bot.main import build_dispatcher
from app.bot.runtime_watch import GetUpdatesWatch, RunningUpdates
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory

BOT_TOKEN = "123456:TEST"
OWNER = 42


async def nothing_to_finish(timeout: float) -> bool:
    return True


def owner_message(text: str = "привет") -> Update:
    user = User(id=OWNER, is_bot=False, first_name="Owner")
    message = Message(
        message_id=1, date=datetime(2026, 11, 20, tzinfo=timezone.utc), chat=Chat(id=OWNER, type="private"),
        from_user=user, text=text,
    )
    return Update(update_id=1, message=message)


# ---- close: the sends first, then the session ---------------------------------------------------

class FakeSession:
    def __init__(self, order):
        self.order = order

    async def close(self):
        self.order.append("session closed")


class FakeBot:
    def __init__(self, order):
        self.session = FakeSession(order)


def test_close_waits_for_the_sends_with_5_seconds_before_it_closes_the_session():
    order = []

    async def finish_sends(timeout):
        order.append(f"sends finished within {timeout:g} s")
        return True

    part = app_main.TelegramPart(FakeBot(order), Dispatcher(), RunningUpdates(), finish_sends)
    asyncio.run(part.close())

    assert order == ["sends finished within 5 s", "session closed"]
    assert app_main.SEND_GRACE == 5 and app_main.HANDLER_GRACE == 10


def test_close_without_a_bot_still_waits_for_the_sends():
    waited = []

    async def finish_sends(timeout):
        waited.append(timeout)
        return False

    asyncio.run(app_main.TelegramPart(None, Dispatcher(), RunningUpdates(), finish_sends, send_grace=0.1).close())

    assert waited == [0.1]


# ---- stop: the started presses get their time ---------------------------------------------------

def press(running: RunningUpdates, release: asyncio.Event) -> asyncio.Task:
    """An update being handled: its handler waits for `release`."""

    async def handler(event, data):
        await release.wait()

    return asyncio.create_task(running(handler, owner_message(), {}))


def test_stop_waits_for_a_running_press_that_ends_within_the_grace(caplog):
    async def scenario():
        running, release = RunningUpdates(), asyncio.Event()
        task = press(running, release)
        await asyncio.sleep(0)
        part = app_main.TelegramPart(None, Dispatcher(), running, nothing_to_finish, handler_grace=5)
        asyncio.get_running_loop().call_later(0.05, release.set)
        with caplog.at_level(logging.WARNING):
            await part.stop()
        return task.done(), running.tasks

    done, left = asyncio.run(scenario())

    assert done is True and left == set()
    assert "нажатий в боте" not in caplog.text


def test_stop_gives_up_after_the_grace_and_logs_how_many_presses_are_left(caplog):
    async def scenario():
        running, release = RunningUpdates(), asyncio.Event()
        tasks = [press(running, release), press(running, release)]
        await asyncio.sleep(0)
        part = app_main.TelegramPart(None, Dispatcher(), running, nothing_to_finish, handler_grace=0.05)
        with caplog.at_level(logging.WARNING):
            await part.stop()
        still_running = [not task.done() for task in tasks]
        release.set()
        await asyncio.gather(*tasks)
        return still_running

    assert asyncio.run(scenario()) == [True, True]  # left to end by themselves
    assert caplog.text.count("остановка: 2 нажатий в боте не закончились за 0.05 с") == 1


# ---- the middleware of dp.update -----------------------------------------------------------------

def test_the_middleware_keeps_the_task_while_the_update_runs_and_drops_it_after_also_when_the_handler_raises():
    running = RunningUpdates()
    dp = Dispatcher()
    dp.update.outer_middleware(running)
    seen = []

    @dp.message()
    async def handler(message: Message):
        seen.append(asyncio.current_task() in running.tasks)
        if message.text == "сбой":
            raise ValueError("handler bug")

    async def scenario():
        bot = Bot(token=BOT_TOKEN)
        await dp.feed_update(bot, owner_message())
        with pytest.raises(ValueError):
            await dp.feed_update(bot, owner_message("сбой"))
        await bot.session.close()

    asyncio.run(scenario())

    assert seen == [True, True] and running.tasks == set()


def test_build_dispatcher_registers_the_given_middleware_before_its_own():
    tracker = Tracker(create_session_factory("sqlite://"), clock=lambda: datetime.now(timezone.utc), sender=None,
                      sources={})
    running = RunningUpdates()

    dp = build_dispatcher(tracker, [OWNER], running=running)

    middlewares = list(dp.update.outer_middleware)  # aiogram's own two come first
    assert middlewares.index(running) < next(i for i, m in enumerate(middlewares) if isinstance(m, AccessMiddleware))
    assert any(isinstance(m, RunningUpdates) for m in build_dispatcher(tracker, [OWNER]).update.outer_middleware)


# ---- getUpdates and the line «Бот не подключён к Telegram» ---------------------------------------

def watch_call(method, fails: bool):
    flags = []

    async def make_request(bot, method):
        if fails:
            raise ConnectionError("no network")
        return "answer"

    async def scenario():
        return await GetUpdatesWatch(flags.append)(make_request, None, method)

    if fails:
        with pytest.raises(ConnectionError):
            asyncio.run(scenario())
    else:
        assert asyncio.run(scenario()) == "answer"
    return flags


def test_a_failing_get_updates_sets_the_flag_and_an_answer_clears_it():
    assert watch_call(GetUpdates(), fails=True) == [True]
    assert watch_call(GetUpdates(), fails=False) == [False]


def test_a_send_does_not_touch_the_flag_whether_it_fails_or_not():
    assert watch_call(SendMessage(chat_id=OWNER, text="x"), fails=True) == []
    assert watch_call(SendMessage(chat_id=OWNER, text="x"), fails=False) == []
