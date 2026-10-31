"""Game events: what changed between two snapshots of a game on the platforms the owner is told about, how the message
reads, how the events of several platforms fold into one, and the samples of «Тестовое событие».

Pure: no database, no network. The previous and the new snapshot are read for the same country of the stores — today's
(spec 5.2 of part 6.1), so a new country gives no messages. Only an exact day gives a message; an approximate date
(«4 квартал 2026», «2027») changes silently. One event per platform keeps the dedup keys exact; one game is still one
line of a message: `fold_key` tells `delivery.fold` which events go together, `message` writes the line of all of them.
"""

from collections.abc import Collection, Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any

from app.tracker.cards import format_day_month
from app.tracker.dedup import moved_key
from app.tracker.games import NOT_ANNOUNCED, GameDate, GameState, PlatformDate, platform_dates, released_by
from app.tracker.kinds import KINDS
from app.tracker.models import TitleKind
from app.tracker.movie_events import DetectedEvent
from app.tracker.platforms import PLATFORMS, Platform

_ICON = KINDS[TitleKind.GAME].icon

RELEASED = "game_released"
EARLY_ACCESS = "game_early_access"
DATE_ANNOUNCED = "game_date_announced"
DATE_MOVED = "game_date_moved"
TYPES = frozenset({RELEASED, EARLY_ACCESS, DATE_ANNOUNCED, DATE_MOVED})

# A day of release older than this, which the answer tells only now, is IGDB correcting old data, not news (KI-36)
FRESH = timedelta(days=30)


def reported(mine: Collection[Platform], playing: Mapping[str, bool]) -> tuple[Platform, ...]:
    """The platforms the owner is told about (spec 6.4): among «Мои платформы», with the mark «играю здесь» in the game.
    A platform the game has no row of yet (IGDB added it) counts as marked: this poll stores its row so."""
    return tuple(platform for platform in Platform if platform in mine and playing.get(platform.value, True))


def older_tells(platform: Platform, told: Collection[Platform]) -> bool:
    """The older platform whose date this one took is itself a platform the owner is told about (Switch 2 ← Switch):
    that one gives the message."""
    older = PLATFORMS[platform].older
    return older is not None and any(PLATFORMS[other].igdb_id == older.igdb_id for other in told)


def _fresh(game_date: GameDate, today: date) -> bool:
    return released_by(game_date, today) and game_date.start >= today - FRESH


def _date_of(dated: PlatformDate | None) -> GameDate:
    return dated.date if dated is not None else NOT_ANNOUNCED


# --- texts ----------------------------------------------------------------------------------------------------------


def platform_label(platform: Platform, via: str = "") -> str:
    """«PS5»; the date of the older platform: «PS4 (идёт на PS5)»."""
    label = PLATFORMS[platform].label
    return f"{via} (идёт на {label})" if via else label


def platforms_text(entries: Iterable[tuple[Platform, str]]) -> str:
    """«ПК», «ПК и PS5», «ПК, PS5 и Xbox Series X|S»: in the order of the table of platforms."""
    order = list(Platform)
    labels = [platform_label(platform, via) for platform, via in sorted(set(entries), key=lambda e: order.index(e[0]))]
    return labels[0] if len(labels) == 1 else f"{', '.join(labels[:-1])} и {labels[-1]}"


def moved_text(old: GameDate, new: GameDate) -> str:
    """«12 марта → 9 июня 2027» in one year; «15 декабря 2026 → 22 января 2027», «12 марта 2027 → 2027»,
    «12 марта 2027 → дата не объявлена» otherwise."""
    if old.exact and new.exact and old.year == new.year:
        return f"{format_day_month(old.start)} → {new.label}"
    return f"{old.label} → {new.label}"


def message(event_type: str, name: str, entries: Iterable[tuple[Platform, str]], data: Mapping[str, Any]) -> str:
    """The line of an event (or of several folded): `entries` are the platforms with the older one whose date they took
    (or «»), `data` the payload whose dates the line names."""
    where = platforms_text(entries)
    if event_type == RELEASED:
        return f"{_ICON} {name} вышла на {where}"
    if event_type == EARLY_ACCESS:
        return f"{_ICON} {name} вышла в раннем доступе на {where}"
    if event_type == DATE_ANNOUNCED:
        return f"{_ICON} {name}: на {where} объявлена дата — {GameDate.parse(data['date']).label}"
    moved = moved_text(GameDate.parse(data["old"]), GameDate.parse(data["new"]))
    return f"{_ICON} {name}: на {where} дата перенесена — {moved}"


# --- folding --------------------------------------------------------------------------------------------------------


def fold_key(event_type: str, title_id: int | None, data: Mapping[str, Any]) -> tuple[Any, ...] | None:
    """Events of one game, one type and the same dates fold into one line (spec 7.4): the date of an announcement, the
    old and the new date of a move; a release and an early access fold whatever their days. None: not a game event, or
    an event without the fields to fold by."""
    if event_type not in TYPES or "platform" not in data or "name" not in data:
        return None
    dates: tuple[Any, ...] = ()
    if event_type == DATE_ANNOUNCED:
        dates = (data.get("date"),)
    elif event_type == DATE_MOVED:
        dates = (data.get("old"), data.get("new"))
    return (event_type, title_id, data["name"], *dates)


def folded_text(event_type: str, members: Sequence[Mapping[str, Any]]) -> str:
    """The line of the folded events (their payloads): the template of the type with the list of their platforms; a
    sample keeps the words it starts with."""
    first = members[0]
    entries = [(Platform(data["platform"]), data.get("via") or "") for data in members]
    return first.get("prefix", "") + message(event_type, first["name"], entries, first)


# --- detection ------------------------------------------------------------------------------------------------------


def detect_events(
    title_id: int,
    name: str,
    old: GameState,
    new: GameState,
    country: str,
    told: Collection[Platform],
    observed_at: datetime,
    today: date,
) -> list[DetectedEvent]:
    """Events between the previous snapshot (taken at `observed_at`) and the new one (taken `today`), for the platforms
    the owner is told about (`told`, see `reported`) that the game has in the new snapshot and that are not cancelled.

    `new` must already keep the dates the source dropped (`games.carry_over`)."""
    observed_on = observed_at.date()
    events: list[DetectedEvent] = []
    for platform in Platform:
        if platform not in told:
            continue
        now_dates = platform_dates(new, platform, country)
        if now_dates is None or now_dates.cancelled:
            continue
        before = platform_dates(old, platform, country)
        prefix = f"game:{title_id}:{platform.value}"

        def event(kind: str, key: str, dated: PlatformDate | None, data: dict[str, Any], earlier: str | None = None):
            via = dated.version_of if dated is not None else None
            if via and older_tells(platform, told):
                return  # the older platform tells it
            data = {"name": name, "platform": platform.value, "via": via or "", **data}
            text = message(kind, name, [(platform, data["via"])], data)
            events.append(DetectedEvent(kind, key, text, data, earlier))

        old_full, new_full = _date_of(before.full if before else None), _date_of(now_dates.full)
        old_early, new_early = _date_of(before.early if before else None), _date_of(now_dates.early)
        full_out_before = released_by(old_full, observed_on)

        if _fresh(new_full, today) and not full_out_before:
            event(RELEASED, f"{prefix}:released", now_dates.full, {"date": new_full.text})
        elif new_full.exact and new_full.start > today and not old_full.exact:
            event(
                DATE_ANNOUNCED,
                # the date may be taken back («not announced») and announced again, the same one too: each announcement
                # is seen from a new look; the same one found again after a failed save, from the same look
                moved_key(f"{prefix}:date_announced:{new_full.text}", observed_at),
                now_dates.full,
                {"date": new_full.text},
            )
        elif old_full.exact and not full_out_before and new_full != old_full and not released_by(new_full, today):
            earlier = f"{prefix}:date_moved:{new_full.text or 'none'}"
            event(
                DATE_MOVED,
                moved_key(earlier, observed_at),
                now_dates.full if now_dates.full is not None else (before.full if before else None),
                {"old": old_full.text, "new": new_full.text},
                earlier,
            )

        if _fresh(new_early, today) and not released_by(old_early, observed_on) and not released_by(new_full, today):
            event(EARLY_ACCESS, f"{prefix}:early_access", now_dates.early, {"date": new_early.text})
    return events


# --- «Тестовое событие» ---------------------------------------------------------------------------------------------

_SAMPLE = "Elden Ring"


def _sample(event_type: str, platform: Platform, **data: Any) -> tuple[str, dict[str, Any]]:
    payload = {"name": _SAMPLE, "platform": platform.value, "via": "", **data}
    return event_type, {"text": message(event_type, _SAMPLE, [(platform, "")], payload), **payload}


SAMPLE_TWO_PLATFORMS_ID = "game-released-two"
SAMPLE_TWO_PLATFORMS_LABEL = "Игра: вышла на двух платформах"


def sample_two_platforms_events() -> list[tuple[str, dict[str, Any]]]:
    """A release on ПК and PS5 as two real events (type and payload): delivery folds them into one message."""
    return [
        _sample(RELEASED, Platform.PC, date="2026-10-31"),
        _sample(RELEASED, Platform.PS5, date="2026-10-31"),
    ]


# (id, menu label, message text) of the sample events in «Тестовое событие»; the core turns them into menu entries
TEST_SAMPLES: list[tuple[str, str, str]] = [
    ("game-announced", "Игра: объявлена дата", _sample(DATE_ANNOUNCED, Platform.PS5, date="2027-03-12")[1]["text"]),
    (
        "game-moved",
        "Игра: дата перенесена",
        _sample(DATE_MOVED, Platform.PS5, old="2027-03-12", new="2027-06-09")[1]["text"],
    ),
    ("game-released", "Игра: вышла", _sample(RELEASED, Platform.PC, date="2026-10-31")[1]["text"]),
    (
        "game-early-access",
        "Игра: ранний доступ",
        message(EARLY_ACCESS, "Hades II", [(Platform.PC, "")], {}),
    ),
]
