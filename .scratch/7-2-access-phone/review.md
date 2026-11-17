# Review 7.2: the app address, the phone, the bot as links, a safer login

Status: in review

One session (2026-11-17).

## What was reviewed

- Commits `0d11990..1816985` (after the accepted slicing): tickets 01 (07399ce), 02 (eb0fe4b), 03 (2d44c2f), 04 (792d7ae), 05 (a1b69dc), 06 (a641393) and their «accepted» commits; the spec, the six tickets, `checks.md`, `docs/history.md` (the decisions the tickets recorded), ADR 0014.
- Against `spec.md` (sections 1–13) and `docs/coding-standards.md` (rules 1–11, with `CONTEXT.md` for rule 5 and ADRs 0002, 0007, 0008, 0013, 0014), with the `code-review` skill at effort xhigh over the stage diff (correctness, removed behaviour, callers, language pitfalls, wrappers, reuse, simplification, efficiency, altitude, conventions), then a pass for the spec. Its findings are below. KI-72…74 (deferred by the spec) were not counted again.

## Tests

- At the start: 4158 passed, 3 skipped, only the three known Windows failures (`test_app_main`, `test_docker_files`, `test_runtime`). `pyflakes app tests` clean.
- At the end (after the fixes): «Tests at the end» below.

## Verified by running

- **A scratch server of the real app** (uvicorn with `web_server`, the whole middleware stack, a copy of `data/tracker.db`, a scratch password, the messages written to a file instead of Telegram, `APP_URL=http://192.168.1.50:8099`, `WEB_HOST=0.0.0.0`, `TRUSTED_PROXIES=127.0.0.1`), walked over HTTP by a script — 44 checks, all passed:
  - host names (5.1): `evil.example` and a public IP → `400` «Неизвестный адрес сайта.» with the security headers and no cookie; `localhost`, `127.0.0.1`, `[::1]`, the host of `APP_URL`, `10.x`, `172.20.x` pass; the refused name is logged once; `HEAD /health` 200 with no body;
  - the login behind the proxy (5.2, 5.3) with `X-Forwarded-For: 8.8.8.8`, `X-Forwarded-Proto: https` → the cookie `HttpOnly; SameSite=Lax; Path=/; Max-Age=2592000; Secure`, the log `web login: ok from 8.8.8.8`; a plain `http` login → no `Secure`; every signed-in answer sends the cookie anew;
  - Settings: the address line without a hint, both forms, the sample «Вход в приложение», «Последний вход: сегодня в …, Android, Chrome.», «Вход открыт на 2 устройствах.»;
  - the login report (6): two 🔐 messages, `Windows, Chrome … адрес 8.8.8.8` and `Android, Chrome` with no address, no buttons; four wrong passwords → `401` «До блокировки осталось попыток: 1» and nothing sent; the fifth → `429`, `Retry-After` 900 and one ⚠️ message with the address; the right password while locked → `429`, nothing more;
  - `data/web_login.json`: version 1, `sid` of 32 hex, `last_login.address` null for the phone, the count;
  - the forms (3): HTMX «Прислать» → `<p>Отправлено — посмотрите в Telegram.</p>` and one message; an unknown sample → the error fragment (HTMX) and `400` (plain); plain «Прислать» → `303` and the notice; HTMX «Проверить» → «Как будто сейчас вс, 22 ноя в 10:00: в этот момент ничего не пришло… сводка, которая уйдёт вс, 22 ноя в 16:10.»; a post with a foreign `Origin` → `403`;
  - «Выйти» (KI-8): the cookie copied before it is refused, the other device stays («на 1 устройстве»); «Выйти на всех устройствах» → `303 /login?out=everywhere`, the sentence on the login page (another `out` shows nothing), the other device signed out, an HTMX request of it → `401` with `HX-Redirect`, the file keeps the last login, the log `web: signed out everywhere (2 sessions)`;
  - the lock across a restart (KI-7): the server stopped and started on the same file → the right password still `429`, the file keeps the count 5 and the end of the lock.
- **The bot in Docker** (the owner's, not restarted for the review): `/health` 200; `Host: evil.example` → `400` with the sentence; `/settings` → `303` to the login; the login page shows the sentence for `?out=everywhere`; the log says `APP_URL: ссылки бота ведут в приложение`, refused my `evil.example` once, `Tracker.poll_due … executed successfully` every minute, no error.
- **The Feed in the browser pane** (scratch server): the day headings «Сегодня», «чт, 19 ноя» had margin 16 px / 4 px and font 16 px instead of 12 px and 15.2 px (F1); after the fix 12 px and 15.2 px again, the two Settings headings keep 16 px.
- **Every backticked Russian text of the spec** compared with the code by a script; the five it could not match literally differ only by `%s` for `<reason>` and the file name, a Python escape of `\` or the plural function.

## Standards

Clean: rule 1 (`record_login_report`, `delivery_check` are coroutines; the file work of `SignIns` in a thread), 2 (the owner's zone read where used: `LoginReports.record`, the block «Вход»), 3 (the link-mode registrations are covered by the owner-filter test), 4, 6, 8 (no new press with the network), 9 (the event through `EventQueue`), 10 (the web imports `core`, `cards`, `moment_words` and `app.config`; the one guard), 11 (the map is current). Comments in English, the UI in Russian, nothing prints a secret.

Findings: rule 7 — the facade squeezed to exactly 400 lines (F5), the rule's table without the new modules (F7); one rule in one place — the private-network rule twice (F8), the plural rule copied (F9), `drop_buttons` copied by the split (F10); robustness — a `KeyError` that means «unknown moment» around a call that sends (F4), the session middleware leaning on Starlette's `Session` (F11).

## Spec

Checked and right: 1.1 (the five rules in order, the one form, IPv6 in brackets, the log lines, the value not logged); 1.2; 2.1–2.7 (every `CARD` a link with its label, the chat card with one button, the menu, `/start` and the old texts with text links, «➕ Добавить», the old callbacks in both modes, the split); 3.1–3.3; 4.1–4.7 (the file, its writes and failures, the cookie, `seen` hourly, 30 days, 20 sign-ins, «Выйти», «Выйти на всех устройствах», the block, the lock on the wall clock, the key); 5.1–5.3; 6.1–6.3; 7 (the CSS of P1–P4 under 40rem, the viewport test); 8; 9 (`docs/outside-access.md` has the eight points); 10; 11; the tests of 12; 13 (`CONTEXT.md` terms, KI-7, 8, 12, 13 fixed, ADR 0014, the map, `PROJECT_CONTEXT.md` rows and gotchas, `.env.example`).

Findings: the Settings heading rule restyles the Feed (F1, against 7: «the PC looks as today»); the device count after a password change (F2, 4.5 «the live sessions»); a Cyrillic domain (F3, 1.1); the sign-in id in the dedup key against the reasoning of ADR 0014 (F6); two departures decided by the tickets (F12, F13).

## Findings

| # | What, where | Decision | Why |
|---|---|---|---|
| F1 | `style.css`: `section.card h3` (ticket 02, for the two Settings headings) outranks `.feed-day`, so the Feed's day headings grew on the PC and the phone (margin 16 / 4 px, font 16 px instead of 12 px and 15.2 px) | fix now | The two forms sit in `<div class="bot-tests">`, the rule is `.bot-tests h3`. Checked in the browser pane: the Feed is back to 12 px and 15.2 px. CSS is checked live, not by tests (spec 12) |
| F2 | `SignIns.count` (the line «Вход открыт на N устройствах», the count of «Выйти на всех устройствах», the cap of 20) counts sign-ins a new `WEB_PASSWORD` or `data/web_secret` has ended: the cookie refuses them, the file keeps them up to 30 days | defer `KI-75` | Rare; the number is too high, nobody gets in; «Выйти на всех устройствах» clears them. The fix keeps the fingerprint in the file — a change of its shape (ADR 0014), not minutes |
| F3 | `parse_app_url`: a Cyrillic domain (`https://трекер.рф`) is refused with «Telegram не открывает такие ссылки — … или имя сайта с точкой», though it has a dot | defer `KI-76` | Only with a Cyrillic domain; the `xn--…` form is taken. `docs/outside-access.md` says so in point 1. Whether Telegram opens such a name was not checked, so the rule is not widened blind |
| F4 | `Tracker.delivery_check` tells an unknown moment by `KeyError`, and the bot and the web catch `KeyError` around the whole call (the send included): an internal `KeyError` would read as «Такого момента нет» with no log line; the old bot checked the id first and logged | no change | No such path exists today (the sample id is a constant). A wish below |
| F5 | `core.py` is exactly 400 lines (the limit of rule 7 and its test); tickets 02 and 05 packed the imports and `__all__` into lines of 150–188 characters to stay under it | no change | Not a fault of behaviour; the next facade method breaks the limit. A wish below |
| F6 | The dedup key `web_login:<sid>` (spec 6.2) puts each sign-in id into `events`, so into the database copies and the encrypted Google Drive copies — ADR 0014 gave «the copies would carry them» as a reason to keep sign-ins out of the database | no change | Spec and ticket 05 chose it; an id opens nothing without the key of `data/web_secret` and the password fingerprint, a restore revives no sign-in, the JSON export leaves events out. A wish below |
| F7 | Rule 7 of `docs/coding-standards.md`: the table and the list of pure modules did not name `login_reports` and `login_events` (the size test lists them) | fix now | Both named; the row of `test_samples` names `delivery_check` |
| F8 | «A private IPv4 address of the home network» twice: `hosts.PRIVATE_NETWORKS` with `HostRules.allows`, `address_line._PRIVATE_NETWORKS` with `_is_private_ipv4` | fix now | One `hosts.is_private_ipv4`, used by `HostRules` and by the hint of Settings |
| F9 | `settings_sign_in.devices_line` wrote the Russian plural rule again | fix now | `cards.plural`; the plural test (1, 2, 5, 11, 21) passes |
| F10 | The split of `tracker_handlers.py` copied the closure `drop_buttons` into `list_handlers.py` | fix now | One module-level `list_handlers.drop_buttons`, imported by `tracker_handlers` (the inbox's own variant, older and with its own log line, stays) |
| F11 | `SessionCookies` uses Starlette's `Session` and its `accessed` / `modified` flags (the cookie refresh rests on them), which older Starlette versions allowed by `fastapi>=0.115.0` do not have | no change | The image and `.venv` get a Starlette that has them (1.10 here); the tests would fail at once on one without. A wish for stage 8 |
| F12 | Spec 3.1, 3.2: an unknown sample or moment is `400`; for HTMX the web answers the same sentence as a fragment with `200` | no change | A decision of ticket 02 (`docs/history.md`): HTMX 2 does not swap a `4xx`; without HTMX it is `400` |
| F13 | Spec 5.2 named uvicorn 0.54 as the lower bound; `requirements.txt` says 0.31.0 | no change | The spec asked the ticket to find the first version with networks in `forwarded_allow_ips`; ticket 04 found 0.31.0 in the changelog. The live run used 0.54 |

## Tests at the end

- 4159 passed, 3 skipped, 2 failed — two of the three known Windows failures (`test_app_main`, `test_docker_files`; `test_runtime`'s passed this time); `pyflakes app tests` clean; `docs/code-map.md` unchanged by `tools/code_map.py`.
- The bot rebuilt and started on the fixes (`.\start-bot.ps1`: «Готово»): `/health` 200, `APP_URL: ссылки бота ведут в приложение`, a foreign `Host` → `400`, the served `style.css` has `.bot-tests h3`, `Tracker.poll_due … executed successfully` with no `polling title … failed`, no error in the log.

## Wishes for later stages

- The next stage that adds a facade method (stage 9 or later): decide how the facade grows past 400 lines — its own limit in rule 7, or the re-exports of `core.py` in a module of their own — and undo the packed lines (F5).
- When the facade next changes: an unknown sample or moment as an error of its own (`UnknownSample`, `UnknownCheck` in `errors.py`), so a `KeyError` inside a send is a failure with a log line (F4).
- KI-75 together with the next change of `data/web_login.json`: the fingerprint of the password and the key in the file.
- Stage 8 (template): pin the lower bounds of `fastapi` / `starlette` to the versions the session middleware needs, or give `sessions.py` a small `Session` of its own (F11); key the login report by a digest of the `sid` instead of the `sid` (F6).
