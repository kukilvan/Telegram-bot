# 04: Polling — the status read again, the facts after a return, the parts of a season, the window per source (migration 0016)

Status: accepted
Complexity: complex (polling and events, anime parts, a migration that drops a column)
Blocked by: 05 (migration 0015 comes before 0016)

Spec: `../spec.md`, sections 4.1 (KI-22), 4.2 (KI-23), 4.3 (KI-1), 4.4 (KI-45), the rows of section 7 on parts of a season, failures of one pass and a window of a day, tests of 4.1–4.4 in section 8, the `KNOWN_ISSUES.md` lines of section 9 (KI-77 is written, stays open for 9.1c). Terms — `CONTEXT.md`; ADRs to read: 0001, 0005; the migration notes of 0009 (why `DROP COLUMN` and not a batch rebuild of `titles`); standards — rules 1, 3, 7, 10, 11. Known issues: KI-22, 23, 1, 45.

## What to do

- **«Бросил» during a check (4.1).** One function `still_checked(session, due) -> bool` used by `Poller.record_all` (so by every poller and by `SequelPoller`), by `EventQueue.queue_failure_notices` and by `Polling._still_checked`: the title exists and the snapshot of `due.snapshot_source` exists; a sequel check (`due.sequels`) — the status is «Просмотрено»; an own-release check (the snapshot source is the title's primary source) — the status is one of `POLLED_STATUSES` and tracking is on; a check at the end of a pass (Steam prices, follow-ups) — the snapshot exists. `EventQueue.record` takes the `due` and checks inside its write session, after the dedup flush (where it checks that the title exists today); not checked → rollback, nothing queued, no dedup key spent. A failure notice of a title no longer checked is not queued. The poll never changes the status.
- **A fact right after «Вернуть в список» (4.2).** `DetectedEvent.happened_at: datetime | None` (naive UTC; a date is its 00:00 UTC) by the table of 4.2: `movie_released`, `movie_digital` — the cinema or digital date; `series_season_started`, `series_episode_out`, `series_season_ended` of a TMDb series — the `air_date` of the episode the event is about (the last one for an ended season); `anime_movie_released` — `aired_on`; `game_released`, `game_early_access` — the date of the platform; every other event, and the episode events of an anime — None. `DueTitle.restored_at` (from `Title.restored_at` in `_due_titles`). In `record_all` with `due.baseline`: an event is queued only if `happened_at` is set and later than `restored_at`; the rest is the reference point as today. The log line of today stays, with the count queued.
- **Moving parts of a season (4.3).** `AnimePoller._sync_entries`: the fixed point of 4.3 — `moves` = the parts whose entry moved; repeat until nothing changes: drop from `moves` a part whose new place is the current place of a part not in `moves`, or the new place of another part in `moves`; the parts in `moves` go out of the way (`number = -id`), flush, then to their places; the others stay. The log says once per check: `title <id>: parts <ids> keep their places, the places they move to are taken`. Exchanges and chains of moves work as today.
- **One «could not check» window per source (4.4).** The window of 24 h is per title **and source** (`failures.source_name`). Read from the events: a notice is due unless an event `source_failure` of this title with `payload.source` equal to the source was detected in the last 24 h (`failures.COOLDOWN`); within one pass one notice per title and source; the dedup key `failure:<title id>:<source>:<stamp of the pass>`. **Migration 0016** drops `titles.failure_notified_at` with `ALTER TABLE titles DROP COLUMN` (not the batch way — a rebuild of `titles` cascades into its children); the model and every reader of the column go. Old events without `source` do not count. Number it after 0015 (ticket 05) — if 0015 is not in `master` yet, stop and tell the owner.
- **Docs:** module docstrings, `tools\code_map.py`, `docs/tests-map.md`; the migration note in `docs/code-map.md` by the script; `KNOWN_ISSUES.md` — KI-22, 23, 1, 45 `fixed (test: …)`, KI-23's text says what remains is KI-77.

## Done when

- [ ] «Бросил» between the pass's start and the title's turn (a source that waits for an event) → no event and no dedup key; a failure notice of a dropped title is not queued; a watched movie dropped during its sequel check gives no announcement.
- [ ] The 23:59:30 / 00:00 example of KI-23 queues «вышла серия»; an episode that aired the day before the return stays silent; an episode of an anime stays silent.
- [ ] The KI-1 example (`[P1, C, B, A]`, `C` leaves the chain) gives no `IntegrityError` and moves nothing, with the log line; an exchange of two parts and a chain still work.
- [ ] The KI-45 example gives two notices (two sources of one title); one source twice within a day gives one; the dedup key carries the source.
- [ ] Migration 0016 on a copy of a database with the column drops it, keeps the rows of `titles` and the tables that cascade from it; downgrade is as the other migrations do.
- [ ] KI-22, 23, 1, 45 are `fixed (test: …)`; pyflakes clean; the code map rebuilt; no core module over 400 lines (the facade 500); the full suite green (the three known Windows failures are not new).

## Tests to add

- `still_checked`: every row of 4.1 (missing title, missing snapshot, sequel with a wrong status, own release with a dropped title or tracking off, end-of-pass check); `EventQueue.record` rolls back without spending the dedup key; `queue_failure_notices` skips a dropped title.
- `happened_at` per event of the table; `record_all` with a baseline and `restored_at`: the example of KI-23, a day-before episode, an anime episode, an event without a moment.
- `_sync_entries`: the KI-1 example, two parts that want one place, an exchange, a chain; the log line once per check.
- `failures`: two sources of one title in one pass → two notices; one source twice in 24 h → one; an event of another source does not block; old events without `source` do not count.
- Migration 0016: upgrade on a copy with the column and with children rows; the column is gone and the children are intact.

## Owner check

The session starts the bot itself and writes the launch result in one line, and in a second line what it watched in the log (a poll pass with no `polling title … failed`, `Job "Tracker.poll_due …" executed successfully` within a minute). Nothing for the owner to press: the visible effect is fewer wrong or doubled messages. One thing to see on the PC: «Лента» and «Мои тайтлы» open without an error page after the migration, the same titles as before.

«Не так»: an error page, titles missing from the list, `alembic` errors in the log at the start.
