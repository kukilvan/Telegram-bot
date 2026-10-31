"""Ticket 29: a date is read in two places only: softly for what a service sent, strictly for what the tracker stored."""

import ast
import pathlib
from datetime import date

import pytest

from app.tracker.sources.dates import parse_date, parse_response_date, response_year

TRACKER = pathlib.Path(__file__).resolve().parent.parent / "app" / "tracker"


@pytest.mark.parametrize(
    "value, expected",
    [
        ("2026-10-24", date(2026, 10, 24)),
        ("2026-10-24T09:00:00.000Z", date(2026, 10, 24)),  # only the first ten characters count
        ("", None),
        (None, None),
        ("soon", None),
        ("2026-13-45", None),
        (20261024, None),  # not even text: still garbage from a service, not a crash
    ],
)
def test_a_date_from_a_service_is_read_softly(value, expected):
    assert parse_response_date(value) == expected


def test_the_year_of_a_date_from_a_service():
    assert response_year("2021-09-15") == 2021
    assert response_year("") is None
    assert response_year("garbage") is None


def test_a_stored_date_is_read_strictly():
    assert parse_date("2026-10-24") == date(2026, 10, 24)
    assert parse_date(None) is None and parse_date("") is None
    with pytest.raises(ValueError):
        parse_date("garbage")
    with pytest.raises(ValueError):
        parse_date("2026-10-24T09:00:00")  # we never store this: it would be a bug, not a service's whim


def defined_functions():
    found: dict[str, list[str]] = {}
    for path in TRACKER.rglob("*.py"):
        if "migrations" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.FunctionDef):
                found.setdefault(node.name, []).append(path.name)
    return found


def test_there_is_one_reader_of_each_kind_and_no_copies():
    functions = defined_functions()
    for name in ("parse_response_date", "response_year", "response_day_of_timestamp", "parse_date"):
        assert functions[name] == ["dates.py"], name
    copies = {name: where for name, where in functions.items() if name in ("_parse_date", "_year", "_parse")}
    assert copies == {}
