"""Tables of the tracker database: titles, seasons, episodes, source snapshots, events, the delivery queue, settings,
game platforms, the price history and the inbox items. Timestamps are naive UTC and are always set by the core at insert time."""

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class TitleKind(StrEnum):
    """The kind of a title. The values are what the database already holds; what a kind means for the owner
    (label, icon, source) is in the table of `app.tracker.kinds`."""

    MOVIE = "movie"
    SERIES = "series"
    ANIME = "anime"
    GAME = "game"


class TitleStatus(StrEnum):
    WANT = "want"  # «Хочу»
    IN_PROGRESS = "in_progress"  # «В процессе»: a series or anime is airing and the owner has watched part of what is out
    WAITING = "waiting"  # «Жду»: everything released is watched, a season is expected
    TO_FINISH = "to_finish"  # «Досмотреть»: the series is closed but not every season is watched
    WATCHED = "watched"  # «Просмотрено»: the title is in the archive
    COMPLETED = "completed"  # «Пройдено»: a game the owner finished; it is in the archive
    DROPPED = "dropped"  # «Бросил»: the owner gave the title up; it is in the archive


# the final statuses: a title with one of them is in the archive, its own release is no longer followed
ARCHIVE_STATUSES = frozenset({TitleStatus.WATCHED, TitleStatus.COMPLETED, TitleStatus.DROPPED})


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    DELIVERED = "delivered"


def _stored_as_text(enum: type[StrEnum], length: int = 16) -> Enum:
    """A column that holds the enum's values as plain text (so the database stays as it was) and hands back members."""
    return Enum(
        enum,
        native_enum=False,
        length=length,
        values_callable=lambda members: [member.value for member in members],
        validate_strings=True,
    )


class TrackerBase(DeclarativeBase):
    """Base of the tracker schema; kept apart from the legacy `Base` so the two databases never mix."""


class Title(TrackerBase):
    """One entry of the owner's list (a movie for now; series, anime and games come with later tickets)."""

    __tablename__ = "titles"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[TitleKind] = mapped_column(_stored_as_text(TitleKind), index=True)
    name: Mapped[str] = mapped_column(String(500))  # Russian name when the source knows it
    original_name: Mapped[str] = mapped_column(String(500))
    year: Mapped[int | None] = mapped_column(Integer)
    genres: Mapped[list] = mapped_column(JSON)
    poster_path: Mapped[str | None] = mapped_column(String(255))
    overview: Mapped[str | None] = mapped_column(Text)
    status: Mapped[TitleStatus] = mapped_column(_stored_as_text(TitleStatus), index=True)
    tracking_enabled: Mapped[bool] = mapped_column(Boolean)
    added_at: Mapped[datetime] = mapped_column(DateTime)
    status_changed_at: Mapped[datetime] = mapped_column(DateTime)
    failure_notified_at: Mapped[datetime | None] = mapped_column(DateTime)  # last «could not check» notice; None: never
    # the last «Вернуть в список»; None: never brought back. A check of the own source older than this is the baseline
    restored_at: Mapped[datetime | None] = mapped_column(DateTime)
    # the owner's score in thirds of a point (`scores`): a film's only one, a series' own one over the average of its
    # seasons; None: not set. It stays when the status changes, even while it is not shown
    score: Mapped[int | None] = mapped_column(Integer)


class ExternalId(TrackerBase):
    """A title's id in an outside source. The source name carries the kind ("tmdb_movie"), because TMDb
    numbers movies and series in one id space."""

    __tablename__ = "external_ids"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_external_ids_source_id"),
        UniqueConstraint("title_id", "source", "role", name="uq_external_ids_title_source_role"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title_id: Mapped[int] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16))  # primary | ...


class SeasonRecord(TrackerBase):
    """A season of a series (number 1 and up; specials are not seasons) and the owner's mark on it."""

    __tablename__ = "seasons"
    __table_args__ = (UniqueConstraint("title_id", "number", name="uq_seasons_title_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    title_id: Mapped[int] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(255))
    episode_count: Mapped[int | None] = mapped_column(Integer)  # announced by the source; None: unknown
    watched: Mapped[bool] = mapped_column(Boolean)  # the status of a season (announced / airing / released) is not stored: it follows the clock
    score: Mapped[int | None] = mapped_column(Integer)  # in thirds of a point; None: not set. Kept, unseen, without the mark


class EpisodeRecord(TrackerBase):
    __tablename__ = "episodes"
    __table_args__ = (UniqueConstraint("season_id", "number", name="uq_episodes_season_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    air_at: Mapped[datetime | None] = mapped_column(DateTime)  # None: no date yet


class PartRecord(TrackerBase):
    """A part of an anime season: one entry of the source with its own ids. A season of one entry has one part.

    `first_episode` counts through the whole season, so the episodes of all parts live in one numbering. An id
    appears once per title: the same entry is never stored for two parts."""

    __tablename__ = "season_parts"
    __table_args__ = (
        UniqueConstraint("season_id", "number", name="uq_season_parts_season_number"),
        UniqueConstraint("title_id", "shikimori_id", name="uq_season_parts_title_shikimori"),
        UniqueConstraint("title_id", "mal_id", name="uq_season_parts_title_mal"),
        UniqueConstraint("title_id", "anilist_id", name="uq_season_parts_title_anilist"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title_id: Mapped[int] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"), index=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)  # 1 and up within the season
    first_episode: Mapped[int] = mapped_column(Integer)
    episode_count: Mapped[int | None] = mapped_column(Integer)  # announced by the source; None: unknown
    shikimori_id: Mapped[str] = mapped_column(String(32))
    mal_id: Mapped[str | None] = mapped_column(String(32))
    anilist_id: Mapped[str | None] = mapped_column(String(32))  # None: AniList was not asked or does not know the entry


class MovieRecord(TrackerBase):
    """A movie of an anime franchise. It is not a season: the owner is told about it, not asked to mark it."""

    __tablename__ = "franchise_movies"
    __table_args__ = (
        UniqueConstraint("title_id", "shikimori_id", name="uq_franchise_movies_title_shikimori"),
        UniqueConstraint("title_id", "mal_id", name="uq_franchise_movies_title_mal"),
        UniqueConstraint("title_id", "anilist_id", name="uq_franchise_movies_title_anilist"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title_id: Mapped[int] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(500))  # Russian name when the source knows it
    aired_on: Mapped[date | None] = mapped_column(Date)  # None: no date yet
    released: Mapped[bool] = mapped_column(Boolean)
    shikimori_id: Mapped[str] = mapped_column(String(32))
    mal_id: Mapped[str | None] = mapped_column(String(32))
    anilist_id: Mapped[str | None] = mapped_column(String(32))


class GamePlatformRecord(TrackerBase):
    """A platform of the tracker a game is on (`app.tracker.platforms.Platform`) and the owner's mark «играю здесь» on
    it. The dates are not here: they live in the snapshot, the one place of the dates (spec 4.3 of part 6.1)."""

    __tablename__ = "game_platforms"
    __table_args__ = (UniqueConstraint("title_id", "platform", name="uq_game_platforms_title_platform"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    title_id: Mapped[int] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(16))
    playing: Mapped[bool] = mapped_column(Boolean)


class PriceRecord(TrackerBase):
    """A record of the price history of a game (spec 4.5 of part 6.2): the price of Steam as a price check saw it. A new
    record only when it differs from the latest one; «самая низкая с добавления» reads them (`prices.lowest`)."""

    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    title_id: Mapped[int] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"), index=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime)  # the moment of the price check that saw the price
    appid: Mapped[str] = mapped_column(String(16))  # the Steam number asked about
    country: Mapped[str] = mapped_column(String(2))  # the store country of that check
    currency: Mapped[str] = mapped_column(String(32))  # as Steam writes a price («₪{}», `prices.currency_of`)
    final: Mapped[int] = mapped_column(Integer)  # the price now, in hundredths
    original: Mapped[int | None] = mapped_column(Integer)  # the price before the discount; None: no discount
    pct: Mapped[int] = mapped_column(Integer)  # the percent of the discount; 0: none


class InboxState(StrEnum):
    """Where an inbox item is (spec 7.1 of stage 6.4)."""

    WAITING = "waiting"  # «ждёт ответа»: the question «Что это?» or an offer waits in the chat
    INBOX = "inbox"  # in «Входящие», with a reason


class InboxReason(StrEnum):
    """Why an item is in «Входящие»; the words the owner reads are `INBOX_REASONS` of `results`."""

    NOT_FOUND = "not_found"  # «не нашёл»
    NO_ANSWER = "no_answer"  # «без ответа»
    NO_TEXT = "no_text"  # «нет текста»
    SOURCE_FAILED = "source_failed"  # «источник не ответил»
    NOT_CONNECTED = "not_connected"  # «игры не подключены»


class InboxRecord(TrackerBase):
    """An inbox item: what the owner sent to the bot (a post, a name, an album, a forward with its comment), kept until
    it is resolved or removed — then the row is deleted. The number is never reused (`AUTOINCREMENT`)."""

    __tablename__ = "inbox_items"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    state: Mapped[InboxState] = mapped_column(_stored_as_text(InboxState), index=True)
    reason: Mapped[InboxReason | None] = mapped_column(_stored_as_text(InboxReason, length=24))
    kind: Mapped[TitleKind | None] = mapped_column(_stored_as_text(TitleKind))  # chosen by the owner or given by a link
    text: Mapped[str] = mapped_column(Text, default="")  # the joined text, at most `inbox.MAX_TEXT` characters
    media: Mapped[str | None] = mapped_column(String(16))  # what came without text (`results.MEDIA_WORDS`)
    bold: Mapped[list] = mapped_column(JSON, default=list)  # the bold pieces of 1–8 words
    links: Mapped[list] = mapped_column(JSON, default=list)  # the addresses of the links of the text
    post_url: Mapped[str | None] = mapped_column(Text)  # the post of a public channel it was forwarded from
    forwarded: Mapped[bool] = mapped_column(Boolean)
    media_group_id: Mapped[str | None] = mapped_column(String(64))  # the album its messages came in
    query: Mapped[str] = mapped_column(Text, default="")  # what «Найти» of the web searches
    offers: Mapped[list] = mapped_column(JSON, default=list)  # the offers of the analysis (ticket 04)
    received_at: Mapped[datetime] = mapped_column(DateTime)  # the 12 hours of waiting count from it
    last_message_at: Mapped[datetime] = mapped_column(DateTime)  # a message joins within 2 seconds of it
    moved_at: Mapped[datetime | None] = mapped_column(DateTime)  # when it went to «Входящие»


class SettingRecord(TrackerBase):
    """One setting of the owner by name; absent means the default."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)


class SourceSnapshot(TrackerBase):
    """Last normalized state of a title as one source reported it."""

    __tablename__ = "source_snapshots"
    __table_args__ = (UniqueConstraint("title_id", "source", name="uq_source_snapshots_title_source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    title_id: Mapped[int] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(32))
    state: Mapped[dict] = mapped_column(JSON)
    observed_at: Mapped[datetime] = mapped_column(DateTime)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)  # None: due now


class Event(TrackerBase):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(64))
    # Deleting a title deletes its events in the database itself; empty for events that belong to no title (test events)
    title_id: Mapped[int | None] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    dedup_key: Mapped[str] = mapped_column(String(255), unique=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime)


class DeliveryItem(TrackerBase):
    __tablename__ = "delivery_queue"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), unique=True)
    status: Mapped[DeliveryStatus] = mapped_column(_stored_as_text(DeliveryStatus), index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime)
