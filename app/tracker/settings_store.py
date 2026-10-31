"""The owner's settings in the `settings` table: the break that splits a season into parts, the delivery rules, the time
zone, the platforms of the games and the country of the stores. Each is read where it is needed, so a change applies at
once. The settings page reads them all (`settings`) and stores all of them at once (`save_settings`).

Each field has one check (`check_…`), shared by the form, by the older methods and by the reading of what is stored: a
value that fails it is a `ValueError` whose text is the phrase for the owner; the form turns it into `SettingsRefused`.
"""

import asyncio
import logging
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import time, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.tracker import delivery, zones
from app.tracker import seasons as season_logic
from app.tracker.context import CoreContext
from app.tracker.errors import SettingsField, SettingsRefused
from app.tracker.models import SettingRecord
from app.tracker.platforms import DEFAULT_COUNTRY, DEFAULT_PLATFORMS, PLATFORMS, STORE_COUNTRIES, Platform
from app.tracker.results import Choice, SettingsChange, SettingsView

logger = logging.getLogger(__name__)

PART_GAP_SETTING = "part_gap_weeks"
DEFAULT_PART_GAP_WEEKS = season_logic.DEFAULT_PART_GAP // timedelta(weeks=1)  # the default lives in `seasons`
MAX_PART_GAP_WEEKS = 52

# settings of the delivery rules (absent: the default of `delivery`; the time zone falls back to the one the core was given)
TIMEZONE_SETTING = "timezone"
WORKDAYS_SETTING = "workdays"  # weekday numbers, Monday is 0
SUMMARY_AT_SETTING = "summary_at"  # "15:00"
QUIET_FROM_SETTING = "quiet_from"
QUIET_UNTIL_SETTING = "quiet_until"
_TIME_FIELDS = {  # the settings that hold a time of day, and the field of `DeliveryRules` each one fills
    SUMMARY_AT_SETTING: "summary_at", QUIET_FROM_SETTING: "quiet_from", QUIET_UNTIL_SETTING: "quiet_until"
}
MY_PLATFORMS_SETTING = "my_platforms"  # the values of `Platform`
STORE_COUNTRY_SETTING = "store_country"  # the code of the country
_WEEKS = re.compile(r"[0-9]{1,3}")

SUMMARY_AT_PHRASE = "Час сводки: время пишется так — 15:00"
QUIET_PHRASE = "Тихие часы: время пишется так — 21:00"


class _Bad(ValueError):
    """A value a field does not take. `text` is the phrase for the owner."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.text = text


def check_zone(name: object) -> str:
    """A name of `zones.known_names()`; the synonyms are in it, `posixrules` and the like are not."""
    if not isinstance(name, str) or name not in zones.known_names():
        raise _Bad("Такого часового пояса нет — выберите его из списка")
    return name


def check_workdays(days: object) -> list[int]:
    """Weekday numbers from 0 (Monday) to 6, each once, in order; none at all is allowed."""
    try:
        ordered = sorted(set(days))  # type: ignore[arg-type]
    except TypeError:  # not a collection, or numbers mixed with texts
        ordered = [None]
    if any(not isinstance(d, int) or isinstance(d, bool) or not 0 <= d <= 6 for d in ordered):
        raise _Bad("Рабочие дни: выберите дни недели из списка")
    return ordered


def check_clock(value: object, phrase: str) -> time:
    """A time of day written «7:30» or «07:30» (or a `time`); `phrase` is what the owner reads when it is not."""
    try:
        return delivery.parse_time(value)  # type: ignore[arg-type]
    except ValueError:
        raise _Bad(phrase) from None


def check_part_gap_weeks(value: object) -> int:
    """Whole weeks from one to `MAX_PART_GAP_WEEKS`: a number, or the text of the form."""
    if isinstance(value, str):
        value = int(value.strip()) if _WEEKS.fullmatch(value.strip()) else None
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= MAX_PART_GAP_WEEKS:
        raise _Bad(f"Части сезона: число недель — целое, от 1 до {MAX_PART_GAP_WEEKS}")
    return value


def check_platforms(values: object) -> list[str]:
    """At least one platform, all of the table: their values, in the order of the table."""
    try:
        chosen = set(values) if isinstance(values, (list, tuple, set, frozenset)) else {None}
    except TypeError:  # a list inside
        chosen = {None}
    if not chosen:
        raise _Bad("Мои платформы: отметьте хотя бы одну платформу")
    if not chosen <= {platform.value for platform in PLATFORMS}:
        raise _Bad("Мои платформы: выберите платформы из списка")
    return [platform.value for platform in PLATFORMS if platform.value in chosen]


def check_country(code: object) -> str:
    """A code of `STORE_COUNTRIES`."""
    if not isinstance(code, str) or code not in STORE_COUNTRIES:
        raise _Bad("Страна магазинов: выберите страну из списка")
    return code


@contextmanager
def _refusing(field: SettingsField) -> Iterator[None]:
    """A value the field does not take is a refusal of the form that names the field."""
    try:
        yield
    except _Bad as bad:
        raise SettingsRefused(field, bad.text) from None


class SettingsStore:
    def __init__(self, ctx: CoreContext) -> None:
        self.ctx = ctx
        self._spoiled: set[tuple[str, str]] = set()  # stored values that are not valid, as the log has told: once each

    def _spoiled_once(self, key: str, value: Any, works: str) -> None:
        mark = (key, repr(value))
        if mark not in self._spoiled:
            self._spoiled.add(mark)
            logger.warning("the stored %s %r is not valid; %s works", key, value, works)

    # --- read inside a session someone else opened ----------------------------------------------

    @staticmethod
    def part_gap_weeks_in(session) -> int:
        record = session.get(SettingRecord, PART_GAP_SETTING)
        return record.value if record is not None else DEFAULT_PART_GAP_WEEKS

    @classmethod
    def part_gap(cls, session) -> timedelta:
        return timedelta(weeks=cls.part_gap_weeks_in(session))

    def stored_zone(self, session) -> str | None:
        """The name of the zone chosen in the settings; None when none is chosen. A stored value that is not a zone of
        the list (`check_zone`) reads as «none chosen» (it would otherwise break the feed and the queue), and the log
        says so once."""
        record = session.get(SettingRecord, TIMEZONE_SETTING)
        if record is None:
            return None
        try:
            return check_zone(record.value)
        except _Bad:
            self._spoiled_once(TIMEZONE_SETTING, record.value, "the zone of the launch file")
            return None

    def time_zone(self, session) -> tzinfo:
        """The owner's time zone: the stored setting, else the one the core was given. Read where it is needed, so a
        change applies at once."""
        name = self.stored_zone(session)
        return ZoneInfo(name) if name is not None else self.ctx.default_tz

    def my_platforms_in(self, session) -> tuple[Platform, ...]:
        """The platforms the owner plays on, in the order of the table. Nothing stored, or a stored value that is not a
        non-empty set of platforms: ПК and PS5 (the log says so once)."""
        record = session.get(SettingRecord, MY_PLATFORMS_SETTING)
        if record is None:
            return DEFAULT_PLATFORMS
        try:
            return tuple(Platform(value) for value in check_platforms(record.value))
        except _Bad:
            self._spoiled_once(MY_PLATFORMS_SETTING, record.value, "the default platforms")
            return DEFAULT_PLATFORMS

    def store_country_in(self, session) -> str:
        """The code of the country of the stores; nothing stored or not a country of the table: Israel."""
        record = session.get(SettingRecord, STORE_COUNTRY_SETTING)
        if record is None:
            return DEFAULT_COUNTRY
        try:
            return check_country(record.value)
        except _Bad:
            self._spoiled_once(STORE_COUNTRY_SETTING, record.value, "the default country")
            return DEFAULT_COUNTRY

    def rules(self, session) -> delivery.DeliveryRules:
        keys = (WORKDAYS_SETTING, SUMMARY_AT_SETTING, QUIET_FROM_SETTING, QUIET_UNTIL_SETTING)
        stored = {r.key: r.value for r in session.scalars(select(SettingRecord).where(SettingRecord.key.in_(keys)))}
        workdays = stored.get(WORKDAYS_SETTING, delivery.DEFAULT_WORKDAYS)
        return delivery.DeliveryRules(
            tz=self.time_zone(session),
            workdays=frozenset(workdays),
            summary_at=delivery.parse_time(stored.get(SUMMARY_AT_SETTING, delivery.DEFAULT_SUMMARY_AT)),
            quiet_from=delivery.parse_time(stored.get(QUIET_FROM_SETTING, delivery.DEFAULT_QUIET_FROM)),
            quiet_until=delivery.parse_time(stored.get(QUIET_UNTIL_SETTING, delivery.DEFAULT_QUIET_UNTIL)),
        )

    # --- the public settings --------------------------------------------------------------------

    async def part_gap_weeks(self) -> int:
        """Weeks of break between two episodes of a season after which the season is split into parts."""
        return await asyncio.to_thread(self._load_part_gap_weeks)

    def _load_part_gap_weeks(self) -> int:
        with self.ctx.session_factory() as session:
            return self.part_gap_weeks_in(session)

    async def set_part_gap_weeks(self, weeks: int) -> None:
        """Change the break that splits a season into parts (1 to 52 weeks, a ValueError otherwise). Parts are worked
        out from the dates, so the new value applies to cards and events from now on without touching the stored
        episodes."""
        await asyncio.to_thread(self._store, {PART_GAP_SETTING: check_part_gap_weeks(weeks)})

    async def delivery_rules(self) -> delivery.DeliveryRules:
        """The owner's time zone, working days, summary hour and quiet hours; what is not set is the default."""
        return await asyncio.to_thread(self._load_delivery_rules)

    def _load_delivery_rules(self) -> delivery.DeliveryRules:
        with self.ctx.session_factory() as session:
            return self.rules(session)

    async def set_delivery_rules(
        self,
        *,
        tz_name: str | None = None,
        workdays: Sequence[int] | None = None,
        summary_at: time | str | None = None,
        quiet_from: time | str | None = None,
        quiet_until: time | str | None = None,
    ) -> None:
        """Change the given rules (the others stay). Nothing is stored when any value is wrong (a ValueError).

        `workdays` are weekday numbers, Monday is 0; none at all is allowed (every day is a day off). Equal
        `quiet_from` and `quiet_until` mean no quiet hours. A summary hour inside the quiet hours is refused (the rules are
        checked whole, with what is stored): the bot would stay silent on working days. The new rules apply to what is
        already queued."""
        new: dict[str, Any] = {}  # the settings to store, as stored
        if tz_name is not None:
            new[TIMEZONE_SETTING] = check_zone(tz_name)
        if workdays is not None:
            new[WORKDAYS_SETTING] = check_workdays(workdays)
        for key, value, phrase in (
            (SUMMARY_AT_SETTING, summary_at, SUMMARY_AT_PHRASE),
            (QUIET_FROM_SETTING, quiet_from, QUIET_PHRASE),
            (QUIET_UNTIL_SETTING, quiet_until, QUIET_PHRASE),
        ):
            if value is not None:
                new[key] = delivery.format_time(check_clock(value, phrase))
        await asyncio.to_thread(self._check_and_store, new)

    # --- the settings page ----------------------------------------------------------------------

    async def settings(self) -> SettingsView:
        """Every setting in one read, with the choices and the line «Сейчас» (by the stored rules)."""
        return await asyncio.to_thread(self._load_settings)

    def _load_settings(self) -> SettingsView:
        now = self.ctx.clock()
        with self.ctx.session_factory() as session:
            rules = self.rules(session)
            tz_name = self.stored_zone(session)
            weeks = self.part_gap_weeks_in(session)
            platforms = self.my_platforms_in(session)
            country = self.store_country_in(session)
        default_name = getattr(self.ctx.default_tz, "key", None) or zones.UTC
        summary_at, quiet_from, quiet_until = (
            delivery.format_time(at) for at in (rules.summary_at, rules.quiet_from, rules.quiet_until)
        )
        return SettingsView(
            tz_name=tz_name,
            default_tz_name=default_name,
            zones=zones.options(now, tz_name),
            default_label=f"Как в файле настроек запуска: {zones.label(default_name, now)}",
            workdays=rules.workdays,
            summary_at=summary_at,
            quiet_from=quiet_from,
            quiet_until=quiet_until,
            part_gap_weeks=weeks,
            saved=SettingsChange(
                tz_name=tz_name or "", workdays=sorted(rules.workdays), summary_at=summary_at, quiet_from=quiet_from,
                quiet_until=quiet_until, part_gap_weeks=str(weeks), my_platforms=[p.value for p in platforms],
                store_country=country,
            ),
            platforms=tuple(Choice(platform.value, info.settings_label) for platform, info in PLATFORMS.items()),
            countries=tuple(Choice(code, info.label) for code, info in STORE_COUNTRIES.items()),
            now_line=rules.now_line(self.ctx.now()),
        )

    async def save_settings(self, change: SettingsChange) -> None:
        """Store the whole form: all eight settings or, when a value is wrong, none (`SettingsRefused` names the first
        wrong one, in the order of the form). The new rules apply from the next pass of the delivery queue."""
        await asyncio.to_thread(self._save_settings, change)

    def _save_settings(self, change: SettingsChange) -> None:
        values = self._checked(change)
        with self.ctx.write_session() as session:  # one transaction: two forms at once never leave half of each
            self._put(session, values)
            session.commit()

    @staticmethod
    def _checked(change: SettingsChange) -> dict[str, Any]:
        """The settings to store, as stored (None: no record, the default works), or the first refusal."""
        with _refusing(SettingsField.TIMEZONE):
            if change.tz_name:  # «»: the zone of the launch file
                check_zone(change.tz_name)
        with _refusing(SettingsField.WORKDAYS):
            days = check_workdays(change.workdays)
        with _refusing(SettingsField.SUMMARY_AT):
            summary_at = check_clock(change.summary_at, SUMMARY_AT_PHRASE)
        with _refusing(SettingsField.QUIET):
            quiet_from = check_clock(change.quiet_from, QUIET_PHRASE)
            quiet_until = check_clock(change.quiet_until, QUIET_PHRASE)
        try:
            delivery.DeliveryRules(summary_at=summary_at, quiet_from=quiet_from, quiet_until=quiet_until).check()
        except ValueError as exc:
            clash = str(exc)
            raise SettingsRefused(
                SettingsField.SUMMARY_AT,
                f"{clash[:1].upper()}{clash[1:]} — сводка не придёт. Сдвиньте час сводки или тихие часы",
            ) from exc
        with _refusing(SettingsField.PART_GAP_WEEKS):
            weeks = check_part_gap_weeks(change.part_gap_weeks)
        with _refusing(SettingsField.MY_PLATFORMS):
            platforms = check_platforms(change.my_platforms)
        with _refusing(SettingsField.STORE_COUNTRY):
            country = check_country(change.store_country)
        return {
            TIMEZONE_SETTING: change.tz_name or None,
            WORKDAYS_SETTING: days,
            SUMMARY_AT_SETTING: delivery.format_time(summary_at),
            QUIET_FROM_SETTING: delivery.format_time(quiet_from),
            QUIET_UNTIL_SETTING: delivery.format_time(quiet_until),
            PART_GAP_SETTING: weeks,
            MY_PLATFORMS_SETTING: platforms,
            STORE_COUNTRY_SETTING: country,
        }

    def _check_and_store(self, new: dict[str, Any]) -> None:
        """Store `new` only when the rules it makes (the stored ones with these values over them) can send a summary.
        Read, check and write are in one write session: two changes cannot both pass the check."""
        with self.ctx.write_session() as session:
            changes = {field: delivery.parse_time(new[key]) for key, field in _TIME_FIELDS.items() if key in new}
            if changes:  # rules stored before the check existed may clash; changing something else must still work
                replace(self.rules(session), **changes).check()
            self._put(session, new)
            session.commit()

    def _store(self, values: dict[str, Any]) -> None:
        with self.ctx.write_session() as session:
            self._put(session, values)
            session.commit()

    @staticmethod
    def _put(session, values: dict[str, Any]) -> None:
        for key, value in values.items():
            record = session.get(SettingRecord, key)
            if value is None:  # not set: the record goes and the default works again
                if record is not None:
                    session.delete(record)
            elif record is None:
                session.add(SettingRecord(key=key, value=value))
            else:
                record.value = value
