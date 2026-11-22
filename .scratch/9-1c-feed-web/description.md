# Stage 9.1c: Лента, web and login — the known issues

Status: accepted

Terms come from `CONTEXT.md`. The stage is part c of stage 9.1 (`docs/project-spec.md`). `.scratch/9-1-known-issues/description.md` set its 11 known issues and a direction of fix for each (part 9.1c, decisions 4 and 5 there). Spec 9.1a passed KI-77 on to this part. This description settles what the owner will see: the episode hour, «Недавно», the genres, the phone filter and the «Найти» button. ADRs it leans on: 0004 (no own JavaScript), 0005 (SQLite, migrations), 0007 (one process), 0014 (sign-ins in a file outside the database).

## Goal

Close the known issues of the Feed, the web screens and the login before the move to the NAS. None of them loses data. Each one shows something wrong or incomplete: an hour the source never gave, an episode missing from «Недавно», one genre under three names, a chosen filter out of sight on the phone, a sign-in count that is too high, a login report that waits for the quiet hours.

## What the owner will see at the end

Mockups: `mockups/feed.html` (the hour of anime episodes, «Недавно» rows from the schedule), `mockups/archive.html` (the phone filter, one name per genre), `mockups/search-inbox.html` (the button of «Найти»).

- **The hour of an anime episode is shown only when the source gave it** (KI-28, KI-32):
  - an episode at exactly 00:00 UTC (09:00 in Tokyo) shows its hour in «Скоро» («в 03:00»); now it shows none;
  - an episode a check found without a schedule shows no hour. Now it shows the hour of the check («Сегодня · Сезон 2, серия 7 · в 14:42»);
  - a premiere Shikimori knows only by the day shows no hour, in the Feed as now and **also in the card and in the bot card**, where it now says «в 03:00» (00:00 UTC on the owner's clock).
- **An anime episode out right after «Вернуть в список» comes as a message** (KI-77): when its moment is from the schedule, the first check after the return reports it like other facts newer than the return. An episode found by a check without a schedule stays silent in that first check. Nobody can tell when it came out.
- **«Недавно» also shows what came out before the title was added** (KI-29, decision 3): episodes and films (premiere in cinema, digital release) of the last 7 days that came out before adding, or while the title lay in the archive, and are not in the event log. Such a row stands on the day of the release by the source's schedule, with no hour and no buttons, and has a grey line «вышла до добавления в список» («вышел …» for a film). No message is sent about them. Games are not included.
- **One name per genre in the Archive filter** (KI-30): an own table of synonyms. «Экшен» (Shikimori) and «Боевик» (TMDb) are «Боевик». A composite TMDb genre of a series counts under each part: «Боевик и Приключения» is «Боевик» and «Приключения», «НФ и Фэнтези» is «Фантастика» and «Фэнтези». Choosing «Фэнтези» shows the series too. The card keeps the genres as the source names them. On the owner's base today this merges «Экшен» with «боевик», «Тайна» with «детектив», and splits «НФ и Фэнтези» and «Боевик и Приключения».
- **Phone: the chosen filter is the first link of its row** (KI-74, decision 1). The rows of «Список» and «Архив» stay one line that scrolls sideways. Under 40rem the chosen link moves to the start of its row, with CSS only. On a computer the order stays as now.
- **«Найти» on an inbox item whose title is in the list already** (KI-65, decision 2): its row in the Search has «В списке» and a button «Это оно — убрать запись». The button deletes the item and leads back to «Входящие» the way «Убрать» does. The Search opened without an item stays as now («В списке» only).
- **A login report that failed to send goes as soon as Telegram answers** (KI-73), whatever the hour and the delivery rules. Today it waits in the queue for the rules (a login at 22:00 is reported at 07:30).
- **The block «Вход» counts only sign-ins that still work** (KI-75). After a change of `WEB_PASSWORD` or a new `data/web_secret`, the next start drops the old sign-ins. The «Вход открыт на N устройствах» count and the cap of 20 no longer count them. `data/web_login.json` keeps a fingerprint of the password and the key, never the password itself (ADR 0014 stays: the same file, one more field). The update logs nobody out.
- **`APP_URL` with a Cyrillic domain works** (KI-76): `https://трекер.рф` is taken and used in its `xn--…` form. Settings shows the name as written.
- **No change, with a test that pins the behaviour** (decision 4 of the stage 9.1 description): KI-72 (an iPad reads as «macOS, Safari»; telling them apart needs JavaScript, ADR 0004); KI-48 if no source has data for season 4 of «Магическая битва».
- No new screens. Every other change is invisible.

## In scope · out of scope

In scope: the 12 entries below and the wish of review 9.1b about `core.py`.

Out of scope: the parts 9.1d («Входящие», copies, code health; KI-64, the precise date of an offer, is there) and 7.3; new features. Games are not part of «Недавно» from the schedule. The genres in the card and in Search stay as now. There is no filter by several genres at once.

## Pulled-in `KNOWN_ISSUES.md` entries and review wishes

| KI | What | Direction of the fix |
|---|---|---|
| 28 | Лента: an anime episode at exactly 00:00 UTC shows no hour | an episode keeps where its moment comes from (one column for 28, 32 and 77; a migration) |
| 29 | «Недавно» misses what came out before adding and before the first check after a return | decision 3: rows from the schedule of the last 7 days not in the event log |
| 30 | The Архив genre filter: one genre under several names | an own synonym table; a composite TMDb genre counts under each part |
| 32 | Лента: an anime episode found without a schedule stands in «Сегодня» with the hour of the check | the same column as 28: «found by a check», shown without an hour |
| 48 | Anime card: no episode or schedule data for an announced season | still so on 2026-11-22: season 4 «Часть 2» of «Магическая битва» has no date and no episode count in the owner's base. The spec asks Shikimori and AniList; if no source has data, **won't fix** with a test of the card |
| 65 | «Найти» cannot remove an item whose title is in the list | decision 2: the button «Это оно — убрать запись» |
| 72 | Login report: an iPad reads as «macOS, Safari» | **won't fix** (ADR 0004); a test pins the words |
| 73 | A login report that failed to send waits for the delivery rules | the login report ignores the delivery rules on every try |
| 74 | Phone: the chosen filter can be past the edge of its row | decision 1: the chosen link first in its row, under 40rem, CSS only |
| 75 | The block «Вход» counts sign-ins ended by a new `WEB_PASSWORD` or key | a fingerprint of the password and the key in `data/web_login.json`; a mismatch at start drops the sign-ins |
| 76 | `APP_URL` with a Cyrillic domain is refused with a reason about the dot | the name is taken and turned into `xn--…`; the spec checks that Telegram opens it in a button |
| 77 | Anime: an episode out right after «Вернуть в список» passes silently | (from spec 9.1a) an episode with a moment from the schedule gets `happened_at` |

Review 9.1b wish: `app/tracker/core.py` has 490 of its 500 lines. If this stage adds facade methods, it first moves a group of them out (or trims the docstrings), not a new module per method.

## Decisions taken with the owner

1. **KI-74: the chosen filter first in its row on the phone** (owner, 2026-11-22). The row stays one short line. Rejected: a wrapping row, which shows every link in the desktop order but makes the genre row 3–4 lines tall on a phone.
2. **KI-65: the button «Это оно — убрать запись»** (owner, 2026-11-22). Rejected: «Убрать запись», shorter but it does not say the title is the one.
3. **KI-29: «Недавно» from the schedule takes episodes and films** (owner, 2026-11-22), as the stage 9.1 description planned. Rejected: games as well.
4. **No wishes beyond the entries** (owner, 2026-11-22).
5. **Taken by the agent, confirmed by the owner's «ОК» of this description:**
   - the episode hour follows the source in the card and the bot too, so a premiere known by the day loses its «в 03:00»;
   - the «Недавно» rows from the schedule have no hour, no buttons and the grey line «вышла до добавления в список»;
   - the genre synonyms apply only to the Archive filter; the card keeps the source's names, and the merged genre is named by the TMDb word («Боевик», «Детектив», «Фантастика»);
   - the sign-in fingerprint is a hash, never the password. The update that adds it logs nobody out: a file without it takes the current one;
   - `APP_URL` with a Cyrillic name is shown in Settings as written.

## Open questions for the spec

- KI-28, 32, 77: the column of an episode moment (values, the migration, what the existing episodes get: an anime moment at 00:00 UTC is «day only», the others «from the schedule» unless the spec finds a way to tell «found by a check»), and where the card and the bot read it.
- KI-29: how a schedule row is matched against the event log, so one episode is not shown twice. Its exact texts, folded like the summary («серии 3–5»). Series from TMDb, anime from AniList and Shikimori, films by their dates.
- KI-30: the synonym table itself, from the genre lists of TMDb (movies and series), Shikimori and IGDB in Russian. What a genre not in the table does (it stays as it is). The glossary entry «Жанр» changes.
- KI-48: what Shikimori and AniList give now for season 4 of «Магическая битва» (answers saved next to the spec).
- KI-65: what the button sends (the item and the title), what happens when the item is gone already.
- KI-73: whether the login events skip the rules in the regular delivery or are retried on their own. A retry must never send a report twice.
- KI-75: what the fingerprint is made of (the password and the key, salted by the key), and whether a mismatch found while the app runs matters (only at start, as the KI says).
- KI-76: the Cyrillic name check (letters of any script in IDNA, the dot rule), and a live check that Telegram accepts an `xn--` link in a button.
- The `core.py` wish: which group of facade methods moves out, if the spec adds any.
