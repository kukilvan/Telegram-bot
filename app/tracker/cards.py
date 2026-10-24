"""Text card of a title: what the owner reads in the bot. Pure formatting, no database."""

from dataclasses import dataclass
from datetime import date

from app.tracker.seasons import RELEASED, SeasonsView

KIND_LABELS = {"movie": "Фильм", "series": "Сериал"}
KIND_ICONS = {"movie": "🎬", "series": "📺"}
STATUS_LABELS = {"want": "Хочу", "watched": "Просмотрено"}
_WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")

_MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)
_SHORT_MONTHS = ("янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")
NOT_ANNOUNCED = "не объявлена"


@dataclass(frozen=True)
class TitleCard:
    id: int
    kind: str
    title: str
    original_title: str
    year: int | None
    genres: list[str]
    status: str
    theatrical_date: date | None = None
    digital_date: date | None = None
    seasons: SeasonsView | None = None  # series only


def format_date(value: date | None) -> str:
    return f"{value.day} {_MONTHS[value.month - 1]} {value.year}" if value else NOT_ANNOUNCED


def format_short_date(value: date) -> str:
    """«15 дек 2026»: the form used when two dates stand side by side."""
    return f"{value.day} {_SHORT_MONTHS[value.month - 1]} {value.year}"


def format_weekday_date(value: date) -> str:
    """«пн, 12 окт»: a near day, as the next episode is announced."""
    return f"{_WEEKDAYS[value.weekday()]}, {value.day} {_SHORT_MONTHS[value.month - 1]}"


def format_day_month(value: date) -> str:
    """«27 марта»: the day a part starts, as the card says «часть 2 — с 27 марта»."""
    return f"{value.day} {_MONTHS[value.month - 1]}"


def season_lines(view: SeasonsView) -> list[str]:
    lines = []
    if view.current is not None:
        current = view.current
        label = f"Сезон {current.number}" + (f", часть {current.part}" if current.part else "")
        line = f"{label}: вышло {current.released} из {current.total if current.total else '?'}"
        if current.status != RELEASED:
            line += f", следующая — {format_weekday_date(current.next_air_at.date()) if current.next_air_at else NOT_ANNOUNCED}"
        elif current.next_part_at is not None:
            line += f"; часть {current.next_part} — с {format_day_month(current.next_part_at.date())}"
        lines.append(line)
    if view.announced is not None:
        announced = view.announced
        when = f"премьера {format_date(announced.first_air_at.date())}" if announced.first_air_at else "дата не объявлена"
        lines.append(f"Сезон {announced.number} анонсирован, {when}")
    if not lines:
        lines.append("Сезонов пока нет")
    if view.watched:
        lines.append(f"Просмотрены сезоны: {', '.join(str(n) for n in view.watched)}")
    return lines


def format_card(card: TitleCard) -> str:
    icon = KIND_ICONS.get(card.kind, "🎞")
    kind = KIND_LABELS.get(card.kind, card.kind)
    status = STATUS_LABELS.get(card.status, card.status)
    names = card.title
    if card.original_title and card.original_title != card.title:
        names = f"{card.title} · {card.original_title}"
    lines = [f"{icon} {kind} · {status}", names]
    if card.year:
        lines.append(f"Год: {card.year}")
    if card.genres:
        lines.append(f"Жанры: {', '.join(card.genres)}")
    if card.seasons is not None:
        lines.extend(season_lines(card.seasons))
    else:
        lines.append(f"Премьера в кино: {format_date(card.theatrical_date)}")
        lines.append(f"Цифровой релиз: {format_date(card.digital_date)}")
    return "\n".join(lines)
