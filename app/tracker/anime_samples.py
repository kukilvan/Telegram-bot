"""The samples of the anime events for «Тестовое событие» (pure): one message of each kind, with an hour on a sample clock.

The texts are those of `series_messages` (with the anime `Flavor`) and of the franchise films of `anime_events`.
"""

from datetime import date, datetime, timedelta, timezone

from app.tracker import series_messages
from app.tracker.anime_events import flavor, message_movie_announced, message_movie_released
from app.tracker.seasons import Episode, Season

_SAMPLE = "Магическая битва (Jujutsu Kaisen)"
_SAMPLE_TZ = timezone(timedelta(hours=3))  # a sample shows how an hour reads, not the owner's zone
_FLAVOR = flavor(_SAMPLE_TZ)
_SAMPLE_SEASON = Season(4, "Сезон 4", 12)
_NEXT = "следующая: пн, 12 окт в 18:00"
# season 3 in two parts of twelve episodes: part 1 in autumn, part 2 after the break
_PARTS = Season(
    3,
    "Сезон 3",
    24,
    tuple(Episode(n, datetime(2026, 10, 5, 9, 0) + timedelta(weeks=n - 1)) for n in range(1, 13))
    + tuple(Episode(n, datetime(2027, 4, 5, 9, 0) + timedelta(weeks=n - 13)) for n in range(13, 25)),
).parts(timedelta(weeks=6))

TEST_SAMPLES: list[tuple[str, str, str]] = [
    (
        "anime-announced",
        "Аниме: объявлена дата сезона",
        series_messages.message_announced(_SAMPLE, 4, Episode(1, datetime(2027, 1, 10, 15, 0)), flavor=_FLAVOR),
    ),
    (
        "anime-started",
        "Аниме: сезон начался",
        series_messages.message_started(_SAMPLE, _SAMPLE_SEASON, 1, _NEXT, _FLAVOR),
    ),
    (
        "anime-episode",
        "Аниме: вышла серия",
        series_messages.message_episode(_SAMPLE, _SAMPLE_SEASON, 6, _NEXT, _FLAVOR),
    ),
    (
        "anime-ended",
        "Аниме: сезон закончился",
        series_messages.message_ended(_SAMPLE, _SAMPLE_SEASON, 12, _FLAVOR),
    ),
    (
        "anime-moved",
        "Аниме: дата серии сдвинулась",
        series_messages.message_moved(
            _SAMPLE,
            4,
            7,
            Episode(7, datetime(2026, 10, 12, 15, 0)),
            Episode(7, datetime(2026, 10, 19, 15, 0)),
            premiere=False,
            flavor=_FLAVOR,
        ),
    ),
    (
        "anime-part-episode",
        "Аниме: вышла серия части",
        series_messages.message_part_episode(_SAMPLE, _PARTS[0], 6, datetime(2026, 11, 10), _NEXT, _FLAVOR),
    ),
    (
        "anime-part-announced",
        "Аниме: объявлена дата части",
        series_messages.message_announced(_SAMPLE, 3, Episode(13, datetime(2027, 4, 5, 6, 0)), part=2, flavor=_FLAVOR),
    ),
    (
        "anime-part-started",
        "Аниме: началась часть сезона",
        series_messages.message_part_started(_SAMPLE, _PARTS[1], 13, "следующая: пн, 12 апр в 12:00", _FLAVOR),
    ),
    (
        "anime-part-ended",
        "Аниме: закончилась часть сезона",
        series_messages.message_part_ended(_SAMPLE, _PARTS[0], 12, _PARTS[1], _FLAVOR),
    ),
    (
        "anime-movie-announced",
        "Аниме: анонсирован фильм франшизы",
        message_movie_announced(_SAMPLE, "Магическая битва: Фильм", date(2027, 2, 5)),
    ),
    (
        "anime-movie-released",
        "Аниме: вышел фильм франшизы",
        message_movie_released(_SAMPLE, "Магическая битва: Фильм"),
    ),
]
