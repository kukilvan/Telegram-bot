# 03: Sign-ins on the server — `data/web_login.json`, the session middleware, «Выйти», «Выйти на всех устройствах», the block «Вход» (KI-7, KI-8, KI-13)

Status: in review
Complexity: complex (the way the whole web knows who is signed in changes; a new store with a file, a middleware of its own, the lock moved to disk; a mistake here locks the owner out or lets a stranger in)
Blocked by: —

Spec: `../spec.md`, sections 4 (all), 10 (the new file), 11 (rows on the file, the sessions, the cookie, «Выйти на всех устройствах», the clock), 12 (tests of sign-ins, the lock, the key), 13 (`CONTEXT.md` term «Вход», KI-7, 8, 13 to `fixed`). The device words (6.3) and the login report (6.1–6.2) are ticket 05's: here `device` is filled by a small seam that returns `неизвестное устройство` until 05 puts `app/web/devices.py` in, and the login does not queue a report. The `Secure` attribute (5.3) is ticket 04's: here the middleware takes it as an argument of the cookie code, off. ADR: `docs/adr/0014-sign-ins-live-in-a-file-outside-the-database.md` (read it; do not rewrite it); also 0007, 0012. Terms — `CONTEXT.md`; standards — rules 1, 3, 7, 10, 11. `KNOWN_ISSUES.md`: find KI-7, KI-8, KI-13 by their `## KI-<n>` headings.

## What to do

- **The store** (4.1, `app/web/sessions.py`): `data/web_login.json` with `version`, `sessions` (`sid` → `since`, `seen`, `device`), `last_login` (`at`, `device`, `address`), `guard` (`wrong`, `locked_until`); `sid` is `secrets.token_hex(16)` and shown nowhere; moments in UTC with `Z`. Held in memory; every change written at once to a temporary file in `data/` and moved over with `os.replace`, mode `0600` where the system has it; file work off the event loop (rule 1). Absent → empty; not JSON, another `version` or a wrong shape → the warning of the spec, treated as empty, rewritten at the next change; `OSError` → warning, kept in memory until the restart. The restore does not touch the file.
- **The session middleware** (4.2, `app/web/sessions.py`): the app's own middleware with the same `request.session` interface and the same signing as today (`itsdangerous`, the key of `data/web_secret`), replacing Starlette's `SessionMiddleware` (it cannot set `Secure` per request, ticket 04 needs that). Cookie `tracker_session`, 30 days from the last request (sent anew on every answer), carries `sid`, `pw` (the fingerprint of `WEB_PASSWORD`) and the page notice (`pages.notify` keeps working on `request.session`). A request is signed in when the signature is good and under 30 days old, `pw` matches, and `sid` is in `sessions` with `seen` under 30 days old; otherwise a stranger (the login page, `next` and `safe_next` as today). `seen` moves to now only when over an hour old; a session over 30 days old is dropped at the next write. Attributes `HttpOnly`, `SameSite=Lax`, `Path=/`, `Max-Age` 30 days. An old cookie without `sid` is a stranger — every device logs in once after the update.
- **Login and «Выйти»** (4.3): the right password makes a new `sid` (`since` = `seen` = now), replaces `last_login` (the address is `null` here: ticket 04 brings the client address), resets the lock count, sets the cookie; at most 20 sessions, the oldest `seen` dropped beyond that. `POST /logout` removes its own `sid`, clears the cookie, `303` to `/login`; a copied cookie of that session no longer works (KI-8). A change of `WEB_PASSWORD` still ends every session.
- **«Выйти на всех устройствах»** (4.4): `POST /settings/sign-out-everywhere` (route `settings_sign_out_everywhere`), `sessions` emptied (`last_login` and the lock stay), this cookie cleared, log info `web: signed out everywhere (<n> sessions)`, `303` to `/login?out=everywhere`; the login page with exactly that value shows `Вы вышли на всех устройствах. Войдите снова.` above the form, any other value is ignored. No question before it. An HTMX request of a signed-out tab goes to `/login` by `HX-Redirect`, as today.
- **The block «Вход»** (4.5): at the bottom of Settings after «Копии и выгрузка» — heading, `Последний вход: {moment}, {device}.` (with `, адрес {address}` only when set; `moment_in_words` on the owner's zone; `Последний вход: сведений нет.` when none), the plural line (`устройстве` for 1, 21, 31… but not 11; `устройствах` otherwise; `n` counts this session), the button and the hint of the spec. Built for the phone from the start.
- **The lock** (4.6, KI-7): `LoginGuard` keeps its count and the end of a lock in `guard` of the file, on the UTC wall clock, written on every wrong try and every reset; the rules stay (the fifth wrong password in a row locks for 15 minutes, a locked try is not looked at and does not extend the lock, the end starts the count anew); one count for the whole app. The lock must survive a new app built on the same file.
- **The key** (4.7, KI-13): `data/web_secret` shorter than 32 bytes is replaced by a new key (temporary file and `os.replace`, mode `0600`) with the warning of the spec; a failed write keeps the key in memory as today.
- **Docs:** `CONTEXT.md` — «Вход» (in code `sign-in`, `app/web/sessions.py`, `sid`; not `drive_sign_in`); `KNOWN_ISSUES.md` — KI-7, 8, 13 → `fixed (test: …)`; the code map's «Not Python» part names `data/web_login.json` (the rest of the doc work is ticket 06's); module docstrings and `tools\code_map.py`; `docs/tests-map.md`.

## Done when

- [ ] Login makes a session in the file; «Выйти» ends only its own; the cookie copied before «Выйти» is refused; «Выйти на всех устройствах» ends all and keeps `last_login`; `?out=everywhere` shows its sentence, another value nothing.
- [ ] A cookie without `sid`, with a wrong `pw`, with a bad or old signature, or whose `sid` is not in the file is a stranger's; after the update a browser with an old cookie sees the login page once.
- [ ] `seen` is written at most once an hour per device; the 21st sign-in drops the oldest; 30 days without a request ends a session.
- [ ] The file: absent, spoiled (the warning, empty, rewritten), unwritable (kept in memory); `0600` where the system has it; a hand-written session in it does not work without a cookie signed by the key.
- [ ] The lock (five wrong passwords) survives a new app on the same file, ends on time, is not extended by a locked try.
- [ ] A short `data/web_secret` is replaced and a sign-in made afterwards survives the next start.
- [ ] The block «Вход» shows its lines, the plural for 1, 2, 5, 11, 21; KI-7, 8, 13 are marked fixed with their tests.
- [ ] The whole web (every page, HTMX answers, the notices of `pages.notify`) works on the new middleware; the existing web tests pass, adapted only where they built a session cookie by hand.
- [ ] No module of the core over 400 lines; `.venv\Scripts\python.exe -m pyflakes app tests` clean; the full suite green (the three known Windows failures are not new).

## Tests to add

- Store: absent, spoiled, wrong `version`, unwritable; atomic rewrite; `0600`; the hourly write of `seen`; 30-day end; the 21st session.
- Middleware: each case of the signed-in rule; the cookie attributes; the notice survives a redirect; an HTMX request of a stranger gets `HX-Redirect`.
- Login, «Выйти» (a copied cookie refused), «Выйти на всех устройствах» (`last_login` and the lock stay), `?out=everywhere` and another value.
- Lock: survives a new app on the same file; ends on the wall clock; not extended by a locked try; one count for the app.
- Key: a short file replaced; a sign-in survives the next start.
- The block «Вход»: both lines of the last login, the plural (1, 2, 5, 11, 21).

## Owner check

The session starts the bot itself and writes the launch result in one line. After this update every browser has to sign in once — that is expected.

1. Browser on the PC, `http://localhost:8080`: the login page. Type the password → the Feed. Settings → at the bottom a block «Вход»: «Последний вход: сегодня в …, неизвестное устройство.» and «Вход открыт на 1 устройстве.»
2. Open `http://localhost:8080` in another browser (or a private window), sign in → in the first one, reload Settings: «Вход открыт на 2 устройствах.»
3. In the second one press «Выйти» (top right) → the login page. In the first one: still signed in, «…на 1 устройстве.»
4. Sign in again in the second one. In the first press «Выйти на всех устройствах» → the login page with «Вы вышли на всех устройствах. Войдите снова.»; reload the second one → also the login page.
5. Five wrong passwords in a row → the lock message. `.\start-bot.ps1` (restart), try the right password at once → still locked until 15 minutes pass.

«Не так»: you are signed out without pressing anything, «Выйти» ends other devices too, the lock disappears after a restart, an error page.
