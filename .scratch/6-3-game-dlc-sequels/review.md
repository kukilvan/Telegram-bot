Status: accepted

# Review of stage 6.3: expansions and sequels of games

## What was reviewed

- Commits `52d3c28..0a24368` (after the accepted slicing), tickets 01–04 of `issues/`: 8b8cd4e (01), 16d0ef5 (02), 0047cde (03), 5d5b0a3 (04), and their «accepted» commits.
- Against `spec.md` (sections 0–12) and `docs/coding-standards.md` (rules 1–11, with `CONTEXT.md` for rule 5 and ADRs 0002, 0007, 0009, 0011), with the `code-review` skill: one pass for the standards, one for the spec, each in its own sub-agent; their reports are below, lightly cleaned. The findings and the decisions are in «Findings».

## Tests

- At the start: 3040 passed, 2 skipped, 3 failed — the three known Windows failures (`test_app_main`, `test_docker_files`, `test_runtime`), nothing new. `pyflakes app tests` clean, `docs/code-map.md` current.
- At the end (after the fixes): 3042 passed (two new tests), 2 skipped, the same 3 known Windows failures; `pyflakes` clean, the code map current.

## What was verified by running

- **The live bot** (Docker, the owner's PC): container `healthy`, `/health` 200; the follow-up snapshots exist for the five games for the check (Hades II, GTA VI, Hunter, «Ведьмак 3», Elden Ring), the first checks silent (reference points: `known` 0, 0, 0, 7, 2), the next in 7 days; the two followed Witcher expansions of type 2 have none (spec 5.1). One `TelegramNetworkError` (a request to Telegram timed out after 60 s, 22:03) — the network, not this stage; the error handler reported it as it should.
- **The web cards of the live bot** (HTTP with the login): «Ведьмак 3» — «Дополнения»: Каменные сердца (12 октября 2015, «Следить»), Кровь и Вино (30 мая 2016, «В списке»), Баллады прошлого (2027, «В списке»); «Продолжения» under «Новые игры серии «The Witcher» на ваших платформах»: Gwent, The Witcher 3 Remastered, The Witcher IV (2028), The Witcher Remake (дата не объявлена) — table 4.6 exactly. Elden Ring: Shadow of the Erdtree and Nightreign. Hades II: «Дополнений пока нет…», «Продолжений пока нет…». «Кровь и Вино»: the line «Дополнение к игре «<a href="/titles/29">Ведьмак 3: Дикая охота</a>»», the platforms, the Steam block, no follow blocks. The List: «дополнение» after both expansions (`row-tag`). Feed and Archive open.
- **The rules on the saved answers** (spec pass): `parse_follow_ups`, `expansions_shown`, `sequels_shown`, `follow_up_date` over the 14 answers, PC + PS5, Israel, 2026-11-04 — table 4.6 exactly (names, dates, order, standalone); Hollow Knight (not in the table) gives Silksong.
- **The fixes**: the new test of F1 fails without the fix and passes with it.

## Standards (report of the standards pass)

Tooling clean: `pyflakes`, `test_tracker_core_split`, `test_code_map`, `test_code_speaks_glossary`. No problems with rule 1 (`Tracker.follow` async), rules 3–4 (log calls), rule 8 (`follow_title` checks the button before the early answer, the source name from `KINDS`), rule 9 (strict and soft reading, write sessions), rule 10 (the web imports only `cards` and `kinds`), rule 11, English comments; ADR 0011 as written, 0002, 0007, 0009 not contradicted. Module sizes: `games.py` 406 (was 360), `follow_ups.py` 333, `pollers/game_follow_ups.py` 320, `web/card.py` 347 (was 422); the size test checks only `MODULES` and `pollers/`, so it misses `games.py`.

Documented rules:
- Rule 5: the word after the name of a row is `tag` (`list_tags`, `TitleSummary.tag`) in code, «the mark «дополнение»» in `CONTEXT.md` and ADR 0011, while `mark` in code is the Steam discount; `tag` is in no «In code» line. `Followable`, `FollowOffer`, `FOLLOW_TYPES` have no glossary entry.
- Rule 7, one reason per module: `pollers/game_follow_ups.py` holds the card reads (`parent`, `card_view`) beside the check, while prices split the check (`game_prices`) from the reads (`game_steam`).
- Rule 7, one rule — one place: `_postpone` decides «still checked» by the status alone (half of `for_follow_ups`); the full expression is written twice more (`_decide`, `_queue`).
- Rule 7, ~400 lines: `games.py` 406.

Judgement calls (smells): the query «snapshot of this title and source» three times (`follow_up_snapshot`, `price_snapshot`, `storage.sequel_snapshot`); the reconciliation skeleton in both end-of-pass checks; the keys of a stored announcement read in three places (`actions`, `feed_rows.followable_of`, `delivery_service`); `sequel_id` for an expansion too and the CSS classes `.sequels`, `.sequel-row` for all three lists; `GameState.expansion` a string and `Candidate.standalone` a bool for the same fact; IGDB type 4 written twice (`igdb_games`, `igdb_follow_ups.STANDALONE_TYPE`); `Candidate.standalone` read by no app code; the game sources routed by keyword names (`price_source`, `follow_up_source`); the closing «»» of the parent line in two places; in `follow_ups.py` the loop over my platforms twice, `check` computing the shown ids inline; `_records_of_dates` close to `_records`; `offers_follow_ups` reaching into `follow_ups.source`.

## Spec (report of the spec pass)

The 293 tests of the stage pass. Checked and right: rules 4.1–4.5 and table 4.6 (run on the saved answers), what is new of 5.4, the reconciliation table of 5.1, 10 a pass the earliest first, the events before the store, «Бросил» checked again in `_queue`, the key of 5.5, the failures of 5.6, the texts and data of 6.2–6.6, the card and bot of 7.1–7.6, the documents of section 10 (CONTEXT terms, ADR 0011, KI-52, the rule-7 table, tests-map, the IGDB line of `PROJECT_CONTEXT.md`). The tickets have no Comments, so no agreed deviations; KI-53 is recorded.

Findings: (a) any exception from the source is a failure of the game with a one-line warning and a «could not check» notice, a parse bug too; a `ValueError` of `follow_ups.check` is logged as «own snapshot unreadable» (5.6: «a bug in the check is logged with its traceback»); (b) the name on «Следить» in a summary is no longer cut to 30 characters, for movie sequels too; (b) a bug in the price check no longer stops the follow-up check and the other way round — harmless; (c) an announcement taken out of the queue by «Бросил» keeps its key, so another game of the series never announces it; (c) a game whose own snapshot cannot be read logs a warning every pass, and is either reported daily (it had a snapshot) or silently never checked (it had none); (c) `_postpone` checks only the status, so a game IGDB turned into an expansion while its request failed gets a notice.

Summary: standards — 4 findings of documented rules and about 15 judgement calls, the worst is rule 7 («still checked» in three places, one of them incomplete); spec — 6 findings, the worst is the announcement lost after «Бросил» (F14).

## Findings

| # | What, where | Decision | Why |
|---|---|---|---|
| F1 | «Still checked» three times in `pollers/game_follow_ups.py`; `_postpone` reads only the status, so a game IGDB made an expansion while its request failed got a notice (standards rule 7, spec 5.6) | fix now | One `_title_checked(session, title_id)` by `for_follow_ups`, used by `_decide`, `_queue` and `_postpone` (a spoiled own snapshot there is still the failure to tell). Test `test_a_game_igdb_turns_into_an_expansion_while_igdb_fails_gets_no_notice` |
| F2 | Rule 5: `tag` vs «the mark»; `Followable`, `FollowOffer`, `FOLLOW_TYPES` not in the glossary | fix now | `CONTEXT.md`: «Дополнение» says «the word «дополнение» after the name» in the List and the Archive, `tag` (`list_tags`, `TitleSummary.tag`), not `mark`; «Продолжение» names `Followable`, `FollowOffer`, `FOLLOW_TYPES` and the kept key `sequel_id`. ADR 0011 is not rewritten (ADRs never are) |
| F3 | The query «snapshot of this title and source» three times | fix now | `storage.snapshot_of(session, title_id, source)`; `price_snapshot` and `follow_up_snapshot` removed, `sequel_snapshot` uses it |
| F4 | IGDB type 4 written twice | fix now | `igdb_games.expansion_type(raw)` is the one reading of `game_type` for both adapters; it is soft (a type that is not a number is no expansion — before, a list there raised in `GAME_QUERY`'s parse). Tests in `test_igdb_game_expansion.py` and `test_igdb_follow_up_source.py` |
| F5 | The closing «»» of the parent line in `cards.parent_line` and in `card_body.html` | fix now | `cards.PARENT_LINE_END`, carried by `ParentLine.end` |
| F6 | The loop over my platforms in `on_my_platforms` and `follow_up_date` | fix now | `follow_ups._dates_on_mine`. `check` keeps computing the shown ids itself: it needs the two lists apart |
| F7 | `games.py` 406 lines; the size test checks only `MODULES` and `pollers/` (`series_events.py` 521 lines, before this stage) | defer `KI-56` | Not a small move (`GameDate` into a module of its own touches many imports); the test gap is older than the stage |
| F8 | The card reads (`parent`, `card_view`) in `pollers/game_follow_ups.py` | no change | Spec 2.1 puts «the read of the card view (7.1)» in this module; 320 lines. If it grows, the reads go to a module of their own as `game_steam` did |
| F9 | The keys of an announcement read in three places | no change | Each reads what it needs: `actions` the button argument (lenient), `feed_rows.followable_of` the typed `Followable`, `delivery_service` only the name; one reader in `actions` would make `feed_rows` the importer of a type it owns (spec 7.6 names `feed_rows.followable_of`) |
| F10 | Other smells: `sequel_id` for an expansion, the CSS classes `.sequel*`, `expansion` as a string and `standalone` as a bool, `Candidate.standalone` unread, the game sources by keyword, the reconciliation skeleton twice, `_records_of_dates`, `offers_follow_ups` | no change | `sequel_id` and both fields are the spec's (6.3, 3.2, 3.3); the rest are cosmetic or two copies only; noted as wishes |
| F11 | Any exception from the source is a failure with a warning and a notice, a parse bug too; a `ValueError` of `follow_ups.check` is logged as an unreadable own snapshot | no change | The same as every source in `polling._poll_one`; spec 5.6's traceback is for a bug of the whole check (`end_of_pass`), which has one. A parse bug still reaches the owner as a notice, so it is seen |
| F12 | The name on «Следить» in a summary is not cut, for movie sequels too | no change | Spec 6.5: «Следить» named by the announced game, its example «👀 Следить: Elden Ring: Shadow of the Erdtree» is 33 characters; one rule for every «Следить» |
| F13 | A bug in the price check no longer stops the follow-up check, and the other way round | no change | Fits 5.6; harmless |
| F14 | An announcement taken out by «Бросил» keeps its key: another game of the series never announces it | defer `KI-54` | Rare (an undelivered announcement and «Бросил» on that very game); the fix is a design choice in the queue for every event type |
| F15 | A game with an unreadable own snapshot: a warning every minute; reported daily or silently never checked, by history | defer `KI-55` | Needs a hand edit or a bug; the fix (log once a day, one behaviour) is a small design choice |

## Wishes for later stages

- Split `games.py` (`GameDate`) and `series_events.py`, and let the size test take every module of the core (KI-56).
- If a third end-of-pass check or a third game-only source comes: one reconciliation skeleton, one bundle of the game sources.
- The CSS classes of the follow lists named after the list (`.follow-*`), not after the movie sequels.
