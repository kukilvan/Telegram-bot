"""Poster addresses (pure): the address of a picture from the value a title stores, and the sizes of the places a poster
is shown (the web page and the bot card). The picture itself is never downloaded here: the browser or Telegram takes it
straight from the site. An address of Shikimori is shown on the site of SHIKIMORI_BASE_URL now, not on the one it was
stored under (the site moves: `shikimori.one` became `shikimori.io`)."""

import ipaddress
import re
from typing import NamedTuple
from urllib.parse import urlsplit, urlunsplit

_HOST = re.compile(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?")  # what may stand in a header: no «;», spaces or quotes

TMDB_IMAGE_SITE = "https://image.tmdb.org"
_TMDB_PATH = f"{TMDB_IMAGE_SITE}/t/p/"
IGDB_IMAGE_SITE = "https://images.igdb.com"
# a cover of a game is stored as a whole address of one size: the size is the part after this, up to the next «/»
_IGDB_PATH = f"{IGDB_IMAGE_SITE}/igdb/image/upload/"


class PosterSize(NamedTuple):
    name: str  # the size TMDb is asked for
    igdb: str  # the size IGDB is asked for
    width: int  # of the picture itself: the browser reserves the room before it loads
    height: int
    css: str  # the class of the frame


# a suggestion and a row of the list; the cover of IGDB is 264 points wide in the room of 92, sharp on an iPhone too
LIST_SIZE = PosterSize("w92", "t_cover_big", 92, 138, "poster-small")
CARD_SIZE = PosterSize("w342", "t_cover_big_2x", 342, 513, "poster-large")  # a card


def shikimori_site(address: str) -> str | None:
    """The site of an address as `https://host[:port]`, or None: only an `https` address with a host that may stand in a
    header counts. It is the site of SHIKIMORI_BASE_URL — where its posters are shown from (here) and where the page
    may load them from (`img-src`, `app.web.posters`)."""
    try:
        parts = urlsplit(address.strip())
        host, port = (parts.hostname or "").lower(), parts.port
    except ValueError:
        return None
    if parts.scheme != "https" or not _HOST.fullmatch(host):
        return None
    return f"https://{host}" + (f":{port}" if port else "")


def poster_url(stored: str | None, size: PosterSize, site: str | None = None) -> str | None:
    """The address of the picture, or None (no poster: the page shows the kind's icon). TMDb stores a file name
    («/abc.jpg»); Shikimori and IGDB the whole address, of one size: IGDB is asked for the size of the place, Shikimori
    has one size for every place; anything else is no poster. `site` is the site of Shikimori now (`shikimori_site`):
    a stored address of Shikimori moves to it; without one the address stays as stored."""
    value = (stored or "").strip()
    if value.startswith("/"):
        return f"{_TMDB_PATH}{size.name}{value}"
    if value.startswith(_IGDB_PATH) and "/" in value[len(_IGDB_PATH):]:
        return f"{_IGDB_PATH}{size.igdb}/{value[len(_IGDB_PATH):].split('/', 1)[1]}"
    if value.startswith("https://"):
        return _on_site(value, site)
    return None


def _on_site(address: str, site: str | None) -> str:
    """An address of `shikimori.<zone>` or of its subdomain (the label before the last one is `shikimori`) with that part
    of the host replaced by the host of `site`; the scheme and the port are the site's, the path and the query stay.
    Any other address, or no site, leaves it as it is."""
    if not site:
        return address
    try:
        parts, new = urlsplit(address), urlsplit(site)
        labels = (parts.hostname or "").split(".")
        new_host = new.hostname or ""
    except ValueError:
        return address
    if len(labels) < 2 or labels[-2] != "shikimori" or not new_host:
        return address
    prefix = labels[:-2]
    try:
        ipaddress.ip_address(new_host)
    except ValueError:
        pass
    else:
        if prefix:  # an address of numbers has no subdomains
            return address
    host = ".".join([*prefix, new_host])
    return urlunsplit((new.scheme, f"{host}:{new.port}" if new.port else host, parts.path, parts.query, parts.fragment))
