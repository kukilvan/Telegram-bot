"""Text card of a title: what the owner reads in the bot. Pure formatting, no database."""

from dataclasses import dataclass
from datetime import date, datetime, timezone, tzinfo

from app.tracker.kinds import KINDS
from app.tracker.models import TitleKind, TitleStatus
from app.tracker.seasons import RELEASED, SeasonsView

STATUS_LABELS = {
    TitleStatus.WANT: "Хочу",
    TitleStatus.IN_PROGRESS: "В процессе",
    TitleStatus.WAITING: "Жду",
    TitleStatus.TO_FINISH: "Досмотреть",
    TitleStatus.WATCHED: "Просмотрено",
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


def season_lines(view: SeasonsView, tz: tzinfo | None = None) -> list[str]:
    lines = []
    if view.current is not None:
        current = view.current
        label = f"Сезон {current.number}" + (f", часть {current.part}" if current.part else "")
        line = f"{label}: вышло {current.released} из {current.total if current.total else '?'}"
        if current.status != RELEASED:
            line += f", следующая — {format_when(current.next_air_at, tz) if current.next_air_at else NOT_ANNOUNCED}"
        elif current.next_part_at is not None:
            line += f"; часть {current.next_part} — с {format_day_month(local_moment(current.next_part_at, tz).date())}"
        lines.append(line)
    if view.announced is not None:
        announced = view.announced
        when = (
            f"премьера {format_date(local_moment(announced.first_air_at, tz).date())}"
            if announced.first_air_at
            else "дата не объявлена"
        )
        lines.append(f"Сезон {announced.number} анонсирован, {when}")
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
    if card.seasons is not None:
        lines.extend(season_lines(card.seasons, card.tz))
        if card.franchise_movies:
            lines.append(franchise_movies_line(card.franchise_movies))
    else:
        lines.append(f"Премьера в кино: {format_date(card.theatrical_date)}")
        lines.append(f"Цифровой релиз: {format_date(card.digital_date)}")
    return "\n".join(lines)
