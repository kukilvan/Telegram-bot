"""Text card of a title: what the owner reads in the bot. Pure formatting, no database."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone, tzinfo
from typing import TYPE_CHECKING

from app.tracker import scores
from app.tracker.kinds import KINDS
from app.tracker.models import TitleKind, TitleStatus
from app.tracker.scores import ScoreView
from app.tracker.seasons import RELEASED, SeasonAnnouncement, SeasonProgress, SeasonRow, SeasonsView

if TYPE_CHECKING:
    from app.tracker.sequel_events import Sequels  # it formats its dates here: a plain import would go round

STATUS_LABELS = {
    TitleStatus.WANT: "Хочу",
    TitleStatus.IN_PROGRESS: "В процессе",
    TitleStatus.WAITING: "Жду",
    TitleStatus.TO_FINISH: "Досмотреть",
    TitleStatus.WATCHED: "Просмотрено",
    TitleStatus.COMPLETED: "Пройдено",
    TitleStatus.DROPPED: "Бросил",
}
_WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")

_MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)
_SHORT_MONTHS = ("янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")
NOT_ANNOUNCED = "не объявлена"


@dataclass(frozen=True)
class MovieLine:
    """A film of an anime franchise, as the card lists it."""

    name: str
    aired_on: date | None
    released: bool


@dataclass(frozen=True)
class SequelLine:
    """A sequel of a watched movie, as the web card lists it."""

    external_id: str  # in the movie source (TMDb)
    name: str
    date: date | None  # None: not announced
    title_id: int | None  # the sequel's title when it is in the list already


@dataclass(frozen=True)
class SequelsView:
    """The sequels of a watched movie: whether its collection was looked at yet, and the sequels found there."""

    checked: bool
    lines: tuple[SequelLine, ...] = ()


def sequel_view(sequels: "Sequels", checked: bool, listed: Mapping[str, int]) -> SequelsView:
    """The parts of the collection that are sequels of the movie, by date (the ones with no date last), each with the
    number of its title when it is in the list (`listed`: id in the movie source → title)."""
    found = sorted(
        (part for part in sequels.parts if sequels.is_sequel(part)),
        key=lambda part: (part.date is None, part.date or date.max),
    )
    return SequelsView(checked, tuple(SequelLine(p.id, p.name, p.date, listed.get(p.id)) for p in found))


@dataclass(frozen=True)
class TitleCard:
    id: int
    kind: TitleKind
    name: str
    original_name: str
    year: int | None
    genres: list[str]
    status: TitleStatus
    theatrical_date: date | None = None
    digital_date: date | None = None
    seasons: SeasonsView | None = None  # series and anime
    franchise_movies: tuple[MovieLine, ...] = ()  # anime only
    tz: tzinfo | None = None  # the owner's time zone, where the source gives the hour of an episode (anime)
    poster_path: str | None = None  # as stored: a TMDb file name or a whole address (the web shows it)
    overview: str = ""  # the description the source gave; empty for an anime
    season_rows: tuple[SeasonRow, ...] = ()  # series and anime: a row per season, for the web
    sequels: SequelsView | None = None  # a watched movie whose sequels are looked for; for the web
    score: ScoreView | None = None  # None: the title cannot be scored now (2.3 of the spec of part 5.3), no field


def format_date(value: date | None) -> str:
    return f"{value.day} {_MONTHS[value.month - 1]} {value.year}" if value else NOT_ANNOUNCED


def format_short_date(value: date) -> str:
    """«15 дек 2026»: the form used when two dates stand side by side."""
    return f"{value.day} {_SHORT_MONTHS[value.month - 1]} {value.year}"


def format_weekday_date(value: date) -> str:
    """«пн, 12 окт»: a near day, as the next episode is announced."""
    return f"{_WEEKDAYS[value.weekday()]}, {value.day} {_SHORT_MONTHS[value.month - 1]}"


def titles_word(count: int) -> str:
    """«тайтл» in the form that follows the number: 1 тайтл, 2 тайтла, 5 тайтлов, 11 тайтлов, 21 тайтл."""
    if count % 10 == 1 and count % 100 != 11:
        return "тайтл"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "тайтла"
    return "тайтлов"


def local_moment(moment: datetime, tz: tzinfo | None) -> datetime:
    """A naive UTC moment as the owner's clock shows it (naive); without a time zone it stays as it is."""
    if tz is None:
        return moment
    return moment.replace(tzinfo=timezone.utc).astimezone(tz).replace(tzinfo=None)


def format_when(moment: datetime, tz: tzinfo | None = None) -> str:
    """«пн, 12 окт»; given the owner's time zone, with the hour: «пн, 12 окт в 18:00»."""
    local = local_moment(moment, tz)
    text = format_weekday_date(local.date())
    return text if tz is None else f"{text} в {local:%H:%M}"


def format_past_moment(moment: datetime, now: datetime) -> str:
    """When something last happened, on the owner's clock (both moments aware, in the same zone): «в 14:05» today,
    «вчера в 23:10», «26 окт в 09:05» before that, «26 окт 2025 в 09:05» in another year."""
    local = moment.astimezone(now.tzinfo)
    days = (now.date() - local.date()).days
    if days <= 0:
        return f"в {local:%H:%M}"
    if days == 1:
        return f"вчера в {local:%H:%M}"
    day = f"{local.day} {_SHORT_MONTHS[local.month - 1]}"
    return f"{day} {local.year} в {local:%H:%M}" if local.year != now.year else f"{day} в {local:%H:%M}"


def format_day_month(value: date) -> str:
    """«27 марта»: the day a part starts, as the card says «часть 2 — с 27 марта»."""
    return f"{value.day} {_MONTHS[value.month - 1]}"


_DEFAULT_SEASON_NAME = re.compile(r"(сезон|season)\s*\d+", re.IGNORECASE)


def season_label(number: int, part: int | None = None, name: str = "") -> str:
    """«Сезон 3, часть 1»; with the season's own name when it is more than «Сезон N»: «Сезон 2 — Магическая битва»."""
    label = f"Сезон {number}" + (f", часть {part}" if part else "")
    own = name.strip()
    return label if not own or _DEFAULT_SEASON_NAME.fullmatch(own) else f"{label} — {own}"


def progress_line(current: SeasonProgress, tz: tzinfo | None = None, name: str = "") -> str:
    """How far the season (or its current part) has got: «Сезон 3, часть 1: вышло 7 из 12, следующая — пн, 12 окт»."""
    line = f"{season_label(current.number, current.part, name)}: вышло {current.released} из {current.total if current.total else '?'}"
    if current.status != RELEASED:
        line += f", следующая — {format_when(current.next_air_at, tz) if current.next_air_at else NOT_ANNOUNCED}"
    elif current.next_part_at is not None:
        line += f"; часть {current.next_part} — с {format_day_month(local_moment(current.next_part_at, tz).date())}"
    return line


def announced_line(announced: SeasonAnnouncement, tz: tzinfo | None = None, name: str = "") -> str:
    """«Сезон 4 анонсирован, премьера 3 апреля 2027» (or «дата не объявлена»)."""
    when = (
        f"премьера {format_date(local_moment(announced.first_air_at, tz).date())}"
        if announced.first_air_at
        else "дата не объявлена"
    )
    return f"{season_label(announced.number, name=name)} анонсирован, {when}"


def season_row_text(row: SeasonRow, tz: tzinfo | None = None) -> str:
    """The line of a season on the web card, with the season's own name."""
    if row.progress is not None:
        return progress_line(row.progress, tz, row.name)
    return announced_line(row.announcement, tz, row.name)


def season_lines(view: SeasonsView, tz: tzinfo | None = None) -> list[str]:
    lines = []
    if view.current is not None:
        lines.append(progress_line(view.current, tz))
    if view.announced is not None:
        lines.append(announced_line(view.announced, tz))
    if not lines:
        lines.append("Сезонов пока нет")
    if view.watched:
        lines.append(f"Просмотрены сезоны: {', '.join(str(n) for n in view.watched)}")
    return lines


MOVIES_SHOWN = 5  # a long list shows the latest ones


def movie_line(movie: MovieLine) -> str:
    """«Магическая битва 0. Фильм (2021)»; an unreleased one: «… — анонсирован»."""
    text = movie.name + (f" ({movie.aired_on.year})" if movie.aired_on else "")
    return text if movie.released else f"{text} — анонсирован"


def franchise_movies_line(movies: tuple[MovieLine, ...]) -> str:
    if len(movies) <= MOVIES_SHOWN:
        return f"Фильмы франшизы: {', '.join(movie_line(m) for m in movies)}"
    latest = ", ".join(movie_line(m) for m in movies[-MOVIES_SHOWN:])
    return f"Фильмы франшизы ({len(movies)}), последние: {latest}"


def movie_date_lines(card: TitleCard) -> list[str]:
    """The two dates of a film: «Премьера в кино: 12 марта 2027», «Цифровой релиз: не объявлена»."""
    return [
        f"Премьера в кино: {format_date(card.theatrical_date)}",
        f"Цифровой релиз: {format_date(card.digital_date)}",
    ]


def format_card(card: TitleCard) -> str:
    kind = KINDS[card.kind]
    names = card.name
    if card.original_name and card.original_name != card.name:
        names = f"{card.name} · {card.original_name}"
    lines = [f"{kind.icon} {kind.label} · {STATUS_LABELS[card.status]}", names]
    if card.year:
        lines.append(f"Год: {card.year}")
    if card.genres:
        lines.append(f"Жанры: {', '.join(card.genres)}")
    if card.score is not None and card.score.shown is not None:
        average = " (среднее по сезонам)" if card.score.by_seasons else ""
        lines.append(f"Оценка: {scores.label(card.score.shown)}{average}")
    if card.seasons is not None:
        lines.extend(season_lines(card.seasons, card.tz))
        if card.franchise_movies:
            lines.append(franchise_movies_line(card.franchise_movies))
    else:
        lines.extend(movie_date_lines(card))
    return "\n".join(lines)
