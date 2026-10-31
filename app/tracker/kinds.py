"""What each kind of title is for the owner: one table, so a new kind cannot be added half-way.

A property that depends on the kind (its label, icon, the request for a name, the source it comes from, whether it has
seasons, its final status and the buttons of its statuses) is read from `KINDS`, never decided by an `if` on the kind. Pure data, no database.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from app.tracker.models import TitleKind, TitleStatus


@dataclass(frozen=True)
class KindInfo:
    label: str  # «Фильм»
    plural: str  # «Фильмы»: the filter of the list
    icon: str  # in the list, on the card and at the start of an event message
    ask_name: str  # the request that follows «Добавить» and the choice of this kind
    source_name: str  # the service the kind comes from, as error texts name it
    seasonal: bool  # has seasons: the status follows the owner's season marks
    local_times: bool  # the time of an episode is shown on the owner's clock (the source gives the exact moment)
    search_note: str = ""  # the line under the switch of the search while the kind is chosen; empty: none
    finished: TitleStatus = TitleStatus.WATCHED  # the final status «done» that `mark_watched` gives
    finish_press: str = ""  # the button of that status on the web card («Посмотрел»); empty: the status follows the marks
    start_press: str = ""  # the button of «В процессе» on the web card («Начал играть»); empty: none, `mark_started` refuses
    web_only: bool = False  # added and moved between statuses only on the web: the bot offers neither


KINDS: Mapping[TitleKind, KindInfo] = {
    TitleKind.MOVIE: KindInfo(
        label="Фильм",
        plural="Фильмы",
        icon="🎬",
        ask_name="Напишите название фильма (можно по-русски или по-английски).",
        source_name="TMDb",
        seasonal=False,
        local_times=False,
        finish_press="Посмотрел",
    ),
    TitleKind.SERIES: KindInfo(
        label="Сериал",
        plural="Сериалы",
        icon="📺",
        ask_name="Напишите название сериала (можно по-русски или по-английски).",
        source_name="TMDb",
        seasonal=True,
        local_times=False,
        search_note=(
            "Аниме лучше искать в «Аниме»: там сезоны и расписание серий точнее. "
            "Найденное здесь добавится как обычный сериал TMDb"
        ),
    ),
    TitleKind.ANIME: KindInfo(
        label="Аниме",
        plural="Аниме",
        icon="🎌",
        ask_name="Напишите название аниме (можно по-русски или по-английски).",
        source_name="Shikimori",
        seasonal=True,
        local_times=True,
    ),
    TitleKind.GAME: KindInfo(
        label="Игра",
        plural="Игры",
        icon="🎮",
        ask_name="Напишите название игры (лучше по-английски).",
        source_name="IGDB",
        seasonal=False,
        local_times=False,
        search_note="Игры лучше искать по-английски: по-русски IGDB находит не всё",
        finished=TitleStatus.COMPLETED,
        finish_press="Прошёл",
        start_press="Начал играть",
        web_only=True,
    ),
}


def is_seasonal(kind: TitleKind) -> bool:
    return KINDS[kind].seasonal


def seasonal_kinds() -> tuple[TitleKind, ...]:
    return tuple(kind for kind in TitleKind if KINDS[kind].seasonal)
