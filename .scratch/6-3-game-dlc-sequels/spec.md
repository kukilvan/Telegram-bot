# Stage 6.3: spec — expansions and sequels of games

Status: in review

Built from the accepted description (`description.md`, mockups in `mockups/`). Terms come from `CONTEXT.md` (written together with this spec: «Дополнение», «Продолжение» widened to games, «Серия игр», «Проверка дополнений и продолжений»). Decisions this stage leans on: ADR 0002, ADR 0007, ADR 0011 (new: a followed expansion is a game of its own). Rule numbers are those of `docs/coding-standards.md`.

## 0. Summary

Once a week the tracker asks IGDB, in one request per game, for the expansions of each game in «Хочу», «В процессе» and «Пройдено» and for the games of its series. The answer is a snapshot of its own (source `igdb_follow_ups`), checked at the end of a polling pass like the Steam prices. A new expansion or a new game of the series on «Мои платформы» comes as a message with «Следить» and «Карточка»; the card shows the blocks «Дополнения» and «Продолжения»; «Следить» on an expansion adds it as a game of its own with the line «Дополнение к игре «…»» and the mark «дополнение» in the List.

### Where the spec refines the description

- **«Вернуть в список»** makes the next check a reference point only from «Бросил»: from «Пройдено» the check never stopped (both statuses are checked), so nothing was missed and it goes on as it was (section 5.1).
- **A standalone expansion** (IGDB type 4: Miles Morales, The Lost Legacy) is an expansion of its parent game (its block «Дополнения», the message «Анонсировано дополнение», the line and the mark), and also a game the owner can play alone: it has its own check and its own blocks. Only an expansion that needs its game (IGDB type 2: Blood and Wine) has none (question 4).
- **Platforms.** A game of the series counts only on «Мои платформы» (decision 3). An expansion counts on «Мои платформы» too, and also while IGDB lists no platform for it yet: it belongs to a game the owner plays, so it is no noise (section 4.2).
- **Texts.** Names are IGDB's Russian names where IGDB has one («Ведьмак 3: Дикая Охота - Кровь и Вино», not the mockup's «Кровь и вино»). After «Следить» the bot answers as it does for a movie sequel: «✅ Добавлено в список» and the card (not the mockup's «Добавил в список: … Сообщу о выходе…»). The line «Дополнение к игре «…»» of the bot card stands after the names line, where the bot card has its names. A row of «Недавно» shows the lines of the message as every event row does (the mockup's «· выход …» was rough).
- **In a summary** the announcements are lines of the one summary message, each with its own button «👀 Следить: …», as movie sequels are now. Outside the summary each is a message of its own (decision 5).
- **The first check of the games already in the list** runs in the first passes after the update: at most 10 checks a pass (one pass a minute), so a long list is checked within minutes, not in one long pass.
- **The wish "a sequel as a pair (kind, id) instead of `SequelOffer`"** is read as review 5.3 wrote it: the sequel travels as a bare tuple `(kind, id)` although a named type exists. The tuple becomes a named type `Followable` (section 7.6).

## 1. Checked against real answers

Live requests of 2026-11-04, saved in `igdb-answers/` (the tickets copy what their tests read into `tests/fixtures/igdb/`):

| File | What it shows |
|---|---|
| `follow-ups-<game>.json` (14 games: witcher-3, elden-ring, hades, hades-2, cyberpunk-2077, uncharted-4, lost-legacy, spider-man, hollow-knight, god-of-war, baldurs-gate-3, ac-valhalla, gta-6, hunter-deathwish) | the answer to the follow-up query of section 3.1 |
| `follow-ups-witcher-3-with-franchises.json` | the same with `franchises.games`: why the franchise is not used |
| `game-<expansion>.json` (blood-and-wine, shadow-of-the-erdtree, phantom-liberty, songs-of-the-past, lost-legacy, miles-morales) | the answer to `GAME_QUERY` with `parent_game.name`: an expansion read as a game |
| `steam-expansions-il.json` | Steam `GetItems` for five expansions in Israel |

What the answers say:

1. **One request with three levels of nesting works**: `collections.games.release_dates.date` comes back. The answer is 4–55 KB, the largest series (Assassin's Creed, 108 records) 144 KB. No limit on nested lists was seen.
2. **Expansions are the fields `expansions` (type 2) and `standalone_expansions` (type 4)** of the game. `dlcs` (type 1) are quests and gear: «Fool's Gold», «Wolf School Gear», «Tarnished Pack».
3. **The series is `collections`, not `franchises`.** The franchise of The Witcher adds only noise to the collection: editions («Game of the Year Edition», «Collector's Edition»), bundles («The Witcher 3 + Dark Souls III»), crossovers («Balatro: Friends of Jimbo», «Reigns: The Witcher») and Thronebreaker, which is a standalone expansion of Gwent (its `parent_game`). Question 1: `collections` only, plus the game's own `remakes` and `remasters` (a game with no collection still gets them).
4. **Which records of the series are games:** the types of Search (spec 4.2 of part 6.1) — 0 main game, 4 standalone expansion, 8 remake, 9 remaster, 10 expanded game, 11 port — and no `version_parent`. Left out: 1 DLC, 2 expansion (of another game), 3 bundle, 5 mod, 6 episode («Fate of Atlantis — Episode 1»), 7 season, 12 fork, 13 pack («The Fleur-de-Lys»), 14 update («Free Next-Gen Update»). Question 1 answered: 12 and 13 are not games of the series.
5. **«Мои платформы» remove the noise of the series.** In The Witcher: Battle Arena, Monster Slayer, Roach Race, Crimson Trail (mobile), Versus (browser) go; The Witcher 1 and 2 came out before The Witcher 3. Left (PC and PS5, Israel): Gwent (2018, a card game on PC), The Witcher 3: Wild Hunt Remastered (29 September 2026), The Witcher IV (2028), The Witcher Remake (no date). Project Sirius has no platform yet: it is not shown until IGDB gives it one of mine (question 3). In Assassin's Creed, of 108 records after Valhalla: Mirage, Shadows, Black Flag Resynced (a remake), Codename Hexe.
6. **A cancelled game stays in the series:** Baldur's Gate III: The Black Hound has one record on PC with `status` 5. A game cancelled on every platform of mine is not shown.
7. **`first_release_date`** is the earliest day of a game over all platforms and regions (a timestamp, UTC). For a date with only a year it is 31 December (The Witcher IV: 2028-12-31); for no date at all it is missing. It ignores early access: Hades II has 25 September 2025.
8. **`GAME_QUERY` reads an expansion as it is** (question 6): Blood and Wine has its Russian name, 6 platforms with dates, the cover, the genres and its Steam number (378648); the parent comes as `parent_game` `{id, name}` once the query asks `parent_game.name`. A remaster, a remake, a port and an expanded game have a `parent_game` too (the original), so «expansion» is decided by the type, not by the parent.
9. **Steam prices of expansions work through part 6.2 as they are**: Shadow of the Erdtree ₪319, Phantom Liberty ₪344,07; Songs of the Past «coming soon»; Blood and Wine and Miles Morales are not sold separately in Israel.
10. **Russian names** are IGDB's alternative names as in Search: «Ведьмак 3: Дикая Охота — Баллады прошлого», «God of War Рагнарёк», «Marvel Человек-Паук 2»; Shadow of the Erdtree and Phantom Liberty have none.

## 2. Modules and the facade

### 2.1 New modules

| Module | Holds |
|---|---|
| `app/tracker/sources/igdb_follow_ups.py` | the IGDB adapter of the check: the query (3.1), the parse of the answer into `FollowUpsSnapshot` (3.2), `IgdbFollowUpSource` (`source_key = "igdb_follow_ups"`) |
| `app/tracker/follow_ups.py` | pure: the stored state of the check (`FollowUps`, `Candidate`), the rules of what is shown (4), the date of a follow-up (4.4), what is new (5.4), the texts and keys of the events (6), the samples of «Тестовое событие» |
| `app/tracker/pollers/game_follow_ups.py` | the check at the end of a pass (5): the rule «игра для проверки» (`for_follow_ups`, one place), the reconciliation of the snapshots, the due games, the queueing, the store, the failures; the read of the card view (7.1) |
| `app/web/card_blocks.py` | the blocks of the web card that depend on the kind, moved out of `app/web/card.py` (wish of review 6.2): the platforms of a game (moved as they are), the line «Дополнение к игре «…»» and the follow lists — the sequels of a film and the expansions and sequels of a game, one row type for all three (7.2) |

If `follow_ups.py` grows over ~400 lines (rule 7), the texts and samples go to `follow_up_events.py`.

### 2.2 Changed modules

- `sources/igdb_games.py`: `GAME_QUERY` asks `parent_game.name` instead of `parent_game`; the parse gives `GameState.expansion` and `GameState.parent` (3.3). Its helpers the new adapter reuses (`russian_name`, `is_game`, the reading of the platforms and the release records) become public where they are private now.
- `games.py`: `GameState` gets `expansion` and `parent` (3.3).
- `pollers/game.py`: `end_of_pass` runs the prices, then the follow-up check; `card_part` adds the parent line and the follow-up view; a new action `list_tags` (7.4).
- `pollers/base.py`: `Poller` loses `price_source` (wish of review 6.2); new action `list_tags` (default: none); new property `offers_follow_ups` (default False; the game poller: True while it has the follow-up source).
- `polling.py`: `Pollers` hands the price source and the follow-up source to the game poller only — `polling.py` is the one place that chooses by kind; `Pollers.follows(kind)`: the kind announces titles to follow (it has a sequel source, or its poller `offers_follow_ups`).
- `core.py`: `Tracker` gets `follow_up_source: Any = None` beside `price_source`; `follow_sequel_of` becomes `follow(kind, external_id)` (it adds an expansion too); `follow_sequel(event_id)` stays for the old movie buttons.
- `titles.py`: `follow` refuses a kind that `Pollers.follows` does not name (`UnknownKind`).
- `cards.py`: `SequelLine` becomes `FollowLine` with a ready `when` text; new `ParentGame`, `FollowUpsView`; `TitleCard` and `CardPart` get `parent` and `follow_ups`; the bot card prints the parent line (7.3).
- `listing.py`, `results.py`: `TitleSummary.tag`, read from the pollers (7.4).
- `actions.py`: `FOLLOW_TYPES` — the one list of the event types with «Следить»; the buttons of the new events (6.4).
- `feed.py`, `feed_rows.py`: `Followable` and `FollowOffer` (7.6); the titles already listed are read for every type of `FOLLOW_TYPES`.
- `delivery_service.py`: the names on the buttons of a summary (6.5).
- `test_samples.py`: two samples (6.6).
- `app/main.py`: one `IGDBProvider` for the game source and the follow-up source (one pace for all IGDB requests); `follow_up_source=IgdbFollowUpSource(igdb)`.
- `app/web/card.py`, `card_body.html`: the blocks of 7.2, the address `card_follow`; `app/web/feed.py`, `feed_body.html`: the address `feed_follow`; `title_rows.py`, `macros.html`, `style.css`: the mark «дополнение» (7.4).
- `app/bot/tracker_handlers.py`: «Следить» of a game; texts by the kind's source (7.5).

No migration: the check makes its snapshots itself (5.2), the parent lives in the game's own snapshot.

## 3. Source: IGDB

### 3.1 The query

One request per checked game, through the same `IGDBProvider` as every IGDB request (`games(body)`, paced: 1.5 s apart, 30 a minute; a 429 repeated with the backoff of the client):

```text
fields name,game_type,first_release_date,
  expansions.<F>,standalone_expansions.<F>,remakes.<F>,remasters.<F>,
  collections.name,collections.games.<F>;
where id = <igdb id>;
```

where `<F>` stands for each of `id,name,game_type,version_parent,first_release_date,platforms,alternative_names.name,alternative_names.comment,release_dates.date,release_dates.date_format,release_dates.y,release_dates.m,release_dates.platform,release_dates.release_region,release_dates.status` with the prefix of its list (`expansions.id,expansions.name,…`). The body is about 3,300 characters. An empty list from IGDB means it no longer knows the game: `TitleGone`. A failure is `IgdbError`, as everywhere.

### 3.2 What the answer becomes

`FollowUpsSnapshot` — what IGDB says now (pure parse, soft: garbage in the answer is «no such field»):

- `own_date`: the day of the game's `first_release_date` (`response_day_of_timestamp`), or None.
- `collections`: the names of its collections, in IGDB order («The Witcher»).
- `expansions`: the records of `expansions` and `standalone_expansions` without a `version_parent`; each a `Candidate` with `standalone` = its type is 4.
- `games`: the records of `remakes`, `remasters` and `collections.games`, each once by its id, without the game itself and without the records already in `expansions`, and only the games of section 1, item 4 (`is_game`).

A `Candidate`:

| Field | From |
|---|---|
| `id` | IGDB id, as text |
| `name` | the Russian alternative name (`russian_name`), else `name` |
| `first` | the day of `first_release_date`, or None |
| `platforms` | the IGDB platforms the tracker knows (as `GameState.platforms`) |
| `releases` | the release records of those platforms, as `GameState.releases` reads them (full, early access, cancelled) |
| `standalone` | expansions only: type 4 |

All candidates are kept whatever their platforms and dates: what is shown depends on «Мои платформы», the store country and today (section 4), so a change of settings reads the stored snapshot again without a request.

### 3.3 An expansion as a game (the own snapshot)

`GAME_QUERY` asks `parent_game.name`. `GameState` gets two fields, stored in the snapshot of source `igdb`:

- `expansion`: `"expansion"` (IGDB type 2) or `"standalone"` (type 4) when the record has a `parent_game`; None otherwise (a game, a remaster, a remake… even with a parent).
- `parent`: the parent game, `{"id": "<igdb id>", "name": "<IGDB name>"}`, only with `expansion` set.

Read strictly (rule 9): another value of `expansion`, or a `parent` without `id` or `name`, raises `ValueError`; a snapshot without the keys (every snapshot stored before 6.3) reads as no expansion. Every poll of the own source stores them again, so a correction in IGDB arrives with the next poll. Adding by id (`add_title(GAME, id)`) already takes any record of IGDB: an expansion is added through «Следить» exactly as a sequel of a film is. Search keeps showing only games.

## 4. What is shown

Everything here is pure (`follow_ups.py`) and reads the stored snapshot with what the owner sees now: «Мои платформы», the store country (`GameScope`) and today on the owner's clock.

### 4.1 On my platforms

A candidate is **on my platforms** when for at least one platform of «Мои платформы» `games.platform_dates(candidate, platform, country)` is not None and not `cancelled`: the candidate is on it (backward compatibility included: a PS4 game is on PS5) and not cancelled there.

### 4.2 Expansions

The **expansions shown** are the snapshot's `expansions` that are on my platforms, or that have no platform and no release record at all (announced without platforms).

### 4.3 Sequels

The **sequels shown** are the snapshot's `games` that are on my platforms and did not **come out before this game**. A candidate came out before when its `first` is known and:

- the game has an `own_date`: `first` ≤ `own_date` (the same day counts as before: a port or a version released with the game is not a sequel);
- the game has none (announced, not out): `first` ≤ today — it is out already, and this game is not.

A candidate without `first` is never «before». Dates of a year only compare as IGDB stores them (31 December): The Witcher 3: Wild Hunt Remastered (29 September 2026) came out before The Witcher IV (2028).

### 4.4 The date of a follow-up

What the card row and the message say after «Выход:»:

1. the announced full-release date of the candidate on «Мои платформы» for the store country (`platform_dates(...).full`, backward compatibility included, cancelled platforms skipped) that ends earliest (KI-39 rule: a day of 2027 is earlier than «2027»);
2. no announced full release on my platforms, but an announced early access: that date with « (ранний доступ)» (Hades II before its full release: «6 мая 2024 (ранний доступ)»);
3. nothing announced: «дата не объявлена».

The text is `GameDate.label`: «21 июня 2024», «март 2027», «4 квартал 2026», «2027», «дата не объявлена».

### 4.5 Order

Both lists by that date, the one that ends earlier first, «дата не объявлена» last; equal dates by name (`text.key`), then by id.

### 4.6 What the saved answers give (PC and PS5, Israel, 2026-11-04)

These are the expected values of the tests on the saved answers.

| Game | Expansions shown | Sequels shown |
|---|---|---|
| Ведьмак 3: Дикая охота | Каменные сердца — 12 октября 2015; Кровь и Вино — 30 мая 2016; Баллады прошлого — 2027 (full Russian names: «Ведьмак 3: Дикая Охота - …») | Gwent: The Witcher Card Game — 23 октября 2018; The Witcher 3: Wild Hunt Remastered — 29 сентября 2026; The Witcher IV — 2028; The Witcher Remake — дата не объявлена |
| Elden Ring | Elden Ring: Shadow of the Erdtree — 21 июня 2024 | Elden Ring Nightreign — 30 мая 2025 |
| Hades | — | Hades II — 25 сентября 2025 |
| Hades II, Grand Theft Auto VI, Baldur's Gate III, Hunter: The Reckoning - Deathwish | — | — (BG3: The Black Hound is cancelled; Hunter has no collection) |
| Cyberpunk 2077 | Phantom Liberty — 26 сентября 2023 | — (Cyberpunk 2 has no platform yet) |
| Marvel's Spider-Man | Miles Morales — 12 ноября 2020 (standalone) | Marvel's Spider-Man Remastered — 19 ноября 2020; Marvel Человек-Паук 2 — 20 октября 2023; Marvel's Wolverine — 15 сентября 2026 |
| Uncharted 4 | The Lost Legacy — 23 августа 2017 (standalone) | Uncharted 4 — Remastered and The Lost Legacy — Remastered, both 28 января 2022 |
| Uncharted: The Lost Legacy | — | the same two remasters |
| God of War (2018) | — | God of War Рагнарёк — 9 ноября 2022; Sons of Sparta — 12 февраля 2026; Laufey — 16 февраля 2027; three remakes — дата не объявлена |
| Assassin's Creed Valhalla | Wrath of the Druids — 13 мая 2021; The Siege of Paris — 12 августа 2021; Discovery Tour: Viking Age — 19 октября 2021 (standalone); Dawn of Ragnarök — 10 марта 2022 | Mirage — 5 октября 2023; Shadows — 20 марта 2025; Black Flag Resynced — 9 июля 2026; Codename Hexe — дата не объявлена |

Gwent and Discovery Tour are what the rules say, not noise to filter: Gwent is a game of The Witcher on PC that came out after The Witcher 3; Discovery Tour is a standalone expansion in IGDB. The owner was told (section 13).

## 5. The check

### 5.1 Which games: «игра для проверки»

A game is checked (`for_follow_ups(status, game)`, one place) when its status is «Хочу», «В процессе» or «Пройдено» and it is not an expansion that needs its game (`GameState.expansion != "expansion"`). So:

| Change | The check |
|---|---|
| a game added (Search, «Следить» on a sequel) | starts: the first check is the reference point |
| «Следить» on an expansion (type 2) | none: no check, no blocks |
| «Следить» on a standalone expansion (type 4) | starts, as for a game |
| «Начал играть», «Прошёл» | goes on as it was |
| «Бросил» | stops; its snapshot goes; its undelivered messages are already taken out by «Бросил» (`EventQueue.withdraw`) |
| «Вернуть в список» from «Бросил» | starts again: the first check is the reference point |
| «Вернуть в список» from «Пройдено» | goes on as it was (it never stopped) |
| the game deleted | its snapshot goes with it (cascade) |

### 5.2 Reconciliation

No button touches the follow-up snapshots: the rule lives in the check, as for the prices (spec 4 of part 6.2). At the start of the check, in one write session and a number of reads that does not grow with the number of games:

- a game for the check without a snapshot of source `igdb_follow_ups` gets one: `state = {}` (not checked yet), `observed_at = now`, `next_check_at = now`;
- a snapshot of that source whose game is no longer for the check (status, expansion, kind) is deleted.

The reconciliation reads of the own snapshot only the key `expansion`; a game whose own snapshot cannot be read is left out of the check with a line in the log, and the other games are checked (unlike KI-50). The games already in the list get their snapshots in the first pass after the update.

### 5.3 When and how

- At the end of each polling pass, in `GamePoller.end_of_pass`, after the price check, under the same `poll_lock`.
- Due: a snapshot with `next_check_at` ≤ now; at most **10 a pass** (`FOLLOW_UPS_PER_PASS`), the earliest `next_check_at` first, then by title id; the others wait for the next pass (a minute).
- Each due game: its stored state is read (strictly: a spoiled state is that game's failure, 5.6); the request of 3.1 goes with no database open; then one read session reads the title, its status, its own snapshot, the scope (`GameScope`), today on the owner's clock and which candidates are in the list (`known_ids` of the game source). A game that is gone, or no longer for the check (pressed «Бросил» while IGDB answered), is skipped: nothing queued, nothing stored; the reconciliation of the next pass removes its snapshot.
- The events are queued first, each in a session of its own (as every poller does); then, in a write session, the snapshot gets the new state, `observed_at = now`, `next_check_at = now + 7 days`.

### 5.4 What is new

The stored state (`FollowUps`) is the snapshot of 3.2 plus `known`: the ids ever shown by this game's check.

- **The reference point** (the stored state is `{}`): `known` = the ids of the expansions and sequels shown now; no event.
- **Otherwise** a candidate is announced when it is shown now (4.2, 4.3) and:
  - its id is not in `known`;
  - it was not shown by the previous snapshot read with today's settings and today's date — so a change of «Мои платформы» or of the store country gives no messages (as in parts 6.1 and 6.2), while a candidate that got its first platform of mine (Project Sirius, Cyberpunk 2) or its first date after this game is news;
  - it is not in the list (the owner follows it already).
  The new `known` = the old one plus every id shown now, the listed ones too.
- A candidate IGDB stops listing goes from the card; its id stays in `known`, so its return is no news.

### 5.5 Deduplication

The key is one per announced game, not per checked game (question 8): `game:follow_up:<igdb id>` for both event types. Two games of one series that both find The Witcher IV give one message (the one checked first); a standalone expansion announced as an expansion of its parent is not announced again as a game of the series of another game.

### 5.6 Failures

- `IgdbError`, `TitleGone`, `SourceNotConfigured` (no keys), a spoiled stored state: the game's check waits 30 minutes (`RETRY_AFTER_FAILURE`), and the failure joins the «could not check» messages of the pass (`(DueTitle, exc)`, source `igdb_follow_ups`, named IGDB by `failures.source_name`): one notice a game in 24 hours, as for every check. The `DueTitle` is the game: its name, its IGDB id, `snapshot_source = "igdb_follow_ups"`.
- One game failing does not stop the others.
- A bug in the check is logged with its traceback; the titles of the pass are checked already (as `polling._end_of_pass` does for the prices).
- No keys of IGDB: the game source and the follow-up source are both «not connected»; the card says «Ещё не проверял…» until keys are given.

## 6. Events

### 6.1 Types

`follow_ups.EXPANSION_ANNOUNCED = "game_expansion_announced"`, `follow_ups.SEQUEL_ANNOUNCED = "game_sequel_announced"`; `follow_ups.TYPES` holds both. The event belongs to the checked game (`title_id`). Not folded: one message per announcement (decision 5).

### 6.2 Texts

`<icon>` is the game icon 🎮, `<name>` the candidate's name, `<game>` the checked game's name in the list, `<date>` the date of 4.4.

```text
🎮 Анонсировано дополнение: <name>
Дополнение к игре «<game>»
Выход: <date>
```

```text
🎮 Анонсирована новая игра серии: <name>
Продолжение игры «<game>»
Выход: <date>
```

Example: «🎮 Анонсирована новая игра серии: The Witcher IV / Продолжение игры «Ведьмак 3: Дикая охота» / Выход: 2028».

### 6.3 Data

`{"text": …, "kind": "game", "sequel_id": "<igdb id>", "sequel_title": "<name>", "date": "<GameDate.text or null>"}`. The keys `kind`, `sequel_id` and `sequel_title` are the ones of the movie sequel announcement: the Feed, the summary and «Следить» already read them; `sequel_id` names the title «Следить» adds — an expansion too (a stored key keeps its name, rule 5).

### 6.4 Buttons

`actions.FOLLOW_TYPES` = the movie `SEQUEL_ANNOUNCED` and `follow_ups.TYPES`: the one list of the types that offer «Следить». Under a game announcement: «👀 Следить» (`follow`, arg `game:<igdb id>`) and «📄 Карточка» (the checked game). A movie announcement keeps «👀 Следить» alone.

### 6.5 In a summary

The buttons of a summary are named by their title: «👀 Следить» by the announced game (`sequel_title`), every other button by the event's title. So under a game announcement: «👀 Следить: Elden Ring: Shadow of the Erdtree» and «📄 Карточка: Elden Ring». «Следить» is never cut (as now).

### 6.6 «Тестовое событие»

Two text samples (no buttons, like the movie sample), after the game samples:

| Id | Label | Text |
|---|---|---|
| `game-expansion` | Игра: анонсировано дополнение | «🎮 Анонсировано дополнение: Ведьмак 3: Дикая Охота — Баллады прошлого / Дополнение к игре «Ведьмак 3: Дикая охота» / Выход: 2027» |
| `game-sequel` | Игра: новая игра серии | «🎮 Анонсирована новая игра серии: The Witcher IV / Продолжение игры «Ведьмак 3: Дикая охота» / Выход: 2028» |

(« / » stands for a new line.)

## 7. What the owner sees

### 7.1 The view the core gives (`cards.py`)

- `FollowLine(external_id, name, when, title_id)`: one row of a follow list; `when` is the ready date text; `title_id` the title when the list has it («В списке»). It replaces `SequelLine`: a film's row gets `when` = `format_date` or «дата не объявлена».
- `FollowUpsView(checked, checked_at, expansions, sequels, collections)`: `checked` — the check has answered once (`known` is in the state); `checked_at` — `observed_at` on the owner's clock (aware); the two lists of 4.2–4.5 as `FollowLine`s; `collections` — the names of the series.
- `ParentGame(name, title_id)`: the parent of an expansion; `name` is the title's name when the parent is in the list (`known_ids`), else the stored IGDB name; `title_id` None when it is not in the list.
- `CardPart` and `TitleCard` get `parent: ParentGame | None` and `follow_ups: FollowUpsView | None`. The game poller fills them: `parent` for a game with `GameState.expansion`; `follow_ups` for a game for the check (5.1) while the core has the follow-up source, whether its snapshot exists yet or not (none yet: `checked = False`); None for any other title (and for every game when the core has no follow-up source: a test core, for one). Read in a number of reads that does not depend on the length of the lists.

### 7.2 Web card

Under the blocks «Платформы» and «Steam», where the movie block «Продолжения» stands now:

| State | What the card shows |
|---|---|
| not checked yet | heading «Дополнения и продолжения», line «Ещё не проверял — проверю в ближайшие минуты» |
| checked | heading «Дополнения», then the heading «Продолжения» |

Block «Дополнения»: the line «Проверяю раз в неделю, последняя проверка — <when>» when it has rows, «Дополнений пока нет. Проверяю раз в неделю, последняя проверка — <when>» when it has none (`<when>` is `format_past_moment`: «в 14:05», «вчера в 23:10», «2 ноя в 09:05»). Block «Продолжения»: the line «Новые игры серии «The Witcher» на ваших платформах» (two series and more: «Новые игры серий «A», «B» на ваших платформах»; none: «Новые игры серии на ваших платформах») when it has rows, «Продолжений пока нет. Проверяю раз в неделю» when it has none.

A row: the name, the date (`when`), then «Следить» (a form) or «В списке» (a link to the card), as the movie rows now. All three lists — the film's sequels, the game's expansions, the game's sequels — are one macro with one row type (`FollowRow`, `FollowBlock` of `card_blocks.py`).

«Следить» posts to `card_follow` (`POST /titles/{id}/follow`, which replaces `card_sequels`) with `kind`, `external_id` and `block` (`sequels` | `expansions`); the owner stays on the card and the row says «В списке». What went wrong is the line of `pages.try_follow` (the texts of now) in the block the press came from.

The line of an expansion, under the original name: «Дополнение к игре «Ведьмак 3: Дикая охота»», the name in quotes a link to its card when the parent is in the list, plain text otherwise. An expansion of type 2 has no follow blocks (it is not for the check); a standalone one has both the line and the blocks.

`card_blocks.py` takes the blocks of the platforms out of `card.py` as they are; `card.py` keeps the routes and the parts every kind has.

### 7.3 Bot card

After the names line: «Дополнение к игре «Ведьмак 3: Дикая охота»». The bot card lists no expansions or sequels.

### 7.4 List and Archive

`Poller.list_tags(session, titles)`: the words after the name of a row, title → text; a game with `GameState.expansion` (either kind) has «дополнение»; read in a constant number of reads. `TitleSummary.tag` carries it, `title_rows.Row.tag` shows it after the name (class `row-tag`: small, muted). The List and the Archive both. The bot list is not changed.

### 7.5 Bot «Следить»

The button `game:<id>` goes through the same handler as a movie's (rule 8: answer → work → tell). After it: «✅ Добавлено в список» and the card of the added title, for every kind («✅ Продолжение добавлено в список» goes); «Уже в списке» as now. The errors name the source of the button's kind (`KINDS[…].source_name`; an old button with a number is a movie's: TMDb): «Не нашёл это в IGDB. Попробуйте чуть позже.», «Не удалось получить данные из IGDB. Попробуйте чуть позже.».

### 7.6 Feed

«Недавно»: an announcement is a row with the first line of the message and the other two smaller, and «Следить» or «В списке», as a movie sequel now. Two names replace the bare tuple:

- `Followable(kind, external_id)`: what «Следить» adds; `feed_rows.followable_of(data)` (was `sequel_of`) returns it or None for an announcement of the old format;
- `FollowOffer(target: Followable, title_id)` (was `SequelOffer`); `feed._listed` is keyed by `Followable` and reads every type of `FOLLOW_TYPES`.

The Feed's «Следить» posts to `feed_follow` (`POST /feed/follow`, replaces `feed_sequels`) with `kind` and `external_id`. «Скоро» and «Позже» show a followed expansion as any game.

### 7.7 What does not change

An expansion in the list is a game: its platforms with «играю здесь», release dates and «вышла» messages, «Начал играть», «Прошёл», scores, the Steam block and discounts in «Хочу» on PC (an expansion pass sold with it counts as a bundle by the rule of part 6.2: two apps or more).

## 8. Edge cases

| Case | Behaviour |
|---|---|
| The first pass after the update | the games of the list get their snapshots; up to 10 checks a pass, all silent (reference points); the cards show the blocks within minutes |
| Two games of one series checked | one message per announced game (key 5.5), under the game checked first |
| The owner pressed «Следить» on a row before the weekly check announced it | no message: it is in the list |
| An announcement waiting for the summary, then «Следить» on the card | the message still comes; its «Следить» answers «Уже в списке» |
| A game of the series gets its first platform of mine (Project Sirius) | announced at the next weekly check |
| The owner adds a platform to «Мои платформы» (or changes the store country) | no message; the card shows the new lists at once |
| IGDB drops a candidate for a week and brings it back | it leaves the card for that week; no message when it returns |
| A candidate gets a date earlier than the game (IGDB fix) | it leaves «Продолжения»; nothing is sent |
| A game in «Хочу» without any date (announced) | the games of the series already out are not sequels; the ones not out are |
| A remaster of the game itself (The Witcher 3 Remastered), a remake of an older game | sequels («новая игра серии»), by decision 3 |
| Gwent for The Witcher 3; Discovery Tour for Valhalla | shown: the rules say so (section 4.6) |
| A game cancelled on every platform of mine | not shown |
| An expansion only on platforms not mine | not shown |
| An expansion with no platform yet | shown, «дата не объявлена»; after «Следить» its card says why it has no platforms, and the platforms come with IGDB |
| The parent of a followed expansion deleted from the list | the line shows the IGDB name without a link |
| «Бросил» pressed while the game's check waits for IGDB | nothing is queued or stored; the snapshot goes in the next pass |
| The game deleted while its check waits for IGDB | the same, silently |
| IGDB fails, rate-limits or has no keys | the game waits 30 minutes; one «could not check» notice a game a day |
| A spoiled follow-up state (hand edit, bug) | that game's failure every 30 minutes, one notice a day; deleting the row heals it (a new snapshot, a new reference point) |
| A standalone expansion added through Search before 6.3 and already «Пройдено» | its own snapshot is not polled any more, so it gets no line «Дополнение к игре» and no mark: KI-52. In «Хочу» or «В процессе» it gets them with its next own poll |
| A type-2 expansion «Пройдено» | no check, as in «Хочу» |
| IGDB changes a game into an expansion (type 2) | the next own poll stores it; the reconciliation removes its check and the blocks go |
| Year-only dates in «before» | compared as IGDB stores them (31 December), so they are approximate |

## 9. Tests and the check

### 9.1 Automated (offline, saved answers, SQLite in memory)

- **Adapter** (`test_igdb_follow_up_source.py`): the query names every field of 3.1; the parse of the 14 saved answers (own date, collections, expansions with `standalone`, the games kept and left out by type and version, the Russian names); an empty answer is `TitleGone`; without keys `SourceNotConfigured` before the network.
- **Own snapshot**: `GAME_QUERY` asks `parent_game.name`; Blood and Wine → `expansion = "expansion"`, parent 1942 «The Witcher 3: Wild Hunt»; Lost Legacy and Miles Morales → `"standalone"`; the Witcher 3 Remastered (type 9 with a parent) → None; a snapshot without the keys reads as no expansion; a wrong value raises.
- **Rules** (`test_tracker_follow_ups.py`): the table of 4.6 exactly (names, dates, order) for PC + PS5 in Israel on 2026-11-04; PC only removes the PS5-only candidates; a candidate cancelled on my platforms; an expansion without platforms shown; «before» with and without the own date and on the same day; the date of 4.4 (the earliest end, early access with « (ранний доступ)», «дата не объявлена» last).
- **What is new**: the reference point gives nothing and fills `known`; a new candidate gives one event with the texts of 6.2 and the data of 6.3; a candidate getting its first platform of mine is news; a change of «Мои платформы» or country is not; a listed candidate gives nothing but goes into `known`; a candidate gone and back is not news; two games of one series give one event; a strict read of the state.
- **The check** (`test_tracker_game_follow_ups.py`): the reconciliation by the table of 5.1 (added, started, completed, dropped, restored from «Бросил» and from «Пройдено», an expansion of type 2 and of type 4, deleted); 10 a pass, the earliest first; 7 days after a success, 30 minutes after a failure; the failure notices; a spoiled own or follow-up snapshot fails only its game; «Бросил» during the request queues nothing; the events go before the store; one IGDB client for both sources (`app/main.py`).
- **Card**: the three states and the texts of 7.2; the rows with «В списке»; «Следить» from both blocks with an error in its block; the line of the parent with and without a link; the movie block on the new row type; the blocks of the platforms unchanged after the move.
- **Bot and Feed**: the buttons of 6.4; the names in a summary (6.5); «Недавно» with «Следить» and «В списке» for game and movie announcements, an old-format announcement without a button; `feed_follow`; the bot «Следить» of a game (rule 8: `test_tracker_early_answer.py`), its texts; the two samples; the bot card line; the mark «дополнение» in the List and the Archive.
- `test_tracker_core_split.py` (no module of the core over 400 lines, no kind compared outside `polling.py`), `test_code_map.py`, `tests/test_code_speaks_glossary.py` stay green.

### 9.2 Live, by the owner (after the last ticket)

1. After the update no message arrives (the first checks are silent).
2. The card of «Ведьмак 3: Дикая охота» (in «Пройдено»): «Дополнения» — the three expansions with dates, «Продолжения» — the four games of section 4.6. «Elden Ring»: Shadow of the Erdtree and Nightreign. «Hades II», «Grand Theft Auto VI», «Hunter»: «… пока нет».
3. «Следить» at «Кровь и Вино»: the row says «В списке»; its card says «Дополнение к игре «Ведьмак 3: Дикая охота»» with a link, the platforms with «играю здесь», the Steam block; the List shows «дополнение»; the bot card (📚 Мои тайтлы) has the line.
4. Telegram, «Тестовое событие»: the two new samples.
5. A real announcement cannot be made on purpose; the tests cover it.

## 10. Documents

- **`CONTEXT.md` — written together with this spec:** «Дополнение» (new), «Продолжение» (games), «Серия игр» (new: the word «серия» alone is an episode), «Проверка дополнений и продолжений» (new), «Архив» (what is still checked there).
- **ADR 0011 — written together with this spec:** a followed expansion is a game of its own in the list.
- **`KNOWN_ISSUES.md` — written together with this spec:** KI-52 (section 8).
- `docs/coding-standards.md`, rule 7: the module table (`follow_ups`, `pollers/game_follow_ups`, `sources/igdb_follow_ups`), the actions of a poller (`list_tags`, `offers_follow_ups`), `price_source` only in the game poller; the web table of rule 10 if it lists the card modules.
- `docs/code-map.md` (built), `docs/tests-map.md` — the new and changed modules.
- `PROJECT_CONTEXT.md`, External services: IGDB also gives expansions and series (one request per game a week, nested fields).

## 11. Out of scope

As in the description: small DLC, mods, updates, editions; games in «Бросил»; expansions and games of the series in Search; new rules for movie sequels; Steam DLC lists; KI-35…38, KI-43…47, KI-50, KI-51. Decided here: the franchises of IGDB; a filter of the series by genre (Gwent stays); the date of early access in «before» (`first_release_date` ignores it); refreshing the own snapshot of archived games (KI-52); taking a waiting announcement out of the queue when the owner follows its game meanwhile.

## 12. Proposed tickets

| # | Ticket | Complexity | Blocked by | The owner checks |
|---|---|---|---|---|
| 01 | **The source and the rules**: `sources/igdb_follow_ups.py` (3.1, 3.2), `follow_ups.py` (4, 5.4, the texts and keys of 6.1–6.3), `GAME_QUERY` and `GameState.expansion` / `parent` (3.3); the saved answers as fixtures. Not connected to the core yet | complex | — | the bot starts as before (nothing visible) |
| 02 | **The weekly check**: `pollers/game_follow_ups.py` (5: rule, reconciliation, 10 a pass, reference point, events queued, store, failures); the game sources only in the game poller; one IGDB client in `app/main.py` | complex | 01 | after the start no message; the log has no red text; the session shows the snapshots in the database |
| 03 | **What the owner sees on the web and in the bot card**: the view of 7.1, `card_blocks.py` with the moved platforms and the three follow lists (7.2), `card_follow`, `Tracker.follow` and `Pollers.follows`, the parent line (web and bot, 7.3), the mark «дополнение» (7.4) | medium | 02 | steps 2–3 of 9.2 |
| 04 | **Announcements**: `FOLLOW_TYPES` and the buttons (6.4), the names in a summary (6.5), `Followable` / `FollowOffer` and `feed_follow` (7.6), the bot «Следить» texts (7.5), the samples (6.6); `CONTEXT.md` checked against the code | medium | 02, 03 | step 4 of 9.2; a sample of each |

Then the review of the stage: 6 sessions with this spec, as estimated.
