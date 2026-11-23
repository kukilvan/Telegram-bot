"""The companies of IGDB asked about the candidates of an inbox item (pure): the text of the request and which names the
answer says are companies (7.3 of stage 9.1d).

A name is a company when a company of IGDB named like it made at least `COMPANY_GAMES` games. «Ubisoft» is no company
name in IGDB («Ubisoft Entertainment» is), so each name is asked as it is and followed by each of `COMPANY_WORDS`; the
`~` of IGDB is equality without case, and an array after it is refused, so the names are joined by `|`.
"""

from collections.abc import Sequence
from typing import Any

from app.tracker.candidates import name_key

COMPANY_WORDS = (
    "Entertainment", "Studios", "Studio", "Games", "Softworks", "Interactive", "Productions", "Software", "Publishing",
    "Digital", "Inc",
)
COMPANY_GAMES = 20  # a name is a company from this many games developed and published; small studios named like games stay
LIMIT = 500


def askable(name: str) -> bool:
    """A name with `"` or `\\` would break the text of the query, so it is not asked."""
    return bool(name.strip()) and '"' not in name and "\\" not in name


def _variants(name: str) -> list[str]:
    return [name, *(f"{name} {word}" for word in COMPANY_WORDS)]


def companies_query(names: Sequence[str]) -> str:
    """The request of `/companies` for names that are all `askable`."""
    conditions = " | ".join(f'name ~ "{variant}"' for name in names for variant in _variants(name))
    return f"fields name,developed,published; where {conditions}; limit {LIMIT};"


def _count(value: Any) -> int:
    """The games in a `developed` or `published` field: IGDB lists their numbers (soft: an answer of a service)."""
    if isinstance(value, list):
        return len(value)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def company_keys(names: Sequence[str], answers: Sequence[Any]) -> frozenset[str]:
    """The name keys of the asked `names` that are companies: one of the answers is the name itself or the name with a
    word of `COMPANY_WORDS`, and has made at least `COMPANY_GAMES` games."""
    owner = {name_key(variant): name_key(name) for name in names for variant in _variants(name)}
    found = set()
    for answer in answers:
        if not isinstance(answer, dict) or not isinstance(answer.get("name"), str):
            continue
        games = _count(answer.get("developed")) + _count(answer.get("published"))
        key = name_key(answer["name"])
        if games >= COMPANY_GAMES and key in owner:
            found.add(owner[key])
    return frozenset(found)
