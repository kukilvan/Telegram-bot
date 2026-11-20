# 03: The stop and the hang — the send and its mark, the presses, the health check, the line of Telegram; ADR 0015

Status: in review
Complexity: complex (asyncio cancellation, the process runtime and shutdown order, Docker init and the health check that kills a process, a request middleware of aiogram)
Blocked by: 01 (the room in `core.py` for `finish_sends`)

Spec: `../spec.md`, sections 2.1 (KI-5), 2.2 (KI-9), 2.3 (KI-6), 2.4 (KI-33), the rows of section 7 on the stop, the hang, the sleep, 503 and the lost internet, tests of 2.1–2.4 and both live checks («by the session», «by the owner») in section 8, the ADR and Gotchas lines of section 9. Terms — `CONTEXT.md`; ADRs to read: 0005, 0007 (the runtime stops the parts), 0014; standards — rules 1, 3, 7, 10, 11. Known issues: KI-5, 6, 9, 33 (KI-78 stays open, already recorded).

## What to do

- **A send and its mark are one unit (2.1).** `DeliveryService._send` runs the unit (the sender's `send`, then `_record_attempts`) as a task of its own, kept in `CoreContext.sends` (a set, removed when done), awaited through `asyncio.shield`. A cancel of the caller waits for its unit to finish (still holding the delivery lock), then goes on as a cancel: no further unit of that pass starts. `Tracker.finish_sends(timeout: float) -> bool` waits up to `timeout` for every unit; True when none is left; a unit still running is logged `остановка: отправка не закончилась за 5 с — сообщение может прийти ещё раз`. Every send of the queue goes through `_send` (messages, summaries, «Сводка сейчас», test events, the delivery check, login reports). `TelegramPart` (`app/main.py`) gets `finish_sends` and calls it with `SEND_GRACE = 5` s at the start of `close()`, before the HTTP session closes.
- **The stop waits for started presses (2.2).** An outer middleware of `dp.update`, registered in `build_dispatcher`, puts `asyncio.current_task()` into a set while the update runs (removed in `finally`). `TelegramPart.stop()`: after `stop_polling` it waits up to `HANDLER_GRACE = 10` s for the tasks of that set; those left are logged `остановка: <n> нажатий в боте не закончились за 10 с`. The web's 5 s and the bot's 10 s run at the same time (step 2 of `Runtime._stop`, as today). `docker-compose.yml`: `stop_grace_period` from `30s` to `45s`.
- **The hung app is ended by its health check (2.3).** `docker-compose.yml`: `init: true`. `app/healthcheck.py`: a **timeout** is a check that connected and got no answer in its 5 s; refused, reset, or any answer (200 or not) is no timeout. The count of timeouts in a row lives in `<temp folder>/release-tracker-health.json` with the app process it belongs to (pid and its start time from `/proc/<pid>/stat`); another process starts the count anew, a check that is no timeout sets it to 0. The fourth timeout in a row sends SIGKILL to the app (the child of PID 1 found in `/proc`), prints `/health не отвечает 4 раза подряд — приложение остановлено для перезапуска`, exit code 1; no child found (no init, not Linux) — no kill, the reason line of today. `HEALTHCHECK` interval, timeout, start period and retries in the `Dockerfile` stay. Keep the decision pure (state, result, process → new state, kill) so it is tested without Docker.
- **ADR 0015** `docs/adr/0015-a-hung-app-is-ended-by-its-health-check.md` in the format of `docs/formats.md` (ADR): the decision, the options rejected (an `autoheal` container, Docker alone, a second watchdog process in the app), consequences; ADR 0007 stays, say that its consequence is still true for the usual hang.
- **«Бот не подключён к Telegram» while receiving (2.4).** A request middleware of the bot's session (`bot.session.middleware(...)`) that watches only `GetUpdates`: an exception sets `Health.telegram_down = True`, an answer sets it to `False`; other requests do not touch the flag. The runtime keeps setting it on a failed connect and clearing it when receiving begins.
- **Docs:** `PROJECT_CONTEXT.md` Gotchas — the health check kills a hung app (budget 20,000 bytes); `docs/code-map.md` by `tools\code_map.py`; `docs/tests-map.md`; `KNOWN_ISSUES.md` — KI-5, 6, 9, 33 `fixed (test: …)`, KI-5's text says what remains is KI-78.

## Done when

- [ ] A fake sender that blocks, `deliver_pending` cancelled while it sends: after the send ends the entry is delivered, the next entry is untouched; no second unit starts after the cancel.
- [ ] `finish_sends` returns False after its timeout with a unit hanging (and logs), True otherwise; `TelegramPart.close` calls it before closing the session.
- [ ] The update middleware tracks a running handler; `TelegramPart.stop` waits for it, gives up after the grace (shrunk in the test) and logs; `stop_grace_period: 45s` and `init: true` are in `docker-compose.yml` (`test_docker_files.py`, replacing the 30 s check).
- [ ] The pure health decision: timeouts in a row, a reset by refused / 503 / 200, another process, the fourth timeout kills; `/proc` reading works from a fake folder; ADR 0015 is written.
- [ ] A failing `GetUpdates` sets `telegram_down`, an answer clears it, a failing `SendMessage` does not touch it.
- [ ] Live, by the session on the owner's PC: `.\start-bot.ps1` → «Готово», `/health` 200; `.\stop-bot.ps1` ends within 45 s with no `прервана` lines; the hang (`docker compose exec tracker kill -STOP <app pid>`) is ended by the check within about 2.5 min, the container restarts, `/health` is 200 again, the log shows the line of 2.3.
- [ ] KI-5, 6, 9, 33 are `fixed (test: …)`; pyflakes clean; the code map rebuilt; the full suite green (the three known Windows failures are not new).

## Tests to add

- `DeliveryService`: cancel during a blocking send (the delivered mark lands, the next entry untouched); `finish_sends` True / False; the unit leaves `CoreContext.sends` when done.
- `TelegramPart`: `close` calls `finish_sends` before the session closes (order test); `stop` waits for a running update task, gives up after the grace and logs the count.
- Dispatcher: the `dp.update` middleware adds and removes the task, also when the handler raises.
- `app.healthcheck`: the pure decision for every row listed above; the state file with a pid and start time from a fake `/proc`; no child of PID 1 found → no kill.
- Session middleware (2.4): `GetUpdates` failing / answering, `SendMessage` failing (flag untouched).
- `test_docker_files.py`: `init: true`, `stop_grace_period: 45s`.

## Owner check

The session starts the bot itself and writes the launch result in one line, plus one line each for the stop and the hang checks it ran. Then one check by the owner, whose phone and PC network are theirs:

1. Browser, `http://localhost:8080`, signed in; open «Лента» — there is no line «Бот не подключён к Telegram».
2. Turn the PC's internet off (Wi-Fi off or unplug the cable) for 2 minutes. Reload «Лента»: the line «Бот не подключён к Telegram» is there.
3. Turn the internet on. Within a minute and a half, reload «Лента»: the line is gone.

«Не так»: the line does not appear after 2 minutes without internet, or does not go within 2 minutes after it comes back, or the page shows an error.
