# Review 7.1: backups and export

Status: in review

Two sessions: the first (2026-11-08) ran the Settings block, the press and the downloads and hit the usage limit; the second (2026-11-15) ran the two-axis review, the restore script live, and made the decisions.

## What was reviewed

- Commits `e8be7e0..907d20c` (after the accepted slicing): tickets 01 (9ff9b4a), 02 (c9d68f8), 03, 04 (457a4cb, 32e1cbf), 05 (9757ed7) and their «in review» / «accepted» commits; the spec, the five tickets, `checks.md`, `docs/history.md` (the decisions the tickets recorded).
- Against `spec.md` (sections 1–11) and `docs/coding-standards.md` (rules 1–11, with `CONTEXT.md` for rule 5 and ADRs 0005, 0006, 0007, 0012), with the `code-review` skill: one pass for the standards, one for the spec, each in its own sub-agent; their reports are below, lightly cleaned. KI-66…70 (deferred by the spec and the tickets) were not counted again.

## Tests

- At the start (2026-11-08): 3781 passed, 3 skipped, only the three known Windows failures (`test_app_main`, `test_docker_files`, `test_runtime`).
- Second session, at the start (2026-11-15): 3780 passed, 3 skipped, 4 failed — the three known ones and `test_drive_copies.py::test_the_pc_that_was_off_sends_at_its_start`, which passed only on 2026-11-08 (F3). `pyflakes app tests` clean.
- At the end (after the fixes): «Tests at the end» below.

## Verified by running

- **The Settings block over HTTP** (signed in, 2026-11-08): the copies line and its hint, the Google Drive line «Работает» with the password note, the buttons, the export hint — the texts of spec 2 and 4.7.
- **«Сделать копию сейчас»**: «Копия сделана и отправлена в Google Drive.», the manual copy `tracker_db_20261108_190406_manual.db`, the line «там 2 копии из 30 хранимых», `data/backups/upload/` empty afterwards, no error in the log.
- **`/settings/export.csv`**: BOM, `;`, only `\r\n`, 8 columns, the header of spec 3.1, the file name with the date; 28 titles, the same count as the JSON. **`/settings/export.json`**: no BOM, the shape of version 1, revision 0014, the owner's offset, all four kinds.
- **The PC that was off sends at its start** (spec 4.5, live 2026-11-15): Docker Desktop had been off since 2026-11-08; at its start the bot made the daily copy `tracker_db_20261115_171614.db` in its first hourly run and sent it at once (token 200, the folder of the token file 200, listing, resumable upload 200; `kept: 4`, `error: null`). After the restore below the next start sent the manual copy that had not gone yet (`kept: 5`).
- **`restore-bot.ps1` on the real project** (2026-11-15, answers piped from Git Bash, so `Read-Host` reads them as UTF-8):
  - the list of 23 copies newest first with «сегодня в 17:16», «8 ноября в 19:04 — сделана вручную», «6 ноября в 07:58 — перед обновлением базы»; Enter → «Отменено. Ничего не изменено.»; `99`, `0`, `абв` → «Нет копии с номером …» and the question again;
  - number 3, «нет» → «Копия от 8 ноября в 19:04 в порядке, тайтлов в ней: 28.», «Отменено. Ничего не изменено.»;
  - a path: a missing file → «Файл не найден: C:\nowhere\…»; `.txt` → «Нужен файл .7z…»; junk named `.7z` → «Это не архив 7z…»; a `.7z` of another password → «Пароль из .env не подходит…»; a SQLite file without the tables → «Этот файл не похож на копию базы трекера…»; a relative path from another folder works; a `.7z` made in the container with the real `BACKUP_PASSWORD` (never printed) → «Копия от сегодня в 17:16 в порядке…», «нет» → cancelled; `data\restore\` empty after every run;
  - **a real restore** with no loss: the bot stopped, a manual copy of the still base made in a one-off container (`tracker_db_20261115_171849_manual.db`), then the script with number 1 and «да»: «Бот и приложение остановлены», «Нынешняя база сохранена: data\backups\tracker_db_20261115_171905_before-restore.db», «База восстановлена из копии от сегодня в 17:18.», «Запускаю бота…», the lines of `start-bot.ps1`, «Готово: бот работает на копии от сегодня в 17:18.»; then `/health` 200, the container healthy, no warning in the log. The way back by the before-restore copy was not repeated on the real base (ticket 05 walked it on a throw-away copy of the project, the owner on the real base); here it would have dropped what the bot wrote after the start.
  - Found by the spec pass, confirmed in PowerShell 5.1: the question before «да» never showed the copy (F4). Piped answers do not echo the prompt, so the live run could not see it.
- **The fixes**: the new tests of F4 and F5 fail without the fix and pass with it.

## Standards (report of the standards pass)

Clean: rules 1, 2, 4, 6, 8, 9 (write sessions), 10, 11; comments in English, the UI in Russian, nothing prints a secret.

Documented rules:
- Rule 7: `export_all._parents` asks `Title.kind == TitleKind.GAME` and copies `GamePoller.parent` / `Poller.known_ids` («the smaller number, as `known_ids`»); `exports`, `export_all` missing from `MODULES` of `test_tracker_core_split.py`, the pure `export_rows` from `PURE`.
- Rule 5 («`kind` значит только тип тайтла»): `Copy.kind`, `KIND_ORDER`, `_of_kind` (`backup.py`), `KIND_WORDS`, `kind_words` (`restore.py`), `dedup_key(kind, …)` with `LOCAL` / `DRIVE` «the kind of the copy» (`backup_events.py`).
- Rule 9 (and «one rule, one place»): `drive_state._moment` is `sources/dates.parse_moment` written again; the token file's `connected_at` read by a bare `datetime.fromisoformat` (no zone check).
- Rule 7, last bullet: the rule «no retry after `sign_in`» in `backup_rows.press_notice` and `backup_events.drive_text`; `local_text` types the `RETRY` sentence out.
- Small: `config.py` names `DriveSettings.on` (the one place is `DriveSettings.setup`); `main.py` writes «12» next to a line that formats its constant; `restore` documents the exit codes 0 / 1 but `run` gives 2 for a wrong command; `providers/google_drive.py` asks for `createdTime` and never reads it.

Judgement calls (smells): `moment_words._MONTHS` repeats `cards._MONTHS` (and the today / yesterday / date logic is near `cards.format_past_moment`); the time in a copy's name parsed in `backup.py`, `drive_copies.py`, `restore.py` and `db.py`; the full-disk check and «на диске нет места» in `backup_events` and `restore`; `reason` meaning a reason key, the owner's text and Google's code (`press_notice(reason=)` holds either); `Copy.kind` a string with `OTHER` for two origins, so `restore` splits the name again; the copies folder worked out from the database URL three times and `rules.local(ctx.now())` four times; `Redirect.LOOPBACK_IP` / `ROOT` behind `REDIRECT = Redirect.CALLBACK` (the Feed knows the Google sign-in for them); `DriveCopies` taking `drive.api`, `drive.files`, `drive.settings.password`, `Backups` setting `drive.on_connected` from outside, `GoogleDrive.on` only returning `_on`.

## Spec (report of the spec pass)

Checked and right: every backticked Russian text of the spec compared with the code by a script (dashes, «», `ё`, the periods, the placeholders); 4.6 (at once for `sign_in`, `full`, `no_copy`, else from the 2nd failure in a row; the key `backup_failed:<local | drive>:<owner's date>`; no retry after `sign_in` while the token is the same); 4.4 (the archive deleted in `finally`, one 401 renewal, a 404 or trashed folder found or made again, same name and size counts as sent, rotation to 30 of its own names, 30 s / 5 min); 4.5 and 2.2 (the shared lock, the 60 s waits, the background sending, two presses in one second making one copy); 5.2–5.5 (the order of the checks, the before-restore copy by the online backup with the `-wal`, a failure before `os.replace` leaving the base whole, `data\restore` emptied in `finally`, the 60 s stop wait, no `.env` value read by the script); section 6; every test group of section 7.

Findings: (c) the question of 5.4 lost `{when}` and the «?» — `"…к копии $phrase? Всё…"`: PowerShell reads `$phrase?` as another, empty variable; the script-text test asserted that very string; (c) spec 1.3: when the copies folder cannot be listed, the copy fails on that listing and the report fails on the same listing in `_report_failure` — the failure never reaches Telegram; (c) spec 2.2: the press notice after `sign_in` leaves out «Попробую снова через час.» (a decision of ticket 04); (b) the fallback redirects of 4.2 still in the code after the live check settled on the callback; (b) small additions: a start warning for a short password, exit code 2 for a wrong command, an archive without a time in its name named by the `.db` inside, «Копий базы на этом ПК пока нет.» in the local report without a copy.

Summary: standards — 4 findings of documented rules and 1 group of small ones, about 9 judgement calls; the worst is rule 7 in the export (F6). Spec — 4 findings and 4 small additions; the worst is the restore question without the copy (F4).

## Findings

| # | What, where | Decision | Why |
|---|---|---|---|
| F1 | `KNOWN_ISSUES.md`, KI-69 «How to reproduce»: `.\restore-bot.ps1` and `data\backups` held a carriage return and a backspace (the backslash escapes were eaten) | fix now | Fixed in the first session |
| F2 | The log line of the Google Drive upload `PUT …&upload_id=***&session_crd=<value>`: `session_crd` unmasked (`app/utils/secrets_mask.py` knew only `upload_id`); seen again live 2026-11-15 | fix now | It belongs to the upload session like `upload_id`. `session_crd` joined the query pattern; a case in `test_the_codes_and_tokens_of_a_google_sign_in_are_masked` |
| F3 | `test_drive_copies.py::test_the_pc_that_was_off_sends_at_its_start` expected a copy named `tracker_db_20261108_…`, but the hourly job names its copy by the real clock (`backup_if_due`): the test passed only on 2026-11-08 | fix now | The test finds the newest daily copy in the folder and expects that one sent. The code is right: the name is the container's clock (KI-66) |
| F4 | Spec 5.4: `restore-bot.ps1` asked «Вернуть базу к копии  Всё, что изменилось позже…» — the copy and the «?» gone (`$phrase?` read as the variable `phrase?`); the test of the script's texts asserted the broken line | fix now | `${phrase}?`. A new test reads the four `.ps1` scripts for a variable written right before «?» (fails on the old script). The owner's check of ticket 05 passed with it: the list chose the copy, but the question did not repeat it |
| F5 | Spec 1.3: a copies folder that cannot be listed fails the copy and then the report too (`Backups._report_failure` listed the folder again): no message in Telegram | fix now | The report goes without the sentence of the last copy: «⚠️ Копия базы не сделана: ошибка, подробности в журнале. Попробую снова через час.», and a warning in the log. Test `test_a_copies_folder_that_cannot_be_read_still_gets_the_report_without_the_last_copy` |
| F6 | Rule 7: `export_all._parents` asks `TitleKind.GAME` and copies the poller's rule of the base game; the size-and-kind test did not list `exports`, `export_all`, `export_rows` | fix now (the test lists) + defer `KI-71` | `exports` joined `MODULES`, `export_rows` `PURE` (both pass). Moving the base game behind the pollers needs a new poller action — a design step, not minutes; the output is right today (the name the card shows) |
| F7 | Rule 5: `kind` named the origin of a copy and the place of a failed copy | fix now | `Copy.origin`, `ORIGIN_ORDER`, `_of_origin` (`backup.py`), `ORIGIN_WORDS`, `origin_words` (`restore.py`), `dedup_key(place, …)` and «the place of the copy» for `LOCAL` / `DRIVE`; `CONTEXT.md` «Копия базы» names `Copy.origin`. Nothing stored changes (the key text stays `backup_failed:local:…`) |
| F8 | Rule 9: `drive_state._moment` a copy of `parse_moment`; `connected_at` of the token file read without the zone check | fix now | Both read by `sources/dates.parse_moment` (a moment with a zone is a spoiled file, as the state's are) |
| F9 | Rule 7, last bullet: «no retry after `sign_in`» in two places, `RETRY` typed out | fix now | One `backup_events.retry_words(reason)` for the report and the press notice; `local_text` uses `RETRY` |
| F10 | Small: `DriveSettings.on` in a `config.py` comment, «12» in the start warning of `main.py`, the exit code 2 of `restore` undocumented; `createdTime` asked and unread | fix now / no change | `DriveSettings.setup`; the warning formats `MIN_PASSWORD_LENGTH` of `google_drive`; `Outcome` and the docstring name code 2 (a command the script never gives). `createdTime` stays: spec 4.4, step 4 asks for exactly those fields |
| F11 | `moment_words._MONTHS` a copy of the card's month names | fix now | `moment_in_words` uses `cards.format_day_month`. The rest of `format_past_moment` stays apart: its texts differ («в 14:05», short months, aware moments) |
| F12 | Spec 2.2: after `sign_in` the press notice leaves out «Попробую снова через час.» | no change | A decision of ticket 04 (`docs/history.md`): spec 4.6 says nothing is retried after `sign_in`, so the promise would be false |
| F13 | The fallback redirects of 4.2 (`Redirect.LOOPBACK_IP`, `ROOT`; the Feed reading Google's answer for them) still in the code | no change | Ticket 03 asked for all three behind one switch, and `checks.md` 4 keeps them on purpose as the way back if Google stops taking `localhost`. A wish below |
| F14 | Beyond the spec: a start warning for a short password, exit code 2, an archive without a time in its name named by its `.db`, «Копий базы на этом ПК пока нет.» in the local report | no change | Each helps and none contradicts the spec: the warning is the line of `PROJECT_CONTEXT.md`; the name of the inner copy is a decision of ticket 05; the spec has no text for a report without any copy |
| F15 | Other smells: the time in a copy's name parsed in four places, the full-disk check twice, `reason` for three things, `OTHER` for two origins, the copies folder and the owner's clock worked out several times, `DriveCopies` / `Backups` reaching into `GoogleDrive`, `GoogleDrive.on` / `_on` | no change | Two or three copies each, all covered by tests; noted as wishes |

## Tests at the end

- 3788 passed, 3 skipped, only the three known Windows failures; `pyflakes app tests` clean; `docs/code-map.md` rebuilt (`backup_events` line).
- The bot rebuilt and started on the fixes (`.\start-bot.ps1`: «Готово»): `/health` 200, healthy, `Tracker.poll_due` executed successfully, no warning in the log; the restore list in the new image names «перед восстановлением» (`origin_words`). The masking of `session_crd` (F2) is checked by its test; the next upload (the daily copy of 2026-11-16) shows it in the log.

## Wishes for later stages

- KI-71 when the pollers next gain an action (stage 9 or later): one poller action «extra fields of the export», then `export_all` joins the kind test.
- One `stamp_of(name)` next to `db.backup_name` for the four parsers of the time in a copy's name; an enum for the origin of a copy that tells «before an update» from «before a restore».
- Stage 8 (template): decide whether the fallback redirects of 4.2 stay — the new repository's users bring their own Google client, where `localhost` may behave otherwise.
- The core works out the copies folder once and hands the `Path` to `Backups` and `DriveCopies`.
