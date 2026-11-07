# Spec 7.1: backups and export

Status: accepted

From `description.md` (accepted 2026-11-07). Terms of `CONTEXT.md`; new terms in section 9. Checks behind the choices: `checks.md` next to this file. ADRs it leans on: 0005 (copies by SQLite's online backup), 0006 (Docker on the PC), 0007 (one process, one scheduler); new: 0012 (section 10).

**One departure from the description.** Decision 3 sends the Google Drive copy «with rclone». The check (`checks.md`, 2) found that rclone's shared Google client «will stop working during 2026», so the owner has to create a Google client of their own whatever carries the file; and rclone cannot finish the Google sign-in inside the container. With the owner's own client, the app talks to the Google Drive API itself (`httpx`, already a dependency), and the sign-in is a button in Settings. rclone is not used. Everything else of decision 3 stays: once a day, 30 kept, off by default, an archive 7-Zip opens by the password. ADR 0012 records it.

## 1. Copies on the PC

### 1.1 What exists (unchanged)

`app/utils/backup.py`: every hour the scheduler makes a **daily copy** `data/backups/tracker_db_<YYYYMMDD_HHMMSS>.db` when the newest one is over 24 hours old; the 14 newest daily copies and the earliest of each of the last 12 calendar months are kept. `app/tracker/db.py` makes `tracker_db_<time>_before-<revision>.db` before a migration; rotation never touches it. The time in a name is the container's clock (`TZ` = `BOT_TIMEZONE`).

### 1.2 New kinds of copies

| Kind | Name | Made by | Kept |
|---|---|---|---|
| daily | `tracker_db_<time>.db` | the hourly job (as now) | 14 newest + 1 a month for 12 months (as now) |
| manual | `tracker_db_<time>_manual.db` | «Сделать копию сейчас» | 10 newest manual copies; the daily rotation does not see them |
| before a migration | `tracker_db_<time>_before-<revision>.db` | the start (as now) | never deleted (as now) |
| before a restore | `tracker_db_<time>_before-restore.db` | `restore-bot.ps1` (section 5) | never deleted |

A manual copy does not move the daily schedule: the next daily copy comes when the newest *daily* one is over 24 hours old. Names that only look like a copy (wrong date, other suffix) are not copies anywhere in this stage.

**A copy** (for Settings, the restore list and the Google Drive copy) is any file of `data/backups` named `tracker_db_<valid time>.db` or `tracker_db_<valid time>_<manual | before-<anything>>.db`, ordered by the time in its name, newest first; on equal times daily before manual before the others.

### 1.3 A failed copy is reported

Today a failed daily copy is only a warning in the log. Now the hourly job, when `create_backup` raises, also queues the event `backup_failed` (section 4.6) with the reason «на диске нет места» (`OSError` with `errno.ENOSPC`) or «ошибка, подробности в журнале» (anything else). Reported at most once a day (the dedup key carries the owner's date).

## 2. Settings: the block «Копии и выгрузка»

At the bottom of Settings, under «Бот в Telegram», a heading «Копии и выгрузка» and, in this order (mockup `mockups/settings-backups.html`; the texts below are final):

1. **Copies on the PC.**
   - `Копии базы на этом ПК: {n}, последняя — {when}.` — `n` counts all copies of 1.2; `when` is the time of the newest one in words (2.1).
   - No copy: `Копий базы на этом ПК пока нет: первая сделается в течение часа.`
   - The folder cannot be read: `Копии базы на этом ПК не прочитать — подробности в журнале.` (and a warning in the log).
   - Hint under it (small text): `Копия делается сама раз в сутки и перед каждым обновлением базы; хранятся 14 последних и по одной за каждый из 12 месяцев. Вернуть базу к копии — .\restore-bot.ps1 в папке трекера.`
2. **The Google Drive copy** — one of the states of 4.7, and its button when it has one.
3. **Button** «Сделать копию сейчас» (2.2).
4. **Buttons** «Скачать список (CSV)» and «Скачать всё (JSON)» (section 3), and the hint: `CSV открывается в Excel: один тайтл — одна строка. JSON — все данные целиком, на память или для переноса. Загрузить выгрузку обратно нельзя: данные возвращают из копии базы.`

The block reads the folder and the Google Drive state files (4.3) in a worker thread (rule 1); a failure of the block never breaks the rest of the page.

### 2.1 A moment in words

One function for the block, the notices and the restore list, on the owner's clock (the zone of Settings): `сегодня в 07:58`, `вчера в 18:32`, `4 ноября в 07:58`, `4 ноября 2025 в 07:58` (another year). The time of a copy is the time in its name, read as written (it is the container's clock; KI-66).

### 2.2 «Сделать копию сейчас»

`POST /settings/backup`. The press makes a manual copy (online backup, as the daily one), rotates the manual copies, and — when the Google Drive copy is on and connected (4.7, state «Работает» or «Не ушла») — sends that copy to Google Drive at once (4.4), waiting up to 60 seconds. Then back to Settings with a notice:

| Outcome | Notice |
|---|---|
| copy made, Google Drive off or not connected | `Копия сделана: сегодня в 16:21.` |
| copy made and sent | `Копия сделана и отправлена в Google Drive.` |
| copy made, sending failed | `Копия сделана, но в Google Drive не ушла: {reason}. Попробую снова через час.` (reasons of 4.6) |
| copy made, sending took over 60 s | `Копия сделана; в Google Drive она ещё отправляется — итог появится здесь.` (the upload goes on in the background) |
| copy failed | `Копия не сделана: {reason}.` (reasons of 1.3) |
| a press while the previous one still works | `Копия уже делается — подождите несколько секунд.` |

One copy at a time: a lock shared with the hourly job; a press while the hourly job copies waits for it (up to the same 60 s, then the «уже делается» notice). Two presses in the same second make one copy (the second gets «уже делается»).

## 3. Export

Both are `GET` addresses behind the sign-in, answer `Content-Disposition: attachment`, are built in a worker thread through the core facade (`Tracker.export_list()`, `Tracker.export_all()`; rule 10), and read the database in one read session (a consistent picture). Dates and times are on the owner's clock (the zone of Settings). A failure gives the page of an unexpected error of the web and an error in the log.

### 3.1 CSV — «Скачать список (CSV)»

- Address `/settings/export.csv`, file name `tracker-list-<YYYY-MM-DD>.csv` (the owner's date), type `text/csv; charset=utf-8`.
- Encoding UTF-8 **with BOM**, separator `;`, lines ending `\r\n`, quoting by RFC 4180 (a value with `;`, `"` or a line break goes in quotes, `"` doubled). This is what Excel with Russian regional settings opens by a double click with Cyrillic intact (the list separator there is `;`).
- One header line, then one line per title — all titles, the archive too — in the order «по названию» of the List (`text.py`).

| Column | Value |
|---|---|
| Название | `name` |
| Оригинальное название | `original_name`; empty when equal to the name |
| Тип | the kind's label of `kinds.py`: Фильм · Сериал · Аниме · Игра |
| Статус | the status label of `cards.STATUS_LABELS` |
| Оценка | the title's visible score as the card shows it (`scores.visible`, label `8+`, `7−`); empty without one |
| Год | `year`; empty when unknown |
| Добавлен | `added_at`, `ДД.ММ.ГГГГ` |
| Завершён | `status_changed_at`, `ДД.ММ.ГГГГ`, only for «Просмотрено», «Пройдено», «Бросил»; empty otherwise |

The column «Оригинальное название» is one more than the description lists: without it two titles of one name cannot be told apart.

- A cell that begins with `=`, `+`, `-`, `@`, a tab or a carriage return gets a leading `'` (Excel would read it as a formula). A score never begins with these (`8+`).
- An empty list gives the header line only.

### 3.2 JSON — «Скачать всё (JSON)»

- Address `/settings/export.json`, file name `tracker-all-<YYYY-MM-DD>.json`, type `application/json`; UTF-8 without BOM, `ensure_ascii=False`, indent 2.
- Moments are ISO 8601 with the owner's offset (`2026-11-07T16:21:05+03:00`); days are `YYYY-MM-DD`; `null` for none.
- Shape (version 1):

```json
{
  "format": "release-tracker-export",
  "version": 1,
  "exported_at": "2026-11-07T16:21:05+03:00",
  "time_zone": "Europe/Moscow",
  "database_revision": "0014",
  "titles": [
    {
      "id": 12,
      "kind": "series",
      "name": "Одни из нас",
      "original_name": "The Last of Us",
      "year": 2023,
      "genres": ["Драма"],
      "overview": "…",
      "poster": "/abc.jpg",
      "status": "in_progress",
      "status_label": "В процессе",
      "score": "8+",
      "tracking": true,
      "added_at": "2026-10-20T19:02:11+03:00",
      "status_changed_at": "2026-10-28T21:40:00+03:00",
      "restored_at": null,
      "sources": [{"source": "tmdb_tv", "id": "100088"}],
      "seasons": [
        {"number": 1, "name": "Сезон 1", "episode_count": 9, "watched": true, "score": "8",
         "episodes": [{"number": 1, "air_at": "2023-01-16T04:00:00+03:00"}],
         "parts": []}
      ],
      "franchise_movies": [],
      "platforms": [],
      "expansion_of": null,
      "price_history": []
    }
  ],
  "settings": {"summary_at": "15:00"},
  "inbox": [
    {"id": 3, "state": "inbox", "reason": "not_found", "kind": null, "text": "…", "links": [],
     "post_url": null, "received_at": "2026-11-06T10:12:00+03:00", "moved_at": "2026-11-06T22:12:00+03:00"}
  ]
}
```

- `status`, `kind`, inbox `state` and `reason` are the stored values of the enumerations; `status_label` is for a human. `score` is the label of the title's own score or `null` (in the JSON the own score, not the average of seasons); a season's `score` is its label or `null`.
- `sources` — the rows of `external_ids` (`source`, `external_id` as `id`), the role left out.
- `parts` of a season — `number`, `first_episode`, `episode_count` (anime source ids left out); `franchise_movies` — `name`, `aired_on`, `released`; `platforms` — `platform`, `playing`; `expansion_of` — the name of the base game as the card shows it (`games.expansion_of`), else `null`; `price_history` — `seen_at`, `country`, `currency`, `final`, `original`, `pct` (amounts in hundredths, as stored).
- `settings` — every row of the table `settings` as stored (key → value).
- `inbox` — every inbox item, newest first, with the fields shown; the internal ones (`bold`, `media`, `media_group_id`, `forwarded`, `query`, `offers`, `last_message_at`) left out.
- **Left out on purpose**: source snapshots (and with them the follow-up snapshots), events, the delivery queue, `failure_notified_at`, anything of `.env` and `data/` files. They are the app's working state, which the sources give again; the export is the owner's data.
- An empty database gives empty lists.

## 4. The Google Drive copy

### 4.1 Launch settings (`.env`, read by `Settings` in `app/config.py`)

| Variable | Meaning |
|---|---|
| `BACKUP_PASSWORD` | the password of the archives; at least 12 characters after the outer spaces are dropped; any letters (the `$` ban of `.env` holds); never printed or logged (masked by its name) |
| `GOOGLE_DRIVE_CLIENT_ID` | the client id of the owner's Google client («Desktop app») |
| `GOOGLE_DRIVE_CLIENT_SECRET` | its secret (Google calls it public for desktop apps, still kept as a secret and masked) |

The Google Drive copy is **on** when all three are set and the password is long enough; it then still needs the one-time connection (4.2). None of them is required for the bot to start; a short password does not stop the start — Settings says so (4.7). `.env.example` gets the three lines with Russian comments (the password: «храните его и вне этого ПК — без него копии из Google Drive не открыть»).

### 4.2 Connecting: «Подключить Google Drive»

The sign-in is OAuth 2.0 for a desktop client with PKCE (S256), scope `https://www.googleapis.com/auth/drive.file` only — the app sees only the files it created itself.

1. `GET /settings/google-drive/connect` (behind the sign-in). Allowed only when the page is opened on this PC: the `Host` of the request is `localhost` or `127.0.0.1` (with any port). Otherwise back to Settings with the notice `Подключить Google Drive можно только на этом ПК: откройте http://localhost:8080/settings.` (the port of `WEB_PORT`, default 8080).
2. The app makes a `state` (32 random bytes) and a PKCE verifier, keeps them in memory for 10 minutes (one pending sign-in; a new press replaces it), and redirects to `https://accounts.google.com/o/oauth2/v2/auth` with `client_id`, `redirect_uri = http://<host of the request>:<port>/settings/google-drive/callback`, `response_type=code`, the scope, `access_type=offline`, `prompt=consent` (so a refresh token always comes), `state`, `code_challenge`, `code_challenge_method=S256`.
3. `GET /settings/google-drive/callback?code=…&state=…` (behind the sign-in; the owner's browser still has the session cookie of the same host). The `state` must match the pending one; then `POST https://oauth2.googleapis.com/token` with `grant_type=authorization_code`, the code, `client_id`, `client_secret`, the same `redirect_uri`, `code_verifier`. The answer's `refresh_token` is written to `data/google_drive_token.json` (4.3). Then the folder is found or made (4.4), the newest copy is sent at once in the background, and Settings shows `Google Drive подключён. Первая копия отправляется — итог появится здесь через минуту.`

| Callback case | Notice in Settings | Stored |
|---|---|---|
| `error=access_denied` | `Вы не дали доступ к Google Drive — копия туда не включена.` | nothing |
| other `error=` | `Google не подтвердил вход ({error}). Попробуйте ещё раз.` | nothing |
| no or stale `state` (over 10 min, a restart in between, another tab) | `Вход в Google не завершён — нажмите «Подключить Google Drive» ещё раз.` | nothing |
| the token request fails or brings no refresh token | `Google не подтвердил вход. Попробуйте ещё раз; если повторится — подробности в журнале.` | nothing |
| the Google Drive copy is not on (4.1) | back to Settings, no notice | nothing |

**Risk checked live in ticket 03:** Google documents the loopback redirect of desktop clients as `http://127.0.0.1:port` with an optional path and says `localhost` is possible; whether `localhost` with the path `/settings/google-drive/callback` is accepted is seen only with the owner's client. Fallbacks, in order: `127.0.0.1` instead of `localhost` (the owner is sent to `http://127.0.0.1:<port>/settings` first, where they sign in once more); then the path `/` with `code` and `state` handled by the Feed address. The ticket records which one works in `checks.md`.

`POST /settings/google-drive/disconnect` — «Отключить Google Drive»: revokes the refresh token (`POST https://oauth2.googleapis.com/revoke`, a failure only logged), deletes `data/google_drive_token.json` and the state file, notice `Google Drive отключён. Копии, которые уже там, остались в папке «Трекер — копии».`

### 4.3 Files in `data/`

| File | Holds | Secret |
|---|---|---|
| `google_drive_token.json` | `refresh_token`, `connected_at` (UTC), `folder_id` | yes: never printed, logged or put into a copy or an export; written with the rights of the app's user only |
| `google_drive_state.json` | `last_attempt_at`, `last_success_at`, `last_success_name`, `kept` (copies in the folder after the last success), `error` (reason key of 4.6 or `null`), `failures_in_row`, all times UTC | no |

A spoiled file of either is treated as absent (the token: «Google Drive не подключён»; the state: no attempts yet), with a warning in the log. Writes go through a temporary file and `os.replace`. They live outside the database on purpose: a restore of an old copy must not bring back an old connection or an old state.

### 4.4 Sending a copy

What is sent: the newest daily or manual copy (before-migration and before-restore copies are not sent).

1. **Archive.** `data/backups/upload/tracker_db_<time>.7z` (a manual copy keeps `_manual`), made with `py7zr`: one file — the copy under its own name — LZMA2 with AES-256, header encryption on (names hidden), password `BACKUP_PASSWORD`. The archive is deleted after the attempt, sent or not. (`checks.md`, 1: 7-Zip 25.01 opens it by the password; 45 KB for today's 520 KB database.)
2. **Access token.** `POST https://oauth2.googleapis.com/token` with `grant_type=refresh_token`; kept in memory until a minute before it expires.
3. **Folder.** `folder_id` from the token file; when absent or Google answers 404 for it (the owner deleted the folder), `GET /drive/v3/files?q=name='Трекер — копии' and mimeType='application/vnd.google-apps.folder' and trashed=false` (sees only the app's own folders); none — `POST /drive/v3/files` with that name and the folder type in the root of My Drive. The id is written to the token file.
4. **Already there?** `GET /drive/v3/files?q='<folder>' in parents and trashed=false&fields=files(id,name,size,createdTime)&pageSize=1000`. A file of the same name and size counts as sent (a retry after a lost answer makes no duplicate).
5. **Upload.** Resumable upload in one piece: `POST https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable` with the metadata `{"name": "<archive name>", "parents": ["<folder>"]}`, then `PUT` of the bytes to the address in `Location` (`Content-Type: application/x-7z-compressed`). Works for any size, a small database too.
6. **Rotation.** From the listing of step 4 plus the new file: the files named `tracker_db_<time>[_manual].7z`, by the time in the name; all but the 30 newest are deleted (`DELETE /drive/v3/files/<id>`; the app deletes only its own archives; other files in the folder are not touched). A failed delete is a warning in the log; the copy counts as sent.
7. **State.** Success: `last_success_*`, `kept`, `error = null`, `failures_in_row = 0`. Failure: `error`, `failures_in_row + 1`, `last_attempt_at`.

Timeouts: 30 s a request; the whole attempt is never longer than 5 minutes. The requests run in `httpx` (async) and the archive in a worker thread (rule 1). A 401 answer refreshes the access token once and repeats the request once.

### 4.5 When copies go

- The hourly job (`backup_database`): after its daily copy (made or not due), when the Google Drive copy is on and connected and the newest sendable copy is not `last_success_name` — send it. So: a new daily copy goes within the same run; a failed one is tried again every hour; a manual copy that did not go is retried too; the PC that was off for days sends at its start.
- «Сделать копию сейчас» (2.2) and the connection (4.2) send at once.
- One attempt at a time (the lock of 2.2 covers it).

### 4.6 Failures and their report

| Reason key | When | Text after «не ушла: » | Reported |
|---|---|---|---|
| `connection` | no answer, DNS, timeout | `нет связи с Google Drive` | at the 2nd failure in a row |
| `sign_in` | `invalid_grant` on refresh, 401 after a refresh, token file gone | `Google Drive не принял вход — подключите его заново в Настройках` | at once |
| `full` | 403 `storageQuotaExceeded` | `в Google Drive нет места` | at once |
| `down` | 5xx, 429, 403 `rateLimitExceeded` / `userRateLimitExceeded` | `Google Drive сейчас недоступен` | at the 2nd failure in a row |
| `no_copy` | no copy on the PC to send | `на этом ПК нет копии базы` | at once |
| `unknown` | anything else (the archive too) | `неизвестная ошибка, подробности в журнале` | at the 2nd failure in a row |

The event `backup_failed` (title-less, so the Feed does not show it; delivered by the delivery rules like «could not check»), dedup key `backup_failed:<drive | local>:<owner's YYYY-MM-DD>` — at most one report of each kind a day. Texts:

- Google Drive: `⚠️ Копия в Google Drive не ушла: {reason}. Последняя удачная — {when}. Попробую снова через час.` — without a success yet: `… Удачных копий там ещё не было. Попробую снова через час.`; for `sign_in`, the last sentence is left out (nothing is retried until the owner connects again — the hourly job does not try while the reason is `sign_in` and the token is the same).
- Local (1.3): `⚠️ Копия базы не сделана: {reason}. Последняя — {when}. Попробую снова через час.`

The texts and reasons live next to the failure texts of the sources (`failures.py` or a module of its own — the ticket decides by rule 7); the bot's sample list of «Тестовое событие» gets both samples.

### 4.7 The line of the Google Drive copy in Settings

| State | Line | Button |
|---|---|---|
| Off: no client id or secret | `Копия в Google Drive выключена. Как включить — docs/backups.md в папке трекера.` | — |
| Keys set, password missing or short | `Копия в Google Drive не включится: в .env нет пароля BACKUP_PASSWORD или он короче 12 знаков.` | — |
| On, not connected | `Google Drive не подключён.` | «Подключить Google Drive» (on another host — the sentence of 4.2 instead of the button) |
| Connected, nothing sent yet | `Google Drive подключён; первая копия уйдёт в течение часа.` | «Отключить Google Drive» |
| Works | `Копия в Google Drive: {when}, там {kept} {копия/копии/копий} из 30 хранимых.` | «Отключить Google Drive» |
| Failed last time | `Копия в Google Drive не ушла: {when of the attempt} — {reason}. Последняя удачная — {when}.` (or `Удачных ещё не было.`) | «Отключить Google Drive»; for `sign_in` «Подключить Google Drive» too |

Under the line, when connected or failed (small text): `Копии зашифрованы паролем BACKUP_PASSWORD из .env. Храните его и вне этого ПК: без него копии из Google Drive не открыть. Новый пароль действует только для новых копий.`

### 4.8 Instructions for the owner: `docs/backups.md`

An English doc (repository rule; the ticket session also gives it to the owner in Russian in chat): what is copied where; turning the Google Drive copy on — create a Google Cloud project, enable the Google Drive API, the consent screen «External» with the scope `drive.file`, **publish the app** («In production»: in «Testing» Google ends the sign-in after 7 days), a client «Desktop app», the two values into `.env`, a password into `.env` and into a password manager, `.\start-bot.ps1`, «Подключить Google Drive» (Google may warn that the app is not verified — «Дополнительно» → «Перейти»); opening an archive by hand with 7-Zip; restoring (section 5); turning off. `CLAUDE.md` "Run" gets one line pointing to it and to `restore-bot.ps1`.

## 5. Restore: `.\restore-bot.ps1`

### 5.1 How it is built

- `restore-bot.ps1` in the root, like `start-bot.ps1`: goes to its folder, UTF-8 console, checks Docker and `.env` with the same texts, and asks the owner (`Read-Host`). The work is done by Python inside a one-off container of the same image, `docker compose run --rm --no-deps --build tracker python -m app.container_start app.utils.restore <command> …`, so it needs no Python, rclone or 7-Zip on the PC. `app.container_start` learns to run a given module after the same rights fix (the default stays `app.main`). The one-off container does not start the bot.
- Commands of `app.utils.restore` (texts in Russian on stdout, exit code 0 / 1; nothing interactive inside the container):
  - `list` — the numbered list of copies (5.2);
  - `check <path>` — checks a copy or opens an archive (5.3) and prints its description; touches nothing;
  - `apply <path>` — the replacement (5.4), only while the bot is stopped.
- The script: `list` (or `check` for a given path) → the owner chooses and confirms → `.\stop-bot.ps1` → `apply` → `.\start-bot.ps1` → the final line. Everything before «да» runs while the bot works: nothing is changed until then.

### 5.2 Without arguments: the list of copies on the PC

```text
Копии базы в data\backups (новые сверху):
  1) сегодня в 07:58
  2) вчера в 18:32 — сделана вручную
  3) вчера в 07:58 — перед обновлением базы
  4) 6 ноября в 16:25 — перед восстановлением
  …
 31) 25 октября 2025 в 09:12
Номер копии (Enter — отмена):
```

All copies of 1.2, newest first, the moment in words (2.1), the kind after a dash (daily — nothing). No copies: `В data\backups нет копий базы. Восстановить можно из скачанной копии: .\restore-bot.ps1 "путь к файлу"` — exit. A number not in the list: `Нет копии с номером {x}.` and the question again; Enter — `Отменено. Ничего не изменено.`

### 5.3 With a path: a downloaded archive or a `.db`

`.\restore-bot.ps1 "C:\Users\…\Downloads\tracker_db_20261107_075800.7z"`. The file must exist (`Файл не найден: {path}`); the script copies it into `data\restore\` (the container sees only `data`), and that folder is emptied when the script ends, whatever happened. A `.7z` is opened by `BACKUP_PASSWORD` from the container's environment (the PowerShell script never reads `.env` values); a `.db` (e.g. taken out of an archive by 7-Zip by hand) is checked as it is. Any other extension: `Нужен файл .7z из Google Drive или .db из копий. Ничего не изменено.`

| Case (`check`) | Text, then exit with nothing changed |
|---|---|
| `.7z`, no `BACKUP_PASSWORD` | `В .env нет BACKUP_PASSWORD — впишите пароль копий и запустите снова. Или откройте архив 7-Zip вручную и укажите путь к файлу .db из него.` |
| not a 7z file (`py7zr.is_7zfile` false) | `Это не архив 7z. Ничего не изменено.` |
| the password does not open it, or the archive is damaged (any exception of py7zr while opening or extracting — a wrong password gives garbage errors, `checks.md`, 1) | `Пароль из .env не подходит к этой копии, или архив повреждён. Проверьте BACKUP_PASSWORD или откройте архив 7-Zip и введите пароль вручную.` |
| the archive holds not exactly one `.db` | `В архиве нет копии базы трекера. Ничего не изменено.` |

### 5.4 The checks of a copy (both ways), before any change

| Check | Text when it fails |
|---|---|
| it opens as SQLite read-only and `PRAGMA integrity_check` says `ok` | `Копия повреждена (проверка SQLite не прошла). Ничего не изменено. Выберите другую копию.` |
| it has the tables `alembic_version` and `titles` | `Этот файл не похож на копию базы трекера. Ничего не изменено.` |
| its revision is known to this version of the code | `Эта копия сделана более новой версией трекера (база {rev}, а эта версия знает до {head}). Обновите трекер и запустите снова. Ничего не изменено.` |
| its revision is older than the head | not an error: the confirmation adds `Копия от более старой версии: при запуске база обновится сама (перед этим сделается ещё одна копия).` |

Then the confirmation (PowerShell): `Вернуть базу к копии от {when}? Всё, что изменилось позже, пропадёт. Нынешняя база сохранится отдельно. (да/нет):` — only `да` (any case, spaces dropped) goes on; anything else — `Отменено. Ничего не изменено.` For a downloaded file the moment is the time in its name; a name without one reads `из файла {name}`.

### 5.5 The replacement (`apply`), with the bot stopped

1. `.\stop-bot.ps1`; then the script makes sure the container is not running (`docker compose ps -q tracker` empty), up to 60 s. Otherwise: `Бот не остановился за 60 секунд. База не тронута. Остановите его: .\stop-bot.ps1 и запустите восстановление снова.` — exit 1, the bot is not started again.
2. `apply` checks the copy again (5.4) — it may have changed — and stops with the same texts, then: `.\start-bot.ps1` brings the bot back on the old base.
3. The current `data/tracker.db` (when it exists) is copied by the online backup to `data/backups/tracker_db_<now>_before-restore.db` — it takes the content of its `-wal` too. `Нынешняя база сохранена: data\backups\{name}`. A failure (a full disk) stops everything: `Не удалось сохранить нынешнюю базу ({reason}). Ничего не изменено.`
4. The current base is checkpointed (`PRAGMA wal_checkpoint(TRUNCATE)`) and closed; its `-wal` and `-shm` files, if still there, are deleted.
5. The copy is written by the online backup into `data/tracker.db.restoring`, checked (`integrity_check`), then `os.replace` onto `data/tracker.db`. A failure before `os.replace` leaves the current base as it was (the temporary file deleted): `Не удалось восстановить ({reason}). База не тронута.`
6. `База восстановлена из копии от {when}.` → `Запускаю бота…` → `.\start-bot.ps1` (its own lines) → `Готово: бот работает на копии от {when}.`. When the start fails: `База восстановлена, но бот не запустился — ошибка выше. Вернуть прежнюю базу: .\restore-bot.ps1 и выберите копию «перед восстановлением».`

The restore touches only `tracker.db` (and its `-wal`/`-shm`): not `.env`, `web_secret`, the Google Drive files or the logs. After it, the Google Drive copy goes on as before: the next daily copy is of the restored base.

## 6. Edge cases

| Case | Behaviour |
|---|---|
| A daily and a manual copy in the same second | different names (`_manual`); both copies |
| The owner restores a before-restore copy | allowed: it is a copy like the others; a new before-restore copy of the current base is made first |
| A copy older than the oldest migration still in the code | its revision is known (all revisions stay in the code), so it migrates at the start |
| The archive is opened while the PC has no `BACKUP_PASSWORD` but the owner knows the password | 7-Zip by hand, then `.\restore-bot.ps1 "…\tracker_db_….db"` |
| The password was changed after older archives went | new ones open with the new password; an old one gives the «Пароль не подходит» text; the owner opens it with 7-Zip and the old password, then restores the `.db` |
| The owner deletes the folder «Трекер — копии» in Drive | the next attempt makes it anew (4.4, 3); the old archives are gone with it |
| The owner moves archives out of the folder | they are no longer counted or deleted |
| Google Drive is full | `full`, reported at once, retried hourly (the owner may free space) |
| The owner revokes the access in the Google account | `sign_in`, reported once, no retries until «Подключить Google Drive» |
| 100 sign-ins with one client (Google's limit of refresh tokens) | the oldest token stops working — irrelevant for one owner who connects once |
| The PC sleeps during an upload | the attempt fails by timeout; the next hour sends the same copy (the same name — step 4 sees a whole file of the same size, or sends anew) |
| The page is opened from the phone in the home network (`WEB_HOST=0.0.0.0`) | Settings works; «Подключить Google Drive» is replaced by the sentence of 4.2; downloads work |
| A manual copy pressed while the bot was restoring | impossible: the bot is stopped during `apply` |
| `restore-bot.ps1` with the bot already stopped | it goes the same way; at the end the bot is started (its normal state) |
| `data\restore\` left from a broken run | emptied at the start and at the end of the script |
| Settings zone differs from `BOT_TIMEZONE` | the copy times are shown as written in the names (the container's clock): KI-66 |
| The export of a huge list | built in memory in a worker thread; thousands of titles are a few MB |

## 7. Tests

**Automated** (offline; fake HTTP for Google, temporary folders, SQLite files):

- Copies: the kinds and names of 1.2, the manual rotation (10) not touching the daily ones and the other way round, the ordering for the list, names that only look like copies; `backup_failed` local at a raising copy, once a day.
- Settings block: every line of 2 and 4.7 from a prepared folder and state files; the moment in words (2.1); «Сделать копию сейчас» with every notice of 2.2 (a fake uploader: success, failure, slow), the lock.
- Export: CSV bytes (BOM, `;`, `\r\n`, quoting, the `'` guard, the columns and the order, empty list); JSON shape and the left-out parts on a prepared database with each kind; both behind the sign-in (rule 10's test covers new addresses by itself).
- Archive: py7zr round trip with a Cyrillic password; wrong password, junk and cut files map to the texts of 5.3. (The real 7-Zip check stays in `checks.md`; no 7-Zip in the test environment.)
- Google Drive: the connect redirect (parameters, PKCE, only on `localhost`/`127.0.0.1`), every callback case of 4.2, disconnect; sending: folder found / made / gone (404), already there, resumable upload, 401 once then success, rotation keeps 30 and only own names, each reason of 4.6 from fake answers, the report rule (2nd failure / at once), the dedup per day, no retry on `sign_in`, the state file; spoiled token and state files; secrets never in the log (the masking test gets the new names).
- Restore: `list`, `check`, `apply` on files in a temporary folder: every text of 5.2–5.5, the before-restore copy taking the WAL content, a newer revision refused, an older one accepted, `integrity_check` failure, a failure before `os.replace` leaving the base whole; `container_start` running a given module. The PowerShell script itself is checked by the session live (as `start-bot.ps1` is), and its texts by a test that reads the script file.

**Live, by the session and the owner**: the downloads open (CSV in Excel), «Сделать копию сейчас», the Google sign-in and the first archive in Drive (only the owner: their Google account), the archive opened with 7-Zip for Windows by the password, both restores (a local copy, a downloaded archive) and the way back by the before-restore copy.

## 8. Dependencies and image

- `py7zr>=1.1,<2` in `requirements.txt` (adds about 25 MB to the image: `checks.md`, 1). No rclone, no 7-Zip in the image.
- `data/backups/upload/` and `data/restore/` are made by the app or the script as needed; `app/container_start.py` already hands `data` over to the app's user.

## 9. Docs to update

- `CONTEXT.md` (by the tickets that bring them, rule 5): **Копия базы** (backup; a file of `data/backups`; kinds daily · manual · before an update · before a restore; in code `backup`), **Копия в Google Drive** (an encrypted archive of a copy in the owner's Drive; in code `drive copy`, module `google_drive`), **Пароль копий** (`BACKUP_PASSWORD`), **Выгрузка** (export: the CSV list and the JSON of everything, download only; in code `export`), **Восстановление** (restore: the base replaced by a copy, by `restore-bot.ps1`; in code `restore`). _Avoid_: бэкап (in messages), дамп, импорт.
- `PROJECT_CONTEXT.md`: the three variables in the `.env` table; Google Drive in the external services table; `data/google_drive_*.json` in the Gotchas next to `startup_failure.json`.
- `CLAUDE.md` "Run": one line — copies, `docs/backups.md`, `.\restore-bot.ps1`.
- `docs/code-map.md` "Not Python": `restore-bot.ps1`, `docs/backups.md`, the new `data/` files.
- `docs/project-spec.md` stage 7.1: «by rclone» → «through the Google Drive API with the owner's own Google client» (done by this session).

## 10. ADR and known issues

- **ADR 0012** «Copies go to Google Drive through its API with the owner's own Google client» — written with this spec.
- **KI-66** — the time of a copy is the container's clock, not the zone of Settings — written with this spec.
- No open KI is closed by this stage.

## 11. Proposed tickets

| # | Ticket | Complexity | Blocked by | Spec sections |
|---|---|---|---|---|
| 01 | Settings block «Копии и выгрузка»: copies on the PC, «Сделать копию сейчас», the manual copies, the local failure report | medium | — | 1, 2 (without the Google Drive line), 4.6 (local), 2.1 |
| 02 | Export CSV and JSON | medium | 01 (the buttons' place) | 3 |
| 03 | Google Drive: `.env` variables, connect and disconnect, the line of 4.7 for the states without copies, `docs/backups.md` (setting up), live check of the redirect (4.2 risk) | complex | 01 | 4.1–4.3, 4.7, 4.8 |
| 04 | Google Drive copies: the archive, sending, rotation, retries, the report, the remaining lines of 4.7, «Сделать копию сейчас» with sending | complex | 03 | 4.4–4.7, 2.2 |
| 05 | Restore: `restore-bot.ps1`, `app.utils.restore`, `container_start` with a module, `docs/backups.md` (restoring) | complex | 01, 04 (the archive) | 5, 6 |

About 7 sessions from here: slicing, five tickets, the review (the estimate in `PROJECT_CONTEXT.md` grows from 6 to 8 with this spec).
