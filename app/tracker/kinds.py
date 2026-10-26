"""What each kind of title is for the owner: one table, so a new kind cannot be added half-way.

A property that depends on the kind (its label, icon, the request for a name, the source it comes from, whether it has
seasons) is read from `KINDS`, never decided by an `if` on the kind. Pure data, no database.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from app.tracker.models import TitleKind


@dataclass(frozen=True)
class KindInfo:
    label: str  # «Фильм»
    icon: str  # in the list, on the card and at the start of an event message
    ask_name: str  # the request that follows «Добавить» and the choice of this kind
    source_name: str  # the service the kind comes from, as error texts name it
    seasonal: bool  # has seasons: the status follows the owner's season marks


KINDS: Mapping[TitleKind, KindInfo] = {
    TitleKind.MOVIE: KindInfo(
        label="Фильм",
        icon="🎬",
        ask_name="Напишите название фильма (можно по-русски или по-английски).",
        source_name="TMDb",
        seasonal=False,
    ),
    TitleKind.SERIES: KindInfo(
        label="Сериал",
        icon="📺",
        ask_name="Напишите название сериала (можно по-русски или по-английски).",
        source_name="TMDb",
        seasonal=True,
    ),
    TitleKind.ANIME: KindInfo(
        label="Аниме",
        icon="🎌",
        ask_name="Напишите название аниме (можно по-русски или по-английски).",
        source_name="Shikimori",
        seasonal=True,
    ),
}


def is_seasonal(kind: TitleKind) -> bool:
    return KINDS[kind].seasonal


def seasonal_kinds() -> tuple[TitleKind, ...]:
    return tuple(kind for kind in TitleKind if KINDS[kind].seasonal)
