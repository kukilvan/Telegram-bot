"""The proxy and `https` (ticket 04 of stage 7.2, spec 5.2–5.3): the reading of `TRUSTED_PROXIES`, the server built with
the proxy headers on (the list) or off (empty), the cookie with `Secure` under `https` only, the client address that
reaches the last login and the log only when it is public, and `X-Forwarded-For` ignored from an untrusted address."""

import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.web import create_web_app, web_server
from app.web.proxy import TrustedProxies, is_https, parse_trusted_proxies, public_address

PASSWORD = "correct horse battery"
PROXY = ("172.18.0.2", 50000)  # the container of the tunnel on the Docker network
FORWARDED = {"X-Forwarded-For": "8.8.8.8", "X-Forwarded-Proto": "https"}


def make_app(tmp_path):
    return create_web_app(
        health=lambda: (200, {"status": "ok"}), password=PASSWORD, secret_file=tmp_path / "web_secret",
        login_file=tmp_path / "web_login.json",
    )


def served(tmp_path, trusted):
    """The app as the server would hand it to the requests, with its proxy layer (`trusted` as `TRUSTED_PROXIES` gave it)."""
    config = web_server(make_app(tmp_path), host="127.0.0.1", port=0, stop_grace=5, trusted_proxies=trusted).config
    config.load()
    return config


def stored(tmp_path):
    return json.loads((tmp_path / "web_login.json").read_text(encoding="utf-8"))


def login(client, **headers):
    response = client.post("/login", data={"password": PASSWORD}, headers=headers)
    assert response.status_code == 303, response.text
    return response


def cookie_of(response):
    return response.headers["set-cookie"].lower()


# ---- TRUSTED_PROXIES ----------------------------------------------------------------------------------------------------

def test_an_address_and_a_network_are_read():
    assert parse_trusted_proxies("172.18.0.0/16, 10.0.0.5, ::1") == TrustedProxies(("172.18.0.0/16", "10.0.0.5", "::1"), ())


@pytest.mark.parametrize("raw", ["", "  ", ",", " , ,"])
def test_nothing_set_is_nothing_trusted(raw):
    assert parse_trusted_proxies(raw) == TrustedProxies()


def test_junk_and_the_star_are_skipped_and_named():
    result = parse_trusted_proxies("*, 172.18.0.0/16, cloudflare, 10.0.0.300, 10.0.0.0/33, 0.0.0.0/0x")

    assert result.items == ("172.18.0.0/16",)
    assert result.skipped == ("*", "cloudflare", "10.0.0.300", "10.0.0.0/33", "0.0.0.0/0x")


def test_a_network_with_host_bits_is_read_as_its_network_and_a_repeat_is_dropped():
    assert parse_trusted_proxies("172.18.0.5/16, 172.18.0.0/16, 10.0.0.5, 10.0.0.5").items == ("172.18.0.0/16", "10.0.0.5")


def test_the_setting_is_read_from_the_environment_and_stripped(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TEST")
    monkeypatch.setenv("TMDB_API_KEY", "key")
    monkeypatch.setenv("TRUSTED_PROXIES", "  172.18.0.0/16  ")

    assert Settings(_env_file=None).trusted_proxies == "172.18.0.0/16"
    monkeypatch.delenv("TRUSTED_PROXIES")
    assert Settings(_env_file=None).trusted_proxies == ""


# ---- the server ---------------------------------------------------------------------------------------------------------

def test_the_server_is_built_with_the_proxy_headers_and_the_list(tmp_path):
    config = web_server(
        make_app(tmp_path), host="127.0.0.1", port=0, stop_grace=5, trusted_proxies=["172.18.0.0/16", "10.0.0.5"]
    ).config

    assert config.proxy_headers is True and config.forwarded_allow_ips == ["172.18.0.0/16", "10.0.0.5"]


def test_without_a_list_the_proxy_headers_are_off(tmp_path):
    config = web_server(make_app(tmp_path), host="127.0.0.1", port=0, stop_grace=5).config

    assert config.proxy_headers is False


# ---- Secure -------------------------------------------------------------------------------------------------------------

def test_the_cookie_is_secure_under_https_and_not_under_http(tmp_path):
    app = make_app(tmp_path)

    over_https = login(TestClient(app, base_url="https://localhost", follow_redirects=False))
    over_http = login(TestClient(app, base_url="http://localhost", follow_redirects=False))

    assert "; secure" in cookie_of(over_https) and "httponly" in cookie_of(over_https)
    assert "secure" not in cookie_of(over_http) and "httponly" in cookie_of(over_http)


def test_the_cookie_that_ends_a_sign_in_is_secure_under_https_too(tmp_path):
    client = TestClient(make_app(tmp_path), base_url="https://localhost", follow_redirects=False)
    login(client)

    response = client.post("/logout")

    assert "; secure" in cookie_of(response) and "1970" in cookie_of(response)


@pytest.mark.parametrize("scope, secure", [({"scheme": "https"}, True), ({"scheme": "http"}, False), ({}, False)])
def test_is_https_reads_the_scheme_of_the_scope(scope, secure):
    assert is_https(scope) is secure


def test_a_trusted_proxy_saying_https_gets_a_secure_cookie(tmp_path):
    client = TestClient(served(tmp_path, ["172.18.0.0/16"]).loaded_app, client=PROXY, follow_redirects=False)

    assert "; secure" in cookie_of(login(client, **FORWARDED))


def test_plain_http_from_a_trusted_proxy_has_no_secure_cookie(tmp_path):
    client = TestClient(served(tmp_path, ["172.18.0.0/16"]).loaded_app, client=PROXY, follow_redirects=False)

    assert "secure" not in cookie_of(login(client, **{"X-Forwarded-For": "8.8.8.8", "X-Forwarded-Proto": "http"}))


def test_https_said_by_an_untrusted_address_is_not_believed(tmp_path):
    client = TestClient(served(tmp_path, ["172.18.0.0/16"]).loaded_app, client=("192.168.1.50", 50000), follow_redirects=False)

    assert "secure" not in cookie_of(login(client, **FORWARDED))


def test_with_the_setting_empty_https_said_by_anyone_is_not_believed(tmp_path):
    client = TestClient(served(tmp_path, []).loaded_app, client=PROXY, follow_redirects=False)

    assert "secure" not in cookie_of(login(client, **FORWARDED))


# ---- the client address ---------------------------------------------------------------------------------------------------

def test_a_public_address_from_a_trusted_proxy_reaches_the_last_login_and_the_log(tmp_path, caplog):
    client = TestClient(served(tmp_path, ["172.18.0.0/16"]).loaded_app, client=PROXY, follow_redirects=False)

    with caplog.at_level(logging.INFO):
        client.post("/login", data={"password": "not the password"}, headers=FORWARDED)
        login(client, **FORWARDED)

    assert stored(tmp_path)["last_login"]["address"] == "8.8.8.8"
    assert "web login: wrong password (1 in a row) from 8.8.8.8" in caplog.text
    assert "web login: ok from 8.8.8.8" in caplog.text


def test_a_private_address_reaches_neither_the_file_nor_the_log(tmp_path, caplog):
    client = TestClient(served(tmp_path, ["172.18.0.0/16"]).loaded_app, client=PROXY, follow_redirects=False)

    with caplog.at_level(logging.INFO):
        login(client, **{"X-Forwarded-For": "192.168.1.77", "X-Forwarded-Proto": "https"})

    assert stored(tmp_path)["last_login"]["address"] is None
    assert "192.168.1.77" not in caplog.text and "web login: ok" in caplog.text and " from " not in caplog.text


def test_at_home_the_docker_address_is_not_shown(tmp_path, caplog):
    client = TestClient(served(tmp_path, []).loaded_app, client=("172.18.0.1", 50000), follow_redirects=False)

    with caplog.at_level(logging.INFO):
        login(client)

    assert stored(tmp_path)["last_login"]["address"] is None and " from " not in caplog.text


def test_x_forwarded_for_from_an_untrusted_address_is_ignored(tmp_path):
    client = TestClient(served(tmp_path, ["172.18.0.0/16"]).loaded_app, client=("93.184.216.34", 50000), follow_redirects=False)

    login(client, **{"X-Forwarded-For": "8.8.8.8"})

    assert stored(tmp_path)["last_login"]["address"] == "93.184.216.34"  # the connection's own, not the forged one


def test_x_forwarded_for_is_ignored_when_no_proxy_is_trusted(tmp_path):
    client = TestClient(served(tmp_path, []).loaded_app, client=("93.184.216.34", 50000), follow_redirects=False)

    login(client, **{"X-Forwarded-For": "8.8.8.8"})

    assert stored(tmp_path)["last_login"]["address"] == "93.184.216.34"


def test_cf_connecting_ip_is_not_read(tmp_path):
    client = TestClient(served(tmp_path, ["172.18.0.0/16"]).loaded_app, client=PROXY, follow_redirects=False)

    login(client, **{"Cf-Connecting-Ip": "8.8.8.8", "X-Forwarded-Proto": "https"})

    assert stored(tmp_path)["last_login"]["address"] is None  # only the proxy's own (private) address was there


@pytest.mark.parametrize("host, shown", [
    ("8.8.8.8", "8.8.8.8"), ("93.184.216.34", "93.184.216.34"), ("2606:4700::1111", "2606:4700::1111"),
    ("::ffff:8.8.8.8", "8.8.8.8"),
    ("10.0.0.5", None), ("172.18.0.1", None), ("192.168.1.1", None), ("127.0.0.1", None), ("::1", None),
    ("169.254.1.1", None), ("fe80::1", None), ("fd00::5", None), ("100.64.0.1", None), ("::ffff:10.0.0.1", None),
    ("testclient", None), ("", None), (None, None),
])
def test_only_a_public_address_is_shown(host, shown):
    assert public_address(host) == shown
