# 01: The source and the rules — IGDB follow-up query, snapshot, pure rules, expansion as a game

Status: in review
Complexity: complex (a new IGDB adapter with a three-level query, the pure rules of what is shown and what is new, a strict change of the own game snapshot)
Blocked by: —

Spec: `../spec.md`, sections 3 (all), 4 (all), 5.4 and 5.5 (what is new, keys), 6.1–6.3 (types, texts, data), 1 (the saved answers and what they say), 2.1 (rows `igdb_follow_ups.py`, `follow_ups.py`), 2.2 (rows `igdb_games.py`, `games.py`), 8 (rows on platforms, dates, «before», cancelled). Terms — `CONTEXT.md` («Дополнение», «Продолжение», «Серия игр», «Проверка дополнений и продолжений»); standards — `docs/coding-standards.md` (rules 5, 7, 9, 11); ADR 0011 (a followed expansion is a game of its own). Not touched here: the check itself (ticket 02), the card, the buttons and the summary (tickets 03, 04). Nothing of this is connected to the core yet.

The saved answers live in `.scratch/6-3-game-dlc-sequels/igdb-answers/`; the tests read copies of them from `tests/fixtures/igdb/` (copy only what the tests use).

## What to do

- **`sources/igdb_follow_ups.py`** (3.1, 3.2): the query with every field of 3.1 (`<F>` expanded for `expansions`, `standalone_expansions`, `remakes`, `remasters`, `collections.games`), through the same `IGDBProvider.games(body)` as every IGDB request; `FollowUpsSnapshot` (`own_date`, `collections`, `expansions`, `games`) and `Candidate` (`id`, `name`, `first`, `platforms`, `releases`, `standalone`) with the soft parse (garbage is «no such field»); the game kinds of section 1 item 4 (`is_game`: types 0, 4, 8, 9, 10, 11, no `version_parent`); each record once by id, without the game itself and without the records already in `expansions`; `IgdbFollowUpSource` with `source_key = "igdb_follow_ups"`: an empty list from IGDB is `TitleGone`, a failure is `IgdbError`, no keys is `SourceNotConfigured` before the network.
- **Public helpers of `sources/igdb_games.py`** (2.2): `russian_name`, `is_game`, the reading of the platforms and of the release records become public where they are private now; the new adapter reuses them, nothing is copied.
- **The own snapshot** (3.3): `GAME_QUERY` asks `parent_game.name` instead of `parent_game`; `GameState` gets `expansion` (`"expansion"` for IGDB type 2, `"standalone"` for type 4, only when the record has a `parent_game`; None otherwise — a remaster, a remake, a port with a parent too) and `parent` (`{"id", "name"}`, only with `expansion` set). Read strictly (rule 9): another value of `expansion`, or a `parent` without `id` or `name`, raises `ValueError`; a snapshot without the keys reads as no expansion.
- **`follow_ups.py`, pure** (section 4):
  - the stored state `FollowUps` (the snapshot of 3.2 plus `known`) with its strict read and write; `{}` is «not checked yet»;
  - **on my platforms** (4.1), **expansions shown** (4.2), **sequels shown** with «came out before» (4.3), **the date of a follow-up** (4.4, `GameDate.label`: earliest end, early access with « (ранний доступ)», «дата не объявлена»), **order** (4.5);
  - **what is new** (5.4): the reference point, the three conditions of an announcement, the new `known`; the key `game:follow_up:<igdb id>` (5.5);
  - **the events** (6.1–6.3): `EXPANSION_ANNOUNCED`, `SEQUEL_ANNOUNCED`, `TYPES`, the two texts, the data with the keys `text`, `kind`, `sequel_id`, `sequel_title`, `date`;
  - **the samples of «Тестовое событие»** (6.6) as data (the two rows `game-expansion`, `game-sequel`); they join `test_samples.py` in ticket 04.
  The rules read «Мои платформы», the store country (`GameScope`) and today as arguments — no clock, no database.
- If `follow_ups.py` grows over ~400 lines (rule 7), the texts and samples go to `follow_up_events.py` (2.1).
- **Docs:** module docstrings (rule 11) and `.venv\Scripts\python.exe tools\code_map.py`; `docs/coding-standards.md` rule 7, the module table: the rows `follow_ups`, `sources/igdb_follow_ups`; `docs/tests-map.md` for the new test files. «Next step» of `PROJECT_CONTEXT.md` changes only with the owner's «ОК».

## Done when

- [ ] The query names every field of 3.1 and the body matches the saved answers' shape; the parse of the 14 `follow-ups-<game>.json` gives the own date, the collections, the expansions with `standalone`, and the games kept and left out by type and `version_parent` (spec 1 items 3–4); the Russian names are IGDB's alternative names.
- [ ] An empty answer is `TitleGone`; `IgdbError` passes through; without keys `SourceNotConfigured` before any request.
- [ ] `GAME_QUERY` asks `parent_game.name`; Blood and Wine → `expansion = "expansion"`, parent 1942 «The Witcher 3: Wild Hunt»; Lost Legacy and Miles Morales → `"standalone"`; The Witcher 3 Remastered (type 9 with a parent) → None; a snapshot stored before 6.3 reads as no expansion; a wrong value raises `ValueError`.
- [ ] The table of 4.6 holds exactly (names, dates, order) on the saved answers for PC + PS5 in Israel on 2026-11-04; PC only removes the PS5-only candidates; a candidate cancelled on my platforms is not shown; an expansion without a platform or a release record is shown with «дата не объявлена»; «before» works with the own date, without it, and on the same day.
- [ ] What is new (5.4): the reference point gives nothing and fills `known`; a new candidate gives one event with the texts of 6.2 and the data of 6.3; a candidate getting its first platform of mine (Project Sirius, Cyberpunk 2) or its first date after the game is news; a change of «Мои платформы» or of the country is not; a listed candidate gives nothing but goes into `known`; a candidate gone and back is not news; two games of one series give one key; a spoiled state raises.
- [ ] Rule 5 (words of `CONTEXT.md`), rule 7 (module placement and size), rule 9 (strict reads), rule 11 (docstrings), `tests/test_code_map.py` and `tests/test_code_speaks_glossary.py` green.
- [ ] `pyflakes app tests` clean; the full test suite green (the three known Windows failures are not new).

## Tests to add

- `test_igdb_follow_up_source.py` — the adapter (spec 9.1 «Adapter»), on fixtures copied into `tests/fixtures/igdb/`.
- An own-snapshot test next to the existing game-source tests (spec 9.1 «Own snapshot»): `GAME_QUERY`, the six `game-<expansion>.json` answers, the strict read.
- `test_tracker_follow_ups.py` — the rules and what is new (spec 9.1 «Rules» and «What is new»), on a fake clock.

## Owner check

Nothing new is visible: the code is not connected. The session starts the bot with `.\start-bot.ps1`, and the owner's check is one line: the bot starts as before — `http://localhost:8080/health` answers, the log has no red text, the List and the cards of games open as they did. The session writes the launch result in one line and the check.
