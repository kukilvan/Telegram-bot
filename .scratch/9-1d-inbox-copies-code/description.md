# Stage 9.1d: «Входящие», copies and code health — the known issues

Status: in review

Terms come from `CONTEXT.md`. The stage is part d, the last part, of stage 9.1 (`docs/project-spec.md`). `.scratch/9-1-known-issues/description.md` set its 15 known issues and a direction of fix for each (part 9.1d, decisions 4 and 5 there). Review 9.1c added KI-83 and KI-84, and spec 9.1c added KI-81. This description settles what the owner will see: the date of an offer and of an anime premiere, the studios in a post, the question after a restart, and the time of a copy. ADRs it leans on: 0005 (SQLite, migrations), 0007 (one process), 0010 (the bot takes posts and names; rules, no AI), 0012 (Drive copies through its API).

## Goal

Close the last known issues before the move to the NAS: the inbox, the copies, three anime cases from part c, and the long modules of the core. None of them loses data. Some show a day nobody announced. Some miss a name, a question or a message. In some the text of the app promises what does not happen. The long modules cost every later session more to read.

The owner has not used «Входящие» yet: `inbox_items` is empty on 2026-11-23. So the candidate rules are tuned on made-up posts and the samples of stage 6.4. Real posts tune them in stage 9.2.

## What the owner will see at the end

- **An approximate date in an offer reads as a phrase** (KI-64, decision 1): «выйдет в 2028», «выйдет во 2 квартале 2027», «выйдет в январе 2027», where today it says «выйдет 31 декабря 2028». A date with a day stays «выйдет 12 февраля 2027». A title already out stays its year («2026»). The precision comes from the source: IGDB by the `date_format` of the release, Shikimori by `airedOn { year month day }`.
- **An anime premiere known by the month or the year is shown as such** (KI-81, decision 2). The card says «часть 2 — в апреле 2027» (or «— в 2027»), where today it says «— с 1 апреля». The Feed puts it in «Позже» as «апрель 2027», on the last day of its period, as it does for games. Like games, an approximate date sends no message. The message «объявлена дата … Премьера: 9 апреля 2027» comes when the exact day is announced. The update itself sends nothing: a stored made-up «1 января» that turns into «январь 2027» is no «перенесена».
- **An anime episode first seen after a bulk drop comes as a message** (KI-83). An episode not stored before, whose airing AniList gives in its 8-day window, is news even when that airing is earlier than the previous look.
- **A premiere moved by hours within its day shows the hours** (KI-84): «9 янв 2027, 18:00 → 9 янв 2027, 19:00» in the owner's zone, not «9 янв 2027 → 9 янв 2027».
- **Studios, publishers and stores are not taken for titles** (KI-59, decision 3). «Ubisoft анонсировала новую игру…» no longer offers «Ubisoft». The bot asks IGDB whether the capitalised names of a post are companies, in one request per item. The fixed list stays for what IGDB does not know: streaming services, outlets and stores («Netflix», «IGN»…). Without IGDB keys, or when IGDB fails, only the fixed list works and the item goes on as usual.
- **A Russian name in the middle of a post is a candidate** (KI-58): «Вчера вышла новая Дюна, и все рады» offers «Дюна». Such a candidate has the lowest weight, below quotes, bold and a kind word. Names of people and places («в Москве») can come up too; one «Нет» dismisses them.
- **Two Latin names read right** (KI-60): «from Software» drops its «from»; «Fallout: 76» keeps its number (an episode line «Bleach: 3 серия» stays an episode line).
- **A typo in an English name of a foreign series is corrected** (KI-61). «Dead-End Jb» finds «Работа с призрачными перспективами». The correction also looks at the English names of TMDb, only when nothing else matched, so a usual item costs no extra request.
- **A kind press tries the links again** (KI-62). A Steam link that IGDB could not look up a moment ago gives its card after «Игра».
- **«Что это?» is not lost to a restart** (KI-57). After a start, the bot asks about the items that got no question because the bot stopped in the 2-second pause. Only items of the last 12 hours: older ones are in «Входящие» «без ответа» anyway.
- **The time of a copy is the time of Settings** (KI-66): the Settings block, the restore list and the Google Drive line show one zone, the one chosen in Settings. Old copies keep their names and stay readable.
- **The Google Drive copy** keeps exactly 30 archives when the folder holds over 1000 files (KI-67). It also leaves no second archive of the same name (KI-68).
- **The restore no longer promises a copy that may not be made** (KI-69). The note of an older copy says: «Копия от более старой версии: при запуске база обновится сама.» The current base is saved by the restore anyway, and its line says so.
- **`.env` holds only what the app reads** (KI-49, decision 5 of the stage 9.1 description). The ticket removes six names from the owner's `.env` by name and never prints a value: `KINOPUB_ACCESS_TOKEN`, `PS_STORE_REGION`, `SHIKIMORI_CLIENT_ID`, `SHIKIMORI_CLIENT_SECRET`, `psn_api_key`, `rawg_api_key`. Their values are gone; no code ever read them. `.env.example` lists every variable the code reads.
- No new screens, so no mockups. Every other change is invisible: shorter modules, one test of size for the whole core, the export without a copy of the poller's rule, the Feed reading the seasons once.

## In scope · out of scope

In scope: the 18 entries below; the wishes of review 9.1c (F4, F5, `series_events.py` split); the wish of review 9.1b about `core.py`.

Out of scope: KI-15 and KI-70 (stage 7.3); KI-78, 79, 80, 82 (stage 9.2); new features; the cleanup of junk files in the repository root (stage 8). Candidates are not learned from the owner's answers. No AI (ADR 0010).

## Pulled-in `KNOWN_ISSUES.md` entries and review wishes

| KI | What | Direction of the fix |
|---|---|---|
| 49 | `.env` holds variables the code does not read | the six names removed from the owner's `.env` by name; `.env.example` complete |
| 56 | The size test misses the pure modules (`series_events.py` 547 lines, `games.py` 422, `cards.py` 400) | the test takes every module of `app/tracker/` with its subfolders; the long ones split |
| 57 | A restart within the 2-second pause leaves the item without «Что это?» | at start the bot asks about the items of the last 12 hours left without the question |
| 58 | A Cyrillic name in the middle of a post is not a candidate | capitalised Cyrillic words in the middle of a sentence, against a list of common words, the lowest weight |
| 59 | The stop list of candidates is a fixed list | decision 3: IGDB companies, one request per item; the fixed list stays for the rest and as the fallback |
| 60 | A Latin run keeps a leading «from»; a number after a colon is cut off | a leading «from» is dropped; `: <number>` is part of the name unless an episode word follows |
| 61 | A typo is not corrected when the source answers in another language | the English names of TMDb (`alternative_titles`), only when nothing else matched |
| 62 | A kind press does not look the links up again | `answer_kind` looks up the links of the chosen kind again |
| 63 | The Shikimori adapter is over 400 lines (481) and the size test does not see it | the season chain moves into a module of its own; every adapter in the size test |
| 64 | An offer of a title announced for a year or a quarter shows a made-up day | decision 1: the adapters say how precise the date is; «выйдет в 4 квартале 2027» |
| 66 | The time of a copy is the container's clock, not the zone of Settings | copies are shown in the zone of Settings; old names readable |
| 67 | A Drive folder of over 1000 files is listed only in part | the listing follows `nextPageToken` |
| 68 | A Drive archive of the same name but another size stays as a duplicate | the same-name file of another size is deleted after the upload |
| 69 | The note «ещё одна копия» of an older copy is not always true | the note drops the promise |
| 71 | The JSON export asks which titles are games | each poller gives the extra fields of its titles; `export_all` joins the size test |
| 81 | An anime premiere Shikimori knows by the month or the year stands on a made-up first day | decision 2: the precision kept with the premiere, shown as games show it; messages only for an exact day |
| 83 | An episode first seen with an AniList airing earlier than the previous look comes with no message | an episode not stored before with an airing from the 8-day window is news |
| 84 | A premiere moved by hours within its day reads «9 янв 2027 → 9 янв 2027» | equal days: the line shows the hours (`cards.format_episode_when`) |

Review 9.1c wishes: the Feed loads the seasons once and hands them to `feed_pieces` and `feed_released` (F4); a small enum for a film date in `feed_released` instead of its text (F5); `series_events.py` split, as KI-81, 83 and 84 touch it.

Review 9.1b wish: `app/tracker/core.py` has 490 of its 500 lines. If this stage adds facade methods (KI-57 may), it first moves a group of them out or trims the docstrings, not a new module per method.

## Decisions taken with the owner

1. **KI-64: an approximate date of an offer reads «выйдет в 4 квартале 2027»** (owner, 2026-11-23); likewise «выйдет во 2 квартале 2027», «выйдет в январе 2027», «выйдет в 2028». Rejected: the card's words without «выйдет» («4 квартал 2027»). The stage 9.1 description said «IV квартал»; the game card writes «4 квартал», and so does this stage.
2. **KI-81: an anime premiere known by the month or the year sends no message, as with games** (owner, 2026-11-23). It is shown in the card and the Feed; the message «объявлена дата» comes with the exact day. Rejected: a message for the approximate date and another for the exact day.
3. **KI-59: the companies come from IGDB** (owner, 2026-11-23): one request per item with the capitalised names of the post. Rejected: a big fixed list made once by the spec and grown in 9.2. What follows: one more request per item (the budget of spec 6.4, 5.5, becomes at most 11); without IGDB keys only the fixed list works; the spec checks live that small companies with names of games do not hide real titles.
4. **No wishes beyond the entries** (owner, 2026-11-23).
5. **Taken by the agent, confirmed by the owner's «ОК» of this description:**
   - the anime card says «часть 2 — в апреле 2027» / «— в 2027» for an approximate premiere; the Feed shows it like an approximate game date;
   - the update sends no message for the stored made-up days of premieres;
   - a Cyrillic candidate from the middle of a sentence has the lowest weight;
   - «Что это?» after a start only for items of the last 12 hours;
   - the copies are shown in the zone of Settings;
   - the restore note of an older copy drops the promise of a copy;
   - the six unread names are removed from the owner's `.env`, values not kept;
   - the code is split first, in its own ticket with no change of behaviour, then the fixes land in the small modules.

## Open questions for the spec

- KI-81, 64: where the precision of an anime premiere lives (one more `timing` value of migration 0017's column, or the premiere stub not stored and kept elsewhere), what the stored made-up stubs turn into at the first poll, and how the Feed, the card, the bot card and `message_announced` read it. One wording of an approximate date for the offer and the card, built from `games.GameDate` («в 4 квартале», «во 2 квартале», «в январе», «в 2028»).
- KI-83: the rule of news in `_newly_out` for an episode with an airing from the 8-day window, kept apart from the `history` of a new entry, so adding a title still sends nothing about its past.
- KI-84: the exact line when the days are equal, in the owner's zone.
- KI-59: the IGDB `companies` request (name matching, case, one request for all names of an item); how a company name is told from a game named the same (count of games published or developed, exact match only); what the request costs in the paced IGDB queue; answers saved next to the spec.
- KI-58: the list of common words that start a sentence or stand capitalised, and how a Cyrillic run ends.
- KI-61: what `alternative_titles` gives for the samples (answers saved), how many records it is asked for, and how it fits the budget of 5.5.
- KI-57: how the start finds the items without the question (the states and times of `inbox_items`), and that a question already in the chat is not asked twice.
- KI-62: the budget of 5.5 when a kind press looks up links again.
- KI-66: names in UTC with a marker, or the Settings zone read when a copy is made; how old names are read; `restore-bot.ps1` shows the same time.
- KI-67, 68: the Drive answers for a long folder and the delete of a same-name file.
- KI-49: whether `.env.example` gets `SHIKIMORI_BASE_URL` and `SHIKIMORI_USER_AGENT` (the code reads them; they are not in it today).
- KI-56, 63, 71: how `series_events.py`, `games.py`, `cards.py` and the Shikimori adapter split, the size test over every module, the poller action of the export; whether a facade group moves out of `core.py`.
- The ticket split. The agent's guess is five tickets: the code split with F4, F5 and KI-71; anime (KI-81, 83, 84); candidates (KI-58, 59, 60); offers and the bot (KI-57, 61, 62, 64); copies and `.env` (KI-49, 66–69). About 9 sessions in all with this one.
