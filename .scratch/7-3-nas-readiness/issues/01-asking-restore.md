# 01: The asking restore — three `docker compose` commands, the running guard, texts with `/`, KI-70

Status: accepted
Complexity: medium (one module grows a mode and a guard, one script changes, texts and docs; no migration)
Blocked by: —

Spec: `../spec.md`, section 1 (facts 1 and 5), section 2 (2.1–2.5), the rows of section 5 about the restore, the first two lines of the tests of section 6 (`tests/test_restore.py` and `restore-bot.ps1`), and the `docs/backups.md`, `CONTEXT.md` «Восстановление» and `KNOWN_ISSUES.md` (KI-70) lines of section 7. Terms — `CONTEXT.md` («Восстановление», «Копия базы»). ADRs to read: 0005, 0007, 0012. Standards — `docs/coding-standards.md`, the rules on modules, texts and tests. The `RESTORE_COMMAND` quote in `docs/nas-move.md` is checked by ticket 03, not here.

## What to do

Work in this order; each step leaves the suite green.

1. **Texts and constants (2.3).** In `app/utils/restore.py` add `RESTORE_COMMAND`, `SERVICE_NAME`, `NO_COPIES_ASKING`, `NUMBER_PROMPT`, `NO_SUCH_COPY`, `CANCELLED`, `QUESTION`, `BOT_RUNNING`, `START_NOW`, `START_OLD`; change `HEADER`, `UNREADABLE`, `SAVED` (the slash), `USAGE` (the asking mode). `NO_COPIES` of the script stays. Existing tests that quote the old texts follow the new ones.
2. **`bot_running()` (2.4).** `socket.getaddrinfo(SERVICE_NAME, 8080)`: `EAI_NONAME` (and `EAI_NODATA` where defined) → stopped; resolves → running; any other error → unknown, counted as running. The function is a parameter of the commands, so the tests fake it. `SERVICE_NAME` is the service of `docker-compose.yml`.
3. **The guard in `apply` (2.4).** `apply` refuses with `BOT_RUNNING` (exit 1, base untouched) while the bot runs, so `restore-bot.ps1` is guarded too (it stops the bot before `apply`, so its flow does not change).
4. **The asking mode (2.2).** No arguments → steps 1–7 of 2.2: the guard, the list without `@` lines, the number prompt (Enter, a wrong number asked again, end of input as empty), `check`, the question, the guard again, `apply`, `START_NOW` or `START_OLD`. One argument that is not `list`, `check`, `apply` → the path of a file, the same steps from `check` on. Answers are read from standard input line by line (input that is not UTF-8 read with replacement characters); `Ctrl+C` at a prompt → `CANCELLED`, exit 1. The commands `list`, `check <path>`, `apply <path>` stay as they are.
5. **`restore-bot.ps1` (2.5, KI-70).** Before the list (or the given file) one `docker compose build --quiet` with `Готовлю образ бота…`; a failure → Docker's lines, `Образ бота не собрать — ошибка выше. Ничего не изменено.`, exit 1. `Invoke-Restore` runs `docker compose run --rm --no-deps --interactive=false -T tracker python -m app.container_start app.utils.restore @Arguments` — no `--build`, no `--quiet-build`. Nothing else in the script changes.
6. **Docs.** `docs/backups.md`: «Restoring the database» gets «Without PowerShell (the NAS)» — the three commands (quoting `RESTORE_COMMAND`) and a downloaded file in `data/restore/`; the quoted texts with `/`. `CONTEXT.md` «Восстановление»: also by three `docker compose` commands with the asking restore. Module docstring of `app/utils/restore.py` says what it holds, the guard by the service name and why it is a detail of this module (no ADR). `tools\code_map.py`; `docs/tests-map.md`; `KNOWN_ISSUES.md`: KI-70 → `fixed (test: …)` (entry and index).

## Done when

- [ ] `printf '1\nда\n' | docker compose run --rm -T tracker python -m app.container_start app.utils.restore` with the bot stopped lists the copies, restores the first one and says `START_NOW`; the copy «перед восстановлением» exists.
- [ ] With the bot running, the asking restore says `BOT_RUNNING` at once, exit 1, and reads no input; the same when the bot starts between the question and the change (base untouched).
- [ ] Enter, end of input, `нет`, `Ctrl+C` cancel with the right exit code and the base untouched; a wrong number is asked again.
- [ ] A path argument restores that file after the same check and question; a missing or wrong file gives `NOT_FOUND` / `WRONG_KIND`; a `.7z` with no `BACKUP_PASSWORD` gives `NO_PASSWORD`.
- [ ] `restore-bot.ps1` lists and restores as before, builds once with `--quiet`, uses no `--build` and no `--quiet-build`; a failed build ends with the new line and exit 1.
- [ ] `docs/backups.md` and `CONTEXT.md` agree with the code; the code map is rebuilt; pyflakes clean; the full suite green (the known Windows failures do not count).

## Tests to add

`tests/test_restore.py`: the asking mode with fake input and output and a fake `bot_running` — list → number → `да` → applied (texts and the copy before the restore); Enter, end of input, `нет` → cancelled; a wrong number asked again; a path argument; running at step 1 (nothing read from input) and at step 6 (base untouched); `apply` of the script refuses while running; `bot_running` with `getaddrinfo` faked (resolves → running, `EAI_NONAME` → stopped, `EAI_AGAIN` → running); the new texts exactly; `SERVICE_NAME` equals the service of `docker-compose.yml`; `RESTORE_COMMAND` quoted exactly in `docs/backups.md`. The script `restore-bot.ps1` (also in `tests/test_restore.py`, as the spec says): `docker compose build --quiet` before the first run; no `--build` and no `--quiet-build`.

## Owner check

The session starts the bot and writes the launch result in one line. Then, in PowerShell in `E:\LocalAI\Bionic\Telegram-bot`, the owner runs, one per block: `docker compose run --rm tracker python -m app.container_start app.utils.restore` while the bot runs — the right answer is the sentence «Бот работает, а базу можно заменить только у остановленного…» and nothing else; then `.\stop-bot.ps1`, the same command again — the list of copies appears, the owner types `1`, then `нет` — «Отменено. Ничего не изменено.»; then `.\start-bot.ps1` — «Готово». «Не так»: a red text with `Traceback`, the list asks nothing, the bot does not start afterwards. The session has already run the real restore of the newest copy and back from the copy «перед восстановлением», and says so.
