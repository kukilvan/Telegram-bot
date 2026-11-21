# 03: The follow-up check and withdrawn events — KI-52, 53, 54, 55

Status: open
Complexity: complex (the same check files as 02, the queue's `withdraw`, a new reading rule for broken snapshots)
Blocked by: 02 (the hook `Poller.after_marks`, `enqueue_all`, `DailyLog`)

Spec: `../spec.md`, section 3.1 (the follow-up snapshots of the hook, KI-53, the docstring of `pollers/game_follow_ups.py`), section 3.2 (the follow-up check queues through `EventQueue.enqueue(…, due=game)`), section 3.3 (KI-54), section 4 (4.1, 4.2), section 8 (the line on a withdrawn discount whose store fails), the Follow-ups and The press lines of the tests of section 9. Terms — `CONTEXT.md`; ADRs to read: 0011 (the decision stands, its last consequence — KI-52 — stops being true; say so in `docs/history.md` at the end of the stage, no new ADR), 0015. Standards — rules 1, 3, 7, 9, 11. Known issues: KI-52, 53, 54, 55.

## What to do

- **The follow-up part of the hook (3.1).** In `GamePoller.after_marks`: the follow-up snapshots of games no longer «игра для проверки» (`for_follow_ups`) go (KI-53: «Бросил» drops the follow-up snapshot at once; «Вернуть в список» gets an empty one at the next pass, and its first check is the silent reference point). Same rule as the reconciliation, in one place. Change the docstring of `pollers/game_follow_ups.py` (the old «No button touches the … snapshots»).
- **KI-54 (3.3).** `EventQueue.withdraw` deletes the undelivered queue entries **and their events**, explicitly both (not by cascade), so a fact taken out by «Бросил», by the end of a price check or by a deeper discount can come again from another game of the series. A withdrawn event also leaves «Недавно». Change the docstring «The events stay: their dedup keys keep the same facts from coming again».
- **The follow-up check's own queueing (3.2).** It queues through `EventQueue.enqueue(…, due=game)` (the wish of review 9.1a) instead of its own `_title_checked`; `_decide` keeps `_title_checked` for reading what the rules need. «The snapshot exists» is enough for `still_checked`.
- **KI-52 (4.1).** `FOLLOW_UPS_QUERY` also asks `parent_game.name`; `parse_follow_ups` reads the game's own expansion kind and parent with `sources/igdb_games` helpers (`expansion_type`, `_parent` made public as `parent_of`) into `FollowUpsSnapshot.own_expansion` / `own_parent` (not stored in the follow-up state). In the store write session, when the game's own check does not run (status not in `POLLED_STATUSES` or tracking off — «Пройдено») and the own snapshot's `expansion` / `parent` differ, they are written into the own snapshot (`GameState` with them replaced; a spoiled own state is left alone — KI-55 reports it). A standalone expansion completed before 6.3 then gets «Дополнение к игре «…»» and the List mark after its next weekly check. A game that turns out to need its game (type 2) is dropped by the next reconciliation, as any.
- **KI-55 (4.2).** Reconciliation: a game whose own snapshot cannot be read (`games.expansion_of` raises) is treated by its status alone — in «Хочу», «В процессе», «Пройдено» it counts as a game for the check (its snapshot is made if missing, never dropped); one log line a day per game (`failures.DailyLog`). The check: the own snapshot is read before IGDB is asked; unreadable → the failure at once, no request; the game waits 30 minutes and joins the «could not check» messages (once a day by the window). A game that had a follow-up snapshot and one that never had are treated alike.
- **Docs:** docstrings, `tools\code_map.py`, `docs/tests-map.md`, rule 7 table (`pollers/game_follow_ups`, `queue`); `KNOWN_ISSUES.md` — KI-52, 53, 54, 55 `fixed (test: …)` with the index rows.

## Done when

- [ ] «Бросил» then «Вернуть в список» within one minute: the next follow-up check is a silent reference point and no old reference point is used (KI-53).
- [ ] A withdrawn announcement comes later from another game of the series; `withdraw` leaves no event row behind and the event is gone from «Недавно»; a deeper discount's withdrawal of an older one frees only the older key (KI-54).
- [ ] A standalone expansion in «Пройдено» gets its kind and parent in its own snapshot after the weekly check, and the List mark; a game in another status leaves its own snapshot to its own poll; a spoiled own state is left alone (KI-52).
- [ ] An unreadable own snapshot: no IGDB request, one failure, 30 minutes of waiting, one «could not check» a day, one log line a day; the follow-up snapshot is made if missing and never dropped by the reconciliation (KI-55).
- [ ] KI-52–55 are `fixed (test: …)`; pyflakes clean; code map rebuilt; no core module over 400 lines (the facade 500); the full suite green (the known Windows failures are not new).

## Tests to add

- `after_marks` follow-up part: «Бросил» drops the snapshot at once; «Вернуть в список» → an empty snapshot at the next pass → the first check is a silent reference point (the KI-53 scenario end to end); a check answering after the press queues nothing.
- `withdraw`: queue entries and events both deleted; «Недавно» no longer shows it; the same fact queued again from another game of the series; the same game cannot repeat it (reference point after the return).
- The follow-up check through `enqueue(…, due=game)`: a dropped game queues nothing, no dedup key spent.
- `parse_follow_ups` with `parent_game.name`; the own-snapshot write for «Пройдено» only; no write for «Хочу» or tracking on; a spoiled own state untouched; a type-2 game dropped by the reconciliation.
- KI-55: an unreadable own snapshot — no IGDB request (the fake counts), one failure, `DailyLog` once a day, the snapshot made if missing, never dropped.

## Owner check

The session starts the bot and writes the launch result in one line, and in a second line what it watched in the log (a pass of polling with no `polling title … failed`). Nothing for the owner to press: the effects are in the weekly check and in the minute after a press, which only the tests can show. One thing to see in the browser: «Мои тайтлы» → the list of games opens without an error page, and the games are the same as before.

«Не так»: an error page; games missing from the list; a game in «Пройдено» that lost its «Дополнение» mark.
