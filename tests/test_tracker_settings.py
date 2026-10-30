"""Tracker core: the settings the owner changes on one page — read all at once, stored all at once.

Driven through the facade only (fake clock, in-memory SQLite). `settings()` gives every setting with the zone list and
the line «Сейчас»; `save_settings()` takes the form as it came, as texts, and stores all six values or none. The
owner's clock is Asia/Jerusalem: UTC+2 from 25 Oct 2026 (the tests at the end of October and in November).
"""

import asyncio
import logging
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.tracker import delivery, zones
from app.tracker.core import SettingsChange, SettingsRefused, Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import SettingRecord

JERUSALEM = ZoneInfo("Asia/Jerusalem")
MINUS = "−"
CLASH = "Час сводки 22:00 попадает в тихие часы 21:00–07:30 — сводка не придёт. Сдвиньте час сводки или тихие часы"


def moment(day, hour, minute=0, month=11):
    """The owner's wall clock as the naive UTC moment the rules take (2026)."""
    aware = datetime(2026, month, day, hour, minute, tzinfo=JERUSALEM)
    return aware.astimezone(timezone.utc).replace(tzinfo=None)


class FakeClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class FakeSender:
    async def send(self, message, actions=()):
        pass


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def clock():
    return FakeClock(datetime(2026, 10, 29, 22, 10, tzinfo=JERUSALEM).astimezone(timezone.utc))  # Thursday 22:10


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def tracker(session_factory, clock):
    return Tracker(session_factory, clock=clock, sender=FakeSender(), sources={}, default_tz=JERUSALEM)


def form(**override):
    values = {
        "tz_name": "Asia/Tokyo",
        "workdays": [0, 1],
        "summary_at": "16:00",
        "quiet_from": "22:00",
        "quiet_until": "06:00",
        "part_gap_weeks": "8",
    }
    return SettingsChange(**{**values, **override})


def stored(session_factory):
    with session_factory() as session:
        return {r.key: r.value for r in session.scalars(select(SettingRecord))}


# --- reading ----------------------------------------------------------------------------------------


def test_on_an_empty_database_every_setting_is_the_default_and_no_zone_is_chosen(tracker):
    view = run(tracker.settings())

    assert view.tz_name is None
    assert view.default_tz_name == "Asia/Jerusalem"
    assert view.default_label == "Как в файле настроек запуска: Asia/Jerusalem (UTC+2)"
    assert view.workdays == delivery.DEFAULT_WORKDAYS
    assert (view.summary_at, view.quiet_from, view.quiet_until) == (
        delivery.format_time(delivery.DEFAULT_SUMMARY_AT),
        delivery.format_time(delivery.DEFAULT_QUIET_FROM),
        delivery.format_time(delivery.DEFAULT_QUIET_UNTIL),
    )
    assert view.part_gap_weeks == 6


def test_what_was_saved_is_what_settings_reads(tracker):
    run(tracker.save_settings(form()))

    view = run(tracker.settings())

    assert view.tz_name == "Asia/Tokyo"
    assert view.workdays == frozenset({0, 1})
    assert (view.summary_at, view.quiet_from, view.quiet_until, view.part_gap_weeks) == ("16:00", "22:00", "06:00", 8)


def test_the_rules_the_core_works_by_are_the_saved_ones(tracker):
    run(tracker.save_settings(form()))

    rules = run(tracker.delivery_rules())

    assert (rules.tz, rules.workdays) == (ZoneInfo("Asia/Tokyo"), frozenset({0, 1}))
    assert (rules.summary_at, rules.quiet_from, rules.quiet_until) == (time(16, 0), time(22, 0), time(6, 0))
    assert run(tracker.part_gap_weeks()) == 8


def test_a_core_made_without_a_zone_of_the_launch_file_says_utc(session_factory, clock):
    tracker = Tracker(session_factory, clock=clock, sender=FakeSender(), sources={})

    view = run(tracker.settings())

    assert view.default_tz_name == "UTC"
    assert view.default_label == "Как в файле настроек запуска: UTC"


def test_the_line_now_is_made_of_the_stored_rules_and_the_clock(tracker, clock):
    run(tracker.set_delivery_rules(workdays=[6, 0, 1, 2, 3], summary_at="15:00", quiet_from="21:00", quiet_until="07:30"))

    assert run(tracker.settings()).now_line == "Сейчас чт, 29 окт, 22:10 — тихие часы: событие придёт сводкой завтра в 07:30"

    clock.now = datetime(2026, 11, 1, 16, 0, tzinfo=JERUSALEM).astimezone(timezone.utc)
    assert run(tracker.settings()).now_line == "Сейчас вс, 1 ноя, 16:00 — рабочий день: событие придёт сразу"


# --- the time zone list -----------------------------------------------------------------------------


def test_the_list_has_the_real_zones_and_not_the_old_synonyms():
    names = zones.listed_names()

    assert "Asia/Jerusalem" in names and "UTC" in names and "America/Argentina/Buenos_Aires" in names
    for old in ("US/Eastern", "posixrules", "Etc/GMT+3", "EST", "localtime"):
        assert old not in names
    assert list(names) == sorted(names)


def test_a_zone_reads_with_the_offset_of_the_moment(tracker, clock):
    def labels():
        return {z.name: z.label for z in run(tracker.settings()).zones}

    winter = labels()
    assert winter["Asia/Jerusalem"] == "Asia/Jerusalem (UTC+2)"
    assert winter["Asia/Kolkata"] == "Asia/Kolkata (UTC+5:30)"
    assert winter["America/Sao_Paulo"] == f"America/Sao_Paulo (UTC{MINUS}3)"
    assert winter["UTC"] == "UTC"

    clock.now = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)  # Israel is on summer time
    assert labels()["Asia/Jerusalem"] == "Asia/Jerusalem (UTC+3)"
    assert run(tracker.settings()).default_label == "Как в файле настроек запуска: Asia/Jerusalem (UTC+3)"


def test_a_zone_with_no_offset_reads_utc_plus_zero():
    assert zones.label("Europe/London", datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)) == "Europe/London (UTC+0)"


def test_a_stored_zone_outside_the_list_is_one_more_choice_and_stays_chosen(tracker, session_factory):
    with session_factory() as session:  # written by hand
        session.add(SettingRecord(key="timezone", value="US/Eastern"))
        session.commit()

    view = run(tracker.settings())

    assert view.tz_name == "US/Eastern"
    assert "US/Eastern (UTC−4)" in [z.label for z in view.zones]  # summer time of the USA lasts to 1 Nov
    assert "Asia/Jerusalem" in [z.name for z in view.zones]
    run(tracker.save_settings(form(tz_name="US/Eastern")))  # saving the page does not change it
    assert run(tracker.settings()).tz_name == "US/Eastern"


def test_a_stored_zone_that_is_not_a_zone_reads_as_no_choice_and_the_log_says_so_once(tracker, session_factory, caplog):
    with session_factory() as session:
        session.add(SettingRecord(key="timezone", value="Mars/Olympus"))
        session.commit()

    with caplog.at_level(logging.WARNING):
        views = [run(tracker.settings()) for _ in range(3)]
        rules = run(tracker.delivery_rules())
        feed = run(tracker.feed())

    assert all(v.tz_name is None for v in views)
    assert "Mars/Olympus" not in [z.name for z in views[0].zones]
    assert rules.tz == JERUSALEM  # the zone of the launch file works
    assert feed.today == datetime(2026, 10, 29).date()
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "Mars/Olympus" in r.getMessage()]
    assert len(warnings) == 1


def test_a_stored_zone_that_is_not_even_a_text_reads_as_no_choice(tracker, session_factory):
    with session_factory() as session:
        session.add(SettingRecord(key="timezone", value=5))
        session.commit()

    assert run(tracker.settings()).tz_name is None
    assert run(tracker.delivery_rules()).tz == JERUSALEM


# --- saving -----------------------------------------------------------------------------------------


def test_an_empty_zone_takes_the_record_away_and_the_launch_file_works_again(tracker, session_factory):
    run(tracker.save_settings(form(tz_name="Asia/Tokyo")))
    assert stored(session_factory)["timezone"] == "Asia/Tokyo"

    run(tracker.save_settings(form(tz_name="")))

    assert "timezone" not in stored(session_factory)
    assert run(tracker.settings()).tz_name is None
    assert run(tracker.delivery_rules()).tz == JERUSALEM


def test_an_empty_set_of_working_days_is_saved_every_day_is_a_day_off(tracker):
    run(tracker.save_settings(form(workdays=[], tz_name="", quiet_from="23:00", quiet_until="05:00")))

    view = run(tracker.settings())

    assert view.workdays == frozenset()
    assert view.now_line == "Сейчас чт, 29 окт, 22:10 — выходной: событие придёт сразу"


def test_working_days_given_twice_or_out_of_order_are_stored_once_in_order(tracker, session_factory):
    run(tracker.save_settings(form(workdays=(4, 1, 4, 0))))

    assert stored(session_factory)["workdays"] == [0, 1, 4]


def test_equal_quiet_hours_mean_none_and_then_any_summary_hour_is_fine(tracker):
    run(tracker.save_settings(form(summary_at="22:00", quiet_from="21:00", quiet_until="21:00")))

    view = run(tracker.settings())

    assert (view.summary_at, view.quiet_from, view.quiet_until) == ("22:00", "21:00", "21:00")


@pytest.mark.parametrize("written", ["7:30", "07:30", " 7:30 "])
def test_a_time_with_one_or_two_digits_of_hour_is_the_same_time(tracker, written):
    run(tracker.save_settings(form(quiet_from="22:00", quiet_until=written)))

    assert run(tracker.settings()).quiet_until == "07:30"


def test_the_summary_hour_at_midnight_is_saved(tracker):
    run(tracker.save_settings(form(summary_at="00:00", quiet_from="01:00", quiet_until="06:00")))

    assert run(tracker.settings()).summary_at == "00:00"


def test_saving_what_is_already_stored_changes_nothing(tracker, session_factory):
    run(tracker.save_settings(form()))
    before = stored(session_factory)

    run(tracker.save_settings(form()))

    assert stored(session_factory) == before


REFUSALS = [
    pytest.param({"tz_name": "Mars/Olympus"}, "timezone", "Такого часового пояса нет — выберите его из списка", id="no-zone"),
    pytest.param({"tz_name": "asia/tokyo"}, "timezone", "Такого часового пояса нет — выберите его из списка", id="zone-case"),
    pytest.param({"workdays": [7]}, "workdays", "Рабочие дни: выберите дни недели из списка", id="day-7"),
    pytest.param({"workdays": [-1]}, "workdays", "Рабочие дни: выберите дни недели из списка", id="day-minus-1"),
    pytest.param({"workdays": [True]}, "workdays", "Рабочие дни: выберите дни недели из списка", id="day-bool"),
    *[
        pytest.param({"summary_at": bad}, "summary_at", "Час сводки: время пишется так — 15:00", id=f"summary-{bad!r}")
        for bad in ("24:00", "15-00", "", "abc", "15:60", "15:0", "15:00:00", "٣:٣٠")
    ],
    *[
        pytest.param({field: bad}, "quiet", "Тихие часы: время пишется так — 21:00", id=f"{field}-{bad!r}")
        for field in ("quiet_from", "quiet_until")
        for bad in ("24:00", "15-00", "", "abc")
    ],
    pytest.param({"summary_at": "22:00", "quiet_from": "21:00", "quiet_until": "07:30"}, "summary_at", CLASH, id="clash"),
    pytest.param({"summary_at": "06:59", "quiet_from": "21:00", "quiet_until": "07:30"}, "summary_at",
                 CLASH.replace("22:00", "06:59"), id="clash-after-midnight"),
    *[
        pytest.param({"part_gap_weeks": bad}, "part_gap_weeks", "Части сезона: число недель — целое, от 1 до 52",
                     id=f"weeks-{bad!r}")
        for bad in ("0", "53", "2.5", "", "abc", "-1", "٣", "1000", "9" * 5000)
    ],
]


@pytest.mark.parametrize("override, field, text", REFUSALS)
def test_a_wrong_value_is_refused_with_its_field_and_nothing_is_stored(tracker, session_factory, override, field, text):
    run(tracker.save_settings(form()))
    before = stored(session_factory)

    with pytest.raises(SettingsRefused) as refused:
        run(tracker.save_settings(form(**{"tz_name": "Asia/Jerusalem", "workdays": [3], "part_gap_weeks": "3", **override})))

    assert (refused.value.field, refused.value.text) == (field, text)
    assert stored(session_factory) == before  # not even the correct fields went in


def test_a_refusal_on_an_empty_database_stores_nothing_at_all(tracker, session_factory):
    with pytest.raises(SettingsRefused):
        run(tracker.save_settings(form(part_gap_weeks="0")))

    assert stored(session_factory) == {}


def test_the_first_wrong_field_in_the_order_of_the_form_is_the_one_named(tracker):
    with pytest.raises(SettingsRefused) as refused:
        run(tracker.save_settings(form(summary_at="abc", quiet_from="abc", part_gap_weeks="0")))
    assert refused.value.field == "summary_at"

    with pytest.raises(SettingsRefused) as refused:
        run(tracker.save_settings(form(tz_name="Mars/Olympus", summary_at="abc")))
    assert refused.value.field == "timezone"

    with pytest.raises(SettingsRefused) as refused:
        run(tracker.save_settings(form(quiet_until="abc", part_gap_weeks="0")))
    assert refused.value.field == "quiet"


def test_rules_stored_before_the_check_are_shown_as_they_are_and_saving_demands_a_fix(tracker, session_factory):
    run(tracker.save_settings(form()))
    with session_factory() as session:  # a summary hour inside the quiet hours, as an earlier version allowed
        session.get(SettingRecord, "summary_at").value = "22:30"
        session.commit()

    assert run(tracker.settings()).summary_at == "22:30"
    with pytest.raises(SettingsRefused) as refused:
        run(tracker.save_settings(form(summary_at="22:30")))
    assert refused.value.field == "summary_at"


def test_the_two_older_methods_agree_with_the_form_on_the_rules_they_share(tracker):
    with pytest.raises(ValueError, match="22:00 попадает в тихие часы 21:00–07:30"):
        run(tracker.set_delivery_rules(summary_at="22:00", quiet_from="21:00", quiet_until="07:30"))
    with pytest.raises(SettingsRefused, match="22:00 попадает в тихие часы 21:00–07:30"):
        run(tracker.save_settings(form(summary_at="22:00", quiet_from="21:00", quiet_until="07:30")))


@pytest.mark.parametrize("weeks", [0, -1, 53, 1000])
def test_the_threshold_of_parts_is_from_one_to_52_weeks_in_the_older_method_too(tracker, weeks):
    with pytest.raises(ValueError):
        run(tracker.set_part_gap_weeks(weeks))

    assert run(tracker.part_gap_weeks()) == 6


@pytest.mark.parametrize("weeks", [1, 52])
def test_the_edges_of_the_threshold_are_allowed(tracker, weeks):
    run(tracker.set_part_gap_weeks(weeks))
    assert run(tracker.part_gap_weeks()) == weeks

    run(tracker.save_settings(form(part_gap_weeks=str(weeks))))
    assert run(tracker.settings()).part_gap_weeks == weeks


def test_two_saves_in_a_row_the_last_one_wins_with_nothing_of_the_first(tracker, session_factory):
    run(tracker.save_settings(form(tz_name="Asia/Tokyo", workdays=[0], summary_at="09:00", part_gap_weeks="10")))
    run(tracker.save_settings(form(tz_name="", workdays=[2, 3], summary_at="17:00", part_gap_weeks="3")))

    assert stored(session_factory) == {
        "workdays": [2, 3], "summary_at": "17:00", "quiet_from": "22:00", "quiet_until": "06:00", "part_gap_weeks": 3,
    }


def test_two_saves_at_once_leave_one_whole_form_not_halves_of_both(tracker, session_factory):
    first = form(tz_name="Asia/Tokyo", workdays=[0], summary_at="09:00", quiet_from="23:00", quiet_until="05:00", part_gap_weeks="10")
    second = form(tz_name="", workdays=[2, 3], summary_at="17:00", quiet_from="20:00", quiet_until="07:00", part_gap_weeks="3")

    async def both():
        await asyncio.gather(tracker.save_settings(first), tracker.save_settings(second))

    run(both())

    def as_stored(change):
        return {
            **({"timezone": change.tz_name} if change.tz_name else {}),
            "workdays": sorted(change.workdays), "summary_at": change.summary_at, "quiet_from": change.quiet_from,
            "quiet_until": change.quiet_until, "part_gap_weeks": int(change.part_gap_weeks),
        }

    assert stored(session_factory) in (as_stored(first), as_stored(second))


# --- the line «Сейчас» -------------------------------------------------------------------------------


DEFAULT_RULES = delivery.DeliveryRules(tz=JERUSALEM)  # the owner's week: Sunday to Thursday, summary 15:00, quiet 21:00–07:30


@pytest.mark.parametrize(
    "when, line",
    [
        ((29, 22, 10, 10), "Сейчас чт, 29 окт, 22:10 — тихие часы: событие придёт сводкой завтра в 07:30"),
        ((31, 22, 0, 10), "Сейчас сб, 31 окт, 22:00 — тихие часы: событие придёт сводкой завтра в 15:00"),
        ((1, 10, 0, 11), "Сейчас вс, 1 ноя, 10:00 — рабочий день, до часа сводки: событие придёт сводкой в 15:00"),
        ((1, 16, 0, 11), "Сейчас вс, 1 ноя, 16:00 — рабочий день: событие придёт сразу"),
        ((30, 12, 0, 10), "Сейчас пт, 30 окт, 12:00 — выходной: событие придёт сразу"),
        ((30, 2, 0, 10), "Сейчас пт, 30 окт, 02:00 — тихие часы: событие придёт сводкой в 07:30"),
    ],
)
def test_the_line_now_for_the_six_moments_of_the_owners_week(when, line):
    day, hour, minute, month = when

    assert delivery.now_line(DEFAULT_RULES, moment(day, hour, minute, month)) == line


def test_the_line_now_with_no_working_days_says_day_off():
    rules = delivery.DeliveryRules(tz=JERUSALEM, workdays=frozenset())

    line = delivery.now_line(rules, moment(1, 10, 0))

    assert line == "Сейчас вс, 1 ноя, 10:00 — выходной: событие придёт сразу"


def test_the_summary_hour_at_midnight_leaves_no_working_morning():
    rules = delivery.DeliveryRules(tz=JERUSALEM, summary_at=time(0, 0), quiet_from=time(1, 0), quiet_until=time(6, 0))

    assert delivery.now_line(rules, moment(1, 10, 0)) == "Сейчас вс, 1 ноя, 10:00 — рабочий день: событие придёт сразу"
    assert delivery.now_line(rules, moment(1, 0, 30)) == "Сейчас вс, 1 ноя, 00:30 — рабочий день: событие придёт сразу"
    assert delivery.now_line(rules, moment(1, 3, 0)) == "Сейчас вс, 1 ноя, 03:00 — тихие часы: событие придёт сводкой в 06:00"


def test_quiet_hours_that_do_not_cross_midnight_are_told_too():
    rules = delivery.DeliveryRules(tz=JERUSALEM, quiet_from=time(1, 0), quiet_until=time(6, 0))

    assert delivery.now_line(rules, moment(30, 3, 0, 10)) == "Сейчас пт, 30 окт, 03:00 — тихие часы: событие придёт сводкой в 06:00"
    assert delivery.now_line(rules, moment(30, 7, 0, 10)) == "Сейчас пт, 30 окт, 07:00 — выходной: событие придёт сразу"


def test_quiet_hours_across_midnight_before_a_working_morning_wait_for_the_summary():
    line = delivery.now_line(DEFAULT_RULES, moment(1, 23, 0, 11))  # Sunday night: Monday is a working day

    assert line == "Сейчас вс, 1 ноя, 23:00 — тихие часы: событие придёт сводкой завтра в 15:00"


def test_a_wait_of_more_than_a_day_names_the_day(caplog):
    # a summary hour inside the quiet hours, as an earlier version let the owner store: the event keeps waiting
    rules = delivery.DeliveryRules(tz=JERUSALEM, summary_at=time(22, 0))

    with caplog.at_level(logging.WARNING):
        line = delivery.now_line(rules, moment(31, 22, 30, 10))

    assert line == "Сейчас сб, 31 окт, 22:30 — тихие часы: событие придёт сводкой в пн, 2 ноя в 22:00"
