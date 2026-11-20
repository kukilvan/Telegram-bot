# Stage 9.1: every open known issue fixed before the move

Status: accepted

Terms come from `CONTEXT.md`. The stage is planned in `docs/project-spec.md` (stage 9.1); the order 9.1 → 7.3 → 9.2 → 8 is the owner's decision of 2026-11-17. ADRs it leans on: 0004 (no own JavaScript), 0007 (bot, polling and web in one process), 0009 (no PlayStation prices), 0010 (the bot takes posts and names), 0011 (a followed expansion is a game of its own), 0012 (Drive copies), 0014 (sign-ins in a file outside the database). **This description splits the stage into four parts** (decision 1); each part skips the description step and starts with its spec.

## Goal

The app moves to the NAS after this stage, and real use starts there (stage 9.2). Every bug and rare failure case collected in `KNOWN_ISSUES.md` since stage 0 is closed first, so what the owner meets on the NAS is new, not something already written down. On 2026-11-20 there are 57 open entries marked «Fix in 9.1»; KI-15 and KI-70 (the container start, `restore-bot.ps1`) belong to 7.3 and are not here.

Most entries are rare cases: a button pressed in the same minute as a check, a source answer of an unusual form, a file edited by hand. None of them loses the owner's data; the worst ones lose or repeat one message, or stop one check until a hand fix.

## What the owner will see at the end

- Every one of the 57 entries closed in `KNOWN_ISSUES.md`: `fixed (test: …)`, or `won't fix (test: …)` with the owner's decision where the app cannot fix it (decision 4). The index has no open row with «Fix in 9.1».
- What changes on the screen or in Telegram (the rest is invisible: fewer repeated, missing or wrong messages):
  - Лента: an anime episode at 00:00 UTC shows its hour; an episode found by a check without a schedule shows no made-up hour; «Недавно» also lists episodes and films out in the last 7 days before the title was added or returned.
  - Архив: one genre under one name («Боевик», not «Боевик», «Экшен» and «Боевик и Приключения» side by side).
  - Phone: the chosen filter of «Список» and «Архив» is always in sight.
  - Games: a release in Japan only is not «вышла»; the card shows it on a line of its own («в Японии — 12 марта 2027»).
  - Steam: the bundle price in the card and the message says it is the price of the whole set.
  - «Это оно?» offers show the date as the card does («IV квартал 2027», «2028»), not a made-up day («31 декабря 2028»).
  - «Найти» on an item whose title is in the list already can remove the item.
  - The web shows «Бот не подключён к Telegram» also when the connection is lost while the bot is running.
  - A hung app restarts itself in Docker.
  - A login report that failed to send goes out as soon as Telegram answers again, not after the quiet hours.
  - `APP_URL` with a Cyrillic domain works.
  - `.env` and `.env.example` hold only variables the code reads.
- No new screens, so no mockups.

## Parts

Each part: spec → slicing → tickets → review, in the folder `.scratch/9-1<letter>-<slug>/`. Ids: «Спека 9.1a», «Тикет 9.1a.02», «Ревью 9.1a»; branches `claude/s9-1a-spec`, `claude/s9-1a-ticket-02`. A part's spec reads this file (its part and the decisions) and the full `KNOWN_ISSUES.md` entries of its part (Grep by heading). The entry «Fix in» column changes to the part (`9.1a` …) when its spec is accepted.

Order: 9.1a → 9.1b → 9.1c → 9.1d. The first two touch polling and the message queue — the most sensitive code, complex tickets on Opus; the splitting of long modules (9.1d) comes last, after the other parts have changed those modules. Sessions (est.): 9.1a 7, 9.1b 6, 9.1c 5–6, 9.1d 6 — about 24 in all.

### 9.1a — start, stop, polling and delivery (17 entries) · `.scratch/9-1a-start-polling/`

| KI | What | Direction of the fix |
|---|---|---|
| 1 | Anime: moving parts of a season can hit the unique key | the moves of `_sync_entries` check that the place is freed, or go through a free number |
| 5 | A stop that cut a send can repeat the message after the start | the send and its «delivered» mark finish together even when a stop comes (spec picks: shielded from cancel, or a mark before the send) |
| 6 | The watchdog does not see a hang that holds the GIL | the container restarts a hung app: e.g. the health check ends the process after several failed answers and `restart: unless-stopped` starts it again |
| 9 | The stop does not wait for started bot presses | the stop waits for the handler tasks (with the same kind of time limit as the scheduler) |
| 16 | A startup failure with a changing text is reported on every retry | the fingerprint does not depend on the volatile parts of the text |
| 17 | The startup failure record is not saved — a report on every retry | an unsaved record still limits the reports (spec picks where to keep it) |
| 18 | `start-bot.ps1` stops a foreign `python -m app.main` | only the `python` of this project's `.venv` is stopped |
| 19 | `start-bot.ps1` can wait longer than 90 seconds | the wait counts by the clock, not by pauses |
| 20 | The name `kind` for the error type in `startup_report.py` | the renames of the entry |
| 21 | Posters of anime not polled vanish when Shikimori changes its address | the poster address follows `SHIKIMORI_BASE_URL` for every anime, polled or not |
| 22 | «Бросил» during a check of the same title can let one message through | the status is read again in the write session that queues the event |
| 23 | A fact right after «Вернуть в список» becomes the reference point | the silent first check after a return reports facts newer than the return |
| 24 | The number of a deleted last title goes to the next one | numbers are never reused (spec picks: `AUTOINCREMENT` by a migration, or a kept maximum) |
| 33 | «Бот не подключён к Telegram» does not appear if the link is lost while receiving | the flag also follows failures inside receiving (an error handler, or a `get_me` once a minute) |
| 41 | Settings spoiled by hand in the database break reading | every setting is read through its `check_…`, as the time zone is |
| 42 | A hand request «Добавить» with a non-digit number says «Не удалось связаться» | a non-digit number is its own error with its own line |
| 45 | A Steam failure and an IGDB failure of one game in a day — one report | the once-a-day window of failure reports is per source |

The review 7.2 wishes go to the first part whose spec changes the facade `core.py` (it has exactly 400 lines), at the latest to 9.1d: decide how the facade grows past 400 lines and undo the packed lines (F5); an unknown sample or check as an error of its own, `UnknownSample`, `UnknownCheck` (F4).

### 9.1b — games and Steam prices (14 entries) · `.scratch/9-1b-games-steam/`

| KI | What | Direction of the fix |
|---|---|---|
| 35 | A release in Japan only counts as a release | decision 2: regions outside the store country's table are not a release; the card shows the date on a line of its own |
| 36 | A release IGDB learned of over 30 days late comes without a message | a mark «release reported» per platform instead of the 30-day rule |
| 37 | The PlayStation Store link can lead to an error page | when the concept is missing in the country's store, a link to the store search (spec checks the PS Store answers and the cost) |
| 38 | An IGDB record without date precision reads as «date not announced» | the precision is read from the fields the record has (`y`, `m`) when `date_format` is missing or unknown; a day is never guessed |
| 43 | The bundle price is for a buyer without the games of the set | **won't fix** (only a Steam sign-in knows what the owner has): the card and the message say it is the price of the whole set |
| 44 | The preorder is checked only on an assembled answer | spec looks for a live preorder in Steam, saves its answer as a fixture, fixes the parsing if it differs |
| 46 | A short discount can pass without a message or with a wrong «до» | **won't fix**, decision 3: prices stay checked every 6 hours and go by the delivery rules; a test pins it |
| 47 | A discount message can go out in the minute the game left «Хочу» | the pending Steam messages are withdrawn by the status change itself |
| 50 | A spoiled price snapshot stops the price check of every game | that game is skipped with a log line once a day; the others are checked |
| 51 | The discounts of one check can come as separate messages | the events of one check are queued at once (one write session or the delivery lock) |
| 52 | A standalone expansion completed before 6.3 never learns it is one | the follow-up check also stores the game's own type and parent |
| 53 | «Бросил» and «Вернуть в список» within a minute keep the old reference point | «Бросил» removes the follow-up snapshot itself, or the return is compared with the snapshot |
| 54 | An announcement withdrawn by «Бросил» never comes from another game of the series | a withdrawn event frees its dedup key |
| 55 | An unreadable own snapshot logs every minute; a never-checked game is never told | one log line a day; both cases fail the check and report once a day |

### 9.1c — Лента, web and login (11 entries) · `.scratch/9-1c-feed-web/`

| KI | What | Direction of the fix |
|---|---|---|
| 28 | Лента: an anime episode at exactly 00:00 UTC shows no hour | the episode keeps whether its moment is a day only (one column for 28 and 32) |
| 29 | «Недавно» misses what came out before adding and before the first check after a return | decision 5: «Недавно» adds the episodes and films of the last 7 days from the schedule that are not in the event log (changes the answer to question 1 of the 5.3 description) |
| 30 | The Архив genre filter: one genre under several names | decision 5: an own table of genre synonyms; a composite TMDb genre («Боевик и Приключения») counts under each of its parts |
| 32 | Лента: an anime episode found without a schedule stands in «Сегодня» with the hour of the check | the episode keeps «moment found by a check» and shows no hour, like 28 |
| 48 | Anime card: no episode or schedule data for an announced season | spec checks Jujutsu Kaisen again (the entry says it may be fine already) and what Shikimori gives; if no source has data — **won't fix**, a test pins the card |
| 65 | «Найти» cannot remove an item whose title is in the list | a row «В списке» opened from an item gets a button that removes the item (text by the spec) |
| 72 | Login report: an iPad reads as «macOS, Safari» | **won't fix** (only JavaScript tells them apart, ADR 0004); a test pins the words |
| 73 | A login report that failed to send waits for the delivery rules | decision 5: a login report ignores the delivery rules on every try, so it goes as soon as Telegram answers |
| 74 | Phone: the chosen filter can be past the edge of its row | decision 5: always in sight without JavaScript (spec picks: the chosen link first in its row, or the row wraps) |
| 75 | The block «Вход» counts sign-ins ended by a new `WEB_PASSWORD` or key | the file keeps a fingerprint of the password and the key; a mismatch at start drops the sign-ins (a field added to `data/web_login.json`; ADR 0014 stays) |
| 76 | `APP_URL` with a Cyrillic domain is refused with a reason about the dot | a Cyrillic name is taken and turned into its `xn--…` form; spec checks that Telegram opens it in a button |

### 9.1d — «Входящие», copies and code health (15 entries) · `.scratch/9-1d-inbox-copies-code/`

| KI | What | Direction of the fix |
|---|---|---|
| 49 | `.env` holds variables the code does not read | decision 5: the ticket removes them from `.env.example` and, on the owner's PC, from `.env` by name, never printing a value |
| 56 | The size test misses the pure modules (`series_events.py` 521 lines, `games.py` 406) | the test takes every module of `app/tracker/`; the long ones split |
| 57 | «Входящие»: a restart within the 2-second pause leaves the item without «Что это?» | at start the bot asks about the items left without the question |
| 58 | A Cyrillic name in the middle of a post is not a candidate | capitalised Cyrillic words in the middle of a sentence become candidates, against a list of common words |
| 59 | The stop list of candidates is a fixed list | spec picks: the list grows (studios, outlets, stores seen in posts), or names of companies from IGDB |
| 60 | A Latin run keeps a leading «from»; a number after a colon is cut off | the two rules of the entry |
| 61 | A typo is not corrected when the source answers in another language | the correction also looks at the English names of TMDb (`alternative_titles`), only when nothing else matched |
| 62 | A kind press does not look the links up again | `answer_kind` looks the links of the chosen kind up again |
| 63 | The Shikimori adapter is over 400 lines and the size test does not see it | the season chain moves into a module of its own; every adapter in the size test |
| 64 | An offer of a title announced for a year or a quarter shows a made-up day | decision 5: the adapters say how precise the date is, and the offer shows it as the card does («IV квартал 2027», «2028») |
| 66 | The time of a copy is the container's clock, not the zone of Settings | the copies show their time in the zone of Settings (old names stay readable) |
| 67 | A Drive folder of over 1000 files is listed only in part | the listing follows `nextPageToken` |
| 68 | A Drive archive of the same name but another size stays as a duplicate | the same-name file of another size is deleted after the upload |
| 69 | The note «ещё одна копия» of an older copy is not always true | the text promises only what happens |
| 71 | The JSON export asks which titles are games | the export asks each poller for the extra fields of its titles; `export_all` joins the size test |

## In scope · out of scope

In scope: the 57 entries above, the two review 7.2 wishes (F4, F5), and every new entry a part's review defers — it goes to the next part of 9.1 if one is left, else to 9.2.

Out of scope: KI-15 and KI-70 (stage 7.3); new features; the review 7.2 wishes for stage 8 (F6, F11); the live check of early tickets (stage 9.2); the cleanup of junk files in the repository root (stage 8).

## Pulled-in `KNOWN_ISSUES.md` entries and review wishes

All 57 open entries with «Fix in 9.1» (on 2026-11-20): KI-1, 5, 6, 9, 16–24, 28–30, 32, 33, 35–38, 41–69, 71–76. Review 7.2 wishes F4 and F5 (part 9.1a, decision 1).

## Decisions taken with the owner

1. **Four parts, a → b → c → d, each from its spec** (owner, 2026-11-20). One spec of 57 entries does not fit one session; three parts leave a third of 26 entries. The decisions every part needs are taken here, so the parts skip their own descriptions.
2. **KI-35: a release in Japan only is not a release** (owner, 2026-11-20). A date of a region outside the store country's table gives no «вышла» and no date of the platform; the card shows it on a line of its own. Rejected: count it, with «вышла в Японии» in the message.
3. **KI-46: short Steam discounts stay as they are** (owner, 2026-11-20): prices checked every 6 hours, messages by the delivery rules (the summary at 15:00). The entry closes as `won't fix` with a test. Rejected: hourly checks, and a discount ending before the summary sent at once.
4. **What the app cannot fix closes as `won't fix (test: …)`** with the decision in the entry: KI-43 (with the note «цена набора целиком»), KI-46, KI-72, and KI-48 if no source has data. The first ticket that closes such an entry adds this status to the rules at the top of `KNOWN_ISSUES.md`.
5. **Taken by the agent, confirmed by the owner's «ОК» of this description** (they change what the owner sees): «Недавно» adds what came out before adding (KI-29); one name per genre (KI-30); the offer date as precise as the card's (KI-64); a login report sent as soon as Telegram answers (KI-73); the chosen phone filter always in sight without JavaScript (KI-74); the session removes the unread variables from `.env` without printing them (KI-49).
6. **No wishes beyond the entries** (owner, 2026-11-20).

## Open questions for the specs

- 9.1a: how a send and its mark survive a stop (KI-5); how the container notices a hang (KI-6) and that it works the same on the NAS; `AUTOINCREMENT` by a table rebuild or a kept maximum (KI-24); `get_me` or the dispatcher's error handler (KI-33); the per-source failure window — a migration (KI-45); how the facade grows past 400 lines (F5).
- 9.1b: a live Steam preorder (KI-44); the PS Store answer for a missing concept and when to ask it (KI-37); where «release reported» lives — a migration (KI-36); which IGDB fields give the precision (KI-38).
- 9.1c: one column for the precision of an episode moment (KI-28, KI-32) — a migration; how the «Недавно» rows from the schedule look (KI-29); the genre synonym table (KI-30); the chosen filter first or a wrapped row (KI-74); what Shikimori and AniList give for Jujutsu Kaisen now (KI-48); a `xn--` name in a Telegram button (KI-76).
- 9.1d: the rules for Cyrillic candidates and the source of stop names (KI-58, KI-59); the cost of `alternative_titles` (KI-61); how the copy names carry their zone (KI-66); how `series_events.py`, `games.py` and the Shikimori adapter split (KI-56, KI-63).
