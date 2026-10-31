"""The settings page: the time zone, the working days, the hour of the summary, the quiet hours, the break between parts of
a season, the platforms of the games and the country of the stores, in one form with one button; under it the line
«Сейчас» and the state of the bot in Telegram. The form is saved as a whole or not at all: a value the core refuses is
shown with the first error and everything as typed, and nothing is stored. Rules: sections 3 and 4 of the spec of part
5.4, section 11 of the spec of part 6.1."""

from typing import NamedTuple

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse
from starlette.datastructures import FormData

from app.tracker.core import SettingsChange, SettingsRefused, SettingsView
from app.web import pages

WEEKDAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")  # Monday is 0, as in the core
DAY_VALUES = frozenset(str(number) for number in range(len(WEEKDAYS)))
SAVED = "Сохранено"
CONNECTED = "Подключён"

router = APIRouter()


class Option(NamedTuple):
    """A line of a list or a box of the form; for the zone `value` «» is the first line: the zone of the launch file."""

    value: str
    label: str
    selected: bool


class DayBox(NamedTuple):
    value: int
    label: str
    checked: bool


def _read_change(form: FormData) -> SettingsChange:
    """The form as the core reads it. Only the boxes of the days are looked at here: a value that is no day is dropped
    (only a hand-made request sends one); a missing field is an empty text, and the core names the field."""
    days = sorted({int(value) for value in form.getlist("workday") if value in DAY_VALUES})
    return SettingsChange(
        tz_name=str(form.get("timezone", "")), workdays=days, summary_at=str(form.get("summary_at", "")),
        quiet_from=str(form.get("quiet_from", "")), quiet_until=str(form.get("quiet_until", "")),
        part_gap_weeks=str(form.get("part_gap_weeks", "")), my_platforms=[str(v) for v in form.getlist("platform")],
        store_country=str(form.get("store_country", "")),
    )


async def _show(
    request: Request, view: SettingsView, shown: SettingsChange, *, error: SettingsRefused | None = None
) -> Response:
    """The page: `shown` fills the fields (what is stored, or what was typed when the form was refused), `view` gives the
    choices, the line «Сейчас» and the rest, always as stored."""
    zones = [Option("", view.default_label, shown.tz_name == "")]
    zones += [Option(zone.name, zone.label, zone.name == shown.tz_name) for zone in view.zones]
    days = [DayBox(number, name, number in shown.workdays) for number, name in enumerate(WEEKDAYS)]
    platforms = [Option(box.value, box.label, box.value in shown.my_platforms) for box in view.platforms]
    countries = [Option(line.value, line.label, line.value == shown.store_country) for line in view.countries]
    chosen_differs = view.tz_name is not None and view.tz_name != view.default_tz_name
    log_note = (
        f"Журнал бота пишет время по поясу из файла настроек запуска ({view.default_tz_name})" if chosen_differs else ""
    )
    return await pages.page(
        request, "settings.html", status_code=400 if error is not None else 200,
        current=str(request.app.url_path_for("settings")), form_address=str(request.app.url_path_for("settings_save")),
        zones=zones, days=days, platforms=platforms, countries=countries, shown=shown, log_note=log_note,
        now_line=view.now_line, telegram_state=pages.telegram_note(request) or CONNECTED,
        error_text=error.text if error is not None else "", invalid={error.field.value: True} if error is not None else {},
    )


@router.get("/settings", name="settings")
@pages.guarded_with_refresh("settings")
async def settings(request: Request) -> Response:
    view = await pages.tracker_of(request).settings()
    return await _show(request, view, view.saved)


@router.post("/settings", name="settings_save")
@pages.guarded_with_refresh("settings")
async def settings_save(request: Request) -> Response:
    tracker = pages.tracker_of(request)
    change = _read_change(await request.form())
    try:
        await tracker.save_settings(change)
    except SettingsRefused as refused:
        return await _show(request, await tracker.settings(), change, error=refused)
    pages.notify(request, SAVED)
    return RedirectResponse(str(request.app.url_path_for("settings")), status_code=303)
