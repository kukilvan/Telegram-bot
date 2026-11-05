# 02: The weekly check — reconciliation, 10 a pass, reference point, events queued, failures

Status: accepted
Complexity: complex (a new poller step with reconciliation by the status rule, a bounded queue per pass, a race with «Бросил», failure handling, a change of who owns the price source)
Blocked by: 01

Spec: `../spec.md`, sections 5 (all), 8 (rows on the first pass, two games of a series, «Бросил» during the request, the deleted game, IGDB failures, a spoiled state, expansion type 2 and 4, KI-52), 2.2 (rows `pollers/game.py`, `pollers/base.py`, `polling.py`, `core.py` — only `follow_up_source`, `app/main.py`), 9.1 («The check»), 9.2 step 1. From ticket 01 it uses `IgdbFollowUpSource`, `FollowUps`, `Candidate`, the rules of 4 and 5.4, the event types, keys and data. Terms — `CONTEXT.md` («Проверка дополнений и продолжений», «Хочу», «В процессе», «Пройдено», «Бросил»); standards — `docs/coding-standards.md` (rules 1, 2, 7, 9). ADR 0002 and 0007. Not touched here: the card, the web, the bot buttons, the summary (tickets 03, 04). `KNOWN_ISSUES.md`: KI-50 and KI-52 are known — KI-50 is not fixed, the new check just does not repeat it (a game with an unreadable own snapshot is left out with a log line); KI-52 is already written.

## What to do

- **`pollers/game_follow_ups.py`** (section 5): 
  - **`for_follow_ups(status, game)`** — the one place of the rule: «Хочу», «В процессе» or «Пройдено» and `GameState.expansion != "expansion"` (5.1);
  - **reconciliation** (5.2) at the start of the check, in one write session and a number of reads that does not grow with the number of games: a game for the check without a snapshot of source `igdb_follow_ups` gets `state = {}`, `observed_at = now`, `next_check_at = now`; a snapshot whose game is no longer for the check is deleted; it reads of the own snapshot only the key `expansion`; a game whose own snapshot cannot be read is left out with a line in the log and the others go on;
  - **due games** (5.3): `next_check_at` ≤ now, at most `FOLLOW_UPS_PER_PASS = 10` a pass, earliest first, then by title id;
  - **each due game** (5.3): read the stored state strictly; the IGDB request with no database open; one read session for the title, its status, its own snapshot, the scope (`GameScope`), today on the owner's clock and `known_ids` of the game source; a game gone or no longer for the check is skipped with nothing queued or stored; the events are queued first, each in a session of its own; then one write session stores the new state, `observed_at = now`, `next_check_at = now + 7 days`;
  - **what is new** comes from `follow_ups.py` (ticket 01), nothing is decided here twice;
  - **failures** (5.6): `IgdbError`, `TitleGone`, `SourceNotConfigured`, a spoiled state → the game waits 30 minutes (`RETRY_AFTER_FAILURE`) and the failure joins the «could not check» messages of the pass as `(DueTitle, exc)` with `snapshot_source = "igdb_follow_ups"` (`failures.source_name` names IGDB); one notice a game in 24 hours; one failing game does not stop the others.
- **`pollers/game.py`**: `end_of_pass` runs the prices, then the follow-up check, under the same `poll_lock`; a bug in the check is logged with its traceback and the titles of the pass are checked already (as `polling._end_of_pass` does for the prices).
- **`pollers/base.py`, `polling.py`, `core.py`, `app/main.py`** (2.2): `Poller` loses `price_source` (wish of review 6.2); `Pollers` hands the price source and the follow-up source to the game poller only (`polling.py` stays the one place that chooses by kind); `Tracker` gets `follow_up_source: Any = None` beside `price_source`; `app/main.py` builds one `IGDBProvider` for the game source and the follow-up source (one pace for all IGDB requests) and passes `follow_up_source=IgdbFollowUpSource(igdb)`. Without keys both are «not connected».
- **Interim state to remember:** until ticket 04 an announcement is a plain text message with no «Следить» and no «Карточка» button; the first check of every game is silent and the next one is a week later, so nothing is expected in between. Write it in the closing message to the owner.
- **Docs:** module docstrings, `tools\code_map.py`; `docs/coding-standards.md` rule 7 — the row `pollers/game_follow_ups`, and `price_source` only in the game poller; `docs/tests-map.md`.

## Done when

- [ ] Reconciliation follows the table of 5.1 line by line: added, started, completed, dropped (snapshot goes), restored from «Бросил» (a new reference point) and from «Пройдено» (goes on as it was), expansion type 2 (no check), expansion type 4 (check), deleted (cascade). The number of reads does not grow with the number of games.
- [ ] 10 a pass, the earliest first; 7 days after a success, 30 minutes after a failure; the others wait for the next pass.
- [ ] The first check of a game is the reference point: nothing queued, `known` filled; a later check queues one event per new announcement with the key of 5.5, each in its own session, **before** the snapshot is stored.
- [ ] «Бросил» (or a deletion) pressed during the IGDB request: nothing queued, nothing stored; the next pass removes the snapshot.
- [ ] A spoiled own snapshot or follow-up state fails only its game (30 minutes, one notice a day); `IgdbError`, `TitleGone` and no keys do the same; one game failing does not stop the others.
- [ ] `end_of_pass` runs the prices first, then the follow-ups, and a bug in the follow-ups does not lose the pass; `Poller.price_source` is gone; one `IGDBProvider` serves both sources in `app/main.py`.
- [ ] Rules 1, 2, 7 (module size, `test_tracker_core_split.py`), 9; `pyflakes app tests` clean; the full test suite green (the three known Windows failures are not new).
- [ ] For the owner (the session starts the bot): after the start no message arrives; the log has no red text and, within a minute, `Job "Tracker.poll_due …" executed successfully` with no `polling title … failed` before it; the session shows the snapshots of source `igdb_follow_ups` in the database for the games of the list.

## Tests to add

- `test_tracker_game_follow_ups.py` — everything in spec 9.1 «The check»: the reconciliation table, 10 a pass, 7 days / 30 minutes, the failure notices, a spoiled snapshot, «Бросил» during the request, events before the store, one IGDB client for both sources (`app/main.py`).
- Adjust the tests of `Poller.price_source` and of `Pollers` to the new owner of the sources.

## Owner check

The session starts the bot itself and writes the launch result in one line. The owner's check (PowerShell and a browser; the cards do not show the blocks yet):

1. After the update, Telegram stays quiet: no «Анонсировано…» and no error message arrives during the first 10 minutes.
2. `http://localhost:8080/health` says ok; `.\logs-bot.ps1` shows no red text (exit with `Ctrl+C`; the bot keeps running).

What the session verifies itself and tells the owner in one line: the rows of source `igdb_follow_ups` in the database, one for each game in «Хочу», «В процессе» and «Пройдено», and none for games in «Бросил» and for expansions of type 2.
