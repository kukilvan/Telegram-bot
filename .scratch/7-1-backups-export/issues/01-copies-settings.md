# 01: Settings block «Копии и выгрузка» — copies on the PC, «Сделать копию сейчас», the failure report

Status: accepted
Complexity: medium (a settings block, a new kind of copy with rotation and a lock, one new event; no external service)
Blocked by: —

Spec: `../spec.md`, sections 1 (all), 2 (all, without the Google Drive line and without the sending of 2.2), 2.1, 4.6 (the local report only: the event `backup_failed`, its dedup key and the local text), 6 (rows on the same-second copies and on the zone of Settings), 7 (Copies, Settings block), 9 (`CONTEXT.md` term «Копия базы»). Mockup: `../mockups/settings-backups.html` (the texts of the spec are final, the mockup is the layout). Terms — `CONTEXT.md`; standards — rules 1, 2, 7, 8, 9, 10, 11; ADRs 0005, 0007. The block is built so that tickets 02, 03 and 04 add their lines and buttons to it without rewriting it.

## What to do

- **Copy kinds** (`app/utils/backup.py`, 1.2): the manual copy `tracker_db_<time>_manual.db` (online backup, as the daily one); one reading of "a copy" — a valid name, ordering newest first, on equal times daily before manual before the others; names that only look like a copy are not copies; rotation of the manual copies (10 newest) that never touches the daily ones, and the daily rotation that never sees the manual ones (the existing 14 + 12 months stay as they are). A manual copy does not move the daily schedule. Before-migration copies are untouched.
- **One lock** for making a copy, shared by the hourly job and the manual press (2.2, last paragraph): a press while the hourly job copies waits up to 60 s, then gives «уже делается»; a second press in the same second gets «уже делается».
- **The failed copy is reported** (1.3, 4.6 local): when `create_backup` raises in the hourly job, queue the event `backup_failed` (title-less, so the Feed does not show it; delivered like «could not check»), dedup key `backup_failed:local:<owner's YYYY-MM-DD>`, reason «на диске нет места» for `OSError` with `ENOSPC`, else «ошибка, подробности в журнале»; text `⚠️ Копия базы не сделана: {reason}. Последняя — {when}. Попробую снова через час.`. The text and the reasons live where rule 7 puts texts next to the failure texts of the sources (`failures.py` or a module of its own — decide by rule 7 and say so in the docstring); the sample goes into the bot's «Тестовое событие» list (ticket 04 adds the Google Drive one). The Google Drive kind of the key and text is not built here.
- **The moment in words** (2.1): one pure function on the owner's clock — `сегодня в 07:58`, `вчера в 18:32`, `4 ноября в 07:58`, `4 ноября 2025 в 07:58`; the time of a copy is read from its name as written (KI-66). It is used by this block, the notices, the failure text, and later by tickets 03–05 (put it where all of them reach it; rule 7).
- **The block** (2, `app/web/settings.py` + `settings.html`): under «Бот в Telegram» a heading «Копии и выгрузка» with, in the order of the spec: the line of the copies on the PC (count and newest; the three states: some, none, folder unreadable with a warning in the log) and its hint; **a place for the Google Drive line** (empty for now; ticket 03 fills it); the button «Сделать копию сейчас»; a place for the export buttons and their hint (empty for now; ticket 02 fills it). The folder is read in a worker thread (rule 1); a failure of the block never breaks the rest of the page. The web reaches it only through the core facade (rule 10) — a new method of `Tracker` handing the pure result to the page.
- **`POST /settings/backup`** (2.2): makes a manual copy, rotates, goes back to Settings with the notice of the table: «Копия сделана: {when}.», «Копия не сделана: {reason}.», «Копия уже делается — подождите несколько секунд.». The rows about Google Drive in that table are ticket 04's; here the press only makes the copy, but the function that decides the notice is built so that ticket 04 adds the sending and the other four notices (leave a clearly named seam, no dead code).
- **Docs:** module docstrings (first sentence = the code-map line), `.venv\Scripts\python.exe tools\code_map.py`; `CONTEXT.md` — the term «Копия базы» (kinds daily · manual · before an update · before a restore; in code `backup`; _Avoid_: бэкап in messages, дамп); `docs/tests-map.md`.

## Done when

- [ ] The four kinds of 1.2 have the names and rotation of the table; 10 manual copies kept; daily and manual rotations do not see each other; names that only look like copies are ignored.
- [ ] Settings shows each state of the copies line from a prepared folder; the notice of every outcome of the press (copy made, copy failed, already working) appears; a failed copy line never breaks the page.
- [ ] The hourly job with a raising `create_backup` queues `backup_failed` once a day, with the right reason; the Feed does not show it; «Тестовое событие» offers its sample.
- [ ] The moment in words gives the four forms (today, yesterday, this year, another year) on the owner's clock.
- [ ] No module of the core over 400 lines; the web goes through the facade only; `.venv\Scripts\python.exe -m pyflakes app tests` clean; the full suite green (the three known Windows failures are not new).

## Tests to add

- Copies: kinds and names, ordering and the tie-break, rotation of manual and daily copies not touching each other, a manual copy not moving the daily schedule, names that only look like copies, the lock (a second press, a press during the hourly copy).
- `backup_failed`: raising copy with `ENOSPC` and with another error, the text, the once-a-day key, the sample of «Тестовое событие».
- The moment in words: the four forms, around midnight, another zone.
- Settings (web): the block for each state; the press with each notice; the page behind the sign-in (rule 10's test covers the new address by itself); a failing block leaves the rest of the page.

## Owner check

The session starts the bot itself and writes the launch result in one line. The owner's check (browser, `http://localhost:8080/settings`, signed in; scroll to the bottom):

1. A heading «Копии и выгрузка» and a line «Копии базы на этом ПК: …, последняя — …». The count is not zero (the bot has made a daily copy before).
2. Press «Сделать копию сейчас» → the page returns with «Копия сделана: сегодня в …». The count in the line grew by one.
3. Open the folder `E:\LocalAI\Bionic\Telegram-bot\data\backups` — a new file `tracker_db_…_manual.db` with the same time is there.
4. Press the button five times in a row, then look at the folder: copies were made one after another (not two with the same time), and «уже делается» shows when the press comes too quickly.

«Не так»: no block at the bottom, the count that does not change after the press, an error page, a manual copy that disappears from the folder after the next one (only more than 10 may be removed).
