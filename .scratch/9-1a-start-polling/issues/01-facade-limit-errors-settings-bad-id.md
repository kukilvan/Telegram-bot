# 01: The facade's limit, its own errors, the settings read safely, the number of «Добавить» checked

Status: in review
Complexity: medium (four small changes in the core and its callers; no database change)
Blocked by: —

Spec: `../spec.md`, sections 3.1 (KI-41), 3.2 (KI-42), 6.1 (F5), 6.2 (F4), the rows «`workdays` spoiled by hand» and «`external_id` of 19 digits» of section 7, tests of 3.1, 3.2, 6.1, 6.2 in section 8. Terms — `CONTEXT.md`; standards — rules 1, 3, 7, 10, 11 (`docs/coding-standards.md`). Known issues: KI-41, KI-42 (set to `fixed (test: …)` in `KNOWN_ISSUES.md`, index row too).

This ticket goes first: it unpacks `core.py` and gives it room that ticket 03 needs.

## What to do

- **The facade's limit (6.1).** `app/tracker/core.py` may have up to 500 lines and no line longer than 120 characters; the other modules of the core stay at 400. Unpack the imports and `__all__` that are packed into lines of 150–188 characters (one name per line or short groups, as the formatter of the project does). No rule or SQL moves into the facade. Rule 7 of `docs/coding-standards.md` and `tests/test_tracker_core_split.py` say it (the facade 500 / 120, the others 400); the rule's «How it is checked» paragraph changes with the test.
- **Own errors (6.2).** In `errors.py`: `UnknownSample` (raised by `TestSamples.send_test_event` for an id it does not know) and `UnknownCheck` (raised by `Tracker.delivery_check` for an id it does not know); both re-exported by `core` (in `__all__`). Callers catch them instead of `KeyError`: `app/web/settings_test_event.py` (both forms, texts of today) and `app/bot/test_event_handlers.py` (texts of today). A `KeyError` from inside a send is no longer «Такого момента нет»: the bot's generic failure branch and the web's error page take it, with a log line.
- **Settings read safely (3.1).** `SettingsStore` reads `part_gap_weeks` (`check_part_gap_weeks`), `workdays` (`check_workdays`), `summary_at`, `quiet_from`, `quiet_until` (`check_clock`) through their checks, as the zone, platforms and country already are. A value that fails reads as the default of that field; the log says once per value (`_spoiled_once`): `the stored <key> <value> is not valid; the default works`. `part_gap_weeks_in` and `part_gap` become methods of the instance (they log); update their callers. Each field is checked alone — the check of the rules as a whole (a summary hour inside the quiet hours) stays the form's.
- **The number of «Добавить» (3.2).** `Titles.add_title` (so `follow` and the «Да» of an offer too) checks the id before asking a source: an id of every source of `add_title` matches `[1-9][0-9]{0,17}` (no sign, no leading zero, no space, at most 18 digits). Otherwise the new error `BadExternalId(TitleNotFound)` (in `errors.py`, re-exported by `core`); nothing is asked or stored. Web «Добавить» (`app/web/search.py`) and «Следить» (`pages.try_follow`) catch it before `TitleNotFound` and say **«Такого номера тайтла не бывает. Поищите заново»**; everywhere else it reads as `TitleNotFound` (the bot's «Следить» says what it says today, the «Да» of an offer goes on to the next offer).
- **Docs:** module docstrings, then `.venv\Scripts\python.exe tools\code_map.py`; `docs/tests-map.md` if a test module is added; `KNOWN_ISSUES.md` — KI-41, KI-42 fixed.

## Done when

- [ ] `core.py` ≤ 500 lines, no line over 120 characters; the other core modules ≤ 400; `tests/test_tracker_core_split.py` and rule 7 say so.
- [ ] `UnknownSample` and `UnknownCheck` exist, are exported by `core`, and the web forms and the bot catch them with today's texts; a `KeyError` inside a send is not «Такого момента нет».
- [ ] Each of the five settings, spoiled by hand in the database, reads as its default, logs once, and the Feed and the delivery rules work on it.
- [ ] `abc`, `007`, `-5`, ` 5`, a 19-digit number give `BadExternalId` with no source call and nothing stored; the web shows the line above; the «Да» of an offer goes to the next offer.
- [ ] KI-41 and KI-42 are `fixed (test: …)` in the entries and in the index.
- [ ] `.venv\Scripts\python.exe -m pyflakes app tests` clean; `tools\code_map.py` run; the full suite green (the three known Windows failures are not new).

## Tests to add

- Size test (`test_tracker_core_split.py`): the facade ≤ 500 lines and no line over 120; the others ≤ 400.
- Unknown sample and unknown check give the new errors; a `KeyError` raised inside a fake sender is not read as «Такого момента нет» (web and bot).
- Settings: each of the five fields spoiled (a non-number, a wrong day list, `25:99`) reads as its default and logs once (a second read adds no line).
- Bad number: the five inputs above → `BadExternalId`, a source stub is never called; the web «Добавить» and «Следить» show the new line; the inbox «Да» moves to the next offer; `BadExternalId` is a `TitleNotFound`.

## Owner check

The session starts the bot itself and writes the launch result in one line, and one more line: what it checked by hand requests (a number like `007` gives «Такого номера тайтла не бывает. Поищите заново»). Nothing else here changes what the owner sees. One look, in the browser, `http://localhost:8080`, signed in:

1. Open «Лента», then «Настройки», then press «Прислать» in the form «Тестовое событие»: all open without an error page and the sentence under the button is the same as before.

«Не так»: an error page in «Лента» or «Настройки», or no sentence under «Прислать».
