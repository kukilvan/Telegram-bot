"""Posters for the browser: the sites the page may load pictures from (`img-src`). The address of a picture is made by
`app.tracker.posters` (shared with the bot card); the browser takes the pictures straight from the sites."""

import ipaddress
import re
from urllib.parse import urlsplit

from app.tracker.core import IGDB_IMAGE_SITE, TMDB_IMAGE_SITE

_HOST = re.compile(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?")  # what may stand in a header: no «;», spaces or quotes


def image_sources(shikimori_base_url: str) -> tuple[str, ...]:
    """The sites pictures may be loaded from, for `img-src`: TMDb, IGDB, and Shikimori with its subdomains (the address
    is the start of SHIKIMORI_BASE_URL). A base address that is not an `https` site gives only TMDb and IGDB."""
    return (TMDB_IMAGE_SITE, IGDB_IMAGE_SITE, *_site_with_subdomains(shikimori_base_url))


def _site_with_subdomains(address: str) -> tuple[str, ...]:
    try:
        parts = urlsplit(address.strip())
        host, port = (parts.hostname or "").lower(), parts.port
    except ValueError:
        return ()
    if parts.scheme != "https" or not _HOST.fullmatch(host):
        return ()
    site = f"https://{host}" + (f":{port}" if port else "")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return (site, f"https://*.{host}" + (f":{port}" if port else ""))
    return (site,)  # an address of numbers has no subdomains
