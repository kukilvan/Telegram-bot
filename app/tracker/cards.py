"""Text card of a title: what the owner reads in the bot. Pure formatting, no database."""

from dataclasses import dataclass
from datetime import date

KIND_LABELS = {"movie": "Фильм"}
KIND_ICONS = {"movie": "🎬"}
STATUS_LABELS = {"want": "Хочу", "watched": "Просмотрено"}

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


def format_date(value: date | None) -> str:
    return f"{value.day} {_MONTHS[value.month - 1]} {value.year}" if value else NOT_ANNOUNCED


def format_short_date(value: date) -> str:
    """«15 дек 2026»: the form used when two dates stand side by side."""
    return f"{value.day} {_SHORT_MONTHS[value.month - 1]} {value.year}"


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
    lines.append(f"Премьера в кино: {format_date(card.theatrical_date)}")
    lines.append(f"Цифровой релиз: {format_date(card.digital_date)}")
    return "\n".join(lines)
