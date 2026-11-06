"""Poster addresses (pure): the address of a picture from the value a title stores, and the sizes of the places a poster
is shown (the web page and the bot card). The picture itself is never downloaded here: the browser or Telegram takes it
straight from the site."""

from typing import NamedTuple

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


def poster_url(stored: str | None, size: PosterSize) -> str | None:
    """The address of the picture, or None (no poster: the page shows the kind's icon). TMDb stores a file name
    («/abc.jpg»); Shikimori and IGDB the whole address, of one size: IGDB is asked for the size of the place, Shikimori
    has one size for every place; anything else is no poster."""
    value = (stored or "").strip()
    if value.startswith("/"):
        return f"{_TMDB_PATH}{size.name}{value}"
    if value.startswith(_IGDB_PATH) and "/" in value[len(_IGDB_PATH):]:
        return f"{_IGDB_PATH}{size.igdb}/{value[len(_IGDB_PATH):].split('/', 1)[1]}"
    if value.startswith("https://"):
        return value
    return None
