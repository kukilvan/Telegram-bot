# Review 9.1a: start, stop, polling and delivery

Status: accepted

One session (2026-11-20).

## What was reviewed

- Commits `8711ded..1085dd9` (after the accepted slicing): tickets 01 (952fe19), 02 (6de25a1), 05 (b147e5e), 03 (813c5e3), 04 (60a6d72) and their «accepted» commits; the spec, the five tickets, ADR 0015. The merge of idea 002 (86d854b: `CONTEXT.md`, `docs/project-spec.md`, `docs/ideas/002-…`) lies in the range but belongs to 9.1b and was not reviewed.
- Against `spec.md` (sections 1–9) and `docs/coding-standards.md` (rules 1–11, with `CONTEXT.md` for rule 5 and ADRs 0005, 0007, 0009 for the migrations, 0014, 0015), with the `code-review` skill at effort xhigh over the stage diff (correctness, removed behaviour, callers, language pitfalls, wrappers, reuse, simplification, efficiency, altitude, conventions), then a pass for the spec: every section and every row of section 7 compared with the code, the tickets' «Done when» lists, the `KNOWN_ISSUES.md` entries and index rows, the tests map, the Gotchas lines. KI-77 and KI-78 (left open by the spec) were not counted again.

## Tests

- At the start: 4379 passed, 3 skipped; only the three known Windows failures (`test_app_main`, `test_docker_files`, `test_runtime`). `pyflakes app tests` clean.
- At the end (after the fixes): «Tests at the end» below.

## Verified by running

- **The bot in Docker** (`.\start-bot.ps1` after the commit of the fixes): «Готово», `/health` 200, `Job "Tracker.poll_due …" executed successfully` within a minute, no `polling title … failed`, no error or traceback in the log.
- **The stop** (`.\stop-bot.ps1`): 1.8 s; `data/logs/bot.log` says `остановка по сигналу SIGTERM` … `остановлено`, no `прервана` line.
- **The hang** (2.3): the app (pid 7, the only child of Docker's init) frozen with `SIGSTOP` (the image has no `kill` program: `python -c "os.kill(7, signal.SIGSTOP)"`). The container restarted by itself after 133 s, the container log shows `/health не отвечает 4 раза подряд — приложение остановлено для перезапуска`, `/health` 200 again, the new app is pid 7 again. A second freeze 18 s after a start: restarted after 130 s — Docker checks every 2 s (`--start-interval`) only until the first healthy check, which comes in the first seconds, so the 1.5–2 min of the ADR hold from the start too (a suspicion of the code pass, dropped).
- **The start script and the old bot** (1.4, F2): two harmless dummies whose command line holds `-m app.main` (`python -c "import time; time.sleep(300)" -m app.main`), one of this folder's `.venv` (which starts the base Python as its child), one of the base Python. `.\start-bot.ps1` said «Остановлен старый бот, запущенный не через Docker», stopped the `.venv` dummy and its child, left the base Python's dummy alone (removed by hand after), and ended in «Готово».
- **A scratch web app of the real code** on a copy of `data/tracker.db` (a scratch password, secret and login files, the messages kept in a list, sources that fail if asked), walked over HTTP by a script — 26 checks, all passed:
  - «Добавить» with `007`, `abc`, `-5`, ` 5` and 19 digits, and «Следить» with `007` in the Feed → «Такого номера тайтла не бывает. Поищите заново», no source asked (3.2);
  - Feed, Список, Архив, Настройки, Входящие, Поиск and 33 cards of the list and the archive open on the real data (migrations 0015 and 0016 applied);
  - the 7 posters of Shikimori are shown from `shikimori.io`; moved back to `shikimori.one` in the copy, all 7 are still shown from `shikimori.io` (3.3);
  - «Тестовое событие» with an unknown id → «Такого примера нет — обновите страницу.» (HTMX) and `400` (plain); «Проверка правил доставки» the same; the sample «Проверка связи» → «Отправлено — посмотрите в Telegram.» and one message (6.2);
  - `workdays` spoiled by hand (`"garbage"`) → the Feed and Settings open, one log line `the stored workdays 'garbage' is not valid; the default works` for three pages (3.1).

## Findings

- **F1. A failure of «Тестовое событие» in the bot promised the event would come later.** `app/bot/test_event_handlers.py`: the generic branch added by ticket 01 (6.2: a `KeyError` inside a send is no longer «Такого события больше нет») answered «Не удалось отправить, событие осталось в очереди и придёт позже.» — the text of a failed send. A failed send never raises (it is `delivered` False); what raises is the database or a bug, possibly before the sample was queued, so the promise may be false. Decision: **fix now** — «Не удалось отправить тестовое событие. Попробуйте ещё раз.» (like the delivery check's «Не удалось выполнить проверку. Попробуйте ещё раз.»); `tests/test_tracker_bot.py` pins the text.
- **F2. The start script took the old bot's children by the parent's id alone.** `start-bot.ps1` (1.4): Windows reuses process ids and keeps a dead parent's id, so a `python.exe` of another program whose dead parent had the old bot's id would be stopped too. Decision: **fix now** — the child must also have the old bot's command (`$oldBotPattern`; the spec says the child has the same command line); `tests/test_docker_files.py` checks the filter; verified live (above).
- **F3. Seven index rows of `KNOWN_ISSUES.md` without their tests.** KI-16–20, KI-41, KI-42 said only `fixed` (Fix in `9.1a.01` / `9.1a.02`), while the file's rule wants `fixed (test: …)` in the index row too (their entries name the tests). Decision: **fix now** — the rows name the test modules, Fix in `9.1a` as the other ten.
- **F4. New comments of `start-bot.ps1` in Russian.** The comments of the old-bot rule and of the wait by the clock (ticket 02) were written in Russian; `CLAUDE.md`: «Everything in the repo written from 2026-11-01 — docs, code comments, commit messages — is English». Decision: **fix now** — translated (the texts the owner reads stay Russian).
- **F5. The new module `checks` is not in rule 7.** `docs/coding-standards.md`, rule 7: the table of the core's modules and the list «Одно правило — одно место» did not name `app/tracker/checks.py` (ticket 04), the one rule every write of a poll asks. Decision: **fix now** — a row for `checks` and «the check of a title still runs» (`checks.still_checked`) in the list.
- **F6. One of the «known Windows failures» was a bug of the test.** `tests/test_docker_files.py::test_the_start_script_stops_only_the_old_bot_by_the_whole_command` read the pattern of `start-bot.ps1` with `^…$` in multiline mode; a checkout on Windows has CRLF, `$` does not match before `\r`, so the test of the old-bot pattern (KI-18) never ran on the owner's PC. Decision: **fix now** — `\r?$`; the test passes on Windows. The known Windows failures are two now (`test_app_main`: `WinError 10106` in a child process without the system environment; `test_runtime`, not on every run).

No fix-round finding: the stage closes with this review.

## Wishes for later stages

- 9.1b: the Steam price check and the follow-up check queue their events through `EventQueue.enqueue` without a `due`, so not through `checks.still_checked` (spec 4.1 left their own rules to 9.1b, KI-47, KI-53). When 9.1b gives them their rules, let them be asked in the same write session through `still_checked`.
- 9.1c: KI-77 (an anime episode right after «Вернуть в список») with KI-28 and KI-32, as the spec says.
- 9.2: KI-78 only if met on the NAS.

## Tests at the end

4380 passed, 3 skipped; only the two known Windows failures (`test_app_main`, `test_runtime`) — `test_docker_files` passes now (F6). `pyflakes app tests` clean. The bot in Docker runs the reviewed code: «Готово», `/health` 200, the poll pass in the log, no restarts.
