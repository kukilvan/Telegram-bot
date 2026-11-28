# Review 6.5: Meta Quest as a platform of games

Status: in review

One session (2026-11-28).

## What was reviewed

- Commits `cf26a59..d52c5a6` (after the accepted slicing): ticket 01 (1f0cf13, accepted 5c74f07) and ticket 02 (2dc410b, accepted d52c5a6); the spec, the two tickets, ADR 0018, the `CONTEXT.md` terms «Платформа», «Обратная совместимость», «Магазин Meta», «Страна магазинов».
- Against `docs/coding-standards.md` with the `code-review` skill at effort xhigh over the whole stage diff: each hunk line by line, removed behaviour (`ps_concept`'s digits rule moved into `_store_id`, `is_cancelled` of one number, `return []` of an event without a title), the callers of every changed function (`detect_events`, `is_cancelled`, `igdb_numbers`, `GameState` built by keyword only, `event_actions` through `_button_data`), Python pitfalls, the rules of `CLAUDE.md`. Rules 5, 6, 7 and 11 hold (module sizes and the code map by their tests).
- Then a pass for the spec, section by section: the table and the numbers not taken (1), the dates of several own numbers, cancellation, `older_tells`, the date outside the country (2), the line of a suggestion (3), what the owner sees (4), the first poll (5), the store number, the address, the cards, the button, the folded and the summary message, the sample (6), the link sent to the bot (7), data (8), the edge cases (10), the tests named in 11. No deviation from the spec found beyond F1 and F2.

## Tests

- At the start: 5591 passed, 3 skipped; only the two known Windows failures (`test_app_main`, `test_runtime`).
- At the end (after the fixes): 5591 passed, 3 skipped (no new test: F3 and F4 changed a doc row and a comment); the same two known Windows failures, nothing new. `pyflakes app tests` clean; the code map unchanged (no docstring changed).

## Verified by running

- **The first poll on the owner's games** (the riskiest part: a complex ticket, every game of the list): the 14 games whose snapshots are from before 6.5 run through `detect_events` with fresh IGDB answers, the owner's «Мои платформы», marks and country: no event with the rule of spec 5, none without it — no game of the list has a SteamVR or Quest number. The polls since the start of 6.5 queued no game event (only the sample of ticket 02). The rule itself is pinned by the tests on saved answers (`test_tracker_meta_quest`).
- **The first follow-up check after the update** on the owner's 16 games with follow-up snapshots, fresh IGDB answers, `follow_ups.check` with «Мои платформы» as now and with ПК + PS5: no announcement at all; the hole of F1 is real, but none of these games falls into it.
- **The web on a copy of the database** (in-process, a generated test password, a sender that sends nothing): Settings — «Meta Quest» the sixth checkmark, ticked; Search — «Batman: Arkham Shadow» with the line «Meta Quest», «Beat Saber» with «ПК, Meta Quest»; the cards — Batman: Arkham Shadow «Meta Quest — 22 октября 2024» with the store page, Supernatural «Meta Quest — 23 апреля 2020» with the store search, Beat Saber «ПК — 21 мая 2019» and «Meta Quest — 21 мая 2019» with Steam and the store page, Red Matter 2 «ПК — 18 августа 2022» and «Meta Quest — 18 августа 2022» with Steam and the store search (its snapshot is from ticket 01, so no store number until its next poll — spec 8); the bot card lines the same, with «Магазин Meta: https://…».
- **The store link live**: `https://www.meta.com/experiences/asgards-wrath-2/2603836099654226/` is read as source `meta`, number `2603836099654226`; IGDB answers Asgard's Wrath II (2023, «Meta Quest») in one request.
- **The bot in Docker**: up since 13:02, healthy, `/health` `{"status":"ok"}`; `Job "Tracker.poll_due …" executed successfully` every minute, the checks of the end of a pass with 0 failed, no error, traceback or `polling title … failed`.
- Seen in passing: a second game search right after another, while the bot also asked IGDB, got «Не удалось связаться с IGDB» (a 429; an at-once search fails without repeats by design, `app/providers/igdb.py`); the next try 2 s later found it. Not of this stage.
- Not run live here: Telegram itself (the owner's check of the tickets: the bot card, the store link sent to the bot, the sample with the button) and a real release on Meta Quest.

## Findings

- **F1 — the first follow-up check after the update can announce an old game of the series as new.** The follow-up snapshots taken before 6.5 hold no SteamVR or Quest records, and their `known` lists only the ids they showed; a game of the series whose only tracker platform is SteamVR (now ПК) or a Quest headset (with Meta Quest ticked) is shown for the first time and announced: «Анонсирована новая игра серии: …». Spec 5 said the follow-up snapshot needs nothing — true for a follow-up already listed, not for one never shown. The owner's 16 games give no such message (simulated above), every old follow-up snapshot is checked within 7 days and then the window closes. Decision: **defer `KI-93`** — the fix (the numbers in the follow-up state, the comparison restricted to them) is a design change worth doing when the next IGDB number is taken, not before; ADR 0018's consequence covers only the own snapshot.
- **F2 — a Meta store link IGDB does not know asks «Что это?», then ends in «не нашёл».** The item goes on as one without links (the 6.4 rule for any link that finds nothing), though a Meta store link can only be a game, and the slug of the address names it; IGDB lacks the store number of about 41 % of Quest games. Decision: **defer `KI-94`, 9.2 if met** (a new candidate rule is a design choice).
- **F3 — the tests-map row of `test_tracker_settings_games` got new Russian text** («шесть платформ по порядку — Meta Quest последней…») against `CLAUDE.md` (English for everything written from 2026-11-01). Decision: **fixed now** — the row is English.
- **F4 — the comment of `TitleCard.store_links` named only Steam and PlayStation Store** (`app/tracker/cards.py`). Decision: **fixed now** — the Meta store added.

No finding needs a fix round: the stage closes once the owner accepts.

## Wishes for later stages

- When ADR 0018 takes another IGDB number: the spec covers the follow-up snapshots too (KI-93), and the check of the first poll on the owner's real list, as done here, goes into its review.
- 9.2: KI-94 if the owner sends Meta store links of upcoming games; a game added before ticket 02 links to the store search until its next poll — if the owner minds, one poll of every game on Meta Quest at the start would fill the numbers.
