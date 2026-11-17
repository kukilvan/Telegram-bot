# 05: The login report — the two events, the device words, the sample

Status: in review
Complexity: medium (two new event types sent at once outside the delivery rules, a pure parser of the `User-Agent`; touches the login of ticket 03)
Blocked by: 03 (the login, the lock and `last_login`), 04 (the public client address)

Spec: `../spec.md`, sections 6 (all), 10 (events in the database), 11 (rows on Telegram down at a login, two locks, no `User-Agent`), 12 (tests of the login report and the device words), 13 (`CONTEXT.md` term «Сообщение о входе», KI-72, KI-73). Terms — `CONTEXT.md`; standards — rules 1, 3, 7, 10, 11; ADRs 0002, 0014. Events without a title follow the ones that exist (`backup_failed`, «could not check»): read how they are recorded, deduplicated and sent before writing.

## What to do

- **The device in words** (6.3, `app/web/devices.py`): a pure function, `User-Agent` (cut to 512 characters) → `{system}, {browser}` by the two first-match tables of the spec; neither known → `неизвестное устройство`; one known → that one alone; no `User-Agent` → `неизвестное устройство`. Replace the seam of ticket 03 with it, for `sessions[sid].device` and `last_login.device`.
- **The two events** (6.1): types `web_login` and `web_login_locked`, title-less (the Feed never shows them), the texts of the spec word for word, `{moment}` by `moment_in_words` on the owner's zone, `{address}` only when public, no buttons. One core method takes the facts (type, device, address, moment) and builds the text; the web never writes event texts. A lock begins by the wrong try that makes the fifth; a locked try and the wrong passwords before the fifth send nothing.
- **Delivery** (6.2): recorded with the dedup key `web_login:<sid>` or `web_login_locked:<end of the lock>` and sent at once whatever the delivery rules (`force`), only this event, as a test event is. The login answer does not wait for Telegram: the record is made in the request, the send runs as a background task. A failed send leaves the event in the queue; the regular delivery sends it later by the rules (a night login reported in the morning — this is KI-73).
- **The sample** (6.2, last paragraph): one more sample of «Тестовое событие», `Вход в приложение` — the text of `web_login` with `Android, Chrome` and the address `203.0.113.5`; it appears in the bot's list (chat mode) and in the Settings list of ticket 02.
- **Docs:** `CONTEXT.md` — «Сообщение о входе» (the events `web_login`, `web_login_locked`); `KNOWN_ISSUES.md` — KI-72 (an iPad reads as `macOS, Safari`) and KI-73 (a failed report waits for the delivery rules) are already there, written by the spec; check that the code and the texts still match them and fix the entries if the ticket changed anything; module docstrings and `tools\code_map.py`; `docs/tests-map.md`.

## Done when

- [ ] A right password queues one `web_login` event with the spec's text and sends it at once; the fifth wrong password queues `web_login_locked`; the sixth (locked) and the first four send nothing.
- [ ] A sender that hangs does not delay the login answer; a sender that fails leaves the event pending and a later regular delivery sends it by the rules.
- [ ] Two locks in a row have their own keys and both come; the same login never reports twice.
- [ ] The Feed shows neither event; the sample `Вход в приложение` is in both lists.
- [ ] Each row of the device table gives the right words from a real `User-Agent`; an empty and an unknown one give `неизвестное устройство`.
- [ ] KI-72 and KI-73 in `KNOWN_ISSUES.md` match the finished behaviour.
- [ ] No module of the core over 400 lines; the web goes through the facade only; `.venv\Scripts\python.exe -m pyflakes app tests` clean; the full suite green (the three known Windows failures are not new).

## Tests to add

- Login report: right password → one `web_login` with the text; the fifth wrong → `web_login_locked`; the sixth and earlier tries → nothing; a failing send → pending; a hanging sender does not hold the answer; both dedup keys; the Feed hides both; the sample is listed.
- Device words: a real `User-Agent` for each of Android Chrome, Android Samsung Internet, Android Yandex, iPhone Safari, iPhone Chrome, iPad, Windows Edge, Windows Chrome, Windows Firefox, macOS Safari, Linux Firefox, ChromeOS; empty; unknown; longer than 512.

## Owner check

The session starts the bot itself and writes the launch result in one line.

1. Browser, sign out and sign in again → in Telegram within seconds: «🔐 Вход в приложение: Windows, Chrome (или ваш браузер), сегодня в …» and the line about «Выйти на всех устройствах». At home no address is shown — that is right.
2. The phone, `APP_URL`'s address, sign in → the same message with `Android, Chrome` (or `iPhone, Safari`).
3. Settings → «Тестовое событие» → choose «Вход в приложение» → «Прислать»: the message with the sample address `203.0.113.5` arrives.
4. Five wrong passwords → «⚠️ Вход в приложение закрыт на 15 минут: 5 неверных паролей подряд…» arrives once; a sixth try sends nothing more.

«Не так»: a message for a wrong password before the fifth, two messages for one login, a login that waits seconds for Telegram, an event in the Feed.
