# Review 9.1c: Лента, web and login — the known issues

Status: accepted

One session (2026-11-23).

## What was reviewed

- Commits `b77174c..2cead07` (after the accepted slicing): tickets 01 (208e4ac), 02 (b37dc61), 03 (de60ca1), 04 (16c761a), 05 (d897ff6) and their «accepted» commits; the spec, the five tickets.
- Against `spec.md` (sections 1–16) and `docs/coding-standards.md` (rules 1–11, with `CONTEXT.md` for rule 5 and ADRs 0004, 0005, 0007, 0014), with the `code-review` skill at effort high over the stage diff (line by line, removed behaviour, callers, the rules of `CLAUDE.md`), then a pass for the spec: every section compared with the code (the timing table of 1.1, the rule of 1.2 in the Feed, both cards and the bot messages, KI-77, the request and the strict reading of 1.5, the rows of 2.1–2.3 and their texts, the genre table, the CSS rule, the form of «Найти», the report types in `due` and «Сводка сейчас», the table of the mark, IDNA and `shown`), the tickets' «Done when» lists, the `KNOWN_ISSUES.md` entries and index rows (KI-28, 29, 30, 32, 65, 73–77 fixed; KI-48, 72 won't fix; KI-81, 82 new), the rule 7 table, `CONTEXT.md` (Серия, Жанр, Лента, Сообщение о входе, Вход, Адрес приложения), the Gotcha of 1.5 and the `APP_URL` row of `PROJECT_CONTEXT.md`, `docs/outside-access.md`.

## Tests

- At the start: 5048 passed, 3 skipped; only the two known Windows failures (`test_app_main`, `test_runtime`). `pyflakes app tests` clean.
- At the end (after the fixes): 5048 passed, 3 skipped; the same two known Windows failures, nothing new. `pyflakes app tests` clean.

## Verified by running

- **The owner's database** (read-only): migration 0017 applied; 1446 anime episodes — 21 `day`, 6 `exact`, 1419 `unknown`; 185 series episodes `day` — the table of spec 11. 34 titles, none without `added_at`, 2 returned from the archive.
- **A scratch web app of the real code** on a copy of that database (SQLite backup API; a scratch password and key, a sender that refuses to send), walked over HTTP by a script: the Feed answers 200 — «Скоро» gives «Монолог фармацевта» its hour (exact), «Недавно» shows episode 8 on 20 ноября; no rows from the schedule today (nothing added in the last 7 days — the rows are covered by `tests/test_tracker_feed_released.py`). The Archive genre row has each genre once («Боевик», «Драма», «Криминал», «Приключения», «Ролевая», «Триллер», «Ужасы», «Фантастика», «Фэнтези» — no «Экшен», no «НФ и Фэнтези»); `?genre=Экшен` and `?genre=экшен` mark «Боевик», `?genre=НФ и Фэнтези` marks «Фантастика». Settings answers 200.
- **Probes of the pure code**: `parse_app_url` — `https://ТРЕКЕР.РФ:8443` → `https://xn--e1aaowdh.xn--p1ai:8443`, shown `https://трекер.рф:8443`; `https://трекер` → the reason about the dot; a 64-letter label → «имя сайта записано с ошибкой…»; a trailing `/` taken. The two cases of F1 and F2 below.
- **The bot in Docker** (`.\start-bot.ps1` after the commit of the fixes; Docker Desktop had to be started first): «Готово», `/health` 200, `Job "Tracker.poll_due …" executed successfully` within a minute (price check 4 games, Russian check 11 games, 0 failed), no `polling title … failed`, no warning about the sign-ins file (the mark matched), no error or traceback.
- Not run live here: the phone width (the CSS rule is pinned by `tests/test_web_css.py`; ticket 04 looked at 375 px), a stopped network for KI-73 and a Cyrillic `APP_URL` in `.env` (ticket 05 did both).

## Findings

- **F1 — an anime episode first seen with an AniList airing earlier than the previous look comes with no message.** `anime_events.assemble` keeps the fresh `exact` moment of an episode found now (spec 1.1, ticket 02); when that episode was not stored at the previous look and its airing is earlier than that look, `series_events._newly_out` counts it as a backfill of history and queues nothing. Before the stage it got the moment of the look and was reported. Needs an episode AniList did not announce as the next one, seen first one look late (a drop of several episodes, a lagging counter, AniList down at the look) — rare; the episode is in the card and the Feed, only the message is missing. Probed: `came == []`. Decision: **defer `KI-83`, fix in 9.1d** (a rule of what is news plus a test: a design choice, not minutes; a fix round would cost five sessions for a rare case). The owner chose 9.1d over a fix round (2026-11-23).
- **F2 — an anime premiere moved by hours within its day reads «9 янв 2027 → 9 янв 2027».** `message_moved` writes the days only for a premiere, while `_moved` reports any change of an `exact` moment. Older than the stage for moments not at 00:00 UTC; the stage extends it to `exact` moments at 00:00. Decision: **defer `KI-84`, fix in 9.1d** (what the line says is a small text decision).
- **F3 — rule 7: `series_events.py` grew from 534 to 547 lines, `cards.py` reached 400.** The size test misses the pure modules (KI-56, open, 9.1). Decision: **defer** — the figures of KI-56 updated.
- **F4 — the Feed loads the seasons and episodes of series and anime twice** (`feed_pieces` and the new `feed_released` each call `storage.load_seasons_of`). The number of reads stays constant, so the rule of the Feed holds; it is double work on the heaviest part of the page (One Piece has 1180 episodes). Decision: a wish (below).
- **F5 — the identity of a film date in `feed_released` is its display text** (`Out.film` and the keys of `logged` are «Премьера в кино» / «Цифровой релиз»). Works, as both sides read one constant. Decision: a wish (below).
- **F6 — a nested `def clock()` in `app/main.py` without a blank line before it.** Decision: **fixed now** (with a comment on what the clock is shared for).

No finding needs a fix round: the stage closes once the owner accepts.

## Wishes for later stages

- 9.1d (code health): load the seasons of the Feed once and hand them to both `feed_pieces` and `feed_released` (F4); a small enum for a film date instead of its text (F5); KI-56 with `series_events.py` split — it is the module the anime fixes of 9.1d (KI-81, 83, 84) touch.
- 9.2: watch the first weeks of the airings (spec 1.5) on the NAS — the moments of «Недавно» and «Сегодня» for running anime.
