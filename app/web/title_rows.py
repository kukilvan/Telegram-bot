"""What the list and the archive share: a row of titles, a link of a row of filters and the search query."""

from collections.abc import Sequence
from typing import NamedTuple

from fastapi import Request

from app.tracker import scores
from app.tracker.cards import STATUS_LABELS
from app.tracker.kinds import KINDS

QUERY_LIMIT = 100  # the letters of a search query; a longer one is cut


class Link(NamedTuple):
    label: str
    address: str
    current: bool


class Row(NamedTuple):
    address: str  # the card
    id: int
    poster: str | None
    icon: str
    name: str
    year: int | None
    status: str  # the label
    score: str  # «9+», «ср. 9−» (the average of the seasons); empty: none to show


def clean_query(raw: str) -> str:
    """The query as it is searched: spaces at the ends do not count, a long one is cut."""
    return raw.strip()[:QUERY_LIMIT].strip()


def score_text(score: int | None, by_seasons: bool) -> str:
    if score is None:
        return ""
    return f"ср. {scores.label(score)}" if by_seasons else scores.label(score)


def rows(request: Request, titles: Sequence) -> list[Row]:
    return [
        Row(
            str(request.app.url_path_for("card", title_id=t.id)), t.id, t.poster_path, KINDS[t.kind].icon, t.name, t.year,
            STATUS_LABELS[t.status], score_text(t.score, t.score_by_seasons),
        )
        for t in titles
    ]
