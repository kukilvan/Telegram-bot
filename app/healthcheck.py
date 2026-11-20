"""The health check for Docker (`python -m app.healthcheck`, KI-3, KI-6): asks `/health`, ends a hung app (ADR 0015).

Exit code 0 only on an answer 200; otherwise 1 and one line with the reason (Docker keeps it in `docker inspect`).
Standard library only and no settings: it starts fast and does not read `.env`. It goes straight to the application,
without a proxy: `HTTP_PROXY` / `NO_PROXY` of the container (from `.env`) must not stand between the check and the port.

A hang that holds the GIL stops the app's own watchdog too, so the check ends it (KI-6). A **timeout** is a check that
connected and got no answer in its 5 s (the kernel still takes the connection of a hung loop); refused, reset or any
answer is no timeout. The timeouts in a row are counted in a file of the temp folder, with the app process they belong
to (pid and start time from `/proc`): another process starts the count anew. The fourth timeout in a row sends SIGKILL
to the app — the only child of PID 1, Docker's init (`init: true`); the init then exits and Docker starts the container
again. No such child (no init, not Linux) — no kill. The decision itself is pure (`decide`), tested without Docker.
"""

import json
import os
import signal
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

URL = "http://127.0.0.1:8080/health"
TIMEOUT_SECONDS = 5
# An opener with an empty proxy table: `urlopen` would read the proxy from the environment
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
PROC = Path("/proc")
STATE_NAME = "release-tracker-health.json"  # in the temp folder: the count dies with the container, as it should
KILL_AFTER = 4  # timeouts in a row; Docker checks every 30 s, so about 1.5–2 min of hang (the watchdog acts first)
KILLED = "/health не отвечает 4 раза подряд — приложение остановлено для перезапуска"
SIGKILL = getattr(signal, "SIGKILL", 9)  # Windows has no SIGKILL, and no /proc either: there the check never kills


@dataclass(frozen=True)
class Answer:
    reason: str | None  # None when healthy, otherwise the reason in one line
    timed_out: bool = False  # connected and got no answer in time: the sign of a hung loop


@dataclass(frozen=True)
class Process:
    pid: int
    started: str  # the start time from `/proc/<pid>/stat`: a new process with an old pid is another process


@dataclass(frozen=True)
class Count:
    process: Process | None
    timeouts: int  # in a row, of this process


def check(url: str = URL, timeout: float = TIMEOUT_SECONDS) -> Answer:
    try:
        with OPENER.open(url, timeout=timeout) as response:
            return Answer(None if response.status == 200 else f"/health ответил {response.status}")
    except urllib.error.HTTPError as exc:
        return Answer(f"/health ответил {exc.code}")
    except TimeoutError as exc:  # the connect succeeded (its own timeout comes wrapped in URLError), the answer did not
        return Answer(f"/health не отвечает: {exc!r}", timed_out=True)
    except Exception as exc:  # refused, reset, a broken answer: not healthy, but the app is not hanging
        return Answer(f"/health не отвечает: {exc!r}")


def decide(count: Count | None, timed_out: bool, process: Process | None) -> tuple[Count, bool]:
    """The new count and whether to kill: a check that is no timeout sets the count to 0; a timeout adds one to the
    count of the same process, or starts it anew for another; the fourth in a row kills, if there is a process."""
    if not timed_out:
        return Count(process, 0), False
    before = count.timeouts if count is not None and count.process == process else 0
    timeouts = before + 1
    return Count(process, timeouts), timeouts >= KILL_AFTER and process is not None


def app_process(proc: Path = PROC) -> Process | None:
    """The app: the only child of PID 1 in `proc`. None when there is no `proc`, no child or several of them."""
    children = []
    try:
        entries = list(proc.iterdir())
    except OSError:
        return None
    for entry in entries:
        if not entry.name.isdigit():
            continue
        stat = _stat_fields(entry / "stat")
        if stat is not None and stat[1] == "1":
            children.append(Process(int(entry.name), stat[19]))
    return children[0] if len(children) == 1 else None


def _stat_fields(path: Path) -> list[str] | None:
    """The fields of `/proc/<pid>/stat` after the name, from the state (field 3) on: the name in brackets may hold
    spaces and brackets itself, so the split starts after the last `)`. None when it cannot be read."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    fields = text[text.rfind(")") + 1:].split()
    return fields if len(fields) >= 20 else None


def state_file() -> Path:
    return Path(tempfile.gettempdir()) / STATE_NAME


def read_count(path: Path) -> Count | None:
    """The saved count; a missing or spoiled file is no count."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        pid, started, timeouts = data["pid"], data["started"], data["timeouts"]
    except (OSError, ValueError, TypeError, KeyError):
        return None
    if not isinstance(timeouts, int) or (pid is not None and not isinstance(pid, int)):
        return None
    process = Process(pid, str(started)) if pid is not None else None
    return Count(process, timeouts)


def write_count(path: Path, count: Count) -> None:
    """Save the count (through a temporary file, so a half-written one is never read); a refusal is ignored: the next
    check counts from what it finds."""
    process = count.process
    data = {"pid": process.pid if process else None, "started": process.started if process else None,
            "timeouts": count.timeouts}
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(json.dumps(data), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        pass


def tell_container_log(line: str, proc: Path = PROC) -> None:
    """Write the line to the container's own log too (the output of PID 1), so `.\\logs-bot.ps1` shows it; best effort."""
    try:
        with open(proc / "1" / "fd" / "1", "a", encoding="utf-8") as out:
            out.write(line + "\n")
    except OSError:
        pass


def main(proc: Path = PROC, kill: Callable[[int, int], object] = os.kill) -> int:
    answer = check()
    path = state_file()
    before = read_count(path)
    process = app_process(proc) if answer.timed_out else None
    count, must_kill = decide(before, answer.timed_out, process)
    if count != before and not (before is None and count.timeouts == 0):
        write_count(path, count)
    if answer.reason is None:
        return 0
    if must_kill:
        try:
            kill(count.process.pid, SIGKILL)
        except OSError as exc:
            print(f"{answer.reason}; остановить приложение не вышло: {exc!r}", flush=True)
            return 1
        print(KILLED, flush=True)
        tell_container_log(KILLED, proc)
        return 1
    print(answer.reason, flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
