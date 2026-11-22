# Review 9.1b: games and Steam prices — the known issues and Russian in games

Status: in review

One session (2026-11-22).

## What was reviewed

- Commits `edaaf60..918e4d2` (after the accepted slicing): tickets 01 (5966e69, d881dfd), 02 (7ef8ba9), 03 (4f659c0), 04 (c872790, c24bac5), 05 (acf9338, 9441960), 06 (63891a3) and their «accepted» commits; the spec, the six tickets, ADR 0016.
- Against `spec.md` (sections 1–11) and `docs/coding-standards.md` (rules 1–11, with `CONTEXT.md` for rule 5 and ADRs 0004, 0009, 0011, 0015, 0016), with the `code-review` skill at effort xhigh over the stage diff (line by line, removed behaviour, callers, language pitfalls, wrappers, the rules of `CLAUDE.md`), then a pass for the spec: every section and the rows of sections 6, 7 and 10 compared with the code, the tickets' «Done when» lists, the 14 `KNOWN_ISSUES.md` entries and index rows, KI-79 and KI-80, the rule 7 table, the tests map, `CONTEXT.md`, the External services rows of `PROJECT_CONTEXT.md`.

## Tests

- At the start: 4838 passed, 3 skipped; only the two known Windows failures (`test_app_main`, `test_runtime`). `pyflakes app tests` clean.
- At the end (after the fixes): «Tests at the end» below.

## Verified by running

- **The owner's database** (a read-only copy by the SQLite backup API; the bot in Docker running the reviewed code): the Russian and ZoG snapshots of the 12 games and `bot.log`. The first pass after the update (2026-11-21) made both snapshots of every game in «Хочу» and «В процессе»; ZoG read two games a minute; today's start: one Steam languages request for six games in the US store, the God of War games recorded as reference points after their own poll gave IGDB's languages; no message, no failure, no traceback. GTA VI (no Steam page, own snapshot from before the update) is due every minute and logs «Russian check: 1 games, 0 failed» (F2).
- **A scratch web app of the real code** on that copy (a scratch password and secret, the messages kept in a list, sources that fail if asked, a ZoG client that serves the saved pages, the real PlayStation client), walked over HTTP by a script:
  - the cards of all 12 games: Hades II and Elden Ring «текст — официально; озвучка — народная» with «Страница перевода» and the bot button «🌐 Страница перевода»; Hunter: The Reckoning «официально нет (ПК)» with the «(ПК)» hint and «Страница на ZoG не найдена…»; Blood and Wine «текст и озвучка — официально (ПК)»; God of War Laufey «нет данных» with «IGDB — проверено …» and «Языки ещё не объявлены. Проверяю: IGDB — …»; Star Wars: Galactic Racer «текст и озвучка — народные»; a game in «Пройдено» without data — no block; GTA VI «нет данных» with «Ещё не проверяли — строка появится через минуту-другую» (F2); the bot lines are the web lines;
  - «Открыть в PlayStation Store»: GTA VI and Hades II → their concept pages in `en-il` (a real `HEAD`, 200); a missing title → the card;
  - «Страница на ZoG» on Hunter: `привет` → «Это не страница игры на ZoG…» with `привет` kept in the field; empty → «Вставьте ссылку…»; a page ZoG answers «Ошибка» → «На ZoG нет такой страницы…»; a link to a file of `baldurs_gate_3` → saved as the owner's page, «текст и озвучка — народные (ПК)», the link and «Не та игра»; «Не та игра» → «Страница на ZoG не указана…»; a game in «Пройдено» → the card without the form; ZoG asked twice in all, no message sent.
- **One real ZoG page** (`star_wars_galactic_racer`) read by the client and the parser: four entries, all «для ПК-версии», text and voice — the line of the card is right.
- **`zog_pages.entry_parts`** on entries of consoles with names of two words (F1): «для Xbox 360-версии», «для Nintendo Switch-версии», «для PS Vita-версии» counted as PC before the fix, not after.

## Findings

- **F1. A ZoG patch for a console of two words counted as a PC patch.** `app/tracker/sources/zog_pages.py`: the platform phrase was `для\s+(\S+?)-версии`, so «Русификатор (текст) - для Xbox 360-версии» (or «Nintendo Switch», «PS Vita») matched no platform and counted as fan Russian for PC: a false «текст — народный» on the card and, when the page was read before, a false «вышел народный русский перевод текста». Decision: **fix now** — the phrase takes any words up to «-версии» / «-версий», and the entry counts only when «ПК» is one of them («для ПК- и Switch-версий» counts, «для PS4- и PS5-версий» does not); five cases added to `tests/test_zog_pages.py`.
- **F2. A game added before 9.1b says «Ещё не проверяли — строка появится через минуту-другую» until its own poll, up to a week.** `GameRussian._store`: until the own poll gives IGDB's languages, nothing is stored and a game without a Steam page stays due — its card says «нет данных» with that hint and the log gets «Russian check: 1 games, 0 failed» every minute. On the owner's PC: GTA VI since 2026-11-21, its own poll on 2026-11-27. KI-79 said such a game is not affected. Decision: **defer KI-79** (widened: title, text, the GTA VI case) — it happens once per old game and ends by itself when the game's own poll runs (at most a week after the update); new games have IGDB's languages from adding. A fix needs a choice (a hint of its own, or the own poll made due at once): 9.2 if met.
- **F3. A bug in the ZoG check was logged as a failure of ZoG.** `GameZog.check`: every exception of one game was a warning with `%r` and a retry in 6 hours, so a bug in reading a page would never show its traceback. Decision: **fix now** — `ZogError` stays the failure (a warning, 6 hours, no message); any other exception goes to the log with its traceback (`logging.exception`), as in the other checks of the end of a pass; `tests/test_tracker_zog_check.py` pins it.
- **F4. Two glossary entries «Народный перевод».** `CONTEXT.md`: ticket 05 wrote the entry with its words in code, the older one of idea 002 (with «In code: not in code yet») stayed below «Проверка русского языка». Decision: **fix now** — the older entry deleted.
- **F5. The index rows of KI-35–38 named a ticket.** `KNOWN_ISSUES.md`: Fix in `9.1b.01`, the other ten rows of the stage `9.1b` (as review 9.1a, F3). Decision: **fix now** — `9.1b`.
- **F6. A docstring gave the owner a pronoun.** `GameZog._moved`: «his state stays». Decision: **fix now** — «the owner's state stays».

No fix-round finding: the stage closes with this review.

## Wishes for later stages

- 9.1c, 9.1d: `app/tracker/core.py` has 490 of its 500 lines; a stage that adds facade methods first moves a group of them out (or trims the docstrings) — not a new module per method.
- 9.2: KI-79 only if met after the update (by then every old game has had its own poll); KI-80 if the log says «ZoG page … cannot be read». On the NAS, a look at the log for «ZoG check of title … failed by a bug».
- ADR 0011 stays; its last consequence (KI-52: a standalone expansion completed before 6.3 never learns it is one) is no longer true — said in `docs/history.md` with this review.

## Tests at the end

4844 passed, 3 skipped; only the two known Windows failures (`test_app_main`, `test_runtime`). The six new cases are F1's five entries and F3's bug. `pyflakes app tests` clean; the code map rebuilt (unchanged).
