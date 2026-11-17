"""The layer that lets the web answer only under its own names: `localhost`, `127.0.0.1`, `[::1]`, the host of `APP_URL`, the home network's private addresses.

Spec 5.1 of stage 7.2 (KI-12). It compares the request's `Host` (the port is not compared; an IPv6 address comes in brackets)
with the allowed names: `localhost`, `127.0.0.1`, `[::1]`; the host of a valid `APP_URL`; and, when the web is open to the
home network (`WEB_HOST=0.0.0.0`), any private IPv4 address (10.x, 172.16–31.x, 192.168.x). Any other name, or no `Host`,
gets `400` with a plain sentence: no page, no session, no `Set-Cookie`, the security headers on, and nothing behind the
layer runs — so a page that points a foreign name at this PC (DNS rebinding) cannot even touch the login lock. A refused
name is logged once per run (at most 100 names are remembered)."""

import ipaddress
import logging
from collections.abc import Mapping

from starlette.types import ASGIApp, Message, Receive, Scope, Send

REFUSED_TEXT = "Неизвестный адрес сайта."
OWN_NAMES = ("localhost", "127.0.0.1", "::1")
PRIVATE_NETWORKS = tuple(ipaddress.ip_network(net) for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
MAX_REMEMBERED = 100  # refused names kept to log each once
MAX_LOGGED_LENGTH = 100  # a refused name is whatever a stranger sent: only its start goes to the log


def host_name(value: str) -> str | None:
    """The name of a `Host` header without the port, lower case (an IPv6 address stays in its brackets), or None when the
    header is no `name[:port]` at all."""
    text = value.strip().lower()
    if text.startswith("["):
        close = text.find("]")
        if close < 0:
            return None
        name, rest = text[:close + 1], text[close + 1:]
        if rest and not (rest.startswith(":") and rest[1:].isascii() and rest[1:].isdigit()):
            return None
        return name
    name, colon, port = text.partition(":")
    if colon and not (port.isascii() and port.isdigit()):
        return None
    return name or None


def is_private_ipv4(text: str) -> bool:
    """Whether `text` is a private IPv4 address of a home network (10.x, 172.16–31.x, 192.168.x): the one rule, also for
    the hint of Settings (`address_line`)."""
    try:
        address = ipaddress.IPv4Address(text)
    except ValueError:
        return False
    return any(address in network for network in PRIVATE_NETWORKS)


def _canonical(name: str) -> str:
    """One form per address (`0:0:0:0:0:0:0:1` and `::1` are the same), a name as it is; no brackets."""
    inner = name[1:-1] if name.startswith("[") and name.endswith("]") else name
    try:
        return str(ipaddress.ip_address(inner))
    except ValueError:
        return inner


class HostRules:
    """Which names the web answers under. `app_host` is the host of a valid `APP_URL` (as `parse_app_url` gives it: lower
    case, an IPv6 address without brackets); `open_to_network` is `WEB_HOST=0.0.0.0` (`address_line.OPEN_TO_NETWORK`)."""

    def __init__(self, app_host: str | None = None, open_to_network: bool = False) -> None:
        self.open_to_network = open_to_network
        self._own = {_canonical(name) for name in OWN_NAMES}
        if app_host:
            self._own.add(_canonical(app_host))

    def allows(self, name: str) -> bool:
        """Whether a name from `host_name` is one of the app's own."""
        known = _canonical(name)
        if known in self._own:
            return True
        return self.open_to_network and not name.startswith("[") and is_private_ipv4(known)


def _host_header(scope: Scope) -> str | None:
    """The one `Host` header of the request as text; None when there is none or there are several."""
    values = [value for key, value in scope.get("headers", ()) if key == b"host"]
    return values[0].decode("latin-1") if len(values) == 1 else None


class AllowedHosts:
    """The layer of 5.1: a request under a name outside `rules` is answered `400` here and goes no further."""

    def __init__(self, app: ASGIApp, *, rules: HostRules, headers: Mapping[str, str] | None = None) -> None:
        self.app = app
        self.rules = rules
        self._headers = [(key.lower().encode("latin-1"), value.encode("latin-1")) for key, value in (headers or {}).items()]
        self._logged: set[str] = set()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        header = _host_header(scope)
        name = None if header is None else host_name(header)
        if name is not None and self.rules.allows(name):
            await self.app(scope, receive, send)
            return
        self._log_once(name if name is not None else (header or "(no usable Host)"))
        body = REFUSED_TEXT.encode("utf-8")
        start: Message = {
            "type": "http.response.start", "status": 400,
            "headers": [
                (b"content-type", b"text/plain; charset=utf-8"), (b"content-length", str(len(body)).encode("ascii")),
                (b"cache-control", b"no-store"), *self._headers,
            ],
        }
        await send(start)
        await send({"type": "http.response.body", "body": body})

    def _log_once(self, name: str) -> None:
        shown = "".join(char if char.isprintable() else "?" for char in name[:MAX_LOGGED_LENGTH])
        if shown in self._logged or len(self._logged) >= MAX_REMEMBERED:
            return
        self._logged.add(shown)
        logging.warning("web: refused host %s", shown)
