# Spec 9.1c: Лента, web and login — the known issues

Status: in review

Built from `description.md` (accepted 2026-11-22). Terms come from `CONTEXT.md`. ADRs it leans on: 0004 (no own JavaScript: KI-72 and KI-74 stay within CSS), 0005 (SQLite, migrations: one migration, section 11), 0007 (one process: the sign-ins and the address are read once at start), 0014 (sign-ins in `data/web_login.json`: one more field, the same file and version — the ADR stands, no new one).

Live answers of 2026-11-22 are saved in `answers/` (section 12); the tickets copy what their tests need into `tests/fixtures/`. The owner's base was read (read-only) to fit the migration rule (section 11).

## 1. The moment of an episode (KI-28, KI-32, KI-77)

### 1.1 Where a moment comes from

Every stored episode keeps where its moment comes from — its **timing** (`EpisodeTiming`, column `episodes.timing`):

| Value | Meaning | Shown |
|---|---|---|
| `exact` | the source named the moment (AniList `nextAiringEpisode.airingAt` or an airing of section 1.5, Shikimori `nextEpisodeAt`) | the day and the hour on the owner's clock |
| `day` | the source knows the day only (TMDb `air_date`; the Shikimori premiere day of an entry); stored as 00:00 UTC of that day | the stored date as it is, no hour |
| `unknown` | the source gave no moment of this episode: the stored one is the moment of the check that found it, or the start day of its entry that Shikimori gives to every episode out | the day of the moment on the owner's clock, no hour |

`seasons.Episode` gets the field `timing` (default `exact`, so a test or a sample that builds `Episode(n, at)` keeps meaning what it meant); `None` `air_at` has no moment and its timing is never read.

Who sets what:
- **TMDb** (`sources/tmdb_series.py`): every dated episode `day`.
- **Shikimori** (`sources/shikimori_anime.part_episodes`): the episode `nextEpisodeAt` names — `exact`; the premiere stub of an announced entry (`airedOn`) — `day`; of the episodes out, the first of the entry is `day` when `airedOn` is known (its start day is the day of episode 1), every other one `unknown` (the start day is not its day; an entry with `releasedOn` alone gives `unknown` to all).
- **AniList** (`anime_events._scheduled`): the next episode with `airingAt` — `exact`; the next one known by number only takes Shikimori's moment with its timing; an episode out takes, in this order, its airing of section 1.5 (`exact`), Shikimori's moment when that one is out (with its timing), else the moment of this look (`unknown`).
- **`anime_events.assemble`** with something stored: an episode out now that was not stored keeps the fresh moment when it is `exact`, otherwise gets the moment of this look as `unknown` (today: always the moment of this look). The first recorded moment of an episode that is out stays with its timing; an episode of a new entry that was out by the previous look keeps its own moment and timing, as now.
- **`series_events.ShowState.keeping_known`**: an episode without a date in the fresh answer takes the stored episode whole (moment and timing).
- **`storage`**: `store_seasons` and `sync_seasons` write the timing wherever they write `air_at`; `load_seasons` and `load_seasons_of` read it.

### 1.2 How a moment reads

One rule, in one place (`cards`, next to `local_moment`): **the hour is shown only for an `exact` moment of a kind with local times** (`KINDS[…].local_times`: anime). The day of a moment: `exact` and `unknown` — the date on the owner's clock (a kind without local times: the stored date); `day` — the stored date as it is, never shifted by the zone.

The rule replaces the «exactly midnight UTC means the day only» guesses of the display:

| Place | Now | After |
|---|---|---|
| Лента, «Скоро» (`feed_rows.day_of`, `season_pieces`) | midnight UTC — the day without hour; any other moment — its hour | by timing: an episode at 00:00 UTC that AniList named — its hour on the owner's clock, «в 02:00» in Israel in winter (KI-28); a premiere known by the day — no hour, as now; an episode found by a check — no hour (KI-32) |
| web card and bot card: «…, следующая — пт, 9 янв в 03:00» (`cards.progress_line`) | the hour for every anime moment | «следующая — пт, 9 янв» for `day` and `unknown`; the hour for `exact` |
| the same: «часть 2 — с 27 марта», «Сезон 4 анонсирован, премьера 3 апреля 2027» | the date of the local moment | the day of section 1.2 (a `day` moment is not moved back a day west of UTC) |
| bot messages: «следующая: пн, 12 окт в 18:00» (`series_events._next_line`), «Премьера: …» (`message_announced`), the two days of «перенесена» (`message_moved`) | by midnight | by timing, the same rule |

So `seasons` hands out the next episode, not only its moment: `_EpisodeRun` gets `next_episode(now) -> Episode | None` and `first_episode() -> Episode | None` (`next_air_at`, `first_air_at` stay for the callers that need the moment alone), and `SeasonProgress.next_air_at`, `SeasonProgress.next_part_at` and `SeasonAnnouncement.first_air_at` carry an `Episode` (or are replaced by fields that do). `series_events._only_the_hour_learned` reads the timing (a `day` moment followed by an `exact` one of the same day is no move), with the same result for every stored episode. `series_events._moment_key` keeps its midnight rule: it makes the dedup keys of events already stored, and a changed key would queue a move again.

Series are not touched in what the owner sees: their kind has no local times, and the day of a `day` moment is the stored date, as now.

### 1.3 KI-77: the episode events of an anime carry their moment

`series_events._aired_at` gives `happened_at` = the moment of the episode when its timing is `exact` or `day`, and None when it is `unknown`. `Flavor.moments` goes (it said the same for a whole kind). The first check after «Вернуть в список» then reports an anime episode whose moment is later than the return (`Poller.record_all`, KI-23), like any other fact; an episode found by a check without a schedule stays silent in that check. With section 1.5 the window of KI-77 is closed for every anime AniList knows: the episode that came out a minute after the return has its airing moment.

A `day` moment is 00:00 UTC of its day: a premiere known by the day on the day of the return is earlier than the return and stays silent, as a film's release does (`movie_events`, `day_start`).

### 1.4 Examples

| Case | Stored | «Скоро» | Card |
|---|---|---|---|
| AniList: episode 4 at 2026-11-25 00:00 UTC, owner in Israel | `exact` 00:00 | «ср, 25 ноя» · «Сезон 3, серия 4» · «в 02:00» (UTC+2 in November) | «следующая — ср, 25 ноя в 02:00» |
| Shikimori only: episodes out grew from 6 to 7, check at 12:42 UTC | episode 7 `unknown` 12:42 | «Сегодня» · «Сезон 1, серия 7», no hour | — |
| Shikimori: the entry is announced for 2027-01-09 | episode 1 `day` 2027-01-09 00:00 | «сб, 9 янв» · «Сезон 4 — премьера», no hour | «Сезон 4 анонсирован, премьера 9 января 2027» |
| AniList: episode 8 came out at 14:00 UTC, the check at 14:37 finds it (section 1.5) | `exact` 14:00 | «Сегодня» · «в 16:00» | — |

### 1.5 The airings of the last days from AniList

AniList's schedule request (`AniListProvider.get_schedules`, packs of 50 ids) gets a second root in the same request:

```graphql
recent: Page(perPage: 50) {
  airingSchedules(mediaId_in: $ids, airingAt_greater: $since, airingAt_lesser: $until, sort: TIME_DESC) {
    mediaId episode airingAt
  }
}
```

`$since` = now − 8 days, `$until` = now (unix seconds). Checked live: one request with both roots answers `200`, and episode 8 of «Монолог фармацевта» (AniList 195516) came back at `1795183200` = 2026-11-20 14:00 UTC, the moment the base holds (`answers/anilist-recent-*.json`). The answer is the airings of the entries in the window, the latest first; `pageInfo` is not asked: past 50 the oldest are not there, and those are the least needed.

`sources/anilist_schedule` reads them strictly: an airing without an `int` `mediaId`, a positive `int` `episode` or an `int` `airingAt` is skipped; an airing of an id that was not asked is skipped. `PartSchedule` gets `aired: Mapping[int, datetime]` — the entry's own episode number to its naive UTC moment. An answer without `recent` or with a broken one gives every part `aired = {}`; the schedules are used as now. Numbers beyond the part's announced count are dropped (as `_usable` does for the rest).

What it gives: the episodes out at adding and at the first check after the return get their own moments when they aired in the last 8 days (section 2 needs them, KI-77 too), and an episode a check finds out gets the moment it aired instead of the moment of the check (KI-32 for every anime AniList knows). The Gotcha «Moments of aired anime episodes are unknown» of `PROJECT_CONTEXT.md` changes: they are known for 8 days for the entries AniList knows.

## 2. «Недавно» from the schedule (KI-29)

### 2.1 Which rows

Besides the events, «Недавно» gets a **row from the schedule** for what came out in its 7 days before the title's baseline and is not in the event log. Only titles that are not in the archive now; series, anime and movies; never games, never the films of an anime franchise.

- **An episode** of a series or an anime: dated, timing `exact` or `day`, out by now (`air_at` ≤ now), its day (section 1.2) within today − 6 … today, and before the baseline: `air_at ≤ titles.added_at` (**before adding**), else `titles.restored_at` is set and `air_at ≤ restored_at` (**in the archive**). An `unknown` episode never makes a row: its day is not known.
- **A film**: its theatrical or digital date (the dates the card shows) within the same 7 days and not after today, and `day_start(date) ≤ added_at` (before adding) or `≤ restored_at` (in the archive).
- **Not in the log**: an episode is in the log when an event of the title of type `series_season_started`, `series_episode_out` or `series_season_ended` (anime use the same types) with `payload.season` and `payload.episode` equal to its season and number was detected since today − 7 (one day more than the window, for the zones west of UTC); a film date is in the log when an event `movie_released` (theatrical) or `movie_digital` (digital) of the title was detected since then.

Nothing is queued and no message goes: the rows are made at each read of the Feed.

### 2.2 How a row reads

`{icon} {name} — {what}` and one grey line under it (the place of `details`):

| What | `{what}` (the pieces of «Скоро», `feed_rows`) | before adding | in the archive |
|---|---|---|---|
| one episode | «Сезон 2, серия 3» | «вышла до добавления в список» | «вышла, пока тайтл был в архиве» |
| several episodes of one part on one day | «Сезон 2, серии 3–5» | «вышли до добавления в список» | «вышли, пока тайтл был в архиве» |
| the first episode of a season or of a part 2+ | «Сезон 3 — премьера», «Сезон 3 — премьера, серии 1–2», «Сезон 3, часть 2 — премьера» | «вышла …» (one) · «вышли …» (several) | the same with «пока тайтл был в архиве» |
| a film in cinema | «Премьера в кино» | «вышла до добавления в список» | «вышла, пока тайтл был в архиве» |
| a digital release | «Цифровой релиз» | «вышел до добавления в список» | «вышел, пока тайтл был в архиве» |
| both on one day | «Премьера в кино и цифровой релиз» | «вышли до добавления в список» | «вышли, пока тайтл был в архиве» |

`{icon}` is the kind's (`KINDS[…].icon`), `{name}` the title's name as the Feed shows it. Example: «📺 Одни из нас — Сезон 2, серия 3» / «вышла до добавления в список».

The line «пока тайтл был в архиве» is this spec's: the description named only «до добавления в список», which would be untrue for a returned title (owner's check of this spec).

- **Folding**: the episodes of one part of one season of a title on one day with the same reason make one row (as «Скоро» cuts its pieces: `season_pieces` with the parts of the card). Different days — different rows.
- **The day**: the row stands on the day of section 1.2 (the source's schedule), not on the day it was found.
- **No hour, no buttons**: `RecentRow.at` is None for it (the type allows it), `watched` False, `follow` None. The row leads to the card, as every row.
- **Order in a day**: the event rows first, the latest first (as now), then the rows from the schedule by name (`text.key`), then by title id, then by season and first episode.
- **«За неделю ничего не случилось»** (the empty sentence of «Недавно») shows only when there are neither events nor rows from the schedule.

### 2.3 Reads

The pollers cut the rows, as they cut the pieces of «Скоро»: `Poller.feed_released(session, shown, basis, since)` (games and the default: none), `SeasonalPoller` from the stored seasons, `MoviePoller` from the own states. `FeedReader` reads the events of the window once more for the matching (types and ids only) — the number of reads stays independent of the number of titles. `added_at` and `restored_at` come with the titles already read. `feed_rows` gets the pure functions (`released_rows`: pieces, reason, folding, matching against the log), so the page compares neither kinds nor statuses.

## 3. One name per genre in the Archive filter (KI-30)

### 3.1 The table

An own table of synonyms in `genres` (no source): a genre's key (`key_of`: case and «ё» do not matter) to the genres it counts as.

| Written by the source | Counts as |
|---|---|
| «Экшен» (Shikimori) | «Боевик» |
| «Тайна» (Shikimori) | «Детектив» |
| «Боевик и Приключения» (TMDb, series) | «Боевик», «Приключения» |
| «НФ и Фэнтези» (TMDb, series) | «Фантастика», «Фэнтези» |
| «Война и Политика» (TMDb, series) | «Военный», «Политика» |

Every other genre counts as itself. Built from the live lists of 2026-11-22 (`answers/tmdb-genres-ru-*.json`, `answers/shikimori-*-genres-*.json`; IGDB has its own Russian already, `sources/igdb_games.GENRES`). Left apart on purpose: «Романтика» (Shikimori) and «мелодрама» (TMDb) — not one genre; «Детский» and «семейный»; «Мыльная опера». The merged genre is named by the TMDb word with a capital letter (`label`).

### 3.2 Where it applies

- `genres.merge` (the links of the genre row) and `genres.keys_of` (the match of a title) read every genre through the table. On the owner's base today: «Экшен» joins «боевик» as «Боевик», «Тайна» joins «детектив» as «Детектив», «НФ и Фэнтези» splits into «Фантастика» and «Фэнтези», «Боевик и Приключения» into «Боевик» and «Приключения». Choosing «Фэнтези» shows the series «НФ и Фэнтези» too.
- **The address**: `?genre=` is read through the table too: a synonym is its genre (`?genre=Экшен` is «Боевик», and the row marks «Боевик» chosen); a composite name is its first part (`?genre=НФ и Фэнтези` is «Фантастика»). An old bookmark keeps working.
- Not touched: the card and the Search show the genres as the source names them; nothing stored changes (no migration); the List has no genre filter.

The glossary entry «Жанр» changes (section 15).

## 4. Phone: the chosen filter first in its row (KI-74)

In `app/web/static/style.css`, inside the existing `@media (max-width: 40rem)` block of the filter rows (where `.filters` gets `flex-wrap: nowrap; overflow-x: auto`):

```css
.filters a[aria-current="true"] { order: -1; }
```

Every row of filter links (the «Список» rows of kind and status, the «Архив» rows of kind, genre, status and order) shows its chosen link first under 40rem; the row stays one line that scrolls sideways; on a computer the order is as now. No JavaScript (ADR 0004). The keyboard (Tab) still goes in the order of the page, not of the screen — acceptable for a phone, where nobody tabs. No markup change.

## 5. «Найти»: «Это оно — убрать запись» (KI-65)

The suggestions of the Search opened from an inbox item (`inbox=<id>`, an item that is there): a row whose title is in the list shows the link «В списке» (as now) and, after it, a plain form (no `hx-` attributes) `POST /inbox/<id>/remove` with the button **«Это оно — убрать запись»**. It is the route of «Убрать»: the item is deleted, the answer of a plain form is `303` to «Входящие»; the menu number follows by the page itself. An item gone already (removed in another tab, resolved by the bot) gives the same answer, as «Убрать» does. No notice (as «Убрать»).

The Search without `inbox` (or with a number that is no item) shows «В списке» only, as now. A row not in the list keeps «Добавить», which deletes the item after adding (as now). `suggestions.html` gets the item's address of «Убрать» from the page (`inbox_remove`), not built in the template. The «already in the list» branch of `add` stays (a race: the title added in another tab between the suggestions and the press).

## 6. The login report goes as soon as Telegram answers (KI-73)

The two report types (`login_events.TYPES`: `web_login`, `web_login_locked`) are taken out of the delivery rules for good, not only at the first send:

- every delivery pass (`deliver_pending`, every minute and the send at once) sends a queued report as its own message, first, whatever the rules — quiet hours, a work day before the summary hour, a pass in which the rules hold everything (`DeliveryRules.holds`);
- a report never joins a summary: «Сводка сейчас» sends the queued reports as their own messages before the summary;
- a report never expires (`delivery.expired` stays for discounts).

Where: `delivery.DeliveryRules.due` returns the reports in its first list (one by one) in every case; `DeliveryService.summary_now` sends them before the summary. The send at once of the web (`LoginReporter._send`) stays as it is.

**Never twice**: every pass runs under `delivery_lock`, and an event is marked delivered by the same step that saw its send succeed (`DeliveryService._send`); the send at once and the minute pass cannot both send one report. A send Telegram took but whose answer was lost may come again — as for every message (KI-78), nothing new.

Example: the network of the container is down, a login at 22:00, the network back at 22:40 — the report comes at 22:41 (the next pass), not at 07:30. The text still says «сегодня в 22:00»: it is made when the login is recorded. A report that waits past midnight says «сегодня» of the day before — new KI-82 (section 15).

## 7. The block «Вход» counts only sign-ins that still work (KI-75)

`data/web_login.json` gets a top-level field `mark`: 64 hex characters, HMAC-SHA256 with the key of `data/web_secret` over the text `web_login.json:` followed by `WEB_PASSWORD`. It changes when either the password or the key changes. It is not the fingerprint the cookie carries (`auth.fingerprint`, HMAC over the password alone): with the file and the key, nobody can make the `pw` of a cookie from it, and the password is never in the file.

At start (`SignIns(file, clock, mark=…)`, before the web serves anything):

| The file | What happens |
|---|---|
| no `mark` (a file of stage 7.2) | the current mark is taken; the sign-ins stay; the file is written at once with it (the update logs nobody out) |
| the same mark | as now |
| another mark | every sign-in is dropped (the last login and the lock count stay); the file is written at once with the new mark; a log line `WEB_PASSWORD или data/web_secret сменились: закрыто старых входов — N` |
| `mark` present but not 64 hex characters | the file is spoiled: empty with the warning, as now (strict reading) |
| no file, or a spoiled one | empty, as now; the mark goes into the first write |
| cannot be written at start | everything in memory until the restart, as now (`UNWRITABLE`) |

Only at start: the password and the key are read once, so they cannot change while the app runs. `VERSION` stays 1: an older app reading the file reads its named keys and ignores `mark` (a rollback keeps working). Without `WEB_PASSWORD` there is no file and no mark, as now.

So after a change of `WEB_PASSWORD` and `.\start-bot.ps1`, a new login on the PC gives «Вход открыт на 1 устройстве.»; «Выйти на всех устройствах» counts only the live ones; the cap of 20 holds only them.

## 8. `APP_URL` with a Cyrillic name (KI-76)

`config._host_reads`: a name with a character outside ASCII is turned into its ASCII form by IDNA with UTS 46 (the `idna` package, installed already as a dependency of `httpx`; `requirements.txt` and `pyproject.toml` name it, `idna>=3.4`), then passes the rules every name passes (a dot inside, not `localhost`). `https://Трекер.РФ` gives `https://xn--e1aaowdh.xn--p1ai`.

- `AppUrl.address` is the ASCII form: the bot's links, `AppLinks`, everything that uses the address.
- `AppUrl.host` is the ASCII host: `AllowedHosts` compares it with the `Host` header, which a browser sends in that form.
- `AppUrl.shown` (new) is the address as written, in lower case (`https://трекер.рф`); an ASCII address — the same as `address`. The Settings line uses it: «Адрес приложения: https://трекер.рф. Кнопки «Карточка» в сообщениях бота открывают его.»
- A name IDNA refuses (`idna.IDNAError`: a label too long, characters not allowed in a name) is malformed with the new reason **«имя сайта записано с ошибкой — проверьте буквы и точки»**. A Cyrillic name without a dot (`https://трекер`) keeps the reason of a Latin one (`_TELEGRAM_REFUSES`).
- Checked live 2026-11-22 (owner's yes): the bot sent the owner a message with a button to `https://xn----8sbnbaormzkdbdx.xn--p1ai/titles/1` (`пример-трекера.рф`); Telegram took it (`ok: true`) and kept the address as sent (`answers/telegram-xn-button-*.json`).

`docs/outside-access.md`, section 1: a Cyrillic name may be written as it is.

## 9. No change, with a test (KI-72, KI-48)

- **KI-72** (an iPad reads as «macOS, Safari») — **won't fix**: telling them apart needs JavaScript (ADR 0004). The test is there: `tests/test_web_devices.py::test_an_ipad_that_says_it_is_a_mac_reads_as_a_mac_known_issue_72`. Only the status changes.
- **KI-48** (season 4 of «Магическая битва» without data) — **won't fix**: checked live 2026-11-22, no source has data. Shikimori 63824 «Магическая битва: Смертельная миграция. Часть 2»: `status: anons`, `episodes: 0`, `airedOn` empty; AniList 209895: `NOT_YET_RELEASED`, `episodes: null`, no `nextAiringEpisode` (`answers/`). The card shows «Сезон 4 анонсирован, дата не объявлена», which is all that is known; it fills in by itself once a source has data. A test pins the card of an announced season without data from these two answers (the saved franchise of `tests/fixtures/shikimori/jujutsu_kaisen.json` with the part as answered now).

## 10. `core.py` (the wish of review 9.1b)

This stage adds no facade method: the Feed goes through `feed()`, the genres through `genres` and `list_titles`, «Это оно — убрать запись» through the route of «Убрать» (`forget_inbox_item`), the login report through `deliver_pending`; the sign-ins and the address live in the web and in `config`. `core.py` stays at its 490 lines. A ticket that finds it must add a method first moves the group of «Входящие» (the 7 inbox methods) out of the facade, as the wish says.

## 11. Data

**Migration 0017** `episodes.timing`: text, not null, values `exact`, `day`, `unknown` (stored as text like the other enums of the models). The copy goes to `data/backups/` first, as for every migration. Filling the existing rows:

| Rows | Value |
|---|---|
| episodes of a series | `day` |
| episodes of an anime with no `air_at` | `unknown` |
| anime, `air_at` with seconds or microseconds (the moment of a check) | `unknown` |
| anime, `air_at` at 00:00:00 UTC: the lowest number of the season with that moment | `day` |
| anime, the other episodes of the season with the same 00:00:00 moment (Shikimori's start day given to every episode out) | `unknown` |
| anime, any other moment | `exact` |

Fitted on the owner's base (2026-11-22, migrations up to 0016): 1446 anime episodes — 1440 at 00:00 (1437 of them sharing one moment with others of their season: «Ван-Пис» has 1180 episodes on 1999-10-20), 6 on a whole minute (AniList: «Монолог фармацевта» season 3, episodes 5–9, at 14:00; «Ван-Пис» 1181 at 14:16), none with seconds; 185 series episodes, all at 00:00. A lone anime episode at 00:00 becomes `day` — the KI-28 case cannot be told from a premiere day in old data, and `day` shows what it shows now. Downgrade drops the column.

The JSON export (7.1) does not carry `timing`. A restore of an older copy runs the migration and fills it by the same rule.

**`data/web_login.json`**: the field `mark` (section 7).

Nothing else is stored: the rows from the schedule are read at each Feed (section 2), the genre table is code (section 3).

New and changed code (rule 7, each module under 400 lines): `seasons` (`EpisodeTiming`, `Episode.timing`, `next_episode`, `first_episode`), `cards` (the rule of 1.2), `feed_rows` (the rows of section 2; it has 292 lines: if they push it past 400, they go to a module `feed_released`), `genres` (the table), `sources/anilist_schedule` (`aired`), `delivery` (the report types), `web/sessions` (`mark`), `config` (IDNA, `shown`).

## 12. External services

| Service | Request | Limits, failures | Checked live 2026-11-22 (`answers/`) |
|---|---|---|---|
| AniList | the schedule request gets the root `recent` (section 1.5); the same request, so no more requests and the same ~90 per minute | a broken or missing `recent` — no airings, the schedules as now; a failed request — as now | `anilist-recent-request.json` (the request: 7 real ids and one unknown), `anilist-recent-2026-11-22.json` (`200`; 195516 episode 8 at 2026-11-20 14:00 UTC; 209895 no data) |
| Shikimori | none new | — | `shikimori-jjk-s4-and-genres-2026-11-22.json` (63824 announced without data; the Russian genre list), `shikimori-premiere-precision-2026-11-22.json` (an announced part gives `airedOn` with `day: null`, sometimes `month: null`: KI-81) |
| TMDb | none new | — | `tmdb-genres-ru-2026-11-22.json` (`/genre/movie/list` and `/genre/tv/list`, `ru-RU`) |
| Telegram | none new | — | `telegram-xn-button-2026-11-22.json` (a button to an `xn--` address taken) |

The requests of the check went with a generic `User-Agent`; the owner's data went nowhere.

## 13. Edge cases

| Case | Behaviour |
|---|---|
| AniList names an episode at 00:00 UTC | `exact`: «в 02:00» / «в 03:00» on the owner's clock (KI-28) |
| an old anime episode at 00:00 that was a real AniList moment | `day` by the migration: no hour, as now; the next episodes are stored with their timing |
| a premiere known by the day, owner west of UTC | the day is the source's date (not the day before) in the Feed, the card and the bot |
| an episode found by a check of an anime AniList does not know | `unknown`: «Сегодня», no hour; no row from the schedule; silent in the first check after a return |
| AniList's `recent` has more than 50 airings in a pack | the oldest are missing: those episodes take the moment of the check (`unknown`) |
| AniList numbers an entry on through the season | `_usable` drops the schedule, and with it the airings |
| an episode of the last 7 days out before adding, and the title was returned later | «до добавления в список» (the first reason wins) |
| an episode reported, the title archived, then returned within 7 days | its event is in the log: an event row, no row from the schedule |
| a title deleted and added again | a new title id: its old events are not its own; the episodes of 7 days before the new adding are rows from the schedule |
| Shikimori renumbers the seasons after an event was logged | the event's `payload.season` is the old number: the episode may show both as an event row and a row from the schedule for up to 7 days (rare: a regrouping within a week of a release) |
| a series whose TMDb date is today, added at 10:00 | out at adding (00:00 ≤ 10:00): a row «вышла до добавления в список» today |
| a title in the archive now | no rows from the schedule (its events still show, as now) |
| a game | no rows from the schedule |
| `?genre=Экшен` from an old bookmark | «Боевик», chosen in the row |
| a genre written «экшен» in lower case | the table works by key: «Боевик» |
| «Это оно — убрать запись» pressed after the item was removed elsewhere | the same answer: «Входящие» without it |
| Telegram down from 22:00 to 08:00 | the report goes at the first pass after 08:00, as its own message, never in the summary |
| a report queued before this update, still waiting | goes at the next pass after the update, whatever the rules |
| `WEB_PASSWORD` changed back to the old one | the mark differs from the stored (new) one only if the key changed; the same password and key give the same mark: nothing dropped beyond what the first change dropped |
| `data/web_secret` deleted | a new key: another mark, every sign-in dropped at start (the cookies stopped working anyway) |
| `web_login.json` with `mark` read by the app of stage 7.2 (rollback) | `mark` ignored, everything else as it was |
| `APP_URL=https://ТРЕКЕР.РФ:8443` | IDNA lowers the case: address `https://xn--e1aaowdh.xn--p1ai:8443`, Settings shows `https://трекер.рф:8443` |
| `APP_URL=https://трекер` | no dot: «Telegram не открывает такие ссылки — …» |
| `APP_URL` with a name IDNA refuses (a label over 63 characters) | «имя сайта записано с ошибкой — проверьте буквы и точки» |

## 14. Tests

Automated:
- **Timing**: the adapters set it (TMDb `day`; Shikimori `exact` / `day` / `unknown` on the saved franchises; AniList `_scheduled` with and without airings); `assemble` keeps a stored moment with its timing, gives the fresh `exact` moment to an episode found now, `unknown` otherwise; `keeping_known` keeps both.
- **The migration** on a base with every row of the table of section 11 (a season of One Piece-like shared moments, a lone 00:00, a whole minute, a moment with microseconds, a series, `NULL`), upgrade and downgrade.
- **Display**: `day_of` by timing (KI-28: 00:00 `exact` shows the hour; KI-32: `unknown` none); `progress_line`, `announced_line`, the part line, `_next_line`, `message_announced`, `message_moved` for `exact` / `day` / `unknown`, a zone east and west of UTC; series unchanged (their existing tests pass untouched).
- **KI-77**: the first check after a return reports an anime episode with an `exact` moment after the return; keeps silent for `unknown`; `_only_the_hour_learned` and `_moment_key` give the old results on old data.
- **AniList airings**: parsing the saved answer; a broken node skipped; no `recent` → `{}`; an unknown id skipped; the request carries `$since` and `$until`.
- **«Недавно» from the schedule**: each row of 2.2 (one, several, premiere, part 2, film, digital, both; before adding and in the archive), folding by part and day, the matching against the log (an episode with an event shows once), the window edges (today − 6 in, today − 7 out; an episode after now out), `unknown` out, archive titles out, games out, the order in a day, the empty sentence; the number of reads does not grow with titles (`test_the_feed_reads_as_much_for_one_title_of_each_sort_as_for_fifty` keeps passing with the rows from the schedule in it).
- **Genres**: the table (synonym, composite, case and «ё»), `merge` and the match on the owner's mix (the list of section 3.2), the address read through the table, the card unchanged.
- **KI-74**: a new test reads `style.css` and finds the rule inside the `max-width: 40rem` block (none reads the CSS yet; a live look at 375 px in the browser pane by the ticket session as well).
- **KI-65**: with `inbox` and a title in the list, the row has «В списке» and the form to `/inbox/<id>/remove` with «Это оно — убрать запись», without `hx-`; without `inbox`, no form; the press deletes the item and answers `303` to «Входящие»; an item gone — the same.
- **KI-73**: `due` gives a report in quiet hours, on a work day before the summary hour and when the rules hold everything; never in a summary; «Сводка сейчас» sends it apart; a failed send is retried at the next pass; the send at once and a pass together send it once.
- **KI-75**: every row of the table of section 7; the mark is neither the password nor the cookie fingerprint; `count` after a mismatch.
- **KI-76**: Cyrillic name, upper case, with a port, without a dot, refused by IDNA, mixed ASCII; `shown` in the Settings line; `AllowedHosts` takes the `xn--` host.
- **KI-48**: the card of the announced season without data (section 9).

The owner checks live (the ticket sessions write the steps): the Feed on the PC and the phone (an anime episode hour, a row «вышла до добавления в список» after adding a running series), the Archive genre row, the chosen filter on the phone, «Это оно — убрать запись», the block «Вход» after a password change. KI-73 and KI-76 are checked by the sessions (stopping the network and a Cyrillic `APP_URL` are not the owner's work).

## 15. Docs, terms, ADR, known issues

- `CONTEXT.md`: **Серия** — a sentence on the moment («точное время», «только день», «неизвестно») and `In code: EpisodeTiming (episodes.timing)`; **Жанр** — synonyms of different sources are merged by an own table in the Archive filter, a composite TMDb genre counts under each part; the card keeps the source's names; `In code: genres.SYNONYMS`; **Лента** — «Недавно» also shows what came out before adding or while in the archive (rows from the schedule, no buttons); **Сообщение о входе** — «one that failed to send goes at the next delivery pass, whatever the rules» instead of the KI-73 sentence; **Вход** — the file keeps a mark of the password and the key, a change of either ends the sign-ins at start; **Адрес приложения** — a Cyrillic name is taken.
- `PROJECT_CONTEXT.md`: the Gotcha about the moments of aired anime episodes (section 1.5); the `APP_URL` row (a Cyrillic name).
- `docs/outside-access.md`, section 1 (section 8).
- No new ADR: nothing here is hard to reverse or a real trade-off beyond what the sections say; ADR 0014 stands (section 7).
- `KNOWN_ISSUES.md`: KI-28, 29, 30, 32, 65, 73, 74, 75, 76, 77 → `fixed (test: …)` by their tickets; KI-48, KI-72 → `won't fix (test: …)`. New entries, written in this session:
  - **KI-81** — anime: a premiere Shikimori knows by the month or the year only stands on a made-up first day («часть 2 — с 1 апреля», «1 января 2027» in «Позже»); `airedOn.day` (and `month`) is null in the answer (`answers/shikimori-premiere-precision-*.json`). Fix with KI-64 (the same Shikimori day), 9.1d.
  - **KI-82** — a login report that waits past midnight says «сегодня» of the day before (the words are made when the login is recorded). Very rare after KI-73; 9.2.

## 16. Proposed tickets

| # | Ticket | Sections | Complexity | Blocked by |
|---|---|---|---|---|
| 01 | The moment of an episode: migration 0017, `EpisodeTiming` through the adapters, `assemble`, `keeping_known` and `storage`; the rule of 1.2 in the Feed, both cards and the bot messages (KI-28, KI-32); `happened_at` by timing, `Flavor.moments` gone (KI-77); the KI-48 card test | 1.1–1.4, 9 (KI-48), 11 | complex | — |
| 02 | AniList airings of the last 8 days: the root `recent`, `PartSchedule.aired`, `_scheduled` and `assemble` take them; the Gotcha | 1.5, 12 | medium | 01 |
| 03 | «Недавно» from the schedule (KI-29): `Poller.feed_released` for series, anime and movies, the pure rows in `feed_rows`, the matching against the log, the order and the template (the grey line, no hour) | 2 | complex | 01 |
| 04 | Web: the genre table in the Archive filter (KI-30), the chosen filter first on the phone (KI-74), «Это оно — убрать запись» (KI-65) | 3, 4, 5 | medium | — |
| 05 | Login and address: the report outside the rules (KI-73), the mark of the sign-ins (KI-75), `APP_URL` with a Cyrillic name (KI-76); KI-72 won't fix; the glossary entries of the three | 6, 7, 8, 9 (KI-72) | medium | — |

Order: 01 first; 02 and 03 after it in either order (02 makes 03 fuller for anime, 03 tests with fakes and does not wait for it); 04 and 05 touch other modules and may go at any point. Sessions after this one: slicing 1, tickets 5, review 1 — 7 (the description's 5–6 for the whole stage becomes 8 with this spec: the moment of an episode and the airings are one complex ticket and one medium more than planned).
