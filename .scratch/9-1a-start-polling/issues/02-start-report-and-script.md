# 02: The start report and the start script

Status: open
Complexity: medium (one module with a decision table, one PowerShell script; no database change)
Blocked by: —

Spec: `../spec.md`, sections 1.1 (KI-16), 1.2 (KI-17), 1.3 (KI-20), 1.4 (KI-18), 1.5 (KI-19), the rows «`startup_failure.json` and the temp record disagree» and «A record of the old form» of section 7, tests of 1.1–1.5 and the live check of `.\start-bot.ps1` in section 8, the `PROJECT_CONTEXT.md` Gotchas line of section 9. Terms — `CONTEXT.md`; standards — rules 1, 3, 10, 11. Known issues: KI-16, 17, 18, 19, 20.

## What to do

- **Same failure, changing text (1.1)** in `app/startup_report.py`: a failure has a **code** (the type and the places — file without folders and function, in order) and a **text** (the masked text: every word that holds a digit, `/` or `\` becomes `#`, spaces folded, the first 300 characters). `data/startup_failure.json` keeps `code` (SHA-256 of the code), `fingerprint` (SHA-256 of the code and the text), `first_seen`, `reported_at`. The decision follows the table of 1.1 exactly: no record / unreadable / another `code` → report at once, the record starts anew; same code and fingerprint → reminder after 24 h «Бот всё ещё не запускается (с …)», `first_seen` stays; same code, other fingerprint → report at once if the last report is ≥ 1 h old (or did not go out, or the clock went back), else no report and the record stays as it is. A record of the old form (no `code`) reads as no record.
- **A record that cannot be saved (1.2):** `data/startup_failure.json` first; on `OSError` `<tempfile.gettempdir()>/release-tracker-startup_failure.json`, with the log line once per start `запись о сбое запуска сохранена во временную папку: <path> (data недоступна: <error>)`. Both fail → the warning of today, the next start reports again. Reading takes both, the one with the later `reported_at` (else `first_seen`) wins. `forget_failure` removes both (a file that cannot be removed is the warning of today).
- **Names (1.3):** `kind` of `fingerprint` → `exc_type`; the parameter `failure` of `decide` → `fingerprint`; the field `Decision.first_seen` goes (callers read `Decision.record.first_seen`).
- **`.\start-bot.ps1` stops only this project's old bot (1.4):** the old bot is a `python.exe` whose `ExecutablePath` equals `<the script's folder>\.venv\Scripts\python.exe` (whole, case-insensitive) and whose command line matches `$oldBotPattern` as today, plus every `python.exe` whose `ParentProcessId` is one of them. A `python -m app.main` of another folder or of the base Python is left alone. The text «Остановлен старый бот, запущенный не через Docker» stays.
- **The wait counts by the clock (1.5):** the loop runs while less than 90 s have passed since the wait began (`Get-Date` against a deadline), a pause of 2 s between checks; the last check starts before the deadline. The texts stay.
- **Docs:** `PROJECT_CONTEXT.md` Gotchas — `data/startup_failure.json` may live in the temp folder (mind the 20,000-byte budget); module docstring and `tools\code_map.py`; `docs/tests-map.md`; `KNOWN_ISSUES.md` — KI-16, 17, 18, 19, 20 fixed.

## Done when

- [ ] Three failures whose texts differ by a temp name, a path, a random word: the first is reported, the second (same code) within 1 h is not, after 1 h is; another place is reported at once; the 24-h reminder keeps `first_seen`; an old-form record reads as none.
- [ ] With `data` not writable the record lands in the temp folder and the next decision reads it; `forget_failure` removes both.
- [ ] No variable `kind` in `startup_report.py`, no `Decision.first_seen`.
- [ ] The script compares `ExecutablePath` with the `.venv\Scripts\python.exe` of its own folder, takes the children by `ParentProcessId`, waits by a deadline of `Get-Date` (`tests/test_docker_files.py`).
- [ ] Live, by the session: `.\start-bot.ps1` next to a dummy `python -m app.main` of another folder does not stop the dummy; the start still ends in «Готово».
- [ ] KI-16–20 are `fixed (test: …)`; pyflakes clean; code map rebuilt; the full suite green (the three known Windows failures are not new).

## Tests to add

- `startup_report`: the sequence of 1.1 with an injected clock (all rows of the table, the clock going back, the last report not gone out); the old-form record; the masking of words with a digit, `/`, `\`.
- 1.2: an unwritable `data` path → the record in the temp folder, the log line once, the next `decide` reads it; both unwritable → warning and no crash; both files present → the later wins; `forget_failure` removes both.
- 1.3: a direct test that `kind` is not in `startup_report.py` and `Decision` has no `first_seen`.
- `tests/test_docker_files.py`: the three script checks of 1.4 and 1.5.

## Owner check

The session starts the bot itself with `.\start-bot.ps1` and writes the launch result in one line («Готово»), plus the one-line result of the dummy-process check. Nothing for the owner to press: the visible parts (fewer repeated start-failure messages in Telegram) appear only when a start really fails.

«Не так»: `.\start-bot.ps1` ending with «Запуск не удался» on a healthy PC.
