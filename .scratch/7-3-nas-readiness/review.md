# Review 7.3: NAS readiness and the move guide

Status: accepted

One session (2026-11-25).

## What was reviewed

- Commits `1375caf..cb17a20` (after the accepted slicing): tickets 01 (7bb4e66, dcd515b), 02 (9436b5c), 03 (2972d5b) and their «accepted» commits; the spec, the three tickets.
- Against `spec.md` (sections 1–8) and `docs/coding-standards.md` (rules 4, 5 and 11 apply: the stage touches no core, web or bot code), with the `code-review` skill at effort high over `app/utils/restore.py`, `app/container_start.py`, `restore-bot.ps1`, `Dockerfile`, the override example, `.gitignore` (line by line, removed behaviour, callers, the rules of `CLAUDE.md`). Then a pass for the spec: the asking restore step by step (2.2), the texts (2.3), the guard (2.4), the script (2.5), KI-15 (3.1), the `# syntax` line (3.2), the override (3.3), the ten sections of the guide and its problems 1–18 (4), the edge cases (5), the docs and terms (7).
- Every text the guide says the app prints exists in the code (`Неизвестный адрес сайта.`, `токен бота неверного вида`, «Google Drive не принял вход…», the refusal to write, `{"status":"ok"}` of `/health`, `polling title … failed`). `CONTEXT.md` has «Восстановление», «Переезд», «Отчёт о переезде» in the words of the guide. No deviation from the spec found beyond F1–F4.

## Tests

- At the start: 5500 passed, 3 skipped; only the two known Windows failures (`test_app_main`, `test_runtime`). `pyflakes app tests` clean.
- At the end (after the fixes): 5500 passed, 3 skipped (no new test: F1–F4 changed docs, the script and the order test); the same two known Windows failures, nothing new. `pyflakes app tests` clean; the code map unchanged (no docstring changed).

## Verified by running

- **The NAS way of the restore, with `docker compose stop`** (the tickets checked the guard after `.\stop-bot.ps1`, which is `docker compose down` and removes the container; on the NAS the container stays, stopped): the guard sees the bot stopped; `printf '\n' | docker compose run --rm -T tracker …` lists the 38 copies and Enter gives «Отменено. Ничего не изменено.», exit 0; `printf '1\nнет\n'` checks the copy («…в порядке, тайтлов в ней: 37»), asks the question and cancels, exit 0. Then `.\start-bot.ps1` — «Готово».
- **The guard with no answer from the name service** (a one-off container of the image on the bot's network with `--dns 192.0.2.1`): bot running — the name resolves at once (`172.18.0.2`); bot stopped — `EAI_AGAIN` after 8 s and `bot_running()` is `True` (F1). With the normal DNS — `EAI_NONAME`, stopped.
- **`restore-bot.ps1` after F4**: a missing file — «Файл не найден: …» at once (0 s, no build); no path and Enter — «Готовлю образ бота…», the list, cancelled, exit 0.
- **The bot in Docker**: before the review up 5 hours, healthy, `/health` `{"status":"ok"}`; after the checks and the fixes started by `.\start-bot.ps1` — «Готово», `/health` `{"status":"ok"}`, `Job "Tracker.poll_due …" executed successfully` every minute (Russian check 1 game, 0 failed), no error, traceback or `polling title … failed`.
- Not run live here: a real restore (done twice by ticket 01, once across two disks by ticket 02), an Engine below 25, the HDD and its sleep, UGOS — the NAS project's report (7.4).

## Findings

- **F1 — with no answer from the name service the asking restore refuses a stopped bot with «Бот работает…».** `bot_running` counts every resolver error but «no such name» as running (spec 2.4: unknown is running); with the host's DNS down Docker's resolver answers `EAI_AGAIN` after 8 s (checked live, above). The base is never touched by mistake, but the text is false and the restore waits for the network. Decision: **defer `KI-92`, 9.2 if met** (a rare case; a way past the guard is a design choice); fixed now in the guide: section 7 says what the pause and the text mean.
- **F2 — `docs/backups.md` «Without PowerShell» says the three commands work in PowerShell on the PC too, and its step 3 starts the bot by `docker compose up -d`**, while `CLAUDE.md` says `.\start-bot.ps1` is the only way to start (it checks `.env` and stops an old bot of `.venv`). Decision: **fixed now** — step 3 says: on the PC `.\start-bot.ps1` instead. The app's lines `START_NOW`/`START_OLD` stay: they are for the NAS.
- **F3 — the `.env` check of the guide (section 5, step 4) missed a `$` after a `#` inside a value** (`grep -n '^[^#]*\$'`; `WEB_PASSWORD=ab#c$d` passed), while `.\start-bot.ps1` refuses any `$` on a line that is not a comment. Decision: **fixed now** — `grep -nv '^[[:space:]]*#' .env | grep '\$' | cut -d= -f1` (checked on a sample file: it finds both lines, the old one only one).
- **F4 — `.\restore-bot.ps1 "wrong path"` built the whole image before «Файл не найден»** (offline: Docker's build error instead of the plain line). Decision: **fixed now** — the given file is checked first, the image is built before the file is used and before the list; the test of the order follows.

No finding needs a fix round: the stage closes once the owner accepts.

## Wishes for later stages

- 7.4: take in from the report the Docker and Compose versions, whether `docker compose stop` + the asking restore worked on the NAS as on the PC, the HDD's sleep (KI-90), `df` after a restart (KI-91).
- 9.2: KI-92 if the restore is ever needed with the network down.
