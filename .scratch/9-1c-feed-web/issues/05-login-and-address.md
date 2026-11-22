# 05: Login and address — the report outside the rules, the mark of the sign-ins, a Cyrillic `APP_URL` — KI-73, KI-75, KI-76, KI-72

Status: in review
Complexity: medium (three independent changes in delivery, the sign-in file and the address; one status change)
Blocked by: —

Spec: `../spec.md`, section 6 (the report), section 7 (the mark, the table of the file at start), section 8 (IDNA, `shown`, the reason), section 9 (KI-72 only), section 11 (`data/web_login.json`: the field `mark`), the KI-73, KI-75 and KI-76 lines of the tests of section 14, the lines of section 13 about a report queued before the update, Telegram down overnight, `WEB_PASSWORD` changed back, `data/web_secret` deleted, a rollback to 7.2, and the three `APP_URL` cases, the glossary entries and the `docs/outside-access.md` line of section 15, the live Telegram answer `../answers/telegram-xn-button-2026-11-22.json` (read it, do not copy it). Terms — `CONTEXT.md` («Сообщение о входе», «Вход», «Адрес приложения», «Доставка»). ADRs to read: 0007, 0014 (stands; no new ADR), 0015. Standards — rules 2, 4, 7, 9, 10, 11. Known issues: KI-73, 75, 76 (`fixed`), KI-72 (`won't fix`).

## What to do

- **KI-73 (6).** The two report types (`login_events.TYPES`: `web_login`, `web_login_locked`) are taken out of the delivery rules for good: `delivery.DeliveryRules.due` returns the reports in its first list (one by one) in every case — quiet hours, a work day before the summary hour, a pass in which `DeliveryRules.holds` holds everything; `DeliveryService.summary_now` sends the queued reports as their own messages before the summary, so a report never joins a summary; a report never expires (`delivery.expired` stays for discounts). The send at once of the web (`LoginReporter._send`) stays as it is. **Never twice:** every pass runs under `delivery_lock` and an event is marked delivered by the same step that saw its send succeed (`DeliveryService._send`) — a test sends at once and passes together and counts one message. A report queued before the update goes at the next pass.
- **KI-75 (7).** `data/web_login.json` gets the top-level field `mark`: 64 hex characters, HMAC-SHA256 with the key of `data/web_secret` over the text `web_login.json:` followed by `WEB_PASSWORD`. It is not `auth.fingerprint` (the cookie's) and the password is never in the file. At start (`SignIns(file, clock, mark=…)`, before the web serves anything): no `mark` (a file of 7.2) — take the current one, keep the sign-ins, write the file at once; the same mark — as now; another mark — drop every sign-in (the last login and the lock count stay), write the file at once, log `WEB_PASSWORD или data/web_secret сменились: закрыто старых входов — N`; a `mark` that is not 64 hex characters — the file is spoiled: empty with the warning, as now; no file or a spoiled one — empty, the mark goes into the first write; cannot be written — memory until the restart (`UNWRITABLE`), as now. Only at start. `VERSION` stays 1; without `WEB_PASSWORD` no file and no mark. After the change the block «Вход» says «Вход открыт на 1 устройстве.» after a new login, «Выйти на всех устройствах» counts only the live sign-ins, the cap of 20 holds only them.
- **KI-76 (8).** `config._host_reads`: a name with a non-ASCII character is turned into ASCII by IDNA with UTS 46 (package `idna`, installed already with `httpx`; name it in `requirements.txt` and `pyproject.toml` as `idna>=3.4`), then passes the rules every name passes (a dot inside, not `localhost`). `AppUrl.address` and `AppUrl.host` are the ASCII form (the bot's links, `AppLinks`, `AllowedHosts` against the `Host` header); the new `AppUrl.shown` is the address as written, in lower case (an ASCII address — the same as `address`) and the Settings line uses it: «Адрес приложения: https://трекер.рф. Кнопки «Карточка» в сообщениях бота открывают его.» A name IDNA refuses (`idna.IDNAError`) is malformed with the reason **«имя сайта записано с ошибкой — проверьте буквы и точки»**; a Cyrillic name without a dot keeps the reason of a Latin one (`_TELEGRAM_REFUSES`). `docs/outside-access.md`, section 1: a Cyrillic name may be written as it is. `PROJECT_CONTEXT.md`: the `APP_URL` row says a Cyrillic name is taken.
- **KI-72 (9).** Won't fix: telling an iPad from a Mac needs JavaScript (ADR 0004). The test is there already (`tests/test_web_devices.py::test_an_ipad_that_says_it_is_a_mac_reads_as_a_mac_known_issue_72`); only the status changes, with the reason and the owner's decision in the entry.
- **Docs.** Docstrings, `tools\code_map.py`, `docs/tests-map.md`; `CONTEXT.md` — **Сообщение о входе** («one that failed to send goes at the next delivery pass, whatever the rules», instead of the KI-73 sentence), **Вход** (the file keeps a mark of the password and the key; a change of either ends the sign-ins at start), **Адрес приложения** (a Cyrillic name is taken); `KNOWN_ISSUES.md` — KI-73, 75, 76 `fixed (test: …)`, KI-72 `won't fix (test: …)`, with the index rows.

## Done when

- [ ] `due` gives a queued report in quiet hours, on a work day before the summary hour and in a pass the rules hold; «Сводка сейчас» sends it apart and never in the summary; a failed send is retried at the next pass; the send at once and a pass together send it once. The example: the network down at 22:00, back at 22:40 — the report comes at 22:41.
- [ ] Every row of the table of section 7 is a test; the mark is neither the password nor the cookie fingerprint; after a mismatch `count` is the number of live sign-ins; a file of 7.2 keeps its sign-ins; the file with `mark` read by an old app keeps working (the named keys only).
- [ ] `https://Трекер.РФ` gives address `https://xn--e1aaowdh.xn--p1ai` and `shown` `https://трекер.рф`; with a port the port stays; `https://трекер` gives the reason about the dot; a label over 63 characters gives the new reason; `AllowedHosts` takes the `xn--` host; mixed ASCII works.
- [ ] The session itself checks the last point live: a Cyrillic `APP_URL` in `.env` (and back), the Settings line and the log; and a stopped network for KI-73 on a test bot run, as the spec says these two are not the owner's work.
- [ ] pyflakes clean; code map rebuilt; no core module over 400 lines; the full suite green (the known Windows failures are not new).

## Tests to add

- KI-73: the cases of «Done when»; a report queued before this change; a report older than a day is not expired.
- KI-75: each row of the table of section 7; the mark's two inputs (password, key); `web_secret` deleted; the same password and key again.
- KI-76: Cyrillic, upper case, with a port, without a dot, refused by IDNA, mixed ASCII; `shown` in the Settings line; `AllowedHosts`.
- KI-72: nothing new (the existing test).

## Owner check

The session starts the bot and writes the launch result in one line. One step for the owner:

1. Open `.env` (in Блокнот), change the line `WEB_PASSWORD=` to another password of at least 8 characters, save, and say so in the chat — the session restarts the bot. Then in the browser at `http://localhost:8080` sign in with the new password and open «Настройки», block «Вход»: it says «Вход открыт на 1 устройстве.» (before this ticket it still counted the old sign-ins). Do not tell the password in the chat.

«Не так»: the block counts old devices after the change; the login page rejects the new password.
