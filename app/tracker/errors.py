"""Errors the tracker core raises to its callers (the bot, later the web app). Re-exported by `core`."""


class TitleNotFound(Exception):
    """The source has nothing at the chosen id (for example a series id picked as a movie)."""


class UnknownTitle(Exception):
    """There is no title with this id in the list."""


class UnknownEvent(Exception):
    """There is no «sequel announced» event with this id."""


class UnknownKind(Exception):
    """Sequels are not announced for this kind of title, so there is nothing to follow."""


class SourceFailed(Exception):
    """The source of the kind did not answer, answered with an error or «too often» while the owner searched or added
    a title. Its own error is the cause (`__cause__`): the log tells it, the owner only learns which source failed."""


class UnknownSeason(Exception):
    """The title has no such season (a season of another title, one the source took away, or one that cannot be
    marked because nothing of it is out)."""


class CannotScore(Exception):
    """Only what is watched gets a score: a film in the archive, a season with its mark, a series with a marked season
    or in the archive."""
