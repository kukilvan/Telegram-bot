"""The names the web answers under (ticket 04 of stage 7.2, spec 5.1, KI-12): each allowed name with and without a port, the
private addresses only with `WEB_HOST=0.0.0.0`, the address of `APP_URL`, a stranger's name or no `Host` at all refused with
`400` and the sentence (no cookie, no page, the lock untouched, the security headers on), the health check, the log line
once per name."""

import asyncio
import logging

import pytest
from fastapi.testclient import TestClient

from app.config import parse_app_url
from app.web import create_web_app
from app.web.hosts import MAX_REMEMBERED, REFUSED_TEXT, HostRules, host_name

PASSWORD = "correct horse battery"


def make_app(tmp_path, *, app_url="", web_host=""):
    return create_web_app(
        health=lambda: (200, {"status": "ok"}), password=PASSWORD, secret_file=tmp_path / "web_secret",
        login_file=tmp_path / "web_login.json", app_url=parse_app_url(app_url), web_host=web_host,
    )


def get(app, host, path="/login", method="GET"):
    return TestClient(app, follow_redirects=False).request(method, path, headers={"Host": host})


def refused(response):
    return response.status_code == 400 and response.text == REFUSED_TEXT


# ---- the allowed names -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "localhost", "127.0.0.1", "[::1]", "LocalHost", "[0:0:0:0:0:0:0:1]",
])
@pytest.mark.parametrize("port", ["", ":8080", ":80"])
def test_each_own_name_passes_with_and_without_a_port(tmp_path, name, port):
    assert get(make_app(tmp_path), name + port).status_code == 200


def test_the_host_of_app_url_passes_with_and_without_its_port(tmp_path):
    app = make_app(tmp_path, app_url="https://Tracker.Example.com")

    assert get(app, "tracker.example.com").status_code == 200
    assert get(app, "tracker.example.com:8443").status_code == 200
    assert get(app, "TRACKER.example.com").status_code == 200
    assert refused(get(app, "other.example.com"))
    assert refused(get(app, "example.com"))
    assert refused(get(app, "tracker.example.com.evil.example"))


def test_an_address_of_app_url_passes_whatever_it_is(tmp_path):
    app = make_app(tmp_path, app_url="http://203.0.113.9:8080")  # not private: the owner named it

    assert get(app, "203.0.113.9:8080").status_code == 200
    assert refused(get(app, "203.0.113.10:8080"))


def test_an_ipv6_address_of_app_url_passes_in_brackets(tmp_path):
    app = make_app(tmp_path, app_url="http://[2001:db8::5]:8080")

    assert get(app, "[2001:db8::5]:8080").status_code == 200
    assert get(app, "[2001:0db8:0:0:0:0:0:5]").status_code == 200
    assert refused(get(app, "[2001:db8::6]"))


@pytest.mark.parametrize("address", ["10.0.0.7", "10.255.255.255", "172.16.0.5", "172.31.255.1", "192.168.1.124"])
def test_a_private_address_passes_only_when_the_web_is_open_to_the_network(tmp_path, address):
    assert refused(get(make_app(tmp_path), f"{address}:8080"))
    assert refused(get(make_app(tmp_path, web_host="127.0.0.1"), f"{address}:8080"))
    assert get(make_app(tmp_path, web_host="0.0.0.0"), f"{address}:8080").status_code == 200
    assert get(make_app(tmp_path, web_host=" 0.0.0.0 "), address).status_code == 200


@pytest.mark.parametrize("name", [
    "8.8.8.8", "172.15.255.255", "172.32.0.1", "192.169.0.1", "11.0.0.1", "100.64.0.1", "169.254.1.1", "127.0.0.2", "0.0.0.0",
    "[fe80::1]", "[fd00::1]", "192.168.1.124.evil.example", "010.0.0.1",
])
def test_other_addresses_are_refused_even_when_the_web_is_open_to_the_network(tmp_path, name):
    assert refused(get(make_app(tmp_path, web_host="0.0.0.0"), name))


# ---- a stranger's name ----------------------------------------------------------------------------------------------------

def test_a_foreign_name_gets_400_with_the_sentence_and_nothing_else(tmp_path):
    response = get(make_app(tmp_path), "evil.example")

    assert refused(response)
    assert response.headers["content-type"].startswith("text/plain")
    assert "set-cookie" not in response.headers
    assert "default-src 'self'" in response.headers["content-security-policy"]  # the security headers are on
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", ["/", "/login", "/feed", "/health", "/static/style.css", "/nowhere"])
def test_no_address_answers_under_a_foreign_name(tmp_path, path):
    assert refused(get(make_app(tmp_path), "evil.example", path))


def test_a_post_under_a_foreign_name_is_refused_without_a_session(tmp_path):
    client = TestClient(make_app(tmp_path), follow_redirects=False)

    response = client.post("/login", data={"password": PASSWORD}, headers={"Host": "evil.example"})

    assert refused(response) and "set-cookie" not in response.headers


def test_a_head_request_under_a_foreign_name_has_the_code_and_no_body(tmp_path):
    response = get(make_app(tmp_path), "evil.example", method="HEAD")

    assert response.status_code == 400 and response.content == b""


def test_a_foreign_name_cannot_touch_the_lock_count(tmp_path):
    client = TestClient(make_app(tmp_path), follow_redirects=False)
    for _ in range(8):
        assert refused(client.post("/login", data={"password": "wrong password"}, headers={"Host": "evil.example"}))

    # the owner's own name: not locked, five tries still to go
    page = client.post("/login", data={"password": "wrong password"})
    assert page.status_code == 401 and "осталось попыток: 4" in page.text
    assert client.post("/login", data={"password": PASSWORD}).status_code == 303


@pytest.mark.parametrize("header", ["localhost:abc", "localhost:", "[::1", "[::1]x", "[::1]:", "", " ", "local host", "a:b:c"])
def test_a_header_that_is_no_name_is_refused(tmp_path, header):
    assert refused(get(make_app(tmp_path), header))


def serve(app, headers):
    """One request with exactly these raw headers, answered the way the server would; (status, headers, body)."""
    scope = {"type": "http", "method": "GET", "path": "/login", "query_string": b"", "headers": headers, "scheme": "http",
             "server": ("localhost", 8080), "client": ("127.0.0.1", 50000), "http_version": "1.1", "root_path": ""}
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    start = sent[0]
    return start["status"], dict(start["headers"]), b"".join(m.get("body", b"") for m in sent[1:])


def test_no_host_header_is_refused(tmp_path):
    status, headers, body = serve(make_app(tmp_path), [])

    assert (status, body) == (400, REFUSED_TEXT.encode("utf-8")) and b"set-cookie" not in headers


def test_two_host_headers_are_refused(tmp_path):
    status, _, body = serve(make_app(tmp_path), [(b"host", b"localhost"), (b"host", b"localhost")])

    assert (status, body) == (400, REFUSED_TEXT.encode("utf-8"))


def test_one_host_header_in_bytes_passes(tmp_path):
    assert serve(make_app(tmp_path), [(b"host", b"localhost:8080")])[0] == 200


def test_the_origin_check_stays_and_compares_with_an_allowed_host(tmp_path):
    client = TestClient(make_app(tmp_path), follow_redirects=False)

    foreign = client.post("/login", data={"password": PASSWORD}, headers={"Origin": "https://evil.example"})
    own = client.post("/login", data={"password": PASSWORD}, headers={"Origin": "http://localhost:8080", "Host": "localhost:8080"})

    assert foreign.status_code == 403 and own.status_code == 303


# ---- the health check -----------------------------------------------------------------------------------------------------

def test_the_docker_health_check_by_127_0_0_1_passes(tmp_path):
    response = get(make_app(tmp_path), "127.0.0.1:8080", "/health")

    assert response.status_code == 200 and response.json() == {"status": "ok"}


# ---- the log --------------------------------------------------------------------------------------------------------------

def test_a_refused_name_is_logged_once_per_name(tmp_path, caplog):
    app = make_app(tmp_path)

    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            get(app, "evil.example")
        get(app, "EVIL.example:9000")  # the same name: the case and the port do not make a new one
        get(app, "other.example")

    assert [r.getMessage() for r in caplog.records] == ["web: refused host evil.example", "web: refused host other.example"]


def test_only_the_first_hundred_names_are_remembered_and_logged(tmp_path, caplog):
    app = make_app(tmp_path)

    with caplog.at_level(logging.WARNING):
        for number in range(MAX_REMEMBERED + 5):
            get(app, f"evil{number}.example")

    assert len(caplog.records) == MAX_REMEMBERED


def test_the_log_gets_a_short_clean_name(tmp_path, caplog):
    app = make_app(tmp_path)

    with caplog.at_level(logging.WARNING):
        serve(app, [(b"host", b"x" * 300 + b"\x01")])
        serve(app, [])

    assert caplog.records[0].getMessage() == "web: refused host " + "x" * 100
    assert caplog.records[1].getMessage() == "web: refused host (no usable Host)"


def test_an_allowed_name_logs_nothing(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        get(make_app(tmp_path), "localhost:8080")

    assert caplog.records == []


# ---- the pure parts -------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("header, name", [
    ("localhost", "localhost"), ("LOCALHOST:8080", "localhost"), ("127.0.0.1:1", "127.0.0.1"), ("[::1]", "[::1]"),
    ("[::1]:8080", "[::1]"), (" Example.COM ", "example.com"),
])
def test_host_name_drops_the_port_and_the_case(header, name):
    assert host_name(header) == name


def test_the_rules_without_anything_extra_know_only_the_own_names():
    rules = HostRules()

    assert [rules.allows(name) for name in ("localhost", "127.0.0.1", "[::1]", "192.168.1.5", "example.com")] == [
        True, True, True, False, False,
    ]
