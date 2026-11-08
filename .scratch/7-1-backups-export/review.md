# Review 7.1: backups and export

Status: open

Unfinished: the session hit the usage limit. The next session «Ревью 7.1» continues from here, on the same branch `claude/s7-1-review`.

## What was reviewed

- Commits `e8be7e0..907d20c` (tickets 01–05), the spec, the tickets, `checks.md`.

## Tests

- At the start: 3781 pass, 3 skipped; only the three known Windows failures (`test_app_main`, `test_docker_files`, `test_runtime`).

## Verified by running

- The Settings block over HTTP (signed in): the copies line and its hint, the Google Drive line «Работает» with the password note, the buttons, the export hint. The texts match spec 2 and 4.7.
- «Сделать копию сейчас»: «Копия сделана и отправлена в Google Drive.», the manual copy `tracker_db_20261108_190406_manual.db`, the line «там 2 копии из 30 хранимых», `data/backups/upload/` empty afterwards, no error in the log.
- `/settings/export.csv`: BOM, `;`, only `\r\n`, 8 columns, the header of spec 3.1, the file name with the date; 28 titles, the same count as the JSON.
- `/settings/export.json`: no BOM, the shape of version 1, revision 0014, the owner's offset, all four kinds.

## Not done yet

- The two-axis `code-review` (standards, spec): both passes were stopped before they finished, so they need to run again.
- `restore-bot.ps1` live: the list, a cancel by Enter and by «нет», a real restore of a fresh manual copy, a `.7z` check, the refusals.
- Decisions on the findings, and the end of the session.

## Findings

- **F1**: in `KNOWN_ISSUES.md`, KI-69 «How to reproduce», `.\restore-bot.ps1` and `data\backups` held a carriage return and a backspace (the backslash escapes were eaten). **Fix now**: fixed in this session.
- **F2**: the log line of the Google Drive upload `PUT …&upload_id=***&session_crd=<value>` shows `session_crd` unmasked, because `app/utils/secrets_mask.py` masks only `upload_id`. Without `upload_id` it is probably useless, but it belongs to the upload session. Proposed: **fix now**: add `session_crd` to the query pattern, plus a test line in `tests/test_google_drive.py`. Decision pending.

## Wishes for later stages

- None yet.
