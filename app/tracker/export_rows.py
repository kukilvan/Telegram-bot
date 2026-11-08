"""The files of the export as bytes (pure): the CSV list with its cell guard and the JSON values, the owner's dates, the file names.

No database here: `exports` reads the tables in one session and hands the values to these functions. The format is spec
3 of stage 7.1: the CSV is for Excel with Russian regional settings (UTF-8 with BOM, `;`, `\\r\\n`), the JSON is the whole
data of the owner (version 1), both with the dates on the owner's clock.
"""

import csv
import io
import json
from datetime import date, datetime, timezone, tzinfo
from typing import Any, NamedTuple

CSV_TYPE = "text/csv; charset=utf-8"
JSON_TYPE = "application/json"
FORMAT = "release-tracker-export"
VERSION = 1
BOM = "﻿"
SEPARATOR = ";"
LINE_END = "\r\n"
FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")  # Excel would read a cell that begins so as a formula
HEADER = (
    "Название", "Оригинальное название", "Тип", "Статус", "Оценка", "Год", "Добавлен", "Завершён",
)


class ExportFile(NamedTuple):
    """A file to download: its name, its media type and its bytes."""

    name: str
    media_type: str
    content: bytes


class ListLine(NamedTuple):
    """One title of the CSV list, as the cells read (the dates are not formatted yet)."""

    name: str
    original_name: str
    kind_label: str
    status_label: str
    score_label: str | None
    year: int | None
    added_at: datetime  # naive UTC, as stored
    finished_at: datetime | None  # naive UTC; None: the status is not a final one


def local(moment: datetime, tz: tzinfo) -> datetime:
    """A stored moment (naive UTC) as an aware one on the owner's clock."""
    return moment.replace(tzinfo=timezone.utc).astimezone(tz)


def moment_text(moment: datetime | None, tz: tzinfo) -> str | None:
    """ISO 8601 with the owner's offset (`2026-11-07T16:21:05+03:00`); None for none."""
    return None if moment is None else local(moment, tz).isoformat(timespec="seconds")


def day_text(day: date | None) -> str | None:
    """`YYYY-MM-DD`; None for none."""
    return None if day is None else day.isoformat()


def csv_date(moment: datetime | None, tz: tzinfo) -> str:
    """`ДД.ММ.ГГГГ` on the owner's clock; empty for none."""
    return "" if moment is None else local(moment, tz).strftime("%d.%m.%Y")


def guard(cell: str) -> str:
    """A cell that begins with a character a spreadsheet takes for a formula gets a leading `'`."""
    return "'" + cell if cell.startswith(FORMULA_STARTS) else cell


def file_day(now: datetime, tz: tzinfo) -> str:
    """The owner's date of the moment of the export, for the file names."""
    return local(now, tz).strftime("%Y-%m-%d")


def list_file_name(day: str) -> str:
    return f"tracker-list-{day}.csv"


def all_file_name(day: str) -> str:
    return f"tracker-all-{day}.json"


def csv_bytes(lines: list[ListLine], tz: tzinfo) -> bytes:
    """The CSV list: the header and one line per title in the order given (RFC 4180 quoting, `;`, `\\r\\n`, with BOM)."""
    out = io.StringIO(newline="")
    writer = csv.writer(out, delimiter=SEPARATOR, lineterminator=LINE_END, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(HEADER)
    for line in lines:
        original = "" if line.original_name == line.name else line.original_name
        cells = (
            line.name, original, line.kind_label, line.status_label, line.score_label or "",
            "" if line.year is None else str(line.year), csv_date(line.added_at, tz), csv_date(line.finished_at, tz),
        )
        writer.writerow(guard(cell) for cell in cells)
    return (BOM + out.getvalue()).encode("utf-8")


def zone_name(tz: tzinfo) -> str:
    """The name of the zone for the JSON: `Europe/Moscow`, `UTC`."""
    return getattr(tz, "key", None) or str(tz)


def json_bytes(document: dict[str, Any]) -> bytes:
    """The JSON file: UTF-8 without BOM, Russian text as it is, indent 2."""
    return json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")
