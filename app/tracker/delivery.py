"""Delivery rules: when a queued event may reach the owner, and how a summary reads.

Pure functions, no database and no network. Moments are naive UTC, like everywhere in the tracker; the rules
turn them into the owner's wall clock (`DeliveryRules.tz`) to decide.

An event is judged by the moment it was queued:
  - in the quiet hours (21:00–07:30 by default) it waits for their end;
  - on a working day (Sunday to Thursday by default) before the summary hour (15:00) it waits for that hour;
  - otherwise it goes out at once.
What waited goes out as one message: after the quiet hours of a day off, the message of that morning; on a working
day, the summary of 15:00 (a night's events join it). At any moment inside the quiet hours or on a working morning
nothing goes out, a retry of a failed send included. An event that should have gone at once, but whose send failed
and which outlived the quiet hours or a working morning, joins that summary too; a retry inside the same open
stretch of time goes out alone.

Several episodes of one season of one title are folded into a single line («вышли серии 5–6») — in a summary only.
Failures of several titles of one source for one reason in one pass are folded into one message, in a summary and
in a message of their own alike.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone, tzinfo
from typing import Any

from app.tracker import failures
from app.tracker.cards import format_weekday_date, local_moment
from app.tracker.series_events import EPISODE_OUT

DEFAULT_WORKDAYS = frozenset({6, 0, 1, 2, 3})  # Sunday to Thursday; Monday is 0, as in `date.weekday()`
DEFAULT_DIGEST_AT = time(15, 0)
DEFAULT_QUIET_FROM = time(21, 0)
DEFAULT_QUIET_UNTIL = time(7, 30)

DIGEST_ICON = "📋"
MESSAGE_LIMIT = 3500  # Telegram refuses more than 4096 characters; a longer summary goes in several messages
_EPISODE_MARK = " — вышла серия "  # where a series message names the title: «📺 Укрытие — вышла серия 5 из 10»


@dataclass(frozen=True)
class DeliveryRules:
    tz: tzinfo = timezone.utc
    workdays: frozenset[int] = DEFAULT_WORKDAYS
    digest_at: time = DEFAULT_DIGEST_AT
    quiet_from: time = DEFAULT_QUIET_FROM
    quiet_until: time = DEFAULT_QUIET_UNTIL

    # --- the clock of the owner ---

    def local(self, moment: datetime) -> datetime:
        """A naive UTC moment on the owner's wall clock (naive)."""
        return local_moment(moment, self.tz)

    def utc(self, local: datetime) -> datetime:
        """The owner's wall clock (naive) back to a naive UTC moment."""
        return local.replace(tzinfo=self.tz).astimezone(timezone.utc).replace(tzinfo=None)

    def is_quiet(self, local: datetime) -> bool:
        at = local.time()
        if self.quiet_from == self.quiet_until:
            return False  # no quiet hours
        if self.quiet_from < self.quiet_until:
            return self.quiet_from <= at < self.quiet_until
        return at >= self.quiet_from or at < self.quiet_until  # they cross midnight

    def is_workday(self, local: datetime) -> bool:
        return local.weekday() in self.workdays

    def holds(self, moment: datetime) -> bool:
        """At this moment the bot is silent: events wait."""
        local = self.local(moment)
        return self.is_quiet(local) or (self.is_workday(local) and local.time() < self.digest_at)

    def _quiet_end(self, local: datetime) -> datetime:
        end = datetime.combine(local.date(), self.quiet_until)
        return end if end > local else end + timedelta(days=1)

    def release(self, queued_at: datetime) -> tuple[datetime, bool]:
        """When an event queued at this moment may go out, and whether it goes in a summary (it had to wait)."""
        local = self.local(queued_at)
        waited = False
        for _ in range(4):  # a quiet end that lands before the summary hour needs a second step; sane settings need two
            if self.is_quiet(local):
                local, waited = self._quiet_end(local), True
            elif self.is_workday(local) and local.time() < self.digest_at:
                local, waited = datetime.combine(local.date(), self.digest_at), True
            else:
                break
        return (self.utc(local), True) if waited else (queued_at, False)

    def next_silence(self, moment: datetime) -> datetime | None:
        """The nearest start of silence strictly after this moment (naive UTC), or None when the bot is never silent.
        Silence starts with the quiet hours or at the midnight of a working day (until the summary hour it is silent),
        whichever comes first."""
        local = self.local(moment)
        starts: list[datetime] = []
        if self.quiet_from != self.quiet_until:
            start = datetime.combine(local.date(), self.quiet_from)
            starts.append(start if start > local else start + timedelta(days=1))
        if self.digest_at > time(0, 0):  # a summary hour at midnight leaves no working morning to be silent in
            for ahead in range(1, 8):
                midnight = datetime.combine(local.date() + timedelta(days=ahead), time(0, 0))
                if self.is_workday(midnight):
                    starts.append(midnight)
                    break
        return self.utc(min(starts)) if starts else None

    def due(self, queue: Sequence["Pending"], now: datetime) -> tuple[list["Pending"], list["Pending"]]:
        """(events to send one by one, events to send in one summary) among the queued ones at `now`.

        An event goes in the summary when it had to wait by the rules, or when silence began after it was allowed to
        go and before now (its send failed and it outlived the quiet hours or a working morning). A plain retry inside
        the same open stretch of time is a message of its own."""
        if self.holds(now):
            return [], []
        single: list[Pending] = []
        summary: list[Pending] = []
        for pending in queue:
            release, waited = self.release(pending.queued_at)
            if release > now:
                continue
            if not waited:
                silence = self.next_silence(release)
                waited = silence is not None and silence <= now  # it sat through silence: it joins the summary
            (summary if waited else single).append(pending)
        return single, summary


@dataclass(frozen=True)
class Pending:
    """An event waiting in the delivery queue, with its text as the owner would read it."""

    item_id: int
    event_id: int
    type: str
    title_id: int | None
    text: str
    data: dict[str, Any]
    queued_at: datetime


@dataclass(frozen=True)
class Unit:
    """One thing to say: a single event or several folded into one. It settles all its members together."""

    members: tuple[Pending, ...]
    text: str

    @property
    def single(self) -> Pending | None:
        return self.members[0] if len(self.members) == 1 else None


def _episode_key(pending: Pending) -> tuple[Any, ...] | None:
    season, episode = pending.data.get("season"), pending.data.get("episode")
    if pending.type != EPISODE_OUT or season is None or episode is None or _EPISODE_MARK not in pending.text:
        return None
    return pending.title_id, pending.text.split(_EPISODE_MARK, 1)[0], season, pending.data.get("part")


def episode_ranges(numbers: Iterable[int]) -> str:
    """«5–6», «3, 5–6, 9»: runs of consecutive episodes become ranges."""
    runs: list[list[int]] = []
    for number in sorted(set(numbers)):
        if runs and number == runs[-1][-1] + 1:
            runs[-1].append(number)
        else:
            runs.append([number])
    return ", ".join(str(r[0]) if len(r) == 1 else f"{r[0]}–{r[-1]}" for r in runs)


def _failure_key(pending: Pending) -> tuple[Any, ...] | None:
    if pending.type != failures.SOURCE_FAILED:
        return None
    key = failures.foldable(pending.data)
    return ("failure", *key) if key is not None else None


def fold(queue: Sequence[Pending], *, episodes: bool) -> list[Unit]:
    """Units in queue order. Two or more failures with the same source, reason and pass become one unit with a common
    text and no buttons; with `episodes`, episodes of one season of one title (two or more) become one unit too. A
    folded unit stands at the place of its first member. The folded episodes keep the second line of the latest one."""
    def key_of(pending: Pending) -> tuple[Any, ...] | None:
        if (key := _failure_key(pending)) is not None:
            return key
        if episodes and (key := _episode_key(pending)) is not None:
            return ("episodes", *key)
        return None

    groups: dict[tuple[Any, ...], list[Pending]] = {}
    for pending in queue:
        key = key_of(pending)
        if key is not None:
            groups.setdefault(key, []).append(pending)
    folded = {
        key: members
        for key, members in groups.items()
        if len(members) > 1 and (key[0] == "failure" or len({m.data["episode"] for m in members}) > 1)
    }

    units: list[Unit] = []
    done: set[tuple[Any, ...]] = set()
    for pending in queue:
        key = key_of(pending)
        members = folded.get(key) if key is not None else None
        if members is None:
            units.append(Unit((pending,), pending.text))
        elif key not in done:
            done.add(key)
            if key[0] == "failure":
                units.append(Unit(tuple(members), _failures_text(key, members)))
            else:
                units.append(Unit(tuple(members), _episodes_text(key, members)))
    return units


def _failures_text(key: tuple[Any, ...], members: Sequence[Pending]) -> str:
    _, source, reason, _ = key
    prefix = members[0].data.get("prefix", "")  # a test sample says so in front of its text
    return prefix + failures.message_many(source, reason, [m.data["title_name"] for m in members])


def _episodes_text(key: tuple[Any, ...], members: Sequence[Pending]) -> str:
    latest = max(members, key=lambda m: m.data["episode"])
    head = f"{key[2]} — вышли серии {episode_ranges(m.data['episode'] for m in members)}"
    tail = latest.text.split("\n", 1)[1] if "\n" in latest.text else ""
    return f"{head}\n{tail}" if tail else head


def one_line(text: str) -> str:
    return " · ".join(part for part in text.split("\n") if part)


def digest_messages(units: Sequence[Unit], moment: datetime, rules: DeliveryRules) -> list[tuple[str, list[Unit]]]:
    """The summary as one message, or several when it would not fit into Telegram. Each message comes with the
    units it holds, so only those are marked as delivered when it goes out."""
    header = f"{DIGEST_ICON} Сводка · {format_weekday_date(rules.local(moment).date())}"
    messages: list[tuple[str, list[Unit]]] = []
    lines: list[str] = []
    held: list[Unit] = []
    size = len(header)
    for unit in units:
        line = one_line(unit.text)
        if held and size + len(line) + 1 > MESSAGE_LIMIT:
            messages.append(("\n".join([header, *lines]), held))
            lines, held, size = [], [], len(header)
        lines.append(line)
        held.append(unit)
        size += len(line) + 1
    if held:
        messages.append(("\n".join([header, *lines]), held))
    return messages


@dataclass(frozen=True)
class WindowScenario:
    """A moment of the week for «Тестовое событие»: the owner sees how the rules treat an event queued then."""

    id: str
    label: str
    weekday: int  # Monday is 0
    at: time

    def next_moment(self, now_local: datetime) -> datetime:
        """The next such moment on the owner's clock (naive), today's included when it is still ahead."""
        ahead = (self.weekday - now_local.weekday()) % 7
        moment = datetime.combine(now_local.date() + timedelta(days=ahead), self.at)
        return moment if moment > now_local else moment + timedelta(days=7)


WINDOW_SCENARIOS: tuple[WindowScenario, ...] = (
    WindowScenario("work-morning", "Вс, 10:00 — рабочий день до сводки", 6, time(10, 0)),
    WindowScenario("work-afternoon", "Вс, 16:00 — рабочий день после сводки", 6, time(16, 0)),
    WindowScenario("friday", "Пт, 12:00 — выходной", 4, time(12, 0)),
    WindowScenario("saturday", "Сб, 10:00 — выходной", 5, time(10, 0)),
    WindowScenario("night-before-day-off", "Чт, 22:00 — ночь перед выходным", 3, time(22, 0)),
    WindowScenario("night-before-workday", "Сб, 22:00 — ночь перед рабочим днём", 5, time(22, 0)),
    WindowScenario("quiet-ends", "Пт, 07:29 — за минуту до конца тихих часов", 4, time(7, 29)),
    WindowScenario("quiet-ended", "Пт, 07:30 — тихие часы кончились", 4, time(7, 30)),
)


def scenario_by_id(scenario_id: str) -> WindowScenario | None:
    return next((s for s in WINDOW_SCENARIOS if s.id == scenario_id), None)


def parse_time(value: str | time) -> time:
    """«15:00» (or a `time`) to a `time`; anything else is a ValueError."""
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    try:
        hours, minutes = value.split(":")
        return time(int(hours), int(minutes))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"time must look like 15:00, got {value!r}") from exc


def format_time(value: time) -> str:
    return f"{value:%H:%M}"
