"""app/healthcheck.py: against a local fake server 200 is healthy, 503, a timeout and a refusal are not, and only an
answer that does not come is a timeout; the count of timeouts in a row ends a hung app on the fourth (KI-6, ADR 0015)."""

import json
import socket
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app import healthcheck
from app.healthcheck import Answer, Count, Process


@pytest.fixture
def serve():
    servers = []

    def start(status: int, delay: float = 0.0):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                time.sleep(delay)
                self.send_response(status)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}/health"

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


@pytest.fixture
def temp(monkeypatch, tmp_path):
    """The temp folder of the count is the test's own."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    return tmp_path


# ---- the check itself ------------------------------------------------------------------------------

def test_200_is_healthy(serve):
    assert healthcheck.check(serve(200)) == Answer(None)


def test_503_is_not_healthy_and_says_why_but_is_no_timeout(serve):
    answer = healthcheck.check(serve(503))

    assert "503" in answer.reason and answer.timed_out is False


def test_a_slow_answer_is_not_healthy_and_is_a_timeout(serve):
    answer = healthcheck.check(serve(200, delay=1.0), timeout=0.2)

    assert "не отвечает" in answer.reason and answer.timed_out is True


def test_a_refused_connection_is_not_healthy_and_is_no_timeout():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    answer = healthcheck.check(f"http://127.0.0.1:{port}/health", timeout=1)

    assert "не отвечает" in answer.reason and answer.timed_out is False


def test_a_connection_closed_without_an_answer_is_no_timeout():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()

    def close_without_answer():
        conn, _ = listener.accept()
        conn.recv(1024)
        conn.close()

    threading.Thread(target=close_without_answer, daemon=True).start()
    try:
        answer = healthcheck.check(f"http://127.0.0.1:{listener.getsockname()[1]}/health", timeout=2)
    finally:
        listener.close()

    assert answer.reason is not None and answer.timed_out is False


def test_the_command_exits_with_0_or_1_and_one_line(monkeypatch, capsys, temp):
    monkeypatch.setattr(healthcheck, "check", lambda: Answer(None))
    assert healthcheck.main(proc=temp / "no-proc") == 0 and capsys.readouterr().out == ""
    assert not (temp / healthcheck.STATE_NAME).exists()  # a healthy check with no count writes nothing

    monkeypatch.setattr(healthcheck, "check", lambda: Answer("/health ответил 503"))
    assert healthcheck.main(proc=temp / "no-proc") == 1 and capsys.readouterr().out == "/health ответил 503\n"


def test_the_check_uses_only_the_standard_library_and_the_port_inside():
    source = open(healthcheck.__file__, encoding="utf-8").read()

    assert "http://127.0.0.1:8080/health" in source and "TIMEOUT_SECONDS = 5" in source
    assert "import app" not in source and "from app" not in source and "httpx" not in source


def test_a_proxy_in_the_environment_does_not_stand_between_the_check_and_the_port(serve, monkeypatch):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        closed = f"http://127.0.0.1:{sock.getsockname()[1]}"  # nobody listens there
    for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(name, closed)
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("no_proxy", "")

    assert healthcheck.check(serve(200)) == Answer(None)


# ---- the decision: timeouts in a row of one process ---------------------------------------------

APP = Process(7, "12345")
NEW_APP = Process(7, "99999")  # the same pid, started later: another process


def test_a_timeout_adds_one_to_the_count_of_the_same_process():
    assert healthcheck.decide(None, True, APP) == (Count(APP, 1), False)
    assert healthcheck.decide(Count(APP, 1), True, APP) == (Count(APP, 2), False)
    assert healthcheck.decide(Count(APP, 2), True, APP) == (Count(APP, 3), False)


def test_the_fourth_timeout_in_a_row_kills():
    assert healthcheck.decide(Count(APP, 3), True, APP) == (Count(APP, 4), True)


def test_a_check_that_is_no_timeout_sets_the_count_to_0():
    # refused, reset, 503 and 200 all reach the decision as «not timed out» (the tests of the check above)
    assert healthcheck.decide(Count(APP, 3), False, None) == (Count(None, 0), False)


def test_another_process_starts_the_count_anew():
    assert healthcheck.decide(Count(APP, 3), True, NEW_APP) == (Count(NEW_APP, 1), False)
    assert healthcheck.decide(Count(APP, 3), True, Process(8, "12345")) == (Count(Process(8, "12345"), 1), False)


def test_without_a_process_the_count_goes_on_but_nothing_is_killed():
    assert healthcheck.decide(Count(None, 3), True, None) == (Count(None, 4), False)


# ---- /proc: the app is the only child of PID 1 ---------------------------------------------------

def stat_line(pid: int, ppid: int, started: str, name: str = "python") -> str:
    """A `/proc/<pid>/stat` line: pid (name) state ppid … starttime is the 22nd field."""
    rest = ["S", str(ppid)] + ["0"] * 17 + [started, "0", "0"]
    return f"{pid} ({name}) " + " ".join(rest)


def fake_proc(folder, *processes):
    proc = folder / "proc"
    for pid, ppid, started, *name in processes:
        (proc / str(pid)).mkdir(parents=True)
        (proc / str(pid) / "stat").write_text(stat_line(pid, ppid, started, *name), encoding="utf-8")
    (proc / "self").mkdir(parents=True, exist_ok=True)  # not a pid: skipped
    return proc


def test_the_app_is_the_child_of_pid_1_with_its_start_time(tmp_path):
    proc = fake_proc(tmp_path, (1, 0, "100", "docker-init"), (7, 1, "12345", "py ) odd (name"), (40, 0, "200"))

    assert healthcheck.app_process(proc) == Process(7, "12345")


def test_no_child_of_pid_1_no_proc_or_several_children_is_no_app(tmp_path):
    assert healthcheck.app_process(fake_proc(tmp_path / "a", (1, 0, "100"))) is None  # the app is PID 1 itself
    assert healthcheck.app_process(tmp_path / "missing") is None  # not Linux
    assert healthcheck.app_process(fake_proc(tmp_path / "b", (1, 0, "1"), (7, 1, "2"), (8, 1, "3"))) is None


# ---- the count in the temp folder and the command -------------------------------------------------

def test_the_count_is_saved_with_its_process_and_a_spoiled_file_is_no_count(temp):
    path = healthcheck.state_file()
    healthcheck.write_count(path, Count(APP, 2))

    assert path == temp / "release-tracker-health.json"
    assert json.loads(path.read_text(encoding="utf-8")) == {"pid": 7, "started": "12345", "timeouts": 2}
    assert healthcheck.read_count(path) == Count(APP, 2)
    path.write_text("{not json", encoding="utf-8")
    assert healthcheck.read_count(path) is None
    path.write_text(json.dumps({"pid": "7", "started": "1", "timeouts": 1}), encoding="utf-8")
    assert healthcheck.read_count(path) is None


def test_four_timeouts_in_a_row_kill_the_app_and_say_so(monkeypatch, capsys, temp):
    proc = fake_proc(temp, (1, 0, "100"), (7, 1, "12345"))
    (proc / "1" / "fd").mkdir()
    (proc / "1" / "fd" / "1").write_text("", encoding="utf-8")  # the container's log
    monkeypatch.setattr(healthcheck, "check", lambda: Answer("/health не отвечает: TimeoutError()", timed_out=True))
    killed = []

    codes = [healthcheck.main(proc=proc, kill=lambda pid, sig: killed.append((pid, sig))) for _ in range(4)]

    assert codes == [1, 1, 1, 1]
    assert killed == [(7, healthcheck.SIGKILL)]
    lines = capsys.readouterr().out.splitlines()
    assert lines[:3] == ["/health не отвечает: TimeoutError()"] * 3
    assert lines[3] == healthcheck.KILLED == "/health не отвечает 4 раза подряд — приложение остановлено для перезапуска"
    assert (proc / "1" / "fd" / "1").read_text(encoding="utf-8") == healthcheck.KILLED + "\n"


def test_a_healthy_check_between_timeouts_starts_the_count_anew(monkeypatch, temp):
    proc = fake_proc(temp, (1, 0, "100"), (7, 1, "12345"))
    answers = [Answer("t", True)] * 3 + [Answer(None)] + [Answer("t", True)] * 3
    killed = []
    for answer in answers:
        monkeypatch.setattr(healthcheck, "check", lambda answer=answer: answer)
        healthcheck.main(proc=proc, kill=lambda pid, sig: killed.append(pid))

    assert killed == []
    assert healthcheck.read_count(healthcheck.state_file()) == Count(APP, 3)


def test_without_a_child_of_pid_1_the_fourth_timeout_kills_nothing_and_says_the_reason(monkeypatch, capsys, temp):
    proc = fake_proc(temp, (1, 0, "100"))
    monkeypatch.setattr(healthcheck, "check", lambda: Answer("/health не отвечает: TimeoutError()", timed_out=True))
    killed = []

    for _ in range(5):
        healthcheck.main(proc=proc, kill=lambda pid, sig: killed.append(pid))

    assert killed == []
    assert capsys.readouterr().out.splitlines() == ["/health не отвечает: TimeoutError()"] * 5
