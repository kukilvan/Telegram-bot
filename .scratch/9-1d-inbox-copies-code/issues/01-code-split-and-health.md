# 01: The code split and code health — KI-56, KI-63, KI-71, F4, F5

Status: open
Complexity: medium (many files touched, no new behaviour; the same tests pass with their imports changed)
Blocked by: —

Spec: `../spec.md`, sections 1 (1.1 the size test, 1.2 what moves, 1.3 `core.py`) and 2 (2.1 KI-71, 2.2 F4, 2.3 F5), the «Split» line of the tests of section 15, the `docs/coding-standards.md` line of section 16. Terms — `CONTEXT.md`. ADRs to read: 0005 (migrations are not touched), 0007. Standards — rules 1, 7, 11 (and 9 for the tests). No fixtures from `answers/`.

## What to do

Work in this order; each step leaves the suite green. Behaviour does not change: if a test needs a new expected value, stop — the move went wrong.

1. **The size test first (1.1).** `tests/test_tracker_core_split.py`: `test_no_part_of_the_core_is_longer_than_the_limit` takes every `app/tracker/**/*.py` except `core.py`, `migrations/` and `__init__.py`, found by a glob (not a list). It fails now on `series_events.py`, `games.py`, `cards.py`, `sources/shikimori_anime.py`, `offers.py`; the steps below make it pass. `docs/coding-standards.md` rule 7: its «Check» names the glob.
2. **The moves (1.2).** Six modules, one commit-sized step each; callers import from the new module, nothing re-exports what moved out:
   - `series_messages.py` out of `series_events.py`;
   - `release_dates.py` out of `games.py` (`GameDate` is renamed **`ReleaseDate`**, 85 uses; the methods stay: `parse`, `from_igdb`, `announced`, `exact`, `text`, `label`, `start`, `end`; `games.released_by` stays in `games.py`; do **not** add `phrase`, `of_day`, `of_period` — ticket 02);
   - the date and moment words out of `cards.py` into the existing `moment_words.py`;
   - `sources/shikimori_chain.py` out of `sources/shikimori_anime.py`;
   - `offer_cards.py` out of `offers.py`;
   - `candidate_words.py` out of `candidates.py` (the word lists only; ticket 03 adds to them).
   Each new module gets its docstring (first sentence = its line in the code map). `PURE` of the split test gets `release_dates`, `series_messages`, `sources/shikimori_chain`, `offer_cards`, `candidate_words`; each must still import nothing it must not (the test says what).
3. **`core.py` ≤ 470 lines (1.3).** Shorten the facade docstrings that retell their part to at most two lines each; no method moves out.
4. **KI-71 (2.1).** `Poller.export_extras(session, title_ids) -> dict[int, dict[str, Any]]`, default `{}`; `GamePoller` answers `{title_id: {"expansion_of": <name>}}` by its own `parent` (the list's name when the list has the base game, else the name IGDB gave; an unreadable state leaves the game out with today's warning). `export_all` asks the poller of every kind present (`Pollers.reader_of`) and writes the fields into the title's object; `_parents` and its query go; `Exports` gets `pollers` in the assembly. `export_all` joins `MODULES` of the split test (the test of the kind question passes).
5. **F4 (2.2).** `feed_pieces` and `feed_released` become one action `feed(session, shown, basis, now) -> FeedParts` (`pieces`, `outs`); base default both empty; the seasonal poller reads `storage.load_seasons_of` once and cuts both from it; movie, game, anime (its films) as now. `FeedReader` calls it once per kind. The test of the set of poller actions lists `feed` instead of the two.
6. **F5 (2.3).** `feed_released.Out.film` becomes `FilmDate | None` (`FilmDate.THEATRICAL`, `FilmDate.DIGITAL`, a `StrEnum` in `feed_released`); the texts «Премьера в кино» and «Цифровой релиз» stay in `feed_rows`, read through the table `FILM_LABELS`; the verb («вышла» / «вышел») is chosen by the enum.
7. **Docs.** `.\.venv\Scripts\python.exe tools\code_map.py`; `docs/tests-map.md` (the split test, any new test module); `KNOWN_ISSUES.md`: KI-56, KI-63, KI-71 → `fixed (test: …)` in the entries and the index (KI-56 and KI-63 by the glob test; KI-71 by the export test), «Fix in» 9.1d.01.

## Done when

- [ ] The glob size test passes: no module of `app/tracker/` besides `core.py` is over its limit; `core.py` is at most 470 lines.
- [ ] The export JSON of a sample base with an expansion, a sequel and every kind is byte for byte the same before and after (the test compares to a document made before the change — make it first).
- [ ] The Feed of a sample base (pieces and «Недавно») is equal before and after (same method: record first).
- [ ] No module re-exports a moved name; `GameDate` does not exist in the code; `pyflakes` clean; the code map rebuilt; the full suite green (the known Windows failures are not new).

## Tests to add

- The glob size test (1.1) and the extended `PURE` / `MODULES`.
- The export JSON before/after on a sample base; `GamePoller.export_extras` (base game in the list, base game not in the list, unreadable state); a kind with no poller answer gets `{}`.
- The Feed before/after; one `feed` call reads the seasons once (a spy on `load_seasons_of`); the set of poller actions; `Out.film` as an enum and the labels through `FILM_LABELS` («вышла» / «вышел»).

## Owner check

The session starts the bot and writes the launch result in one line. Nothing new to see; the check is that nothing broke. In the browser, `http://localhost:8080`: the tab «Лента» opens and shows its sections as before; open any card; in «Настройки» press «Скачать всё (JSON)» — a file downloads. «Не так»: an error page, an empty Лента for a list that is not empty, or red text in `.\logs-bot.ps1`.
