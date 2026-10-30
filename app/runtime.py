"""One process: the web server, the scheduler and the bot run in one event loop (ADR 0007).

The runtime starts the parts in order, stops them in order on SIGTERM / SIGINT, stops everything (exit code 1) when a
part dies and leaves the process at once when the loop hangs, so that Docker starts it again. It keeps what `/health`
reports. It knows nothing of aiogram or FastAPI: the parts are handed to it, so the tests hand it fakes.

Nothing here touches signals or the OS on import: the tests run on Windows too.
"""

import asyncio
import logging
import os
import signal
import threading
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_SUBMITTED, JobEvent
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)

STOP_SIGNALS = ("SIGTERM", "SIGINT")  # by name: the values are looked up only when the loop is running


@dataclass(frozen=True)
class Timings:
    """How long the runtime waits, in seconds. The tests shrink them."""

    job_grace: float = 15  # running scheduler jobs get this long to finish on stop, then they are cancelled
    bot_retry_first: float = 30  # pause before the bot connects to Telegram again; doubles each time
    bot_retry_max: float = 300
    beat_every: float = 5  # the loop marks that it is alive
    scheduler_mark_every: float = 30  # the scheduler marks that it runs jobs
    watch_every: float = 15  # the watchdog looks at the loop's mark
    loop_stale: float = 60  # a mark this old on two checks in a row: the loop hangs


class WebServer(Protocol):
    started: bool  # it listens

    async def serve(self) -> None:
        """Serve until `stop`; finishing otherwise (or raising) means the web is dead."""

    def stop(self) -> None:
        """Stop taking new connections, finish the started requests, then let `serve` return."""


class BotPart(Protocol):
    async def connect(self) -> None:
        """Reach Telegram (who am I, the command menu); raises when it cannot."""

    async def receive(self, started: Callable[[], None]) -> None:
        """Receive messages until `stop`, calling `started` once receiving has begun; raises when receiving fails."""

    async def stop(self) -> None:
        """Stop receiving; nothing to do when it does not receive."""

    async def close(self) -> None:
        """Close the HTTP session to Telegram (sending goes through it too, so this comes last)."""


class Health:
    """What `/health` reports. The runtime keeps it current; reading it touches neither the database nor the network."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, scheduler_mark_stale: float = 180) -> None:
        self.clock = clock
        self.scheduler_mark_stale = scheduler_mark_stale
        self.stopping = False
        self.bot_running = False  # waiting to connect again counts as running: Telegram is not part of health
        self.telegram_down = False  # the last try to connect or to receive failed (the web says so); not part of health
        self.scheduler_running = False
        self.scheduler_mark: float | None = None

    def report(self) -> tuple[int, dict[str, object]]:
        """The HTTP status and the body: 200 ok, 503 with the parts not in order, 503 while stopping."""
        if self.stopping:
            return 503, {"status": "stopping"}
        failed = []
        if not self.bot_running:
            failed.append("bot")
        mark = self.scheduler_mark
        if not self.scheduler_running or mark is None or self.clock() - mark > self.scheduler_mark_stale:
            failed.append("scheduler")
        if failed:
            return 503, {"status": "fail", "failed": failed}
        return 200, {"status": "ok"}


class Watchdog:
    """A thread outside the event loop. The loop marks itself alive (`beat`); when the mark is older than `stale` on
    two checks in a row and has not moved between them, the process leaves at once: the loop stands, so an orderly
    stop is impossible. Two checks, because after the PC wakes from sleep the old mark looks stale once, and the loop
    marks again within seconds."""

    def __init__(
        self,
        stale: float = 60,
        check_every: float = 15,
        clock: Callable[[], float] = time.monotonic,
        exit: Callable[[int], object] = os._exit,
    ) -> None:
        self._stale = stale
        self._check_every = check_every
        self._clock = clock
        self._exit = exit
        self._mark = clock()
        self._stale_mark: float | None = None  # the mark that was stale on the previous check
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None

    def beat(self) -> None:
        self._mark = self._clock()

    def check(self) -> None:
        mark = self._mark
        age = self._clock() - mark
        if age <= self._stale:
            self._stale_mark = None
            return
        if self._stale_mark == mark:
            logger.critical("цикл событий не отвечает %d с — выход для перезапуска", age)
            self._exit(1)
            return
        self._stale_mark = mark

    def start(self) -> None:
        self._thread = threading.Thread(target=self._watch, name="loop-watchdog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()

    def _watch(self) -> None:
        while not self._stopped.wait(self._check_every):
            self.check()


async def _pause(stop: asyncio.Event, seconds: float) -> None:
    """Wait `seconds`, or less when the stop comes first."""
    with suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), seconds)


class Runtime:
    """Starts the parts (web → scheduler → bot → watchdog), watches them and stops them. `run` returns the exit code."""

    def __init__(
        self,
        *,
        web: WebServer,
        scheduler: AsyncIOScheduler,
        bot: BotPart,
        health: Health,
        timings: Timings = Timings(),
        watchdog: Watchdog | None = None,
        pause: Callable[[asyncio.Event, float], Awaitable[None]] = _pause,
    ) -> None:
        self._web = web
        self._scheduler = scheduler
        self._bot = bot
        self.health = health
        self._timings = timings
        self._watchdog = watchdog or Watchdog(timings.loop_stale, timings.watch_every)
        self._pause = pause
        self._stop_requested = asyncio.Event()
        self._running_jobs: dict[str, str] = {}  # job id → its name, while the job runs

    def request_stop(self, why: str = "по запросу") -> None:
        """Begin the orderly stop (a signal, or a direct call: the tests, Windows). A second request only logs."""
        if self._stop_requested.is_set():
            logger.warning("повторный запрос остановки %s: остановка уже идёт", why)
            return
        logger.info("остановка %s", why)
        self._stop_requested.set()

    async def run(self) -> int:
        loop = asyncio.get_running_loop()
        signals = self._catch_signals(loop)
        try:
            return await self._run()
        finally:
            for sig in signals:
                loop.remove_signal_handler(sig)

    def _catch_signals(self, loop: asyncio.AbstractEventLoop) -> list[signal.Signals]:
        caught = []
        for name in STOP_SIGNALS:
            sig = getattr(signal, name)
            try:
                loop.add_signal_handler(sig, self.request_stop, f"по сигналу {name}")
            except NotImplementedError:
                # Windows: the loop cannot catch signals. Ctrl+C there cancels the main task (asyncio.run), and `_run`
                # turns that into the same orderly stop
                continue
            caught.append(sig)
        return caught

    async def _run(self) -> int:
        web = asyncio.create_task(self._web.serve(), name="web")
        while not self._web.started and not web.done():  # the scheduler and the bot start once the web listens
            await asyncio.sleep(0.05)
        tasks = {web: "веб"}
        beat = None
        if not web.done():
            self._start_scheduler()
            tasks[asyncio.create_task(self._run_bot(), name="bot")] = "бот"
            beat = asyncio.create_task(self._beat(), name="loop-beat")
            self._watchdog.start()

        stop = asyncio.create_task(self._stop_requested.wait(), name="stop-requested")
        try:
            done, _ = await asyncio.wait({*tasks, stop}, return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:
            # Windows, Ctrl+C: asyncio.run cancelled the main task. Undo that and stop the same orderly way
            asyncio.current_task().uncancel()
            self.request_stop("по Ctrl+C")
            done = {stop}
        code = 0
        if stop not in done:
            dead = next(task for task in tasks if task in done)
            reason = "отменена" if dead.cancelled() else (dead.exception() or "закончила работу без остановки")
            logger.error("часть «%s» остановилась: %s", tasks[dead], reason,
                         exc_info=reason if isinstance(reason, BaseException) else None)
            code = 1
        stop.cancel()
        await self._stop(web, next((task for task in tasks if task is not web), None), beat)
        return code

    async def _stop(self, web: asyncio.Task, bot: asyncio.Task | None, beat: asyncio.Task | None) -> None:
        # 1. The watchdog is off, /health says "stopping", the scheduler starts nothing more
        self._watchdog.stop()
        if beat is not None:
            beat.cancel()
        self.health.stopping = True
        if self._scheduler.running:
            self._scheduler.pause()
        self._stop_requested.set()  # also breaks the bot's wait before connecting again
        # 2. At once: the web finishes the started requests, the bot stops receiving
        self._web.stop()
        await asyncio.gather(asyncio.wait({web}), self._stop_bot(bot))
        # 3. The running jobs finish, or are cancelled after the grace time
        if self._scheduler.running:
            await self._stop_scheduler()
        # 4. The HTTP session to Telegram
        try:
            await self._bot.close()
        except Exception:
            logger.exception("остановка: сессия Telegram не закрылась")
        # 5.
        logger.info("остановлено")

    async def _stop_bot(self, bot: asyncio.Task | None) -> None:
        if bot is None:
            return
        try:
            await self._bot.stop()
        except Exception:
            logger.exception("остановка: бот не остановил приём сообщений")
        bot.cancel()  # it may be connecting or waiting to connect again
        with suppress(asyncio.CancelledError):
            await bot

    def _start_scheduler(self) -> None:
        scheduler = self._scheduler
        scheduler.add_listener(self._job_event, EVENT_JOB_SUBMITTED | EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
        scheduler.add_job(
            self._mark_scheduler, "interval",
            seconds=self._timings.scheduler_mark_every, next_run_time=datetime.now(timezone.utc),
            id="scheduler-alive", name="планировщик жив",
            misfire_grace_time=None, coalesce=True, max_instances=1,
        )
        scheduler.start()
        self.health.scheduler_running = True

    async def _stop_scheduler(self) -> None:
        # `AsyncIOScheduler.shutdown()` itself cancels the running coroutine jobs without waiting for them (APScheduler
        # 3.11), so the waiting is done here, before it
        deadline = time.monotonic() + self._timings.job_grace
        while self._running_jobs and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        for name in self._running_jobs.values():
            logger.warning("остановка: задача %s прервана", name)
        # A database write already running in a thread is not interrupted: the thread finishes, asyncio.run waits for it
        self._scheduler.shutdown(wait=False)
        await asyncio.sleep(0)  # AsyncIOScheduler shuts down on the loop's next turn
        self.health.scheduler_running = False
        # The cancelled jobs end at their next await (the job's runner reports them then); a moment for that, so a
        # cancelled send does not meet a closed session
        deadline = time.monotonic() + 1
        while self._running_jobs and time.monotonic() < deadline:
            await asyncio.sleep(0.01)

    def _job_event(self, event: JobEvent) -> None:
        if event.code == EVENT_JOB_SUBMITTED:
            job = self._scheduler.get_job(event.job_id)
            self._running_jobs[event.job_id] = job.name if job is not None else event.job_id
        else:
            self._running_jobs.pop(event.job_id, None)

    async def _mark_scheduler(self) -> None:
        self.health.scheduler_mark = self.health.clock()

    async def _beat(self) -> None:
        while True:
            self._watchdog.beat()
            await asyncio.sleep(self._timings.beat_every)

    async def _run_bot(self) -> None:
        """The bot part does not die of Telegram: no network, a wrong token, a second instance or a bug in a handler —
        it logs the error and tries again after a pause (30 s, doubling, at most 5 min; 30 s again once receiving has
        begun, not merely connected: receiving that fails at once keeps doubling). Meanwhile the web and the polling of
        sources go on."""
        self.health.bot_running = True
        pause = self._timings.bot_retry_first

        def receiving_began() -> None:
            nonlocal pause
            pause = self._timings.bot_retry_first
            self.health.telegram_down = False

        try:
            while not self._stop_requested.is_set():
                try:
                    await self._bot.connect()
                    await self._bot.receive(receiving_began)
                    if self._stop_requested.is_set():
                        return
                    raise RuntimeError("приём сообщений закончился без остановки")
                except Exception:
                    if self._stop_requested.is_set():
                        return
                    self.health.telegram_down = True
                    logger.error("бот: нет связи с Telegram, повтор через %d с", pause, exc_info=True)
                await self._pause(self._stop_requested, pause)
                pause = min(pause * 2, self._timings.bot_retry_max)
        finally:
            self.health.bot_running = False
