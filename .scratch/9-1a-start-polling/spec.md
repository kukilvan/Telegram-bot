Status: accepted

# Spec 9.1a: start, stop, polling and delivery

Built from `.scratch/9-1-known-issues/description.md` (part 9.1a, decisions 1, 4, 5) and the full entries KI-1, 5, 6, 9, 16–24, 33, 41, 42, 45 of `KNOWN_ISSUES.md`; the review 7.2 wishes F4 and F5 come here because this part changes the facade `core.py` (sections 3.2, 6.1). Terms from `CONTEXT.md`. ADRs: 0001, 0005, 0007 (one process; the runtime stops the parts), 0014. One new ADR (0015, section 2.3).

Almost nothing here changes what the owner sees: fewer repeated, missing or wrong messages. Visible: the line «Бот не подключён к Telegram» also when the connection is lost while the bot runs (2.4); a hung app restarts by itself (2.3); one new line of the web «Добавить» (6.2).

## 1. Start: the report of a failed start and the start script

### 1.1 The same failure with a changing text (KI-16)

Today «the same failure» is the SHA-256 of the type, the places in the code and the text with numbers masked; any other change of the text makes it new, so it is reported on every retry (every minute).

New rule in `app/startup_report.py`:
- **The code** of a failure: the type and the places (file without folders and function, in order) — as today, without the text. **The text** of it: the masked text, where every word that holds a digit, `/` or `\` becomes `#` (a temporary name `tmpk3j9x_q`, a path, a port, an address in memory), spaces folded, the first 300 characters.
- The record `data/startup_failure.json` keeps both: `code` (SHA-256 of the code) and `fingerprint` (SHA-256 of the code and the text), with `first_seen` and `reported_at` as today.
- Decision (replaces table 1.4 of spec 5.1 fix round 1):

| Record | Failure | Report |
|---|---|---|
| none, unreadable, or another `code` | any | at once, heading «Бот не запустился»; the record starts anew (`first_seen` = now) |
| same `code`, same `fingerprint` | the same failure | 24 h after the last report (or at once if the last report did not go out, or the clock went back past it), heading «Бот всё ещё не запускается (с …)»; `first_seen` stays |
| same `code`, another `fingerprint` | the same place, another text | at once, heading «Бот не запустился», if the last report is 1 h old or older (or did not go out, or the clock went back); otherwise no report and the record stays as it is (the new text is not saved, so it compares with the reported one) |

So a text that changes on every retry gives at most one report an hour (one a day if only digits and paths change); another failure at another place is reported at once. A record of the old form (no `code`) reads as no record: one report at once.

### 1.2 The record that cannot be saved (KI-17)

The record goes to `data/startup_failure.json`; when that raises `OSError`, to `<temp folder>/release-tracker-startup_failure.json` (`tempfile.gettempdir()`: `/tmp` in the container — its own layer survives Docker's restarts of the same container, and `.\start-bot.ps1` makes a new container, so a fresh report then is right). Log, once per start: `запись о сбое запуска сохранена во временную папку: <path> (data недоступна: <error>)`. Both files fail: the warning of today, and the next start reports again (better an extra message than silence).

Reading: both files; the one with the later `reported_at` (else `first_seen`) wins. `forget_failure` (a successful start) removes both; a file that cannot be removed is the warning of today.

### 1.3 Names (KI-20)

In `app/startup_report.py`: the variable `kind` of `fingerprint` → `exc_type`; the parameter `failure` of `decide` → `fingerprint`; the field `Decision.first_seen` goes (callers read `Decision.record.first_seen`).

### 1.4 `.\start-bot.ps1` stops only this project's old bot (KI-18)

The old bot is a `python.exe` whose `ExecutablePath` is `<the script's folder>\.venv\Scripts\python.exe` (compared whole, case-insensitively) and whose command line matches `$oldBotPattern` as today; plus every `python.exe` whose `ParentProcessId` is one of them (on Windows the `python.exe` of a `.venv` starts the base Python as its child with the same command line). A `python -m app.main` of another folder, or of the base Python, is left alone. The text «Остановлен старый бот, запущенный не через Docker» stays.

### 1.5 The wait of `.\start-bot.ps1` counts by the clock (KI-19)

The loop runs while less than 90 seconds have passed since the wait began (`(Get-Date)` against a deadline), with a pause of 2 s between the checks; the last check starts before the deadline, so «Приложение запускается дольше обычного» comes after at most 90 s plus one check. The texts stay.

## 2. Stop and hang

### 2.1 A stop does not cut a send from its «delivered» mark (KI-5)

Today a stop cancels the delivery job after 15 s; cancelled between «Telegram took the message» and «the entry is marked delivered», the entry stays pending and goes out again after the start.

Rule: **one send and the record of its outcome are one unit that a cancel does not cut.**
- `DeliveryService._send` runs the unit (the sender's `send`, then `_record_attempts`) as a task of its own, kept in a set of the context (`CoreContext.sends`, removed when done), and awaits it through `asyncio.shield`. A cancel of the caller waits for its unit to finish (still holding the delivery lock: no other pass can read the same entries as pending), then goes on as a cancel: no further unit of that pass starts.
- `Tracker.finish_sends(timeout: float) -> bool`: waits up to `timeout` for every unit in the set; True when none is left. A unit still running then is logged: `остановка: отправка не закончилась за 5 с — сообщение может прийти ещё раз`.
- `TelegramPart` (`app/main.py`) gets `finish_sends` and calls it, with `SEND_GRACE = 5` s, at the start of `close()`, before it closes the HTTP session (step 4 of the stop). So a send that the web started (its request cancelled after the 5 s of the web) is covered too.

Every send of the queue goes through `_send`: messages, summaries, «Сводка сейчас», test events, the delivery check, login reports. What remains: a send Telegram has not answered within those 5 s fails when the session closes and is recorded as failed; if Telegram had in fact taken it, it comes again after the start — new entry KI-78 (section 8).

### 2.2 The stop waits for the started bot presses (KI-9)

aiogram runs each update as a task of its own and `stop_polling` does not wait for them. New:
- An outer middleware of `dp.update` (registered in `build_dispatcher`, public aiogram API) puts the task that runs the update into a set while it runs (`asyncio.current_task()`, removed in `finally`).
- `TelegramPart.stop()`: after `stop_polling`, waits up to `HANDLER_GRACE = 10` s for the tasks of that set. Those still running are left (they end when the session closes or at the exit) and logged: `остановка: <n> нажатий в боте не закончились за 10 с`.
- The web's 5 s and the bot's 10 s run at the same time (step 2 of `Runtime._stop`, as today).

The stop now takes at most about 10 (web and bot) + 16 (jobs) + 5 (sends) = 31 s; `stop_grace_period` in `docker-compose.yml` goes from `30s` to `45s`, so Docker does not kill the process in the middle.

### 2.3 A hang that holds the GIL: the health check ends the app (KI-6)

The watchdog thread cannot run when the loop hangs in C code holding the GIL; Docker marks such a container `unhealthy` and leaves it. New:
- `docker-compose.yml`: `init: true`. Docker's init is PID 1, the app (`app.container_start` replaced by `app.main`) is its only child; when the app dies, the init exits with its code, and `restart: unless-stopped` starts the container again. The init passes SIGTERM on to the app, so the orderly stop is as today. (A PID 1 cannot be killed from inside its container; with the init the app is not PID 1.)
- `app/healthcheck.py`: a **timeout** is a check that connected and got no answer in its 5 s (a hung loop: the kernel still takes the connection). Refused, reset, or any answer (200 or not) is no timeout. The count of timeouts in a row is kept in `<temp folder>/release-tracker-health.json` with the app process it belongs to (pid and its start time from `/proc/<pid>/stat`); another process starts the count anew, a check that is no timeout sets it to 0.
- The fourth timeout in a row (about 1.5–2 min of hang; the watchdog acts after 60–90 s and logs the reason, so it gets the first chance) sends SIGKILL to the app and prints `/health не отвечает 4 раза подряд — приложение остановлено для перезапуска`; exit code 1. The app is the child of PID 1 found in `/proc`; none found (no init, not Linux) — no kill, the reason line of today.
- The interval, timeout, start period and retries of `HEALTHCHECK` in the `Dockerfile` stay.
- The same on the NAS: `init: true` and `/proc` are plain Docker on Linux.
- **ADR 0015** «A hung app is ended by its health check»: the check is the only part outside the app's own threads; options rejected — an `autoheal` container (needs the Docker socket, a second container), Docker alone (does not restart an unhealthy container), a second watchdog process inside the app (a child of the hung process, more code to stop and start).

### 2.4 «Бот не подключён к Telegram» while receiving (KI-33)

aiogram retries a failed `getUpdates` inside `start_polling` and raises nothing, so the flag `Health.telegram_down` never sets. A dispatcher error handler does not see these failures (it gets only errors of handlers), so: a **request middleware of the bot's session** (`bot.session.middleware(...)`, public aiogram API) watches only `GetUpdates`: an exception sets `telegram_down = True`, an answer sets it to `False`. Other requests (sending) do not touch the flag. The runtime keeps setting it on a failed connect and clearing it when receiving begins.

`getUpdates` waits up to 70 s for an answer (the session's 60 s plus the polling timeout of 10 s, aiogram 3.31), so the line appears at most about 1–1.5 min after the connection is lost (at once when the network answers with an error), and goes at the first answer after it comes back. A second instance of the bot (Telegram's 409) shows the line too: the bot does not receive.

## 3. Rare input

### 3.1 Settings spoiled by hand (KI-41)

`SettingsStore` reads every stored setting through its `check_…`, as the zone, platforms and country already are: `part_gap_weeks` (`check_part_gap_weeks`), `workdays` (`check_workdays`), `summary_at`, `quiet_from`, `quiet_until` (`check_clock`). A value that fails its check reads as the default of that field, and the log says once per value (`_spoiled_once`): `the stored <key> <value> is not valid; the default works`. `part_gap_weeks_in` and `part_gap` become methods of the instance (they log). The check of the rules as a whole (a summary hour inside the quiet hours) stays the form's: on reading, each field is checked alone.

### 3.2 A hand request «Добавить» with a number not of digits (KI-42)

`Titles.add_title` (and so `follow` and the «Да» of an offer) checks the number before asking a source: an id of every source of `add_title` is a positive whole number written plainly — `[1-9][0-9]{0,17}` (no sign, no leading zero, no space). Otherwise a new error `BadExternalId(TitleNotFound)` (in `errors.py`, re-exported by `core`), nothing is asked or stored. Its words:
- web «Добавить» (`app/web/search.py`) and «Следить» (`pages.try_follow`): **«Такого номера тайтла не бывает. Поищите заново»** (caught before `TitleNotFound`);
- everywhere else it reads as `TitleNotFound` (it is one): the bot's «Следить» says what it says today for a title not found, the «Да» of an offer goes on to the next offer.

(A leading zero is refused because `007` would be stored as another id than `7` and add the same title twice.)

### 3.3 Posters of anime that are not polled (KI-21)

The address is fixed when it is shown, not stored anew. `poster_url(stored, size, shikimori_site)`: a stored `https://` address whose host is `shikimori.<zone>` or a subdomain of it (the label before the last one is `shikimori`) gets that `shikimori.<zone>` part of the host replaced by the host of `shikimori_site`, the scheme and port taken from `shikimori_site`, the path and query kept. `shikimori_site` is the site of `SHIKIMORI_BASE_URL` as `image_sources` reads it (`https` only); no valid site — the address stays as stored. TMDb and IGDB addresses do not change.
- Examples (site `https://shikimori.io`): `https://shikimori.one/uploads/poster/animes/1/a.jpg` → `https://shikimori.io/uploads/poster/animes/1/a.jpg`; `https://desu.shikimori.one/system/x.jpg` → `https://desu.shikimori.io/system/x.jpg` (allowed by `img-src` as `*.shikimori.io`); `https://shikimori.io/…` unchanged.
- Callers: the web (the template global `poster_url` gets the site from `create_web_app`), the bot's card (`tracker_handlers.py`) and the inbox card (`inbox_handlers.py`), both given the site by `build_dispatcher`; `app/main.py` passes `settings.shikimori_base_url`.
- The stored addresses stay; the first check of an anime still writes the new one, as today.

## 4. Polling

### 4.1 «Бросил» during a check of the same title (KI-22)

Rule: **an event of a check is queued only if, in the write session that queues it, the title is still checked by that check.** One function, `still_checked(session, due) -> bool`, used by `Poller.record_all` (so by every poller and by `SequelPoller`), by `EventQueue.queue_failure_notices` and by `Polling._still_checked`:
- the title exists and the snapshot of `due.snapshot_source` exists;
- a sequel check (`due.sequels`): the status is «Просмотрено»;
- an own-release check (the snapshot source is the title's primary source): the status is one of `POLLED_STATUSES` and tracking is on;
- a check at the end of a pass (Steam prices, follow-ups; their own rules belong to 9.1b, KI-47, KI-53): the snapshot exists.

`EventQueue.record` takes the `due` and checks inside its write session (after the dedup flush, where it checks today that the title exists); not checked — rollback, nothing queued, no dedup key spent. A failure notice of a title no longer checked is not queued. The status is never changed by the poll, as today.

Left as is (rare inside rare): «Бросил» and «Вернуть в список» both within the few seconds before the title's turn in the same pass — the check then runs as an ordinary one.

### 4.2 A fact right after «Вернуть в список» (KI-23)

The first check after the return stays silent about what happened while the title was in the archive, and now reports **what happened after the return**:
- A detected event that says something came out carries the moment it came out, `DetectedEvent.happened_at: datetime | None` (naive UTC; a date is its 00:00 UTC — TMDb counts an episode out from the start of its day in UTC):

| Event | `happened_at` |
|---|---|
| `movie_released`, `movie_digital` | the cinema or digital date |
| `series_season_started`, `series_episode_out`, `series_season_ended` of a series (TMDb) | the `air_date` of the episode the event is about (the last one for an ended season) |
| `anime_movie_released` | `aired_on` |
| `game_released`, `game_early_access` | the date of the platform |
| every other event; the episode events of an anime | None |

- `DueTitle` gets `restored_at` (from `Title.restored_at` in `_due_titles`). In `record_all` with `due.baseline`: an event is queued only if `happened_at` is set and later than `restored_at`; the rest is the reference point, as today. The log line of today stays, with the count queued.
- The episode events of an anime carry no moment here: an episode found by a check without a schedule gets the moment it was found, which would read as «after the return». Part 9.1c stores whether an episode's moment is from the schedule (KI-28, KI-32); until then such an episode right after a return stays silent — new entry KI-77 (section 8), fixed in 9.1c.

### 4.3 Moving parts of an anime season (KI-1)

`AnimePoller._sync_entries`: a part may take its new place only when the place is free after the moves. Fixed point:
1. `wanted`: the known parts whose entry moved (as today).
2. `moves` = `wanted`; repeat until nothing changes: drop from `moves` a part whose new place is the current place of a part not in `moves`, or the new place of another part in `moves` (two want one place: neither moves).
3. Parts in `moves` go out of the way (`number = -id`), flush, then to their places (as today); parts not in `moves` stay where they are.

The example of KI-1 (`[P1, C, B, A]`, `C` leaves the chain): `B` wants place 2, where `C` stays, so `B` stays; `A` wants place 3, where `B` stays, so `A` stays. No `IntegrityError`; the parts keep their old places until the places are free; the log says once per check: `title <id>: parts <ids> keep their places, the places they move to are taken`. Exchanges and chains of moves work as today.

### 4.4 One «could not check» window per source (KI-45)

The window of 24 h is per title **and source** (`failures.source_name`: TMDb, Shikimori, AniList, IGDB, Steam — so a movie's own check and its sequel check are one source, a game's IGDB check and follow-up check are one, Steam is another).
- The window is read from the events, not stored apart: a notice is due unless an event `source_failure` of this title with `payload.source` equal to the source was detected in the last 24 h (`failures.COOLDOWN`).
- Within one pass: one notice per title and source (today: per title).
- The dedup key: `failure:<title id>:<source>:<stamp of the pass>`.
- Migration **0016** drops `titles.failure_notified_at` (`ALTER TABLE titles DROP COLUMN`, not the batch way: a rebuild of `titles` would cascade into its children, see migration 0009). Old events without `source` do not count: at most one notice per title and source more, right after the upgrade.

## 5. Numbers of titles are never reused (KI-24)

A kept maximum, not `AUTOINCREMENT`: `titles` cannot be rebuilt safely (eight tables cascade from it; alembic runs in one transaction, where `PRAGMA foreign_keys=OFF` does nothing), and titles are created in one place only (`Titles._store_title`).
- Migration **0015**: table `issued_ids` (`name` text primary key, `last_id` integer not null), one row `('titles', <max(titles.id) or 0>)`. Model `IssuedId` in `models.py`.
- `_store_title`, in its write session (which holds the database): `id = max(issued last_id, max(titles.id)) + 1`, set on the new `Title`, and `last_id` updated in the same commit. A row missing (a hand edit) is made again from `max(titles.id)`.
- A restore of an old copy brings its own `last_id`: numbers given after that copy may come again — accepted, the restore is the owner's deliberate step (`docs/backups.md` gets one line).

## 6. The facade (review 7.2 wishes)

### 6.1 How the facade grows past 400 lines (F5)

`core.py` has exactly 400 lines, its imports and `__all__` packed into lines of 150–188 characters. Decision: **the facade has a limit of its own, 500 lines**, and no line of it is longer than 120 characters. It holds no rules and grows by one pass-through method per feature; a split of the facade itself (mixins, a second door) would cost more than it gives. Rule 7 of `docs/coding-standards.md` and `tests/test_tracker_core_split.py` say so (the limit of the other modules stays 400); the packed lines are unpacked.

### 6.2 An unknown sample or check (F4)

New errors in `errors.py`, re-exported by `core`: `UnknownSample` (`TestSamples.send_test_event` with an id it does not know) and `UnknownCheck` (`delivery_check`). The callers catch those instead of `KeyError`: the web forms «Тестовое событие» and «Проверка правил доставки» (`settings_test_event.py`, texts of today) and the bot (`test_event_handlers.py`, texts of today). A `KeyError` from inside a send is no longer read as «Такого момента нет»: it is a failure with a log line (the bot's generic branch, the web's error page).

## 7. Edge cases

| Case | Behaviour |
|---|---|
| A stop while a summary of three messages goes out | the message being sent finishes and is marked; the other two stay pending and go after the start |
| A stop while Telegram hangs on a send | the stop goes on after 5 s; the send is recorded failed and comes after the start (KI-78) |
| A second Ctrl+C on Windows during the stop | as today: leaves at once (`KeyboardInterrupt`) |
| The app hangs during the start period of the check | the web does not listen yet (refused): no timeout, no kill; the start report rules apply |
| The PC sleeps (Docker Desktop's VM too) | no checks run while asleep; after waking the app answers, the count is 0 |
| `/health` answers 503 | no timeout: unhealthy as today, never killed by the check |
| The internet is lost for 10 s | the line may show for those seconds; it goes with the next answer |
| `startup_failure.json` and the temp record disagree | the later one wins |
| A record of the old form | no record: one report at once |
| Two parts of a season want one place | neither moves; logged |
| A failure of IGDB and of Steam of one game in one pass | two notices, folded by source and reason as today |
| A failure of TMDb's own and sequel check of one movie in a day | one notice (one source) |
| `workdays` spoiled by hand | the default work days (Sunday to Thursday); one log line |
| `external_id` of 19 digits | refused (`BadExternalId`): no source has such ids |
| A title created by a test directly in the session | the next `add_title` still gives `max + 1`: `max(titles.id)` is part of the rule |
| `SHIKIMORI_BASE_URL` not `https` | posters of Shikimori stay as stored (and `img-src` does not allow them, as today) |

## 8. Tests

Automated (one per item at least; names in the tickets):
- 1.1: three failures with texts differing by a temp name, a path, a random word — first reported, the second (same code) within 1 h not, after 1 h yes; another place at once; the reminder after 24 h keeps `first_seen`; an old-form record reads as none.
- 1.2: `data` read-only (a path that cannot be written) — the record lands in the temp folder and the next decision reads it; `forget_failure` removes both.
- 1.3: `tests/test_code_speaks_glossary.py` or a direct test: no `kind` in `startup_report.py`.
- 1.4, 1.5: `tests/test_docker_files.py` — the script compares `ExecutablePath` with `.venv\Scripts\python.exe` of `$PSScriptRoot`, takes the children by `ParentProcessId`, and waits by a deadline of `Get-Date`.
- 2.1: a fake sender that blocks; cancel `deliver_pending` while it sends — after the send ends the entry is delivered, the next entry is untouched; `finish_sends` returns False after its timeout with a unit hanging, True otherwise; `TelegramPart.close` calls it before closing the session.
- 2.2: the middleware tracks a running handler; `TelegramPart.stop` waits for it, gives up after the grace (shrunk in tests) and logs; `stop_grace_period: 45s` (`test_docker_files.py`, replacing the 30 s check).
- 2.3: the pure decision of `app.healthcheck` (state, result, process → new state, kill) for timeouts in a row, a reset by refused / 503 / 200, another process, the fourth timeout; `/proc` reading from a fake folder; `init: true` in `docker-compose.yml`.
- 2.4: the session middleware: a failing `GetUpdates` sets the flag, an answer clears it, a failing `SendMessage` does not touch it.
- 3.1: each spoiled field reads as its default and logs once; the feed and the delivery rules work.
- 3.2: `abc`, `007`, `-5`, ` 5`, 19 digits → `BadExternalId`, no source call; the web line; the inbox «Да» goes to the next offer.
- 3.3: the examples of 3.3; TMDb and IGDB unchanged; no valid site — unchanged.
- 4.1: «Бросил» between the pass's start and the title's turn (a source that waits for an event) — no event, no dedup key; a failure notice of a dropped title not queued; a watched movie dropped during its sequel check — no announcement.
- 4.2: the 23:59:30 / 00:00 example of KI-23 queues «вышла серия»; an episode of the day before the return stays silent; an anime episode stays silent.
- 4.3: the KI-1 example gives no `IntegrityError` and moves nothing; an exchange of two parts and a chain still work.
- 4.4: the KI-45 example gives two notices; one source twice in a day gives one; migration 0016 on a copy of a database with the column.
- 5: delete the last title, add another — a new number; migration 0015 seeds `max(id)`; a missing row is made again.
- 6.1: the size test: `core.py` ≤ 500 lines, no line over 120; the others ≤ 400.
- 6.2: an unknown sample / check gives the new errors; a `KeyError` inside a send is not «Такого момента нет».
- The full suite passes (the three known Windows failures do not count).

Checked live by the session on the owner's PC (ticket 03):
- `.\start-bot.ps1` → «Готово»; `/health` 200; a stop by `.\stop-bot.ps1` ends within 45 s without `прервана` lines.
- The hang: `docker compose exec tracker kill -STOP <app pid>` freezes the app; within about 2.5 min the check kills it, the container restarts, `/health` is 200 again, the log of the check shows the line of 2.3. This verifies `init: true`, the timeout and the restart on Docker Desktop.
- `.\start-bot.ps1` next to a dummy `python -m app.main` of another folder: the dummy is not stopped (ticket 02).

Checked live by the owner (ticket 03's check): turn the internet of the PC off for 2 minutes, reload «Лента» — the line «Бот не подключён к Telegram» is there; turn it on — within a minute and a half the line goes.

## 9. Docs, terms, ADRs, known issues

- `KNOWN_ISSUES.md`: on acceptance of this spec the «Fix in» of the 17 entries becomes `9.1a`; each ticket sets its entries to `fixed (test: …)`. New entries, written with this spec:
  - **KI-77** «Anime: an episode right after «Вернуть в список» passes silently» — the rest of KI-23 (section 4.2); Fix in 9.1c (with KI-28, KI-32).
  - **KI-78** «A send Telegram has not answered within 5 s of a stop can come again after the start» — the rest of KI-5 (section 2.1); Fix in 9.2 (only if met: only Telegram knows whether it took the message).
- `docs/adr/0015-a-hung-app-is-ended-by-its-health-check.md` (ticket 03); ADR 0007 stays (its consequence «the process leaves itself when the loop hangs» is still true for the usual hang).
- `docs/coding-standards.md` rule 7: the facade's own limit (ticket 01).
- `PROJECT_CONTEXT.md` Gotchas: `data/startup_failure.json` may live in the temp folder (1.2); the health check kills a hung app (2.3); `issued_ids` keeps the last number of a title (5). `docs/backups.md`: the line of section 5.
- `CONTEXT.md`: no new terms.
- `docs/code-map.md`: by `tools/code_map.py` after each ticket.

## 10. Proposed tickets

| # | Ticket | KI / wish | Complexity | Blocked by |
|---|---|---|---|---|
| 01 | The facade's limit, its own errors, the settings read safely, the number of «Добавить» checked | F5, F4, KI-41, KI-42 | medium | — |
| 02 | The start report and the start script | KI-16, 17, 20, 18, 19 | medium | — |
| 03 | The stop and the hang: the send and its mark, the presses, the health check, the line of Telegram; ADR 0015 | KI-5, 9, 6, 33 | complex | 01 |
| 04 | Polling: the status read again, the facts after a return, the parts of a season, the window per source (migration 0016) | KI-22, 23, 1, 45 | complex | 05 |
| 05 | Numbers never reused (migration 0015) and posters on the current Shikimori address | KI-24, 21 | medium | — |

Order: 01 → 02 → 05 → 03 → 04 (01 first: it makes room in the facade that 03 needs; 05 before 04 for the order of the migrations). Sessions: spec, slicing, 5 tickets, review — 8 (the description estimated 7).
