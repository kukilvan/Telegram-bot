# 04: Google Drive copies — the archive, sending, rotation, retries, the report, the full lines of Settings

Status: in review
Complexity: complex (a new dependency, a multi-step Google Drive API client, failure classification, retries and reports in the hourly job)
Blocked by: 03 (the connection, the token file, the lines of Settings)

Spec: `../spec.md`, sections 2.2 (the rows about Google Drive and the 60-second wait), 4.3 (the state file, written here), 4.4 (all), 4.5 (all), 4.6 (all; the local kind is ticket 01's), 4.7 (the rows «Works» and «Failed last time», the buttons), 6 (rows on the Google Drive folder deleted or full, the revoked access, the PC that sleeps, a password changed, archives moved out), 7 (Archive, Google Drive: sending, rotation, reasons, report, dedup, no retry on `sign_in`, the state file), 8 (dependency), 9 (`docs/backups.md` — the by-hand archive section). ADR 0012; checks: `../checks.md`, 1 (py7zr and real 7-Zip; the unchecked Windows 7-Zip with a Cyrillic password is checked here). Standards — rules 1, 4, 7, 8, 9, 10, 11.

## What to do

- **Dependency** (8): `py7zr>=1.1,<2` in `requirements.txt`; the image still builds with `start-bot.ps1`; no rclone, no 7-Zip in the image.
- **The archive** (4.4, 1): `data/backups/upload/tracker_db_<time>[_manual].7z` with `py7zr`, one file, LZMA2 + AES-256, header encryption on, password `BACKUP_PASSWORD`, made in a worker thread, deleted after the attempt whatever happened. What is sent is the newest daily or manual copy (never before-migration or before-restore ones).
- **The Google Drive client** (module `google_drive`, `httpx` async, 30 s a request, 5 minutes an attempt; steps 2–7 of 4.4): the access token from the refresh token and kept in memory until a minute before it expires; the folder («Трекер — копии»: the id from the token file, a search when absent or 404, creation when none; the id is written back); the listing of what is already there (a file of the same name and size counts as sent); the resumable upload in one piece; the rotation to the 30 newest archives of the app's own names (a failed delete is a warning in the log, the copy counts as sent; other files in the folder are not touched); a 401 refreshes the access token once and repeats the request once.
- **State and failures** (4.3, 4.6): `google_drive_state.json` written atomically after every attempt (success: `last_success_*`, `kept`, `error = null`, `failures_in_row = 0`; failure: `error`, `failures_in_row + 1`, `last_attempt_at`); the six reason keys with the texts of the table and the rule «at the 2nd failure in a row / at once»; the event `backup_failed:drive:<owner's date>` (title-less, delivered like «could not check», at most one of each kind a day, the texts of 4.6 with `Последняя удачная — {when}` or the first-copy variant, no «Попробую снова» for `sign_in`); the sample for «Тестовое событие». Texts and reasons live next to ticket 01's local ones (rule 7).
- **When copies go** (4.5): the hourly job, after its daily copy, sends the newest sendable copy when the Google Drive copy is on and connected and that copy is not `last_success_name`; no attempt while the reason is `sign_in` with the same token; the connect of ticket 03 now sends in the background (plug the seam); one attempt at a time under ticket 01's lock.
- **«Сделать копию сейчас»** (2.2): after the manual copy, when the Google Drive copy is on and connected (states «Работает» or «Не ушла»), send that copy and wait up to 60 s; the four notices of the table (sent, failed with the reason, over 60 s — the upload goes on in the background, copy failed unchanged).
- **The lines of Settings** (4.7): «Works» and «Failed last time» with their buttons («Подключить Google Drive» too for `sign_in`); the small text about the password under them; the line reads the state file in a worker thread.
- **`docs/backups.md`**: the section «opening an archive by hand with 7-Zip» (the password, where the `.db` comes out) and the notes of the edge-case table (a changed password, a deleted folder).
- **Docs:** module docstrings, `.venv\Scripts\python.exe tools\code_map.py`; `docs/tests-map.md`; `docs/code-map.md` "Not Python": the new `data/` files if ticket 03 did not add them.

## Done when

- [ ] On fake Google answers: a copy goes end to end (folder found / made / gone, already there, resumable upload, rotation keeping 30 and touching only its own names); a 401 once then success; each reason of 4.6 comes from its fake answer.
- [ ] The report follows its rules: the 2nd failure in a row or at once, once per kind per day, no retry while `sign_in`, and the success after a failure clears the state; the secrets appear nowhere in the log.
- [ ] The hourly job sends a new daily copy in the same run, retries a failed or a manual one, and the PC that was off sends at its start.
- [ ] «Сделать копию сейчас» gives each notice of 2.2 (fake uploader: success, failure, slow).
- [ ] The line of Settings shows «Works» and «Failed last time» from prepared state files.
- [ ] The real run: the first archive appears in the folder «Трекер — копии» of the owner's Drive and 7-Zip for Windows opens it by `BACKUP_PASSWORD` with the Cyrillic text intact (`../checks.md` records the result).
- [ ] No module of the core over 400 lines; `pyflakes app tests` clean; the full suite green (the three known Windows failures are not new).

## Tests to add

- The archive: py7zr round trip with a Cyrillic password, the archive deleted after the attempt, the names (`_manual` kept).
- The client with a fake transport: every step of 4.4, the 401 retry, the folder 404, the same file already there, the rotation (30, own names only, a failed delete), the timeouts, each reason key from its answers (`invalid_grant`, 403 `storageQuotaExceeded`, 5xx, 429, `rateLimitExceeded`, a connection error, an unknown one).
- The report: the 2nd-failure rule against the at-once rule, the dedup key per day and kind, no retry on `sign_in`, the state file after success and failure, a spoiled state file, the text with and without a last success.
- The hourly job and the press (2.2): all notices, the 60-second wait and the background finish, the lock shared with ticket 01's copy; the lines of Settings for the two new states.

## Owner check

The session starts the bot itself and writes the launch result in one line. The owner's check (browser at `http://localhost:8080/settings`, «Копии и выгрузка»; Google Drive already connected in ticket 03):

1. Press «Сделать копию сейчас» → «Копия сделана и отправлена в Google Drive.» The line above says «Копия в Google Drive: сегодня в …, там 1 копия из 30 хранимых.»
2. Open `https://drive.google.com` → «Мой диск» → the folder «Трекер — копии»: a file `tracker_db_…_manual.7z` of some tens of KB.
3. Download it. Install 7-Zip for Windows if you have none (the session gives the step-by-step in chat), open the file: it asks for a password — type `BACKUP_PASSWORD` from `.env`; inside there is one `.db` file.
4. Unplug the internet (or turn the Wi-Fi off), press «Сделать копию сейчас» → «Копия сделана, но в Google Drive не ушла: нет связи с Google Drive. Попробую снова через час.» Turn the internet back — within the hour the line returns to «Копия в Google Drive: …».

«Не так»: an archive that opens without a password or asks for a password that is wrong, a duplicate of the same file in the folder, more than 30 files after a long time, a message in Telegram on the first failure of a bad connection (it comes only on the second).
