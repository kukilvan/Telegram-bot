"""The texts of the series events and their samples (pure): the message of each event, the `Flavor` that makes an anime
read as itself, and the samples of «Тестовое событие».

The detection, the keys and the check interval are `series_events`; an anime goes through the same texts with its own
`Flavor` (its icon, its key prefix, the owner's time zone). A moment reads by the one rule of `moment_words.episode_when`.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from typing import Any

from app.tracker.kinds import KINDS
from app.tracker.models import EpisodeTiming, TitleKind
from app.tracker.moment_words import (
    NOT_ANNOUNCED,
    episode_when,
    format_date,
    format_day_month,
    format_episode_when,
    format_short_date,
)
from app.tracker.seasons import Episode, Part, Season

# TMDb's status of the show, as the state keeps it, and what the owner is told
ENDED_STATUS = "Ended"
CANCELED_STATUS = "Canceled"


@dataclass(frozen=True)
class Flavor:
    """What differs between the kinds of title that share these events: the icon, the prefix of the dedup keys and
    whether the hour is told (and in which time zone)."""

    icon: str = KINDS[TitleKind.SERIES].icon
    key_prefix: str = TitleKind.SERIES.value  # the keys already stored start with the kind's value
    tz: tzinfo | None = None  # None: the source knows only the day, so no hour is shown

    def day(self, episode: Episode) -> date:
        return episode_when(episode, self.tz)[0]


SERIES = Flavor()


def _total_text(season: Season | Part) -> str:
    total = season.total()
    return str(total) if total else "?"


def next_episode_line(season: Season | Part, now: datetime, flavor: Flavor = SERIES) -> str:
    coming = season.next_episode(now)
    return f"следующая: {format_episode_when(coming, flavor.tz) if coming else NOT_ANNOUNCED}"


def message_announced(name: str, season: int, premiere: Episode, part: int | None = None, flavor: Flavor = SERIES) -> str:
    what = f"сезона {season}" if part is None else f"части {part} сезона {season}"
    return f"{flavor.icon} {name} — объявлена дата {what}\nПремьера: {format_date(flavor.day(premiere))}"


def message_started(name: str, season: Season, episode: int, next_line: str | None, flavor: Flavor = SERIES) -> str:
    tail = f" · {next_line}" if next_line else ""
    return f"{flavor.icon} {name} — начался сезон {season.number}\nВышла серия {episode} из {_total_text(season)}{tail}"


def message_episode(name: str, season: Season, episode: int, next_line: str | None, flavor: Flavor = SERIES) -> str:
    tail = f" · {next_line}" if next_line else ""
    return f"{flavor.icon} {name} — вышла серия {episode} из {_total_text(season)}\nСезон {season.number}{tail}"


def message_ended(name: str, season: Season, episode: int, flavor: Flavor = SERIES) -> str:
    return f"{flavor.icon} {name} — сезон {season.number} закончился\nВышла последняя серия — {episode} из {_total_text(season)}"


def message_part_started(name: str, part: Part, episode: int, next_line: str | None, flavor: Flavor = SERIES) -> str:
    tail = f" · {next_line}" if next_line else ""
    return f"{flavor.icon} {name} — началась часть {part.number} сезона {part.season}\nВышла серия {episode}{tail}"


def message_part_episode(
    name: str, part: Part, episode: int, now: datetime, next_line: str | None, flavor: Flavor = SERIES
) -> str:
    tail = f" · {next_line}" if next_line else ""
    return (
        f"{flavor.icon} {name} — вышла серия {episode}\n"
        f"Сезон {part.season}, часть {part.number}: вышло {part.released_through(episode, now)} из {_total_text(part)}{tail}"
    )


def message_part_ended(name: str, part: Part, episode: int, following: Part | None, flavor: Flavor = SERIES) -> str:
    head = f"{flavor.icon} {name} — закончилась часть {part.number} сезона {part.season}\n"
    if following is None:
        return f"{head}Вышла последняя серия — {episode}"
    start = following.first_episode()
    when = f"с {format_day_month(flavor.day(start))}" if start else NOT_ANNOUNCED
    return f"{head}Вышла последняя серия части — {episode}; часть {following.number} — {when}"


def message_moved(
    name: str,
    season: int,
    episode: int,
    old: Episode,
    new: Episode,
    premiere: bool,
    part: int | None = None,
    flavor: Flavor = SERIES,
) -> str:
    days = f"{format_short_date(flavor.day(old))} → {format_short_date(flavor.day(new))}"
    if premiere and part:
        return f"{flavor.icon} {name} — премьера части {part} сезона {season} перенесена\n{days}"
    if premiere:
        return f"{flavor.icon} {name} — премьера сезона {season} перенесена\n{days}"
    return (
        f"{flavor.icon} {name} — дата серии {episode} сдвинулась\n"
        f"Сезон {season} · {format_episode_when(old, flavor.tz)} → {format_episode_when(new, flavor.tz)}"
    )


def message_closed(name: str, status: str | None, last_season: int | None, flavor: Flavor = SERIES) -> str:
    verb = "отменён" if status == CANCELED_STATUS else "закрыт"
    tail = f"\nПоследний сезон — {last_season}" if last_season else ""
    return f"{flavor.icon} {name} — сериал {verb}{tail}"


_SAMPLE = "Укрытие"


def _day_only(day: datetime) -> Episode:
    return Episode(1, day, EpisodeTiming.DAY)

_SAMPLE_SEASON = Season(2, "Сезон 2", 10)
_SAMPLE_DATE = datetime(2027, 7, 8)
# season 3 in two parts of eight episodes: part 1 in autumn, part 2 after the break
_SAMPLE_PARTS = Season(
    3,
    "Сезон 3",
    16,
    tuple(Episode(n, datetime(2026, 9, 7) + timedelta(weeks=n - 1)) for n in range(1, 9))
    + tuple(Episode(n, datetime(2027, 3, 29) + timedelta(weeks=n - 9)) for n in range(9, 17)),
).parts()

# (id, menu label, message text) of the sample events in «Тестовое событие»; the core turns them into menu entries
TEST_SAMPLES: list[tuple[str, str, str]] = [
    ("series-announced", "Сериал: объявлена дата сезона", message_announced(_SAMPLE, 4, _day_only(_SAMPLE_DATE))),
    ("series-started", "Сериал: сезон начался", message_started(_SAMPLE, _SAMPLE_SEASON, 1, "следующая: пн, 12 окт")),
    ("series-episode", "Сериал: вышла серия", message_episode(_SAMPLE, _SAMPLE_SEASON, 6, "следующая: пн, 12 окт")),
    ("series-ended", "Сериал: сезон закончился", message_ended(_SAMPLE, _SAMPLE_SEASON, 10)),
    (
        "series-moved",
        "Сериал: дата серии сдвинулась",
        message_moved(_SAMPLE, 2, 7, _day_only(datetime(2026, 10, 12)), _day_only(datetime(2026, 10, 19)), premiere=False),
    ),
    (
        "series-part-announced",
        "Сериал: объявлена дата части",
        message_announced(_SAMPLE, 3, _day_only(datetime(2027, 3, 29)), part=2),
    ),
    (
        "series-part-started",
        "Сериал: началась часть сезона",
        message_part_started(_SAMPLE, _SAMPLE_PARTS[1], 9, "следующая: пн, 5 апр"),
    ),
    (
        "series-part-ended",
        "Сериал: закончилась часть сезона",
        message_part_ended(_SAMPLE, _SAMPLE_PARTS[0], 8, _SAMPLE_PARTS[1]),
    ),
    ("series-closed", "Сериал: закрыт", message_closed(_SAMPLE, ENDED_STATUS, 4)),
    ("series-canceled", "Сериал: отменён", message_closed(_SAMPLE, CANCELED_STATUS, 4)),
]

SAMPLE_EPISODES_ID = "series-two-episodes"
SAMPLE_EPISODES_LABEL = "Сериал: две серии подряд"


def sample_episode_payloads() -> list[dict[str, Any]]:
    """The payloads of two episodes of one season, as real «вышла серия» events carry them (the type is
    `series_events.EPISODE_OUT`): a summary folds them into one line."""
    return [
        {"text": message_episode(_SAMPLE, _SAMPLE_SEASON, 5, None), "season": 2, "episode": 5},
        {"text": message_episode(_SAMPLE, _SAMPLE_SEASON, 6, "следующая: пн, 12 окт"), "season": 2, "episode": 6},
    ]
