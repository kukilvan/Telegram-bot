"""One process (`app/runtime.py`, ADR 0007): start, orderly stop, a dead part, the bot's reconnects, the watchdog.

The parts are fakes; the scheduler is the real `AsyncIOScheduler`. One test runs the real uvicorn in a child process
and sends it SIGTERM.
"""

import ast
import asyncio
import logging
import os
import signal
import socket
import subprocess
import sys
import textwrap
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.runtime import Health, Runtime, Timings, Watchdog

ROOT = Path(__file__).resolve().parent.parent
FAST = Timings(job_grace=1, beat_every=0.05, scheduler_mark_every=0.05)


class FakeWeb:
    def __init__(self, steps: list[str], die_after: float | None = None, fail_to_listen: bool = False) -> None:
        self.steps = steps
        self.started = False
        self._die_after = die_after
        self._fail_to_listen = fail_to_listen
        self._stopped = asyncio.Event()

    async def serve(self) -> None:
        if self._fail_to_listen:
            raise RuntimeError("веб-сервер не запустился (код 1)")
        self.started = True
        if self._die_after is not None:
            await asyncio.sleep(self._die_after)
            raise OSError("the web broke")
        await self._stopped.wait()
        self.steps.append("web done")

    def stop(self) -> None:
        self.steps.append("web stop")
        self._stopped.set()


class FakeBot:
    def __init__(self, steps: list[str], connect_fails: list[bool] | None = None, receive_fails: bool = False) -> None:
        self.steps = steps
        self.connects = 0
        self._connect_fails = list(connect_fails or [])
        self._receive_fails = receive_fails
        self._stopped = asyncio.Event()

    async def connect(self) -> None:
        self.connects += 1
        if self._connect_fails and self._connect_fails.pop(0):
            raise ConnectionError("no network")

    async def receive(self) -> None:
        if self._receive_fails:
            raise RuntimeError("Conflict: terminated by other getUpdates request")
        self.steps.append("receiving")
        await self._stopped.wait()

    async def stop(self) -> None:
        self.steps.append("bot stop")
        self._stopped.set()

    async def close(self) -> None:
        self.steps.append("bot close")


class NoWatchdog(Watchdog):
    """The real one, but its exit is recorded instead of taken."""

    def __init__(self) -> None:
        self.exits: list[int] = []
        super().__init__(exit=self.exits.append)


def make_runtime(web, bot, scheduler=None, timings=FAST, **kwargs) -> Runtime:
    return Runtime(
        web=web, scheduler=scheduler or AsyncIOScheduler(), bot=bot, health=Health(),
        timings=timings, watchdog=NoWatchdog(), **kwargs,
    )


async def wait_for(condition, timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "the condition never came true"
        await asyncio.sleep(0.01)


# ---- the orderly stop -----------------------------------------------------

def test_a_stop_lets_a_running_job_finish_and_goes_in_order(caplog):
    steps: list[str] = []
    job_started = asyncio.Event()

    async def slow_send():
        job_started.set()
        await asyncio.sleep(0.3)
        steps.append("job done")

    async def scenario():
        scheduler = AsyncIOScheduler()
        scheduler.add_job(slow_send, "interval", seconds=60, next_run_time=datetime.now(timezone.utc))
        runtime = make_runtime(FakeWeb(steps), FakeBot(steps), scheduler)
        run = asyncio.create_task(runtime.run())
        await job_started.wait()
        await wait_for(lambda: "receiving" in steps and runtime.health.report()[0] == 200)
        assert runtime.health.report() == (200, {"status": "ok"})

        runtime.request_stop("в тесте")
        await wait_for(lambda: runtime.health.stopping)
        assert runtime.health.report() == (503, {"status": "stopping"})
        code = await run
        return code, scheduler

    with caplog.at_level(logging.INFO):
        code, scheduler = asyncio.run(scenario())

    assert code == 0
    assert steps[:1] == ["receiving"]
    assert set(steps[1:4]) == {"web stop", "bot stop", "web done"}  # step 2: both at once
    assert steps[4:] == ["job done", "bot close"]  # step 3 waited for the job, then step 4
    assert not scheduler.running
    assert caplog.records[-1].getMessage() == "остановлено"
    assert "прервана" not in caplog.text


def test_a_job_longer_than_the_grace_time_is_cancelled_and_the_stop_does_not_wait_for_it(caplog):
    steps: list[str] = []
    job_started = asyncio.Event()

    async def endless_poll():
        job_started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            steps.append("job cancelled")
            raise

    async def scenario():
        scheduler = AsyncIOScheduler()
        scheduler.add_job(endless_poll, "interval", seconds=60, next_run_time=datetime.now(timezone.utc),
                          name="опрос")
        runtime = make_runtime(FakeWeb(steps), FakeBot(steps), scheduler, timings=Timings(job_grace=0.2))
        run = asyncio.create_task(runtime.run())
        await job_started.wait()
        began = time.monotonic()
        runtime.request_stop()
        code = await run
        return code, time.monotonic() - began

    with caplog.at_level(logging.INFO):
        code, took = asyncio.run(scenario())

    assert code == 0 and took < 2
    assert "остановка: задача опрос прервана" in caplog.text
    assert steps[-2:] == ["job cancelled", "bot close"]


def test_the_scheduler_starts_nothing_new_once_the_stop_began():
    runs: list[float] = []

    async def frequent():
        runs.append(time.monotonic())
        await asyncio.sleep(0.3)

    async def scenario():
        scheduler = AsyncIOScheduler()
        scheduler.add_job(frequent, "interval", seconds=0.1, next_run_time=datetime.now(timezone.utc),
                          max_instances=5)
        runtime = make_runtime(FakeWeb([]), FakeBot([]), scheduler)
        run = asyncio.create_task(runtime.run())
        await wait_for(lambda: runs)
        runtime.request_stop()
        await wait_for(lambda: runtime.health.stopping)
        stop_began = time.monotonic()
        await run
        return stop_began

    stop_began = asyncio.run(scenario())

    assert all(started < stop_began for started in runs)


def test_a_second_stop_request_only_logs(caplog):
    async def scenario():
        runtime = make_runtime(FakeWeb([]), FakeBot([]))
        run = asyncio.create_task(runtime.run())
        await asyncio.sleep(0.1)
        runtime.request_stop("по сигналу SIGTERM")
        runtime.request_stop("по сигналу SIGTERM")
        return await run

    with caplog.at_level(logging.INFO):
        assert asyncio.run(scenario()) == 0

    assert "остановка уже идёт" in caplog.text
    assert caplog.text.count("остановлено") == 1


def test_windows_ctrl_c_cancels_the_main_task_and_the_stop_is_the_same_orderly_one(caplog):
    """On Windows the loop cannot catch signals; asyncio.run cancels the main task on Ctrl+C instead."""
    steps: list[str] = []

    async def scenario():
        loop = asyncio.get_running_loop()

        def no_signals(*args):
            raise NotImplementedError

        loop.add_signal_handler = no_signals
        runtime = make_runtime(FakeWeb(steps), FakeBot(steps))
        run = asyncio.create_task(runtime.run())
        await wait_for(lambda: "receiving" in steps)
        run.cancel()
        return await run

    with caplog.at_level(logging.INFO):
        assert asyncio.run(scenario()) == 0

    assert steps[-1] == "bot close" and "web done" in steps
    assert "остановлено" in caplog.text


# ---- a dead part ----------------------------------------------------------

def test_when_the_web_dies_the_other_parts_are_stopped_and_the_exit_code_is_1(caplog):
    steps: list[str] = []

    async def scenario():
        runtime = make_runtime(FakeWeb(steps, die_after=0.2), FakeBot(steps))
        return await runtime.run(), runtime

    with caplog.at_level(logging.INFO):
        code, runtime = asyncio.run(scenario())

    assert code == 1
    assert "часть «веб» остановилась: the web broke" in caplog.text
    assert steps[-2:] == ["bot stop", "bot close"]
    assert not runtime.health.scheduler_running


def test_when_the_web_cannot_listen_nothing_else_starts_and_the_exit_code_is_1(caplog):
    steps: list[str] = []
    bot = FakeBot(steps)

    async def scenario():
        scheduler = AsyncIOScheduler()
        code = await make_runtime(FakeWeb(steps, fail_to_listen=True), bot, scheduler).run()
        return code, scheduler

    with caplog.at_level(logging.INFO):
        code, scheduler = asyncio.run(scenario())

    assert code == 1 and bot.connects == 0 and not scheduler.running
    assert "часть «веб» остановилась: веб-сервер не запустился" in caplog.text


# ---- the bot and Telegram -------------------------------------------------

def test_a_bot_that_cannot_connect_retries_with_doubling_pauses_while_the_web_and_health_stay_up(caplog):
    pauses: list[float] = []
    reports: list[tuple[int, dict]] = []
    runtime: Runtime

    async def recorded_pause(stop, seconds):
        pauses.append(seconds)
        await asyncio.sleep(0.02)  # the scheduler's mark comes in meanwhile
        reports.append(runtime.health.report())
        if len(pauses) == 7:
            runtime.request_stop()

    async def scenario():
        nonlocal runtime
        runtime = make_runtime(FakeWeb([]), FakeBot([], connect_fails=[True] * 10), pause=recorded_pause)
        return await runtime.run()

    with caplog.at_level(logging.INFO):
        assert asyncio.run(scenario()) == 0

    assert pauses == [30, 60, 120, 240, 300, 300, 300]
    assert reports[-1] == (200, {"status": "ok"})
    assert "бот: нет связи с Telegram, повтор через 30 с" in caplog.text
    assert "ConnectionError: no network" in caplog.text  # with the traceback


def test_after_a_successful_connect_the_pause_is_30_seconds_again():
    pauses: list[float] = []
    runtime: Runtime

    async def recorded_pause(stop, seconds):
        pauses.append(seconds)
        if len(pauses) == 4:
            runtime.request_stop()
        await asyncio.sleep(0)

    async def scenario():
        nonlocal runtime
        # fails, fails, connects (and receiving fails: a second instance), fails
        bot = FakeBot([], connect_fails=[True, True, False, True], receive_fails=True)
        runtime = make_runtime(FakeWeb([]), bot, pause=recorded_pause)
        return await runtime.run()

    assert asyncio.run(scenario()) == 0
    assert pauses == [30, 60, 30, 60]


def test_a_stop_while_the_bot_waits_to_connect_again_does_not_wait_out_the_pause():
    async def scenario():
        runtime = make_runtime(FakeWeb([]), FakeBot([], connect_fails=[True] * 10))
        run = asyncio.create_task(runtime.run())
        await asyncio.sleep(0.1)  # the bot is in its first 30 s pause now
        began = time.monotonic()
        runtime.request_stop()
        code = await run
        return code, time.monotonic() - began

    code, took = asyncio.run(scenario())

    assert code == 0 and took < 2


# ---- /health --------------------------------------------------------------

class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def healthy(clock: Clock) -> Health:
    health = Health(clock=clock)
    health.bot_running = health.scheduler_running = True
    health.scheduler_mark = clock.now
    return health


def test_health_is_ok_when_the_bot_runs_and_the_scheduler_marked_lately():
    clock = Clock()
    health = healthy(clock)
    clock.now += 179

    assert health.report() == (200, {"status": "ok"})


def test_health_fails_when_the_scheduler_is_stopped_or_its_mark_is_older_than_3_minutes():
    clock = Clock()
    stopped = healthy(clock)
    stopped.scheduler_running = False
    stale = healthy(clock)
    no_bot = healthy(clock)
    no_bot.bot_running = False
    clock.now += 181

    assert stopped.report() == (503, {"status": "fail", "failed": ["scheduler"]})
    assert stale.report() == (503, {"status": "fail", "failed": ["scheduler"]})
    assert no_bot.report() == (503, {"status": "fail", "failed": ["bot", "scheduler"]})


def test_health_says_stopping_during_the_stop():
    health = healthy(Clock())
    health.stopping = True

    assert health.report() == (503, {"status": "stopping"})


# ---- the watchdog ---------------------------------------------------------

def test_the_watchdog_exits_when_the_mark_is_stale_on_two_checks_in_a_row(caplog):
    clock = Clock()
    exits: list[int] = []
    watchdog = Watchdog(stale=60, check_every=15, clock=clock, exit=exits.append)
    watchdog.beat()

    clock.now += 61
    watchdog.check()
    assert exits == []
    clock.now += 15
    with caplog.at_level(logging.CRITICAL):
        watchdog.check()

    assert exits == [1]
    assert "цикл событий не отвечает 76 с — выход для перезапуска" in caplog.text


def test_the_watchdog_does_not_exit_when_the_mark_moved_between_the_checks_after_a_wake_from_sleep():
    clock = Clock()
    exits: list[int] = []
    watchdog = Watchdog(stale=60, check_every=15, clock=clock, exit=exits.append)
    watchdog.beat()

    clock.now += 3600  # the PC slept for an hour
    watchdog.check()
    clock.now += 2
    watchdog.beat()  # the loop woke up
    clock.now += 13
    watchdog.check()
    clock.now += 15
    watchdog.check()

    assert exits == []


def test_the_watchdog_does_not_exit_while_the_loop_marks():
    clock = Clock()
    exits: list[int] = []
    watchdog = Watchdog(stale=60, check_every=15, clock=clock, exit=exits.append)
    for _ in range(20):
        clock.now += 15
        watchdog.beat()
        watchdog.check()

    assert exits == []


def test_the_watchdog_thread_checks_on_its_own():
    clock = Clock()
    exits: list[int] = []
    watchdog = Watchdog(stale=60, check_every=0.01, clock=clock, exit=exits.append)
    clock.now += 61
    watchdog.start()
    try:
        deadline = time.monotonic() + 5
        while not exits and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        watchdog.stop()

    assert exits and exits[0] == 1


# ---- Windows: nothing on import -------------------------------------------

def test_runtime_does_nothing_with_signals_or_the_os_on_import():
    """The tests run on Windows too, where `loop.add_signal_handler` is missing: signals only inside functions."""
    tree = ast.parse((ROOT / "app" / "runtime.py").read_text(encoding="utf-8"))
    offenders = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Attribute) and isinstance(inner.value, ast.Name) and inner.value.id in {
                "signal", "os", "threading",
            }:
                offenders.append(f"{inner.value.id}.{inner.attr}:{node.lineno}")

    assert offenders == []


# ---- the real uvicorn and a real SIGTERM ----------------------------------

CHILD = textwrap.dedent("""
    import asyncio, logging, sys
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from app.runtime import Health, Runtime
    from app.web import create_web_app, web_server

    class Bot:
        def __init__(self):
            self.stopped = asyncio.Event()
        async def connect(self): pass
        async def receive(self): await self.stopped.wait()
        async def stop(self): self.stopped.set()
        async def close(self): pass

    async def main():
        health = Health()
        server = web_server(create_web_app(health=health.report), host="127.0.0.1", port=int(sys.argv[1]),
                            stop_grace=5)
        runtime = Runtime(web=server, scheduler=AsyncIOScheduler(), bot=Bot(), health=health)
        return await runtime.run()

    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(message)s")
    code = asyncio.run(main())
    print("exit code", code, flush=True)
    sys.exit(code)
""")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.mark.skipif(sys.platform == "win32", reason="real signals: the app runs only in a Linux container")
def test_the_real_uvicorn_stops_on_sigterm_with_exit_code_0_and_no_signal_again(tmp_path):
    script = tmp_path / "child.py"
    script.write_text(CHILD, encoding="utf-8")
    port = free_port()
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    child = subprocess.Popen([sys.executable, str(script), str(port)], cwd=ROOT, env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        deadline = time.monotonic() + 15
        body = None
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                    body = response.read().decode()
                    break
            except OSError:
                time.sleep(0.1)
        assert body == '{"status":"ok"}'

        child.send_signal(signal.SIGTERM)
        output, _ = child.communicate(timeout=30)
    finally:
        if child.poll() is None:
            child.kill()

    assert child.returncode == 0, output
    assert "exit code 0" in output and "остановлено" in output
    assert "остановка уже идёт" not in output  # uvicorn did not send the signal again
    assert "Uvicorn running" in output  # uvicorn writes to the process's log
