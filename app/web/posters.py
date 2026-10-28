"""Posters for the browser: the address of a picture from the value the title stores, and the sites the page may load
pictures from. The browser takes the pictures straight from the sites (the web app downloads nothing)."""

import ipaddress
import re
from typing import NamedTuple
from urllib.parse import urlsplit

TMDB_IMAGE_SITE = "https://image.tmdb.org"
_TMDB_PATH = f"{TMDB_IMAGE_SITE}/t/p/"
_HOST = re.compile(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?")  # what may stand in a header: no «;», spaces or quotes


class PosterSize(NamedTuple):
    name: str  # the size TMDb is asked for
    width: int  # of the picture itself: the browser reserves the room before it loads
    height: int
    css: str  # the class of the frame


LIST_SIZE = PosterSize("w92", 92, 138, "poster-small")  # a suggestion and a row of the list
CARD_SIZE = PosterSize("w342", 342, 513, "poster-large")  # a card


def poster_url(stored: str | None, size: PosterSize) -> str | None:
    """The address of the picture, or None (no poster: the page shows the kind's icon). TMDb stores a file name
    («/abc.jpg»), Shikimori the whole address, of one size for every place; anything else is no poster."""
    value = (stored or "").strip()
    if value.startswith("/"):
        return f"{_TMDB_PATH}{size.name}{value}"
    if value.startswith("https://"):
        return value
    return None


def image_sources(shikimori_base_url: str) -> tuple[str, ...]:
    """The sites pictures may be loaded from, for `img-src`: TMDb, and Shikimori with its subdomains (the address is
    the start of SHIKIMORI_BASE_URL). A base address that is not an `https` site gives only TMDb."""
    return (TMDB_IMAGE_SITE, *_site_with_subdomains(shikimori_base_url))


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
