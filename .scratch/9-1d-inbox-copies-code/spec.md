# Spec 9.1d: «Входящие», copies and code health — the known issues

Status: accepted

Built from `description.md` (accepted 2026-11-23). Terms come from `CONTEXT.md`. ADRs it leans on: 0005 (SQLite, migrations: two small migrations, section 12), 0007 (one process: the bot asks its unanswered item at start, section 9), 0010 (the bot takes posts and names by rules, no AI: the companies of IGDB are one more rule, not a model), 0012 (Drive copies through its API with the owner's client: section 10 stays within the same calls). No ADR is contradicted; no new ADR (section 16).

Live answers of 2026-11-23 are saved in `answers/` (section 13); the tickets copy what their tests need into `tests/fixtures/`. The owner's base was read (read-only): `inbox_items` is empty; three anime have a premiere on a made-up first day (section 4.6).

## 1. The code split (KI-56, KI-63, the wish on `core.py`)

No change of behaviour: the same tests pass with their imports changed. Callers import from the new modules; no module re-exports what moved out of it.

### 1.1 The size test covers every module

`tests/test_tracker_core_split.py`: `test_no_part_of_the_core_is_longer_than_the_limit` takes **every** `app/tracker/**/*.py` except `core.py` (its own limit), `migrations/` and `__init__.py`, found by a glob, not by a list. `MODULES` stays for the test of the kind question; `export_all` joins it (section 2.1). `PURE` gets the new pure modules (`release_dates`, `series_messages`, `sources/shikimori_chain`, `offer_cards`, `candidate_words`). Rule 7 of `docs/coding-standards.md` keeps its text; its "Check" names the glob.

### 1.2 What moves

| From (lines now) | Moves out | Into (new) | What stays |
|---|---|---|---|
| `series_events.py` (547) | `Flavor`, `message_*`, `_total_text`, `_next_line`, `TEST_SAMPLES`, `sample_episode_events` and their samples | `series_messages.py` — the texts of the series events and their samples of «Тестовое событие» | the detection, the keys, `check_interval` (~330) |
| `games.py` (422) | `GameDate` renamed **`ReleaseDate`**, `NOT_ANNOUNCED`, `NOT_ANNOUNCED_LABEL`, the IGDB `date_format` constants, `_whole`, the month names | `release_dates.py` — a release date that may be approximate: a day, a month, a quarter or a year | the game state, the platforms, the intervals (~260) |
| `cards.py` (400) | `format_date`, `format_short_date`, `format_weekday_date`, `format_day_month`, `format_past_moment`, `local_moment`, `episode_when`, `format_episode_when`, the month and weekday tables | `moment_words.py` (exists, 25 lines) — dates and moments in words | the card (~310) |
| `sources/shikimori_anime.py` (481) | `collect_entries`, `chain_order`, `_is_season`, `_continues_season`, `group_seasons`, `_day`, `part_episodes`, `build_season`, `build_snapshot`, `assign_anilist_ids` | `sources/shikimori_chain.py` — the franchise built from the chain of entries | parsing, suggestions, the source class (~300) |
| `offers.py` (365) | `Offer`, `offer_of`, `released_line`, `card_text`, `shown`, `HEADING`, `CORRECTED`, `NO_DATE` | `offer_cards.py` — an offer as the item keeps it and the text of its card | the searches (~280) |
| `candidates.py` (333) | `STOP_NAMES`, `_KIND_WORDS`, `_MARKERS` (the word lists) | `candidate_words.py` — the word lists of the candidate rules | the rules (~290) |

`ReleaseDate` keeps the methods of `GameDate` (`parse`, `from_igdb`, `announced`, `exact`, `text`, `label`, `start`, `end`); its 85 uses are renamed. `games.released_by` stays in `games.py`.

### 1.3 `core.py`

490 of its 500 lines. The ticket shortens the facade docstrings that retell their part (the part's method keeps the detail) to at most two lines each, so `core.py` is **at most 470 lines**; no method moves out (the facade stays the only door). The facade grows by two lines of assembly (section 7.4) and one method (section 9).

## 2. Code health without a visible change (KI-71, F4, F5)

### 2.1 KI-71: the export asks the pollers

`Poller` gets the action `export_extras(session, title_ids) -> dict[int, dict[str, Any]]`, default `{}`. `GamePoller` answers `{title_id: {"expansion_of": <name>}}` for its expansions, by its own `parent` (the name in the list when the list has the base game — `known_ids`, else the name IGDB gave); a state that cannot be read leaves the game out with the warning of today. `export_all` asks the poller of every kind present (`Pollers.reader_of`) and puts the fields into the title's object; `_parents` and its query go. `Exports` gets `pollers` in the assembly. `export_all` joins `MODULES`; the test of the kind question passes. The JSON is byte for byte the same on the same base (a test compares the document before and after on a sample base).

### 2.2 F4: the Feed reads the seasons once

The two poller actions `feed_pieces` and `feed_released` become one, `feed(session, shown, basis, now) -> FeedParts` (`pieces`, `outs`); the base default gives both empty; the seasonal poller reads `storage.load_seasons_of` once and cuts both from it; movie, game and anime (its films) pieces as now. `FeedReader` calls it once per kind. The test of the set of actions lists `feed` instead of the two.

### 2.3 F5: a film date is an enum

`feed_released.Out.film: str` becomes `film: FilmDate | None` (`FilmDate.THEATRICAL`, `FilmDate.DIGITAL`, a `StrEnum` in `feed_released`); the texts «Премьера в кино», «Цифровой релиз» stay in `feed_rows` and are read through a table `FILM_LABELS`. The verb («вышла» / «вышел») is chosen by the enum.

## 3. An approximate date in words (shared by sections 4 and 8)

`ReleaseDate` gets one property more, **`phrase`**: how a date reads inside a sentence.

| Date | `label` (exists: card, «Позже») | `phrase` (new) |
|---|---|---|
| a day | «12 февраля 2027» | «12 февраля 2027» |
| a month | «январь 2027» | «в январе 2027» |
| a quarter | «4 квартал 2027» | «в 4 квартале 2027»; quarter 2: «во 2 квартале 2027» |
| a year | «2028» | «в 2028» |
| not announced | «дата не объявлена» | «дата не объявлена» |

The months in the prepositional case: январе, феврале, марте, апреле, мае, июне, июле, августе, сентябре, октябре, ноябре, декабре. «во» only before «2» («во втором»); 1, 3, 4 take «в».

`ReleaseDate.of_day(day)` makes a day; `ReleaseDate.of_period(start, timing)` makes a month or a year from the first day of its period (section 4.2).

## 4. Anime: a premiere known by the month or the year (KI-81)

### 4.1 What Shikimori says

`airedOn { date year month day }` (the answer of 9.1c, `shikimori-premiere-precision-2026-11-22.json`): `day` null — the month is known (`date` is its first day); `month` null too — the year alone (`date` is 1 January). The provider asks `airedOn { date year month day }` wherever it asks `airedOn` (the entries, the search, the lookup by id). `Entry` keeps `aired_on: date | None` as today (the order of the chain, the history rule) and gets **`aired: ReleaseDate`** — the day, the month or the year as Shikimori knows it (`NOT_ANNOUNCED` without `airedOn`). Garbage in `year`/`month`/`day` (out of range, not a number) is read softly: the precision falls to what is sure (no year — `NOT_ANNOUNCED`; a bad day — the month; a bad month — the year).

### 4.2 The approximate premiere stub

`EpisodeTiming` gets two values: **`month`** and **`year`** — the premiere of an announced entry known only by its month or year. Stored in `episodes.timing` (text, 16 characters; no schema change) with `episodes.air_at` = 00:00 UTC of the first day of the period.

In memory such an episode has **no moment**: `seasons.Episode(number, air_at=None, timing=MONTH|YEAR, rough=ReleaseDate(...))`. The new field `rough: ReleaseDate | None = None` holds the period; it is set only for these two timings. So every rule that reads moments treats the stub as undated, as it should be for an approximate date (CONTEXT, «Примерная дата»: seen, no messages):
- the season stays announced, the stub is never out (`released`, `status`), whatever the clock says — today a made-up 1 April turns «out» on 1 April and would send «начался сезон»;
- no next episode, no move, no «объявлена дата», no `check_interval` effect (an announced anime is looked at daily, `INTERVAL_WAITING`);
- `feed_released` and «Недавно» never see it.

`storage` is the one place that turns one into the other: `store_seasons` and `sync_seasons` write `air_at = rough.start` at 00:00 and the timing; `load_seasons` and `load_seasons_of` read a `month` or `year` row into `Episode(number, None, timing, ReleaseDate.of_period(air_at.date(), timing))`.

Who makes it — `shikimori_chain.part_episodes`:
- an announced entry with no episode out and no `nextEpisodeAt`: `aired.exact` — the stub of today (`day`); a month or a year — the approximate stub; no `airedOn` — no stub, as now;
- the episodes out of an entry whose `aired` is not exact all get `unknown` (none gets `day`: the first of a month is no day of episode 1).

### 4.3 What a fresh approximate stub does to what is stored

- `anime_events.assemble`: as now; the stub has no moment, so the loops over the episodes out skip it.
- `series_events._keep_season` (the gaps of an answer are not news): a fresh episode without a moment takes the stored one whole — **unless it is an approximate stub**: an approximate date is something the source said, not a gap. So the stored made-up day of a premiere (`day`, the 1st of a month, written before this stage) is replaced by the stub at the first look after the update, and so is a real day if Shikimori ever falls back to the month (the source's word is taken; no message).
- No event comes of either change: the move needs a dated fresh episode (`_moved` skips an episode without a moment), the announcement a dated first episode.

### 4.4 The day announced after an approximate date

When the exact day comes, the season (or part) had no dated first episode at the previous look, so «объявлена дата … Премьера: 9 апреля 2027» is queued, as for any first date (CONTEXT: messages come only about an exact day). Its key: when the previous look had an approximate stub for that season or part, `dedup.moved_key("<season key>[:p<n>]:date_announced", observed_at)`, so a message about a made-up day sent before this stage (whose key is the plain one) does not swallow the real one; a repeat after a failed save is seen from the same look and dropped. Otherwise the plain key, as now.

### 4.5 How it reads

The one place is `cards` with `moment_words`; the approximate stub is reached through a new `_EpisodeRun.premiere() -> Episode | None`: the first dated episode, else the approximate stub, else None. `SeasonAnnouncement.premiere`, `SeasonProgress.next_part_start` and `message_part_ended` (the part that follows) read `premiere()` instead of `first_episode()`; the events keep `first_episode()`.

| Place | Exact day (as now) | Approximate (new) |
|---|---|---|
| card, bot and web: the next part (`progress_line`) | «Сезон 3, часть 1: вышло 12 из 12; часть 2 — с 9 января» | «…; часть 2 — в январе 2027», «…; часть 2 — в 2027» |
| card: an announced season (`announced_line`) | «Сезон 4 анонсирован, премьера 9 января 2027» | «Сезон 4 анонсирован, премьера в январе 2027» / «… премьера в 2027» |
| message «закончилась часть» (`message_part_ended`) | «…; часть 2 — с 9 января» | «…; часть 2 — в январе 2027» |
| Лента, «Позже» (`feed_rows.season_pieces`) | the day | the piece stands on the last day of its period (`rough.end`), `when` = `rough.label` («январь 2027», «2027»), never in «Скоро» — as an approximate game date; only while `rough.end` is today or later |
| JSON export, an episode | `"air_at": "<moment>"` | `"air_at": null, "approximate": "2027-01"` (or `"2027"`, `ReleaseDate.text`) |

A helper in `cards`, `premiere_words(episode, tz) -> str`, gives «с 9 января» / «в январе 2027» for the next part and the message, and `announced_line` uses «премьера 9 января 2027» / «премьера в январе 2027» (`ReleaseDate.phrase`).

### 4.6 The owner's titles now and the first look after the update

On 2026-11-23 the owner's base has three anime with such a premiere (read-only): «Ванпанчмен» season 3 part 2 (2027-01-01, month only in Shikimori), «Реинкарнация безработного…» season 3 part 2 (2027-01-01, the year only), «Монолог фармацевта» season 3 part 2 (2027-04-01, month only).

**Migration 0018** (data only) sets the time of the next check of the Shikimori snapshot of every anime title to the moment of the migration, so the first polling pass after the start (within a minute) reads their premieres again and stores the stubs; nothing else changes. Downgrade: nothing to undo. The stubs cannot be told from real first-of-month days by the base alone, so no row is rewritten by the migration itself.

## 5. Anime: an episode first seen after a bulk drop (KI-83)

`anime_events.assemble` returns `Assembled(seasons, late)` instead of the tuple of seasons. `late` holds `(season number, episode number)` of every episode that, with something stored:
- was not stored, or was stored without a moment;
- is out now with an `exact` moment that is **not later than the previous look** (`observed_at`);
- is not in an entry the title never had (`history`: those stay history, as now).

It is the branch where `assemble` keeps a fresh exact moment of an episode found out now (spec 1.1 of 9.1c). At adding (`previous` is None) `late` is empty.

`series_events.detect_events(..., late: Collection[tuple[int, int]] = ())` hands it to `_newly_out`: an episode of `late` is news even though its moment is behind the previous look. Its event carries that moment as `happened_at` (`exact`), so the first check after «Вернуть в список» reports it only when it aired after the return (KI-23). Series pass nothing: a TMDb episode listed late with an old date stays a backfill of history.

The case of the KI (review probe of 9.1c): look 13:00 stores episode 7 at 14:00; look 14:30, AniList still says 6 out; look 20:00, AniList says 9 out with airings of 8 and 9 at 14:00. Now: «вышла серия 8» and «вышла серия 9» (or one line in a summary), both `happened_at` 14:00 UTC; before: nothing.

## 6. Anime: a premiere moved by hours (KI-84)

`series_messages.message_moved` with `premiere=True`: when the two days (`flavor.day`) are equal, each side gets its hour on the owner's clock where it has one: «🎌 Магическая битва — премьера сезона 4 перенесена\n9 янв 2027, 18:00 → 9 янв 2027, 19:00». Different days stay «9 янв 2027 → 16 янв 2027».

`_moved`: equal days where one side has no hour (a `day` or `unknown` moment and an `exact` one) is no move, both ways — today only `day` → `exact` is excused (`_only_the_hour_learned`); an `exact` premiere that falls back to Shikimori's day of the same day would read «9 янв 2027 → 9 янв 2027». Series: both sides `day`, so equal days mean equal moments, as now.

## 7. Candidates (KI-58, KI-60, KI-59)

### 7.1 KI-58: a Russian name in the middle of a sentence

A new rule of `candidates`, the **middle name**: a run of capitalised Cyrillic words (each starts with `А–Я Ё І Ї Є Ґ` followed by lower-case letters, so «АНОНС» is no name), one space between them, at most 4 words; it ends at a word in lower case, punctuation, a digit or a Latin word.

Not a middle name:
- the first word of a sentence: the start of a line (after leading emoji, dashes, quotes and spaces), or after `.`, `!`, `?`, `…` and spaces — a capital there is no sign of a name; the run then starts at its second word, if any;
- a run inside a quote, a bold piece or a Cyrillic name after a kind word (those rules have it, with their weights);
- a run right after a marker (`_MARKERS`: «из», «от», «студия», «после»…);
- a word of `COMMON_WORDS` (in `candidate_words`): Вы, Вас, Вам, Вами, Ваш, Ваша, Ваше, Ваши, Вашего, Вашей, Вашу, Вашим, Ваших, Бог, Бога, Богу, Господь, Господи, Боже, Интернет, Интернете, the months and the days of the week in the nominative and the genitive («Январь», «Января», …, «Понедельник», «Понедельника», …), Новый, Новый год, Рождество, Рождества, Пасха, Хэллоуин. Such a word ends the run (a run of one such word is nothing).

Weight **`MIDDLE = 2`** — below a quote (3), bold (8), a Cyrillic name after a kind word (5) and a Latin run (6); the fallback (1) and a quote after a marker (0.5) stay lower. A repeat adds `REPEAT_BONUS` as for any name found again. Names of people and places («Москве», «Илон Маск») come up too; one «Нет» dismisses them, and with a Latin title of weight 10 they are not searched at all (half of the first one's weight, `searched`).

Examples: «Вчера вышла новая Дюна, и все рады» → «Дюна» (2); «Смотрю Мастер и Маргарита вечером» → «Мастер», «Маргарита» (each 2; «Смотрю» starts the sentence); «Новый трейлер Дюны» → «Дюны» (2: «Новый» starts the sentence and is a common word, «трейлер» is in lower case).

### 7.2 KI-60: «from» and a number after a colon

- A Latin run whose first word is «from» (any case) loses it; the rest is weighted as a run after a marker (`AFTER_MARKER_PENALTY`; a kind word before «from» no longer counts: «from» stands between). «Игра from Software вышла вчера…» → «Software», low; a run of «from» alone is nothing.
- `: <number>` joins a run unless the number is followed by an episode word (`сери…`, `сері…`, `епізод…`, `эпизод…`, `episode`, `ep`, any case): «Вышел Fallout: 76 вчера…» → «Fallout: 76»; «Bleach: 3 серия» stays the episode line with «Bleach».

### 7.3 KI-59: the companies of IGDB

After the rules, before the searches (`OfferSearch.by_kind` and the candidate part of `by_links`), the candidates are asked about once per analysis: **which of them are companies**. Asked: the first 10 candidates by rank that have a Latin letter, except a name message (`WHOLE`: the owner typed that name on purpose) and a name Steam gave a link; a name with `"` or `\` is not asked. None to ask — no request.

The request (`IgdbGameSource.companies(names) -> frozenset[str]`, the name keys that are companies; the provider gets `companies(body)` on `/companies`, at once, like the search):

```text
fields name,developed,published;
where name ~ "Ubisoft" | name ~ "Ubisoft Entertainment" | name ~ "Ubisoft Studios" | … ;
limit 500;
```

For every asked name: the name itself and the name followed by each word of `COMPANY_WORDS` = Entertainment, Studios, Studio, Games, Softworks, Interactive, Productions, Software, Publishing, Digital, Inc. — `~` is equality without case (checked live: `name ~ "Marvel"` found «marvel», `name ~ "CD Projekt Red"` found «CD Projekt RED»; an array after `~` is refused with 400, so the names are joined by `|`). A name is a company when one of its answers has made **at least 20 games** (`len(developed) + len(published) >= COMPANY_GAMES`, 20): small studios named like games do not hide them.

Live (`answers/igdb-companies-*.json`): Ubisoft (as «Ubisoft Entertainment», 1362), Mojang («Mojang Studios», 202), Remedy («Remedy Entertainment», 53), Bethesda («Bethesda Softworks», 379), Blizzard, Capcom, FromSoftware, Valve, Netflix, Rockstar («Rockstar Games») are companies; Control («Control Entertainment», 9), Halo («Halo Studios», 17), Portal («Portal Studios», 4), Hades («Hades Productions», 2), Metro (13), Arcane («Arcane Raise», 11), Marvel («Marvel Games», 16), Dune, Doom, Fallout, Batman, Witcher, Frostpunk, Silksong, Elden Ring are not. «Ubisoft» alone is no company name in IGDB — so the variants.

A company is dropped from the candidates before `searched` picks the ones to search, so the next name moves up. No IGDB keys (`SourceNotConfigured`), a failure or a 429 of this request: the warning goes to the log and the candidates stay as the fixed list left them; the analysis goes on as usual. The fixed list (`STOP_NAMES`) stays and grows by what IGDB does not know: Crunchyroll, Kinopoisk, Кинопоиск, Okko, Иви, Wink, Amediateka, Prime Video, Apple TV, Hulu, Paramount+, Game Pass, PS Plus, Gamescom, The Game Awards, Summer Game Fest, State of Play, Nintendo Direct, Reddit, VK, Kotaku, Polygon, Eurogamer, GameSpot, StopGame, Игромания, DTF.

The core hands the source over at assembly: `Tracker.company_source` (the game source; None — not asked), passed to `InboxAnswers` and `OfferSearch` like `imdb_source`, so the core asks no kind.

«Ubisoft анонсировала новую игру, и все очень этому рады сегодня» → «Игра»: «Ubisoft» is not searched; the next candidate, if any, is; none — «Не нашёл — сохранил во «Входящие»…».

## 8. Offers (KI-64, KI-61, KI-62)

### 8.1 KI-64: the date of an offer as precise as the source

`Suggestion.released` becomes a `ReleaseDate` (default `NOT_ANNOUNCED`); `Offer.released` too, stored in `inbox_items.offers` as `ReleaseDate.text` («2027-Q4», «2028», «2027-02-12»). Reading is strict (`ReleaseDate.parse`); an offer stored before keeps its day text and reads as a day.

Who fills it:
- TMDb (movies, series, `/find`): `ReleaseDate.of_day` of the date of the answer.
- Shikimori: `Entry.aired` (section 4.1).
- IGDB: the search asks `release_dates.date,release_dates.date_format,release_dates.y,release_dates.m` beside `first_release_date`; the record whose `date` equals `first_release_date` gives `ReleaseDate.from_igdb` (several such records — the least precise wins: a year over a quarter over a month over a day, so one approximate platform never makes a day); none — the year of `first_release_date` alone (never a made-up day).

`offer_cards.released_line(released, today)`: an exact day after today — «выйдет 12 февраля 2027»; an approximate date whose period has not ended (`end >= today`) — «выйдет » + `phrase`: «выйдет в 2028», «выйдет во 2 квартале 2027», «выйдет в январе 2027»; anything else — the year («2026»); not announced — «дата не объявлена». The order of offers (5.3 of 6.4) reads `released.year` and `released.start`.

Live (`answers/igdb-search-date-format-2026-11-23.json`): The Witcher IV `date_format` 2 → «выйдет в 2028»; Intergalactic: The Heretic Prophet and Marvel 1943: Rise of Hydra 2 → «выйдет в 2027»; Fishy Bar 4 (quarter 2) → «выйдет во 2 квартале 2027»; Hollow Knight: Silksong 0 → «2025».

### 8.2 KI-61: the English names of TMDb for a typo

The correction of a typo (5.4 of 6.4, a name message of 2 words or more with no match) searches the name without one word. Now: when such a search in the source's language gives no close name and the source of the kind can search in English, the same shortened name is searched once more **in English** (`language=en-US`); a close English name is the correction, as with any other. TMDb movies and series can (`suggest(query, english=True)`; the provider's `search_movie`/`search_tv` get `language`); Shikimori and IGDB give English names already and are not asked twice.

The corrected name is then searched in the source's language, and the offer is the record of the same id from that search (its Russian name); when that search does not have it, the English record.

Live (`answers/tmdb-alternative-titles-2026-11-23.json`): «Dead-End Jb» finds nothing; «Dead-End» in Russian gives «Работа с призрачными перспективами» (original «꿀알바») — not close; «Dead-End» in English gives «Dead-End Job» first → close (ratio over 0.85) → «Dead-End Job» in Russian gives id 289517, «Работа с призрачными перспективами»: the card «Возможно, вы имели в виду:». `alternative_titles` (one request per record) would give «Dead End Job» (US) too, but at up to 20 requests a search; the English search costs one.

### 8.3 KI-62: a kind press looks the links up again

`answer_kind`: before the name candidates, the links of the item **of the chosen kind** are looked up again (`SourceLink.kind == kind`; an IMDb link for a movie or a series), as `by_links` does: their records come first, a Steam number IGDB does not know gives Steam's name as a candidate; a link that fails again goes to the log and gives nothing. Then the name candidates, as now. A link of another kind is not looked up (the owner said what it is).

### 8.4 Requests per item (replaces 5.5 of spec 6.4)

| Analysis | At most | Usually |
|---|---|---|
| the end of the pause (links) | 3 link lookups (+1 Steam `appdetails` each) + 1 companies + 3 candidate searches = 10 | 1–3 |
| a kind press | 3 link lookups of the kind (+1 each) + 1 companies + 3 candidate searches + 4 for a typo + 3 English searches of the typo (TMDb only) = 17 | 1–3 |

The companies request is made only when there is a Latin candidate to ask; the links of a kind press only when the item has links of the kind; the English searches only on the typo path of a name message. All go at once, ahead of the paced polling (TMDb and IGDB count them in their windows). The description's «at most 11» counted the companies alone.

## 9. «Что это?» after a restart (KI-57)

**Migration 0019**: the column `inbox_items.answered_at` (`DateTime`, nullable): when the pause of the item got its answer — the question «Что это?» or the first offer card. Existing rows get their `last_message_at` (they are answered or in the tab; the owner's table is empty).

Every write of `InboxAnswers` that leaves the item `waiting` after its pause sets it: the question (the path of `pause_over` that answers `ASK` gets a small write: it sets `answered_at` when the item still waits) and the offer card (`_show`). An item that leaves `waiting` (the tab, resolved, deleted) needs none.

`Tracker.inbox_unanswered() -> list[int]` (`Inbox.unanswered`): the items in `waiting` with `answered_at` empty and `received_at` within the last 12 hours, oldest first (at most one in practice: a new item moves the waiting one to «Входящие»).

The bot, once polling starts (the dispatcher's start, before the first update is handled), asks for them and gives each its pause answer: `inbox_pause_over(id)` and the messages of `say`, sent to the owner's chat (`OWNER_CHAT_ID`, as the events), without the line «Предыдущий…». `say` gets a target that is the owner's chat instead of the message it answered (the question, the card with its poster, the texts). A failure goes to the log; the item is in «Входящие» after its 12 hours anyway.

Not asked twice: an item asked before the stop has `answered_at`. The rest of the window: a stop between the write of `answered_at` and Telegram's answer to the send (milliseconds), or a send that fails, leaves the item without the question until its 12 hours — the KI entry says so when it is fixed.

## 10. Copies (KI-66, KI-67, KI-68, KI-69)

### 10.1 KI-66: names in UTC, shown in the zone of Settings

A copy made from now on has its time in **UTC with `Z`**: `tracker_db_20261123_132100Z.db`, `tracker_db_20261123_132100Z_manual.db`, `tracker_db_20261123_132100Z_before-0018.db`, `…Z_before-restore.db`; the Google Drive archive `tracker_db_20261123_132100Z.7z`. Every writer takes `datetime.now(timezone.utc)` (naive): `create_backup`, `create_manual_backup`, `backup_if_due`, `_backup_before_migration` (`create_session_factory`'s `now`), the restore's copy before a restore.

Reading (`backup.copies`, `drive_copies.own_archives`, `restore.phrase_of`): `COPY_NAME`, `ARCHIVE_NAME`, `NAME_TIME` accept an optional `Z` after the time. `Copy.moment` is **naive UTC**: a `Z` name as written; a name without `Z` (made before this stage) in the zone of the process — the container's clock, `TZ` = `BOT_TIMEZONE`, the clock that wrote it — turned into UTC (a parameter `old_zone`, None — the process's zone, for the tests). Rotation, the daily due check and «already in Drive» compare moments in UTC; old and new names mix in one order.

Shown: the Settings block (`backup_rows.copies_block`), the notice after «Сделать копию сейчас» and the reason «copy not made» (`backups`) turn the moment into the zone of Settings before `moment_in_words`, like the Google Drive line already does. The restore (`app.utils.restore`: `list`, `check`, `apply`) reads the zone of Settings from the base being replaced (`settings` row `time_zone`, read-only; missing, unreadable or not a zone — the process's zone) and shows every copy in it; `now` is that zone's wall clock. `moment_words`' docstring about KI-66 goes.

`docs/backups.md`: the names of the table say the time is UTC («время в UTC»), the old names the clock of the PC.

### 10.2 KI-67: a long folder listing

`google_drive._files` follows `nextPageToken` (`fields=nextPageToken,files(id,name,size,createdTime)`, `pageToken` of the previous page) until there is none; at most 50 pages (50,000 files), then it stops with a warning and works with what it has. `list_folder` and `find_folder` both go through it.

### 10.3 KI-68: no second archive of the same name

`DriveCopies._upload`: once the archive is in the folder (sent now, or found with its name and size), every other file of that name in the listing is deleted for good (`delete`), each failure a warning; the count of kept archives does not include what was deleted. Rotation follows as now.

### 10.4 KI-69: the note of an older copy

`restore.OLDER` = «Копия от более старой версии: при запуске база обновится сама.» The line «Нынешняя база сохранена: data\backups\…» after «да» stays: the base that is replaced is always saved by the restore itself.

## 11. `.env` (KI-49)

- `.env.example` lists every variable the code reads (`Settings` fields by their names, plus `WEB_PORT`, `WEB_HOST`, `PUID`, `PGID` of `docker compose` and `app/container_start.py`); it gets `SHIKIMORI_BASE_URL` and `SHIKIMORI_USER_AGENT`, commented out with their defaults and one line each. A test reads `Settings.model_fields` and the names `docker-compose.yml` and `container_start` read, and fails when `.env.example` misses one or names one nobody reads.
- The owner's `.env`: the session on the owner's PC removes the lines of six names — `KINOPUB_ACCESS_TOKEN`, `PS_STORE_REGION`, `SHIKIMORI_CLIENT_ID`, `SHIKIMORI_CLIENT_SECRET`, `psn_api_key`, `rawg_api_key` — by a small script that matches the name before `=` and prints only the names it removed and the count; no value is printed, copied or kept (decision 5). Comments and other lines stay byte for byte. Then `.\start-bot.ps1` checks the file as usual.

## 12. Data

| Migration | What | Ticket |
|---|---|---|
| **0018** `0018_anime_check_now.py` | data only: `source_snapshots.next_check_at` of the Shikimori snapshot of every anime title = the moment of the migration (section 4.6); downgrade does nothing | 02 |
| **0019** `0019_inbox_answered_at.py` | `inbox_items.answered_at DATETIME NULL` by `ALTER TABLE … ADD COLUMN`, filled with `last_message_at`; downgrade drops it the same way (see 0016) | 04 |

Each start copies the base before a migration, as usual (with a `Z` name after ticket 05; before it, the old name).

Stored values without a schema change: `episodes.timing` gets `month` and `year` (section 4.2); `inbox_items.offers[].released` may hold a month, a quarter or a year (section 8.1); copies get `Z` names (section 10.1).

## 13. External services

| Service | Request | Checked |
|---|---|---|
| IGDB `/companies` | `fields name,developed,published; where name ~ "<n>" | name ~ "<n> <word>" …; limit 500;` once per analysis, at once | 2026-11-23: `igdb-companies-exact-2026-11-23.json` (`name = (…)` is case-sensitive: «Ubisoft», «Mojang», «Remedy» missing), `igdb-companies-case-2026-11-23.json` (`~ (…)` with an array: 400), `igdb-companies-or-2026-11-23.json` (`~` joined by `|`: exact without case, and the «<n> <word>» names) |
| IGDB `/games` search | `release_dates.date,date_format,y,m` added to the fields of a suggestion | `igdb-search-date-format-2026-11-23.json` |
| Shikimori | `airedOn { date year month day }` | the answer of 9.1c (`shikimori-premiere-precision-2026-11-22.json`) |
| TMDb `/search/movie`, `/search/tv` | `language=en-US` for the English search of a typo | `tmdb-alternative-titles-2026-11-23.json` (with `alternative_titles` for comparison) |
| Google Drive `files.list` | `nextPageToken` / `pageToken` | documented behaviour of the API (`pageSize` up to 1000); the tests use a fake with two pages |

Failures: the companies request never fails the analysis (section 7.3); the English search follows the rule of the typo path (a failure after an offer — the log; before — «источник не ответил»); a Drive page that fails fails the sending as any listing does today.

## 14. Edge cases

| Case | Behaviour |
|---|---|
| Shikimori gives `airedOn` with `day` but no `month` | garbage read softly: the year alone |
| An approximate premiere whose period has passed and Shikimori still says the month | the season stays announced; the card keeps «премьера в январе 2027»; «Позже» drops the piece (its end is before today); no message |
| The approximate stub of a part and an AniList `nextAiringEpisode` for it | AniList's exact moment wins (`_scheduled`), «объявлена дата» with the key of section 4.4 |
| A real premiere on the 1st of a month stored before this stage | Shikimori gives the day: it stays `day`, nothing changes |
| Shikimori falls back from a day to the month | the stub replaces the day, no message; the next exact day is announced again (key of 4.4) |
| An anime film of the franchise known by the month | unchanged (its stored `aired_on` is a day); new KI-85 |
| `late` episode of a season renumbered at this look | numbers are those of the fresh answer (`relayout` first), as the events use |
| A bulk drop of 12 episodes found late | 12 «вышла серия» events, folded in a summary as any batch |
| The premiere moved by minutes within a day | «9 янв 2027, 18:00 → 9 янв 2027, 18:30» |
| A candidate that is both a company and a title (e.g. «Valve» posts about the company, a game «Metro» by «Metro» 13 games) | the 20-games rule decides; a wrong drop costs one candidate, the owner finds it with «Найти» |
| IGDB keys missing | no companies request; the fixed list only |
| A Cyrillic run that is a company («Юбисофт») | not asked (no Latin letter); stays a candidate of weight 2 |
| A name message «Ubisoft» | not asked (`WHOLE`): searched as typed |
| A kind press on an item with a link of another kind | that link is not looked up; only the candidates |
| The English search finds a close name of another record than the Russian search | the record of the corrected name's Russian search with the same id; none — the English record |
| The bot starts with an unanswered item 13 hours old | not asked: over 12 hours, the expiry job moves it «без ответа» |
| The owner sends a message during the start | the new item moves the old one to «Входящие»; its `pause_over` answers nothing (it no longer waits) |
| Settings zone unreadable in the restore | the process's zone (`BOT_TIMEZONE`) |
| An old copy name at the hour the clocks went back | the earlier of the two moments (`fold=0`); the order of copies may swap by an hour once |
| A Drive folder with 1001 files | two pages; rotation sees all |
| Two files of the archive's name, one of the right size | it counts as sent; the other is deleted |
| `.env` has none of the six names | the script removes nothing and says «0» |

## 15. Tests

Automated (offline, as all tests):
- **Split** (01): the glob size test; `PURE` and `MODULES` with the new modules and `export_all`; the export JSON equal before and after on a sample base; the Feed equal on a sample base; the `feed` action.
- **Approximate** (02, 04): `ReleaseDate.phrase` for every form, quarter 2 «во»; `of_period`.
- **Anime** (02): Shikimori parsing of `airedOn` (day, month, year, garbage); `part_episodes` stubs and the `unknown` of an approximate entry with episodes out; storage round trip of `month`/`year`; never out on and after the first day of the period; `_keep_season` replaces a stored made-up day by the stub, no event; the exact day after an approximate one queues «объявлена дата» with the `moved_key` key and is not swallowed by an old plain key; the card lines, `message_part_ended`, «Позже» piece on `rough.end` with `when`; export `approximate`; migration 0018 on a copy of a base (the anime snapshots due, others untouched); KI-83 the probe case of the KI and that a new entry's past stays silent and adding sends nothing; KI-84 the hour line and both no-move cases.
- **Candidates** (03): KI-58 examples of 7.1 and the sentence-start, quote, marker, common-word and upper-case cases; KI-60 both rules and the episode line kept; the 18 samples of 6.4 keep their first offers (`tests/fixtures`) — any change explained in the ticket; companies: the request text for given candidates, the 20-games rule on the saved answers, the drop moves the next candidate up, no keys / failure / 429 go on with a warning, `WHOLE` and Steam names not asked, nothing asked without a Latin candidate.
- **Offers and bot** (04): `released_line` on the forms of 8.1; IGDB precision from the saved search answer (least precise record wins, no matching record — the year); Shikimori precision; old stored offers read; KI-61 the «Dead-End Jb» path on the saved answers, the same-id rule; KI-62 a Steam link that failed at the pause gives its card after «Игра», a link of another kind is not looked up; the budget counts of 8.4; KI-57 migration 0019, `answered_at` set by the question and the card, `inbox_unanswered` (12 hours, state, answered), the start sends the question to the owner's chat once.
- **Copies** (05): names with `Z`; old names read in a given `old_zone`; mixed rotation; Settings block, notice and restore list in the zone of Settings (a base with `time_zone` set, and without); `phrase_of`; Drive pages (a fake with `nextPageToken`), the same-name delete and its failure; `OLDER` text; `.env.example` test.

The owner checks live — each ticket's owner check (section 17).

## 16. Docs, terms, ADR, known issues

- `CONTEXT.md`: «Примерная дата» — also the premiere of an anime season or part known by the month or the year («в январе 2027» in the card, «январь 2027» in «Позже»); «выйдет в 4 квартале 2027» in an offer; in code `ReleaseDate` without a day (`release_dates`), `EpisodeTiming.MONTH`/`YEAR`, `Episode.rough`. «Серия»: the moment known in the three ways, or the premiere stub of an announced entry known approximately (no moment). «Копия базы»: the time in the name is UTC (`Z`); names before 9.1d — the container's clock; shown in the zone of Settings. «Кандидат»: the companies of IGDB are dropped (`companies`, 20 games). «Входящие»: the question comes after a restart too (`answered_at`).
- `docs/coding-standards.md` rule 7: the check is the glob of the size test.
- `PROJECT_CONTEXT.md`: IGDB row (the companies), TMDb row (the English search of a typo); Gotchas: copy names in UTC with `Z`; «Ubisoft» is no company name in IGDB (the variants).
- `docs/backups.md`: the names (section 10.1).
- `docs/code-map.md`: rebuilt by `tools/code_map.py`; `docs/tests-map.md`: the new test modules.
- `.env.example` (section 11).
- No new ADR: the companies are one more rule (ADR 0010 stands), the names of copies a format detail, the approximate stub a reading of the source.
- `KNOWN_ISSUES.md`: the 18 entries `fixed (test: …)` by their tickets (KI-57 with the rest of section 9). New **KI-85**: an anime film of the franchise known by the month or the year stands on a made-up first day (`MovieRecord.aired_on`, the Feed «Фильм «…»» and the card's year) — fix in 9.2 if met.

## 17. Proposed tickets

| # | Ticket | Sections | Complexity | Blocked by |
|---|---|---|---|---|
| 01 | The code split and code health: the moves of 1.2, `core.py` ≤ 470, the size test over every module, KI-71, F4, F5 | 1, 2 | medium | — |
| 02 | Anime: the approximate premiere (with `ReleaseDate.phrase`), migration 0018, late airings, hour moves | 3, 4, 5, 6 | complex | 01 |
| 03 | Candidates: the middle name, «from» and `: N`, the companies of IGDB, the stop list | 7 | medium | 01 |
| 04 | Offers and the bot: the date of an offer, the English names, the links again, «Что это?» after a restart (migration 0019) | 8, 9 | complex | 02, 03 |
| 05 | Copies and `.env`: UTC names, the zone of Settings, Drive pages and duplicates, the restore note, `.env.example`, the six names out of the owner's `.env` | 10, 11 | medium | 01 |

Owner checks (live, after the session starts the bot):
- **01** — nothing new to see: the Лента, a card and «Скачать всё (JSON)» in Settings work as before.
- **02** — within a minute of the start: the card of «Ванпанчмен» says «часть 2 — в январе 2027», «Реинкарнация безработного…» «часть 2 — в 2027», «Монолог фармацевта» «часть 2 — в апреле 2027» (or «Сезон 3 анонсирован, премьера …» as the card has it); the Лента, «Позже»: «январь 2027», «2027», «апрель 2027»; no Telegram message about it.
- **03** — send the bot «Ubisoft анонсировала новую игру, и все очень этому рады сегодня», press «Игра»: no offer «Ubisoft»; «Вчера вышла новая Дюна, и все рады», «Фильм»: an offer of «Дюна»; «Вышел Fallout: 76 вчера и все очень этому рады сегодня вечером», «Игра»: «Fallout 76».
- **04** — «The Witcher IV», «Игра»: «выйдет в 2028»; «Dead-End Jb», «Сериал»: «Возможно, вы имели в виду:» «Работа с призрачными перспективами». The restart and the failed link are checked by the tests (the session says so).
- **05** — Settings: the copies' time is the time of the Settings zone, and so is the Google Drive line; «Сделать копию сейчас» — the notice gives the time of your clock; `data\backups` has a new file with `Z` in its name; the session says which six names left `.env` (no values).

About 9 sessions in all with the description, this spec, the slicing, five tickets and the review.
