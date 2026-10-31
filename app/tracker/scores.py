"""The owner's score: ten points with «+» and «−». Pure functions, no database.

«+» and «−» weigh a third of a point each, so a score is kept as a whole number of thirds: `3 × n + m`, where `n` is
the point (1 to 10) and `m` is −1 («−»), 0 or +1 («+»). That is every number from 3 («1») to 30 («10») without a gap:
3 = «1», 4 = «1+», 5 = «2−», …, 28 = «9+», 29 = «10−», 30 = «10». «1−» (2) and «10+» (31) are not on the scale.

A series or an anime has a score of its own or the average of its seasons: the exact average is what orders titles,
the step nearest to it (exactly half-way: the higher one) is what the owner reads.
"""

import math
from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction

from app.tracker.kinds import is_seasonal
from app.tracker.models import ARCHIVE_STATUSES, Title

LOWEST, HIGHEST = 3, 30  # «1» and «10»
SCALE = tuple(range(HIGHEST, LOWEST - 1, -1))  # from the highest down: the order of the choices
_MODIFIERS = {-1: "−", 0: "", 1: "+"}  # the minus sign is U+2212, as the owner writes it


def check(value: int) -> int:
    """The value itself when it is on the scale; ValueError otherwise (a mistake of the caller)."""
    if isinstance(value, bool) or not isinstance(value, int) or not LOWEST <= value <= HIGHEST:
        raise ValueError(f"not a score: {value!r}")
    return value


def label(value: int) -> str:
    """«9+», «9», «9−»."""
    point = (check(value) + 1) // 3  # the nearest point: 28 is 9 and a third, 29 is 10 less a third
    return f"{point}{_MODIFIERS[value - 3 * point]}"


def average(values: Iterable[int]) -> Fraction | None:
    """The exact average of the scores; None when there are none."""
    scored = [check(value) for value in values]
    return Fraction(sum(scored), len(scored)) if scored else None


def rounded(value: Fraction) -> int:
    """The step of the scale nearest to an average; exactly half-way, the higher one."""
    return check(math.floor(value + Fraction(1, 2)))


@dataclass(frozen=True)
class ScoreView:
    """The score of a title as its card shows it, when the title can be scored at all."""

    own: int | None  # the owner's own score of the title; None: not set
    average: Fraction | None  # the exact average of the seasons that can be scored; None: none scored, or a film
    shown: int | None  # what the owner reads: the own score, else the average to the nearest step; None: nothing
    by_seasons: bool  # `shown` is the average of the seasons


def title_view(own: int | None, seasons: Iterable[int]) -> ScoreView:
    """The score of a title that can be scored: its own one over the average of the seasons' scores (only the seasons
    that can be scored, and of them only the scored ones; a film has none)."""
    mean = average(seasons)
    if own is not None:
        return ScoreView(own, mean, own, by_seasons=False)
    return ScoreView(None, mean, None if mean is None else rounded(mean), by_seasons=mean is not None)


# --- which score is seen ---------------------------------------------------------------------------------
# One rule for the card, the list and the archive. A score stays in the database when it stops being seen.


def scorable(title: Title, any_marked: bool) -> bool:
    """Whether the title can be scored, which is also whether its score is shown: a title in the archive, or a series
    or an anime with a marked season (`any_marked`)."""
    return title.status in ARCHIVE_STATUSES or (is_seasonal(title.kind) and any_marked)


def season_score(watched: bool, score: int | None) -> int | None:
    """The score of a season as it is shown: only a season with its «watched» mark has one."""
    return score if watched else None


def visible(title: Title, seasons: Iterable[tuple[bool, int | None]]) -> ScoreView | None:
    """The score of the title as the owner sees it; None while the title cannot be scored. `seasons` are the
    «watched» marks and the scores of its stored seasons: only the scores of the marked ones count."""
    marks = list(seasons)
    if not scorable(title, any(watched for watched, _ in marks)):
        return None
    shown = (season_score(watched, score) for watched, score in marks)
    return title_view(title.score, (score for score in shown if score is not None))
