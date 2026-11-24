# Review 9.1d: «Входящие», copies and code health — the known issues

Status: in review

One session (2026-11-24).

## What was reviewed

- Commits `114c522..ec987fb` (after the accepted slicing): tickets 01 (3f2c917), 02 (079a49f), 03 (9bd3fbc), 04 (56b4f4f), 05 (5c6f2d7) and their «accepted» commits; the spec, the five tickets.
- Against `spec.md` (sections 1–17) and `docs/coding-standards.md` (rules 1–11, with `CONTEXT.md` for rule 5 and ADRs 0005, 0007, 0010, 0012, 0015), with the `code-review` skill at effort xhigh over the 70 changed files of `app/` (line by line, removed behaviour, callers, language pitfalls, the wrappers `OwnerChat` and `Chat`, the rules of `CLAUDE.md`), then a pass for the spec: every section compared with the code — the moves of 1.2 and `core.py` (464 lines), `export_extras`, the one `feed` action, `FilmDate`; `ReleaseDate.phrase`, `of_day`, `of_period`; `airedOn` in the four queries, the stub through `part_episodes`, storage, `_keep_season`, the key of 4.4, `premiere()`, the card, the message, «Позже» and the export; migration 0018; `Assembled.late` and `_newly_out`; `series_moves` and the hour line; the middle name, «from», `: N`, the companies request and the 20-games rule, the stop list; `first_release`, `released_line`, the English search and the same-id rule, the links of a kind press, the budget of 8.4; migration 0019, `answered_at`, `inbox_unanswered`, the start of the bot; the `Z` names, `name_moment`, the zone of Settings in the block, the notice, the report and the restore, the Drive pages and twins, `OLDER`; `.env.example` and its test. Also the tickets' «Done when» lists, the `KNOWN_ISSUES.md` entries and index rows (KI-49, 56–64, 66–69, 71, 81, 83, 84 fixed; KI-85 open), the rule 7 table, `CONTEXT.md`, the Gotchas and service rows of `PROJECT_CONTEXT.md`, `docs/backups.md`.
- One wording slip of the spec, no bug: 10.1 names the `settings` row `time_zone`; the row is `timezone` (`SettingsStore.TIMEZONE_SETTING`), and the restore reads that one.

## Tests

- At the start: 5438 passed, 3 skipped; only the two known Windows failures (`test_app_main`, `test_runtime`). `pyflakes app tests` clean. The largest module of the core: `pollers/game_follow_ups.py`, 400 lines (the limit).
- At the end (after the fixes): 5450 passed (the 12 new tests of F1–F3), 3 skipped; the same two known Windows failures, nothing new. `pyflakes app tests` clean; the code map unchanged (no docstring changed).

## Verified by running

- **The owner's database** (read-only): migration 0019; the three anime of 4.6 hold their stubs — «Ванпанчмен» season 3 episode 13 `month` 2027-01, «Монолог фармацевта» `month` 2027-04, «Реинкарнация безработного…» episode 15 `year` 2027; no waiting inbox item; `data\backups` mixes the old names with two `Z` names (`…20261124_131848Z_manual.db`, `…20261124_161816Z.db`). No zone in Settings, so everything is shown in `BOT_TIMEZONE`.
- **The core of the real code on a copy of that database** (SQLite backup API, a sender that refuses to send): the card lines «Сезон 3, часть 1: вышло 12 из 12; часть 2 — в январе 2027» and «…вышло 14 из 14; часть 2 — в 2027»; «Позже» — «Ванпанчмен — Сезон 3, часть 2 — премьера», «январь 2027» on 31 Jan 2027, «Реинкарнация…» «2027» on 31 Dec 2027, beside the games «3 квартал 2027», «2027», «2028»; «Монолог фармацевта» stays in «Скоро» with part 1. The JSON export: the three `"air_at": null, "approximate"` («2027-04», «2027-01», «2027») and `expansion_of` of both Witcher 3 expansions; the Settings block over an old and a `Z` name; `inbox_unanswered` empty.
- **Probes of the candidate rules**: the code of 9.1d against the code before it (`git show 114c522`) on forwarded posts — F1, F4, F5 and KI-86 below.
- **The bot in Docker**: before the fixes up 4 hours, healthy, `/health` 200, no error in the log. With the fixes (`.\start-bot.ps1`): «Готово», `/health` 200, polling started, `Job "Tracker.poll_due …" executed successfully` within a minute (Russian check 1 game, 0 failed), no `polling title … failed`, no error or traceback.
- Not run live here: the restart of the bot with an unanswered item (tests with a fake dispatcher and bot; ticket 04), the companies request and the English search (ticket 03 and 04 live checks), a Drive folder of 1001 files (a fake with two pages).

## Findings

- **F1 — a number after a colon joins the name before «сезон» or «часть»: «The Boys: 5 сезон» → «The Boys: 5».** KI-60 (ticket 03) made `: <number>` part of a Latin run unless an episode word follows; before 9.1d a bare number never joined. A season or a part word counts the piece as an episode word does, and posts about series and anime use it often («Arcane: 2 часть»); the glued name may match no record. Probed: «Вышел трейлер The Boys: 5 сезон…» gave «The Boys: 5», now «The Boys». Decision: **fixed now** — `_PIECE_WORD` also takes «сезон», «season», «част…», «part» (a test per word, and «party» is no part word). Other counting words after the number («Hades: 2 дня…», «Elden Ring: 10 из 10», «Stalker 2: 1 место») still glue it: **defer `KI-86`, fix in 9.2** (which words, or another rule that keeps «Fallout: 76 вчера», is a design choice to make with real posts).
- **F2 — «Что это?» for an item a newer message moved to «Входящие».** `InboxAnswers._ask` (ticket 04) read the item and marked `answered_at` only when it still waited, but answered `ASK` either way; spec 14 wants nothing for an item that no longer waits (a message during the start, or during the seconds of the link lookups of the pause). Decision: **fixed now** — `_ask` answers nothing for an item that no longer waits (a test). The same gap on the offer path of the pause (`_finish` shows the card of the links of a moved item) is older, stage 6.4: **defer `KI-87`, fix in 9.2 if met**.
- **F3 — the companies request goes before the link lookups of the pause.** `by_links` asked IGDB about the candidates before it knew whether any link gave a kind; with none it returns before the names are searched, so the request (and, without IGDB keys, its warning) was for nothing. Decision: **fixed now** — asked after the kind is known (a test: links that give nothing ask no companies).
- **F4 — the series «From» is no candidate any more.** Spec 7.2 drops «from» as the start of a Latin run and makes «from» alone nothing; «Вышел трейлер 4 сезона сериала From…» gave «From» (14) before 9.1d and now only the fallback. Decision: **defer `KI-88`, fix in 9.2 if met** (one title; a name message «From» is searched as typed).
- **F5 — a Russian name with a hyphen is cut at the hyphen: «Человек-паук» → «Человек».** The middle name of 7.1 is a capital and lower-case letters. Decision: **defer `KI-89`, fix in 9.2 if met** (weight 2, a quote, bold or Latin name wins).
- **F6 — rule 7 of `docs/coding-standards.md`: the check text added by ticket 01 is Russian** («модули находит glob …»), while `CLAUDE.md` says that everything written from 2026-11-01 is English. Decision: **fixed now** (that clause in English, as the other additions of the file); the whole file is a wish (below).

No finding needs a fix round: the stage closes once the owner accepts.

## Wishes for later stages

- 9.2: KI-86 with the real posts of the first weeks (the counting words after `: N`); watch the first exact premiere day of the three anime of 4.6 — «объявлена дата» must come once, with the key of 4.4.
- The next change of `pollers/game_follow_ups.py` (400 lines, the limit of rule 7) splits it first.
- 8 (cleanup): `docs/coding-standards.md` in English as a whole — it mixes Russian rules with English additions since stage 6.
