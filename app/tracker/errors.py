"""Errors the tracker core raises to its callers (the bot, later the web app). Re-exported by `core`."""

from enum import StrEnum


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


class SourceNotConfigured(Exception):
    """The source of the kind has no keys in the launch settings (`.env`): nothing was asked, the network was not
    touched. Games without the keys of IGDB."""


class UnknownSeason(Exception):
    """The title has no such season (a season of another title, one the source took away, or one that cannot be
    marked because nothing of it is out)."""


class UnknownPlatform(Exception):
    """The game has no such platform: a platform it is not on, a value that is no platform of the tracker, or a title
    that is no game."""


class CannotScore(Exception):
    """Only what is watched gets a score: a film in the archive, a season with its mark, a series with a marked season
    or in the archive. `title_id` is the title; `season_id` the record of the season when the score was a season's."""

    def __init__(self, title_id: int, season_id: int | None = None) -> None:
        super().__init__(title_id if season_id is None else f"{title_id}:{season_id}")
        self.title_id = title_id
        self.season_id = season_id


class SettingsField(StrEnum):
    """The fields of the settings form that a refusal can point at (the values are what the page highlights by)."""

    TIMEZONE = "timezone"
    WORKDAYS = "workdays"
    SUMMARY_AT = "summary_at"
    QUIET = "quiet"  # both fields of the quiet hours
    PART_GAP_WEEKS = "part_gap_weeks"
    MY_PLATFORMS = "my_platforms"
    STORE_COUNTRY = "store_country"


class SettingsRefused(Exception):
    """The settings form was refused and nothing was stored. `field` names the setting to point at; `text` is the
    phrase for the owner."""

    def __init__(self, field: SettingsField, text: str) -> None:
        super().__init__(text)
        self.field = field
        self.text = text
