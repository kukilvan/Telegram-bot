"""app/healthcheck.py against a local fake server: 200 is healthy; 503, a timeout and a refusal are not."""

import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app import healthcheck


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


def test_200_is_healthy(serve):
    assert healthcheck.check(serve(200)) is None


def test_503_is_not_healthy_and_says_why(serve):
    assert "503" in healthcheck.check(serve(503))


def test_a_slow_answer_is_not_healthy(serve):
    assert "не отвечает" in healthcheck.check(serve(200, delay=1.0), timeout=0.2)


def test_a_refused_connection_is_not_healthy():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    assert "не отвечает" in healthcheck.check(f"http://127.0.0.1:{port}/health", timeout=1)


def test_the_command_exits_with_0_or_1_and_one_line(monkeypatch, capsys):
    monkeypatch.setattr(healthcheck, "check", lambda: None)
    assert healthcheck.main() == 0 and capsys.readouterr().out == ""

    monkeypatch.setattr(healthcheck, "check", lambda: "/health ответил 503")
    assert healthcheck.main() == 1 and capsys.readouterr().out == "/health ответил 503\n"


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

    assert healthcheck.check(serve(200)) is None
