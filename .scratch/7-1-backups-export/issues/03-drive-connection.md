# 03: Google Drive connection — variables, sign-in and sign-out, the first lines of Settings, `docs/backups.md`

Status: accepted
Complexity: complex (OAuth with PKCE against a real Google client, secrets on disk, a live risk the ticket must settle)
Blocked by: 01 (the block of Settings and the place of the Google Drive line)

Spec: `../spec.md`, sections 4.1 (all), 4.2 (all, with the risk paragraph), 4.3 (files; only the token file is written here, the state file is read and removed), 4.7 (the first four rows: off · keys set but password missing or short · on, not connected · connected, nothing sent yet — and the small text under the line), 4.8 (the part «turning on» and «turning off»), 6 (rows on a sign-in from another host, on a revoked access, on a deleted folder is ticket 04's), 7 (Google Drive: connect redirect, callback cases, disconnect; spoiled token file; secrets never in the log), 9 (`CONTEXT.md` terms «Копия в Google Drive», «Пароль копий»; `PROJECT_CONTEXT.md`, `CLAUDE.md`). ADR 0012 (read it; if the live risk changes a decision, say so explicitly). Checks: `../checks.md`, 3 (Google documentation). Standards — rules 1, 4, 7, 8, 10, 11.

## What to do

- **Launch settings** (4.1, `app/config.py`): `BACKUP_PASSWORD` (stripped, at least 12 characters), `GOOGLE_DRIVE_CLIENT_ID`, `GOOGLE_DRIVE_CLIENT_SECRET`, none required, a short password does not stop the start; one place decides «the Google Drive copy is on» (all three set, password long enough). Masking: the password and the secret are masked by their names in the log (the test of masking gets the new names); `.env.example` gets the three lines with Russian comments (the password: «храните его и вне этого ПК — без него копии из Google Drive не открыть»); `start-bot.ps1`/`docker-compose.yml` hand the three variables to the container the same way as the others, and the `$` check of `start-bot.ps1` covers them already (verify).
- **The token file** (4.3): `data/google_drive_token.json` (`refresh_token`, `connected_at` UTC, `folder_id`), written through a temporary file and `os.replace` with the rights of the app's user only; never printed, logged, copied into a backup or an export; a spoiled file is treated as absent with a warning in the log. The state file `google_drive_state.json` is only read here (a missing or spoiled one = no attempts yet) and removed at sign-out; ticket 04 writes it.
- **Connect** (4.2): `GET /settings/google-drive/connect` (only when `Host` is `localhost` or `127.0.0.1`, otherwise the notice with the port of `WEB_PORT`), one pending sign-in in memory for 10 minutes (`state` of 32 random bytes, PKCE S256 verifier), the redirect to Google with the parameters of the spec (`access_type=offline`, `prompt=consent`, scope `drive.file` only); `GET /settings/google-drive/callback`: the `state` check, `POST https://oauth2.googleapis.com/token` through `httpx` (30 s), the refresh token into the file, every row of the callback table with its exact notice and nothing stored on a failure; the Google Drive copy not being on silently returns to Settings. On success the folder «Трекер — копии» is found or made and the newest copy is sent in the background **by ticket 04's function**; until it exists the connect only stores the token and shows the first-copy notice of 4.2 (leave a named seam, no dead code, and ticket 04 plugs the sending in).
- **Disconnect** (4.2, end): `POST /settings/google-drive/disconnect` revokes the refresh token (`https://oauth2.googleapis.com/revoke`; a failure only logged), deletes the token and state files, and shows the notice.
- **The lines of Settings** (4.7, first four rows + the small text under the line when connected): in the place ticket 01 left; the block reads the files in a worker thread; «Подключить Google Drive» on another host is replaced by the sentence of 4.2; the buttons «Подключить Google Drive» / «Отключить Google Drive».
- **The live risk of 4.2** (the part of this ticket only the owner can finish): which redirect Google accepts with the owner's client — `http://localhost:8080/settings/google-drive/callback`, else `127.0.0.1` (the owner is sent to `http://127.0.0.1:<port>/settings` first), else the path `/` handled by the Feed address. The session builds all three behind one switch, tests the three by fakes, then walks the real sign-in with the owner and records which one works — and the first real answers of Google with tokens masked — in `../checks.md`. If none works, stop and say so: that changes ADR 0012.
- **`docs/backups.md`** (4.8, English; the session also gives the same steps to the owner in Russian in chat): what is copied where; turning the Google Drive copy on step by step (Google Cloud project, the Google Drive API on, the consent screen «External» with the scope `drive.file`, **publish the app** — in «Testing» Google ends the sign-in after 7 days —, a client «Desktop app», the two values and a password into `.env` and into a password manager, `.\start-bot.ps1`, «Подключить Google Drive»; Google may warn that the app is not verified — «Дополнительно» → «Перейти»); turning off. Sections «archive by hand with 7-Zip» and «restoring» are written by tickets 04 and 05. `CLAUDE.md` "Run" gets one line pointing to it (keep the file within its budget).
- **Docs:** module docstrings, `.venv\Scripts\python.exe tools\code_map.py`; `CONTEXT.md` — «Копия в Google Drive» (in code `drive copy`, module `google_drive`) and «Пароль копий» (`BACKUP_PASSWORD`); `PROJECT_CONTEXT.md` — the three variables in the `.env` table, Google Drive in the table of external services, `data/google_drive_*.json` in the Gotchas next to `startup_failure.json`; `docs/tests-map.md`.

## Done when

- [ ] Each state of the first four rows of 4.7 shows from prepared `.env` values and files; the secrets appear in no log line and no page.
- [ ] The connect redirect has every parameter of 4.2 (PKCE, scope, `prompt=consent`) and works only on `localhost`/`127.0.0.1`; every callback case writes its exact notice and stores nothing on a failure; a stale or foreign `state` is refused.
- [ ] Disconnect revokes (a failure only logged), removes the files, shows its notice; a spoiled token file reads as «не подключён».
- [ ] The real sign-in is walked with the owner's own Google client, the working redirect is recorded in `../checks.md`, and the token file appears with the right rights.
- [ ] `docs/backups.md` lets the owner turn the copy on without anything else read.
- [ ] No module of the core over 400 lines; `pyflakes app tests` clean; the full suite green (the three known Windows failures are not new).

## Tests to add

- Settings: the values of 4.1 (stripped, the 12-character edge, the «on» rule in one place); masking by the new names.
- The files: the token written atomically, a spoiled token and a spoiled state, removal at sign-out.
- Connect/callback with fake Google (`httpx` mock transport): the redirect URL parameters and PKCE, the host rule, the 10-minute window, one pending sign-in replaced by a new press, every row of the callback table, the token request failing or with no refresh token, the Google Drive copy being off.
- Disconnect with a revoke that fails; the lines of Settings for the four states; the other-host sentence.

## Owner check

This ticket is the one that needs the owner's Google account; the session walks it with the owner. First the session gives the step-by-step instruction in Russian for creating the Google client (from `docs/backups.md`), then:

1. The owner puts the three values into `.env` (the session says exactly which lines and where; no values are written in the chat), the session starts the bot and writes the launch result in one line.
2. Browser, `http://localhost:8080/settings`, «Копии и выгрузка»: «Google Drive не подключён.» and the button «Подключить Google Drive».
3. Press it. Google's page opens: choose your account, press «Продолжить» (a warning that the app is not verified → «Дополнительно» → «Перейти …»), allow access to the files the app created.
4. You land back in Settings with «Google Drive подключён. Первая копия отправляется — итог появится здесь через минуту.» (the line may say «подключён; первая копия уйдёт в течение часа» until ticket 04). The button is now «Отключить Google Drive».
5. Press «Отключить Google Drive» → «Google Drive отключён…», and connect again to see it works the second time.

«Не так»: Google says «redirect_uri_mismatch» (tell the session — it switches the redirect, `../checks.md` records it), «access blocked» (the app is not published or you are not among the test users), the page returns with no notice, the line stays «не подключён» after a successful sign-in.
