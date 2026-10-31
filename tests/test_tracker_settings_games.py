"""Part 6.1, ticket 02: the platforms and the country of the stores in the settings, and one check per field (KI-34).

`platforms.py` is the table of the platforms and the countries; `my_platforms` and `store_country` are read where they
are needed and saved with the other six settings in one transaction. The checks are shared by the form
(`save_settings`), by the older methods (`set_delivery_rules`, `set_part_gap_weeks`) and by the reading of what is
stored. Driven through the facade (fake clock, in-memory SQLite).
"""

import asyncio
import logging
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.tracker import delivery
from app.tracker.core import SettingsChange, SettingsField, SettingsRefused, Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import DeliveryItem, Event, SettingRecord
from app.tracker.platforms import (
    DEFAULT_COUNTRY, DEFAULT_PLATFORMS, PLATFORMS, STORE_COUNTRIES, OlderPlatform, Platform,
)

JERUSALEM = ZoneInfo("Asia/Jerusalem")
NOW = datetime(2026, 10, 29, 20, 10, tzinfo=timezone.utc)  # Thursday 22:10 in Jerusalem


class FakeSender:
    async def send(self, message, actions=()):
        pass


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def tracker(session_factory):
    return Tracker(session_factory, clock=lambda: NOW, sender=FakeSender(), sources={}, default_tz=JERUSALEM)


def form(**override):
    values = {
        "tz_name": "Asia/Tokyo", "workdays": [0, 1], "summary_at": "16:00", "quiet_from": "22:00", "quiet_until": "06:00",
        "part_gap_weeks": "8", "my_platforms": ["pc", "xbox_series"], "store_country": "us",
    }
    return SettingsChange(**{**values, **override})


def stored(session_factory):
    with session_factory() as session:
        return {r.key: r.value for r in session.scalars(select(SettingRecord))}


def spoil(session_factory, key, value):
    with session_factory() as session:
        session.add(SettingRecord(key=key, value=value))
        session.commit()


def warnings_about(caplog, word):
    return [r for r in caplog.records if r.levelno == logging.WARNING and word in r.getMessage()]


# --- the tables ---------------------------------------------------------------------------------


def test_the_five_platforms_are_in_the_order_of_the_settings_with_their_labels_and_numbers():
    assert [p.value for p in PLATFORMS] == ["pc", "ps5", "xbox_series", "switch_2", "switch"]
    assert [(i.settings_label, i.label, i.igdb_id) for i in PLATFORMS.values()] == [
        ("ПК", "ПК", 6),
        ("PlayStation 5", "PS5", 167),
        ("Xbox Series X|S", "Xbox Series X|S", 169),
        ("Nintendo Switch 2", "Switch 2", 508),
        ("Nintendo Switch", "Switch", 130),
    ]


def test_a_newer_console_knows_the_older_one_it_runs_the_games_of():
    assert {p: i.older for p, i in PLATFORMS.items()} == {
        Platform.PC: None,
        Platform.PS5: OlderPlatform("PS4", 48),
        Platform.XBOX_SERIES: OlderPlatform("Xbox One", 49),
        Platform.SWITCH_2: OlderPlatform("Switch", 130),
        Platform.SWITCH: None,
    }


def test_the_nine_countries_are_by_label_with_their_stores_and_regions():
    labels = [c.label for c in STORE_COUNTRIES.values()]
    assert list(STORE_COUNTRIES) == ["gb", "de", "il", "kz", "pl", "ru", "us", "tr", "ua"]
    assert labels == sorted(labels)
    assert {code: c.playstation_locale for code, c in STORE_COUNTRIES.items()} == {
        "gb": "en-gb", "de": "de-de", "il": "en-il", "kz": None, "pl": "pl-pl", "ru": None, "us": "en-us", "tr": "en-tr",
        "ua": "ru-ua",
    }
    world, europe, america = 8, 1, 2
    assert STORE_COUNTRIES["us"].regions == (world, america, europe)
    assert all(c.regions == (world, europe, america) for code, c in STORE_COUNTRIES.items() if code != "us")


def test_the_defaults_are_pc_and_ps5_and_israel():
    assert DEFAULT_PLATFORMS == (Platform.PC, Platform.PS5)
    assert DEFAULT_COUNTRY == "il"


# --- reading ------------------------------------------------------------------------------------


def test_nothing_stored_reads_as_pc_and_ps5_and_israel_with_the_choices_of_the_tables(tracker):
    view = run(tracker.settings())

    assert view.saved.my_platforms == ["pc", "ps5"] and view.saved.store_country == "il"
    assert [(c.value, c.label) for c in view.platforms] == [
        ("pc", "ПК"), ("ps5", "PlayStation 5"), ("xbox_series", "Xbox Series X|S"), ("switch_2", "Nintendo Switch 2"),
        ("switch", "Nintendo Switch"),
    ]
    assert [(c.value, c.label) for c in view.countries][:3] == [
        ("gb", "Великобритания"), ("de", "Германия"), ("il", "Израиль")
    ]
    assert len(view.countries) == 9


def test_what_is_stored_is_read_in_the_order_of_the_table(tracker, session_factory):
    spoil(session_factory, "my_platforms", ["switch", "pc", "xbox_series"])
    spoil(session_factory, "store_country", "de")

    view = run(tracker.settings())

    assert view.saved.my_platforms == ["pc", "xbox_series", "switch"] and view.saved.store_country == "de"


@pytest.mark.parametrize("value", [[], "pc", ["pc", "wii"], ["pc", 5], 7, {"pc": 1}, [["pc"]], None])
def test_a_spoiled_set_of_platforms_reads_as_the_default_with_one_warning(tracker, session_factory, caplog, value):
    spoil(session_factory, "my_platforms", value)

    with caplog.at_level(logging.WARNING):
        views = [run(tracker.settings()) for _ in range(3)]

    assert all(v.saved.my_platforms == ["pc", "ps5"] for v in views)
    assert len(warnings_about(caplog, "my_platforms")) == 1


@pytest.mark.parametrize("value", ["", "xx", "IL", 5, ["il"], None])
def test_a_spoiled_country_reads_as_israel_with_one_warning(tracker, session_factory, caplog, value):
    spoil(session_factory, "store_country", value)

    with caplog.at_level(logging.WARNING):
        views = [run(tracker.settings()) for _ in range(3)]

    assert all(v.saved.store_country == "il" for v in views)
    assert len(warnings_about(caplog, "store_country")) == 1


def test_the_two_settings_are_read_where_they_are_needed_not_kept(tracker, session_factory):
    store = tracker._settings

    with session_factory() as session:
        assert store.my_platforms_in(session) == (Platform.PC, Platform.PS5) and store.store_country_in(session) == "il"
    run(tracker.save_settings(form(my_platforms=["switch"], store_country="pl")))
    with session_factory() as session:  # the same store sees the change at once
        assert store.my_platforms_in(session) == (Platform.SWITCH,) and store.store_country_in(session) == "pl"


# --- saving -------------------------------------------------------------------------------------


def test_a_form_stores_eight_records_and_the_page_reads_the_same_form_back(tracker, session_factory):
    change = form()

    run(tracker.save_settings(change))

    assert stored(session_factory) == {
        "timezone": "Asia/Tokyo", "workdays": [0, 1], "summary_at": "16:00", "quiet_from": "22:00",
        "quiet_until": "06:00", "part_gap_weeks": 8, "my_platforms": ["pc", "xbox_series"], "store_country": "us",
    }
    saved = run(tracker.settings()).saved
    assert saved == SettingsChange(
        "Asia/Tokyo", [0, 1], "16:00", "22:00", "06:00", "8", ["pc", "xbox_series"], "us"
    )
    run(tracker.save_settings(saved))  # what the page shows is a form the core takes as it is
    assert run(tracker.settings()).saved == saved


def test_the_platforms_given_out_of_order_or_twice_are_stored_once_in_the_order_of_the_table(tracker, session_factory):
    run(tracker.save_settings(form(my_platforms=("switch", "pc", "switch", Platform.PS5))))

    assert stored(session_factory)["my_platforms"] == ["pc", "ps5", "switch"]


REFUSALS = [
    pytest.param({"my_platforms": []}, SettingsField.MY_PLATFORMS, "Мои платформы: отметьте хотя бы одну платформу", id="none"),
    pytest.param({"my_platforms": ["pc", "ps4"]}, SettingsField.MY_PLATFORMS, "Мои платформы: выберите платформы из списка", id="ps4"),
    pytest.param({"my_platforms": ["PC"]}, SettingsField.MY_PLATFORMS, "Мои платформы: выберите платформы из списка", id="case"),
    pytest.param({"my_platforms": "pc"}, SettingsField.MY_PLATFORMS, "Мои платформы: выберите платформы из списка", id="a-text"),
    pytest.param({"my_platforms": [["pc"]]}, SettingsField.MY_PLATFORMS, "Мои платформы: выберите платформы из списка", id="a-list"),
    pytest.param({"store_country": "xx"}, SettingsField.STORE_COUNTRY, "Страна магазинов: выберите страну из списка", id="xx"),
    pytest.param({"store_country": ""}, SettingsField.STORE_COUNTRY, "Страна магазинов: выберите страну из списка", id="empty"),
    pytest.param({"store_country": "IL"}, SettingsField.STORE_COUNTRY, "Страна магазинов: выберите страну из списка", id="upper"),
]


@pytest.mark.parametrize("override, field, text", REFUSALS)
def test_a_wrong_platform_or_country_is_refused_with_its_field_and_nothing_is_stored(
    tracker, session_factory, override, field, text
):
    run(tracker.save_settings(form()))
    before = stored(session_factory)

    with pytest.raises(SettingsRefused) as refused:
        run(tracker.save_settings(form(tz_name="", workdays=[3], **override)))

    assert (refused.value.field, refused.value.text) == (field, text)
    assert stored(session_factory) == before  # not even the correct fields went in


def test_the_first_wrong_field_in_the_order_of_the_form_is_the_one_named_the_platforms_before_the_country(tracker):
    with pytest.raises(SettingsRefused) as refused:
        run(tracker.save_settings(form(store_country="xx", my_platforms=[])))
    assert refused.value.field == SettingsField.MY_PLATFORMS

    with pytest.raises(SettingsRefused) as refused:
        run(tracker.save_settings(form(store_country="xx", part_gap_weeks="0")))
    assert refused.value.field == SettingsField.PART_GAP_WEEKS


def test_two_saves_in_a_row_the_last_one_wins_with_the_new_fields_too(tracker, session_factory):
    run(tracker.save_settings(form(my_platforms=["pc"], store_country="de")))
    run(tracker.save_settings(form(my_platforms=["switch", "switch_2"], store_country="tr")))

    assert stored(session_factory)["my_platforms"] == ["switch_2", "switch"]
    assert stored(session_factory)["store_country"] == "tr"


def test_changing_the_platforms_and_the_country_makes_no_message_by_itself(tracker, session_factory):
    run(tracker.save_settings(form(my_platforms=["pc"], store_country="us")))
    run(tracker.save_settings(form(my_platforms=["xbox_series", "switch"], store_country="de")))

    with session_factory() as session:
        assert session.scalars(select(Event)).all() == [] and session.scalars(select(DeliveryItem)).all() == []


def test_the_fields_of_a_refusal_are_the_names_the_page_has_always_used():
    assert [f.value for f in SettingsField] == [
        "timezone", "workdays", "summary_at", "quiet", "part_gap_weeks", "my_platforms", "store_country"
    ]
    assert SettingsField.QUIET == "quiet"  # the old strings still compare equal


# --- one check per field (KI-34) ----------------------------------------------------------------


@pytest.mark.parametrize("bad", ["16:5", "+16:05", "١٦:٠٥", "16:05:00", "1605", " ", "", "24:00", "15:60", "-1:30", "16:٠٥"])
@pytest.mark.parametrize("field", ["summary_at", "quiet_from", "quiet_until"])
def test_ki_34_a_time_the_form_refuses_is_refused_by_set_delivery_rules_too(tracker, field, bad):
    before = run(tracker.delivery_rules())

    with pytest.raises(ValueError):
        run(tracker.set_delivery_rules(**{field: bad}))
    with pytest.raises(SettingsRefused):
        run(tracker.save_settings(form(**{field: bad})))

    assert run(tracker.delivery_rules()) == before


@pytest.mark.parametrize("written, expected", [("16:05", "16:05"), ("7:30", "07:30"), (" 7:30 ", "07:30")])
def test_ki_34_the_older_method_still_takes_the_times_the_form_takes(tracker, written, expected):
    run(tracker.set_delivery_rules(summary_at="17:00", quiet_from="22:00", quiet_until=written))

    assert delivery.format_time(run(tracker.delivery_rules()).quiet_until) == expected


def test_ki_34_the_older_method_takes_a_time_and_a_text_as_before(tracker):
    run(tracker.set_delivery_rules(summary_at=time(16, 5), quiet_from="22:00", quiet_until="6:00"))

    rules = run(tracker.delivery_rules())
    assert (rules.summary_at, rules.quiet_from, rules.quiet_until) == (time(16, 5), time(22, 0), time(6, 0))


@pytest.mark.parametrize("days", [[1, "x"], ["1"], [None], [1.5], [True], [7], [-1], 5, "12"])
def test_ki_34_a_working_day_the_form_refuses_is_a_refusal_not_a_type_error_in_both_ways(tracker, days):
    with pytest.raises(ValueError):
        run(tracker.set_delivery_rules(workdays=days))
    with pytest.raises(SettingsRefused) as refused:
        run(tracker.save_settings(form(workdays=days)))

    assert refused.value.field == SettingsField.WORKDAYS


def test_ki_34_a_zone_outside_the_list_of_names_is_refused_by_both_ways(tracker):
    for name in ("posixrules", "Mars/Olympus", "asia/tokyo", ""):
        with pytest.raises(ValueError):
            run(tracker.set_delivery_rules(tz_name=name))
    with pytest.raises(SettingsRefused):
        run(tracker.save_settings(form(tz_name="posixrules")))


def test_ki_34_a_stored_posixrules_reads_as_no_choice_with_one_warning_and_the_page_can_save(
    tracker, session_factory, caplog
):
    spoil(session_factory, "timezone", "posixrules")  # ZoneInfo opens it, `available_timezones()` does not know it

    with caplog.at_level(logging.WARNING):
        views = [run(tracker.settings()) for _ in range(3)]
        rules = run(tracker.delivery_rules())

    assert all(v.tz_name is None for v in views) and rules.tz == JERUSALEM
    assert len(warnings_about(caplog, "posixrules")) == 1
    run(tracker.save_settings(views[0].saved))  # «Сохранить» no longer demands another zone first
    assert "timezone" not in stored(session_factory)


@pytest.mark.parametrize("weeks", [None, "x", 2.5, True, [], 0, 53])
def test_ki_34_the_weeks_that_are_not_whole_numbers_of_the_range_are_a_value_error_not_a_type_error(tracker, weeks):
    with pytest.raises(ValueError):
        run(tracker.set_part_gap_weeks(weeks))
    assert run(tracker.part_gap_weeks()) == 6


@pytest.mark.parametrize("weeks", [None, [], 2.5, "", "x", "0", "53", "9" * 5000])
def test_ki_34_the_weeks_of_the_form_that_are_no_number_of_the_range_are_a_refusal(tracker, weeks):
    with pytest.raises(SettingsRefused) as refused:
        run(tracker.save_settings(form(part_gap_weeks=weeks)))

    assert refused.value.field == SettingsField.PART_GAP_WEEKS
    assert refused.value.text == "Части сезона: число недель — целое, от 1 до 52"


# --- the line «Сейчас» --------------------------------------------------------------------------


def test_the_line_now_is_a_method_of_the_rules_not_a_function_of_the_module():
    rules = delivery.DeliveryRules(tz=JERUSALEM)

    assert rules.now_line(NOW.replace(tzinfo=None)) == (
        "Сейчас чт, 29 окт, 22:10 — тихие часы: событие придёт сводкой завтра в 07:30"
    )
    assert not hasattr(delivery, "now_line")


def test_ki_34_no_working_days_given_at_all_is_a_refusal_of_the_form(tracker):
    with pytest.raises(SettingsRefused) as refused:
        run(tracker.save_settings(form(workdays=None)))

    assert refused.value.field == SettingsField.WORKDAYS
