"""An offer as the item keeps it and the text of its card (pure).

An offer is the record of a source shown as «Это оно?»: how it is stored in `inbox_items.offers` and read back, and the
lines of its card (spec 6.1 of stage 6.4).

The searches that find the records are `offers`; this module only holds what is found and how it reads.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

from app.tracker.candidates import name_key
from app.tracker.kinds import KINDS
from app.tracker.models import TitleKind
from app.tracker.moment_words import format_date
from app.tracker.sources.dates import parse_date

HEADING = "Это оно?"
CORRECTED = "Возможно, вы имели в виду:"  # the heading of the offers of a corrected typo
NO_DATE = "дата не объявлена"


@dataclass(frozen=True)
class Offer:
    """A record of a source the owner is asked about. `shown`: its card was sent; `title_id`: the title in the list it
    is, as the search found it (not stored: it is checked again when the card is shown)."""

    kind: TitleKind
    external_id: str
    name: str
    original_name: str
    released: date | None
    details: str | None
    poster: str | None  # as the title stores it (`poster_path`)
    heading: str
    shown: bool = False
    title_id: int | None = None

    def stored(self) -> dict[str, Any]:
        """As the item keeps it (`inbox_items.offers`)."""
        return {
            "kind": self.kind.value,
            "external_id": self.external_id,
            "name": self.name,
            "original_name": self.original_name,
            "released": self.released.isoformat() if self.released else None,
            "details": self.details,
            "poster": self.poster,
            "heading": self.heading,
            "shown": self.shown,
        }

    @classmethod
    def read(cls, raw: dict[str, Any]) -> "Offer":
        """What `stored` wrote, strictly: garbage is a bug of ours (rule 9)."""
        return cls(
            kind=TitleKind(raw["kind"]),
            external_id=str(raw["external_id"]),
            name=raw["name"],
            original_name=raw.get("original_name") or "",
            released=parse_date(raw.get("released")),
            details=raw.get("details"),
            poster=raw.get("poster"),
            heading=raw["heading"],
            shown=bool(raw.get("shown")),
        )


def offer_of(suggestion: Any, heading: str) -> Offer:
    return Offer(
        kind=suggestion.kind,
        external_id=suggestion.external_id,
        name=suggestion.name,
        original_name=suggestion.original_name,
        released=suggestion.released,
        details=suggestion.details,
        poster=suggestion.poster_path,
        heading=heading,
        title_id=suggestion.title_id,
    )


def released_line(released: date | None, today: date) -> str:
    """Out: the year («2026»); in the future: «выйдет 12 февраля 2027»; no date: «дата не объявлена»."""
    if released is None:
        return NO_DATE
    return f"выйдет {format_date(released)}" if released > today else str(released.year)


def card_text(offer: Offer, today: date) -> str:
    """The text of an offer card (6.1): the heading, the icon and the name, the original name when its key differs, the
    date and the details of the record (the platforms of a game)."""
    lines = [offer.heading, "", f"{KINDS[offer.kind].icon} {offer.name}"]
    if offer.original_name and name_key(offer.original_name) != name_key(offer.name):
        lines.append(offer.original_name)
    lines.append(" · ".join(part for part in (released_line(offer.released, today), offer.details) if part))
    return "\n".join(lines)


def shown(offers: Sequence[Offer], number: int) -> list[Offer]:
    """The offers with the card of `number` marked as sent."""
    return [replace(offer, shown=True) if index == number else offer for index, offer in enumerate(offers)]
