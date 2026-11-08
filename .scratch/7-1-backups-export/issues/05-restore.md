# 05: Restore — `restore-bot.ps1` and `app.utils.restore`

Status: in review
Complexity: complex (replaces the live database; a PowerShell script around a one-off container; many refusals that must leave the base whole)
Blocked by: 01 (the copies and the moment in words), 04 (the archive made by py7zr and the by-hand section of `docs/backups.md`)

Spec: `../spec.md`, sections 5 (all), 6 (rows on the before-restore copy, an old revision, the archive opened without `BACKUP_PASSWORD`, a changed password, `restore-bot.ps1` with the bot stopped, `data\restore\` left over, a manual copy during a restore), 7 (Restore and the live part), 9 (`CONTEXT.md` term «Восстановление», `CLAUDE.md`, `docs/code-map.md` "Not Python"). Terms — `CONTEXT.md`; standards — rules 1, 4, 7, 11; ADRs 0005, 0006, 0007, 0012. Read `start-bot.ps1` and `stop-bot.ps1` first: the new script copies their texts and checks.

## What to do

- **`app.container_start`** (5.1): runs a module given by name after the same rights fix (the default stays `app.main`); tests for both.
- **`app/utils/restore.py`** (commands `list`, `check <path>`, `apply <path>`; Russian texts on stdout, exit code 0 / 1; nothing interactive; the database is touched only by `apply`):
  - `list` — the numbered list of 5.2 (all copies of 1.2, newest first, the moment in words from ticket 01, the kind after a dash; the «нет копий» text);
  - `check` — a `.7z` opened with `BACKUP_PASSWORD` from the container's environment (`py7zr`; every exception on open or extract maps to the one text of 5.3, a missing password and a non-7z file to their own, an archive without exactly one `.db` to its own) or a `.db` as it is; then the checks of 5.4 in their order (integrity, the tables `alembic_version` and `titles`, a newer revision refused, an older one accepted with the note); prints the description of the copy;
  - `apply` — 5.5, steps 2–5 only while the bot is stopped: the check again; the current base copied by the online backup to `tracker_db_<now>_before-restore.db` (its `-wal` content included; a failure stops everything); `wal_checkpoint(TRUNCATE)`, close, the `-wal`/`-shm` removed; the copy written by the online backup to `data/tracker.db.restoring`, `integrity_check`, `os.replace`; a failure before `os.replace` leaves the base as it was with the temporary file deleted; only `tracker.db` and its `-wal`/`-shm` are touched, never `.env`, `web_secret`, the Google Drive files or the logs.
- **`restore-bot.ps1`** (5.1–5.5): in the root, like `start-bot.ps1` (goes to its folder, UTF-8 console, checks Docker and `.env` with the same texts); runs the commands through `docker compose run --rm --no-deps --build tracker python -m app.container_start app.utils.restore …`; without arguments the list and `Read-Host` for the number («Нет копии с номером {x}.» and ask again; Enter — «Отменено. Ничего не изменено.»); with a path the file must exist («Файл не найден: {path}»), is copied into `data\restore\` (emptied at the start and at the end whatever happened), any other extension than `.7z`/`.db` gets its text; the confirmation «Вернуть базу к копии от {when}? … (да/нет):» (only `да`, any case, spaces dropped); then `.\stop-bot.ps1`, `docker compose ps -q tracker` empty within 60 s (otherwise the text and exit 1, the bot not started again), `apply`, `.\start-bot.ps1`, the final line or the «бот не запустился» text; the script never reads `.env` values itself. With the bot already stopped it goes the same way and starts the bot at the end.
- **Docs:** `docs/backups.md` — the restoring section (from the list; from a downloaded archive; from a `.db` taken out by 7-Zip; the way back by the «перед восстановлением» copy; what the restore does not touch); `CLAUDE.md` "Run": the pointer line gets `.\restore-bot.ps1` (budget 60 lines / 6,000 bytes); `docs/code-map.md` "Not Python": `restore-bot.ps1`, `docs/backups.md`, `data/restore/`, `data/backups/upload/`; `CONTEXT.md` — the term «Восстановление» (in code `restore`; _Avoid_: откат); module docstrings, `.venv\Scripts\python.exe tools\code_map.py`; `docs/tests-map.md`.

## Done when

- [ ] `list`, `check` and `apply` print every text of 5.2–5.5 on files in a temporary folder; every refusal leaves the base and the files as they were.
- [ ] A restore from a local copy and from a downloaded `.7z` replaces the base, makes the before-restore copy first (with the WAL content), and leaves `.env`, `web_secret`, the Google Drive files and the logs alone; a newer revision is refused, an older one accepted and migrated at the start (with its own before-update copy).
- [ ] A failure before `os.replace` leaves the current base whole.
- [ ] The script, run live with the bot working: the list, a refusal by Enter, a refusal by «нет», a real restore, the bot back on «Готово»; a second restore back by the before-restore copy.
- [ ] A test reads the script file and finds its texts; `start-bot.ps1` and `stop-bot.ps1` keep working.
- [ ] No module of the core over 400 lines; `pyflakes app tests` clean; the full suite green (the three known Windows failures are not new).

## Tests to add

- `container_start` running a given module and the default.
- `list`: ordering, kinds, the moments, no copies; a number outside the list is the script's matter and is tested by the script-text test.
- `check`: a `.db` and a `.7z` (Cyrillic password), the wrong password, junk, a cut file, no password, two `.db` in an archive, a damaged SQLite, a file with no tables, a newer revision, an older one.
- `apply`: the before-restore copy taking the WAL content, the replacement, the `-wal`/`-shm` removal, a failure at each stage before `os.replace` leaving the base whole, a full disk on the before-restore copy, the files outside `tracker.db` untouched.
- The script: a test that reads `restore-bot.ps1` for its texts and the commands it calls.

## Owner check

The session starts and stops the bot itself during its own checks and writes the result in one line. The owner's check (PowerShell, folder `E:\LocalAI\Bionic\Telegram-bot`; the session gives it step by step in Russian):

1. Add a title in the web (any), then `.\restore-bot.ps1`: the list of copies appears; choose the copy from before that title (the newest daily one) and type `да`. The script stops the bot, replaces the base, starts the bot: «Готово: бот работает на копии от …».
2. Open the web: the title you just added is gone, everything older is as it was.
3. Run `.\restore-bot.ps1` again and choose the copy «перед восстановлением» of the same minute: the added title is back.
4. Download the `.7z` from Google Drive and run `.\restore-bot.ps1 "C:\Users\…\Downloads\<file>.7z"`: it asks the confirmation; type `нет` → «Отменено. Ничего не изменено.»

«Не так»: the bot not starting after a restore, a title that is still there after step 1, no «перед восстановлением» copy in the list, a question that accepts anything but «да».
