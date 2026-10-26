"""Errors the tracker core raises to its callers (the bot, later the web app). Re-exported by `core`."""


class TitleNotFound(Exception):
    """The source has nothing at the chosen id (for example a series id picked as a movie)."""


class UnknownTitle(Exception):
    """There is no title with this id in the list."""


class UnknownEvent(Exception):
    """There is no «sequel announced» event with this id."""


class UnknownKind(Exception):
    """Sequels are not announced for this kind of title, so there is nothing to follow."""


class UnknownSeason(Exception):
    """The title has no season with this number (specials, season 0, are not seasons)."""
