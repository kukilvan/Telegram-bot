"""The reading of `TRUSTED_PROXIES` and the two things the web takes from a proxy: the public client address and `https`.

Spec 5.2 and 5.3 of stage 7.2. `TRUSTED_PROXIES` lists addresses or networks (`172.18.0.0/16`) from which the proxy headers
are believed; empty — they are ignored. An item that is no address or network, `*` included (trusting everyone is never
what the owner wants), is skipped and reported. uvicorn does the work (`app/web/server.py`): for a connection from a
trusted address it puts the client address of `X-Forwarded-For` and the scheme of `X-Forwarded-Proto` into the request's
scope, and this module reads them from there. The address is shown only when it is public: at home every request comes
from the Docker network, which says nothing."""

import ipaddress
from dataclasses import dataclass

from starlette.types import Scope


@dataclass(frozen=True)
class TrustedProxies:
    """`items` in the form uvicorn takes (an address or a network, one form each, no repeats); `skipped` the items
    as written that were neither."""

    items: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()


def parse_trusted_proxies(raw: str) -> TrustedProxies:
    """`TRUSTED_PROXIES` read: comma-separated addresses and networks, blank items ignored, the rest skipped. A network
    written with host bits (`172.18.0.5/16`) is read as its network."""
    items: list[str] = []
    skipped: list[str] = []
    for part in raw.split(","):
        text = part.strip()
        if not text:
            continue
        try:
            item = str(ipaddress.ip_network(text, strict=False)) if "/" in text else str(ipaddress.ip_address(text))
        except ValueError:
            skipped.append(text)
            continue
        if item not in items:
            items.append(item)
    return TrustedProxies(tuple(items), tuple(skipped))


def public_address(host: str | None) -> str | None:
    """The client address when it is a public one, otherwise None: private, loopback, link-local and other addresses of
    the owner's own networks say nothing about who came."""
    if not host:
        return None
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return str(address) if address.is_global else None


def is_https(scope: Scope) -> bool:
    """Whether the request came over `https` (behind a trusted proxy that said so): the session cookie then gets `Secure`."""
    return scope.get("scheme") == "https"
