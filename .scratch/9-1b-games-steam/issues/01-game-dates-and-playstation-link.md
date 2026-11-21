# 01: Game dates and the PlayStation link — KI-35, KI-36, KI-37, KI-38

Status: open
Complexity: medium (dates and events of games, one new route)
Blocked by: —

Spec: `../spec.md`, section 1 (1.1–1.4), section 8 (the lines on a release in Japan and a late release that folds), the first, second and fourth lines of the automated tests of section 9, the PlayStation Store row of section 7. Terms — `CONTEXT.md`; ADRs to read: 0009 (why no PlayStation prices; this ticket reads no price), 0004 (no own JavaScript). Standards — rules 1, 2, 7, 8, 9, 10, 11. Known issues: KI-35, 36, 37, 38. Fixtures: none to copy (the PlayStation pages are too big to keep, spec 1.4; the test fakes the `HEAD` answers `200` and `302 Location: /<locale>/error?conceptId=…`).

## What to do

- **KI-35 (1.1).** `games.pick` takes only the records of the regions of the country (`STORE_COUNTRIES[country].regions`, in their order); the fallback to the earliest of the others goes. `follow_ups.follow_up_date` reads through the same `pick`. A platform with records only outside those regions: «PS5 — дата не объявлена», no «вышла», no Feed piece, no effect on `check_interval`.
- **The outside line (1.1).** Pure, in `game_rows`: from the full-release records (own IGDB platform and its older one) outside the country's table, announced dates only, over the platforms of «Мои платформы» the game is on and that are not cancelled; the earliest by start; shown only when it ends earlier than the platform's own date for the country (or the platform has none). Text `«в <region> — <date label>»` with the region words of the table in `platforms` (rule 6): 3 «в Австралии», 4 «в Новой Зеландии», 5 «в Японии», 6 «в Китае», 7 «в Азии», 9 «в Корее», 10 «в Бразилии», 0 «в другой стране». `CardPart.outside_date: str` (empty — none). Web card: a row after the platform rows, no checkbox, with the hint «Дата только в Японии — не выход для вашей страны: сообщения «вышла» по ней не будет.»; bot card: the same line after the platform lines.
- **KI-36 (1.2).** Replace the 30-day rule (`game_events.FRESH`): «вышла» and «вышла в раннем доступе» come when the new date is an exact day not later than today, the previous snapshot did not have it out, and the day is not earlier than 30 days before the tracker began following the game (the later of `Title.added_at` and `Title.restored_at`, UTC date). `GamePoller.apply` reads it in the read session it opens already and passes `since: date` to `detect_events`. The late form: a day earlier than yesterday is named — «🎮 Hades II вышла на ПК 5 октября», «…вышла в раннем доступе на ПК 5 октября», another year «5 октября 2025»; the payload gets `late` (the day as stored text, absent when on time) and `game_events.fold_key` of these two types adds `late`. No migration, no mark per platform.
- **KI-38 (1.3).** `GameDate.from_igdb`: `date_format` missing or not 0–7 → a year (`y`, else the year of `date` in UTC), never a month or a day; 7 stays «not announced». The KI example `{"date": 1795046400, "y": 2026}` reads «2026» and gives no message.
- **KI-37 (1.4).** Route `GET /titles/<id>/playstation` (`card_playstation`, behind the login, rule 10) and `Tracker.playstation_link(title_id)` through the facade: the core reads the concept, the original name and the country (no network), then one `HEAD` without redirects (5 s; rule 8 — answer first, work, report): `200` → the concept page; `302` to an address with `/error` → the search by the original name; a failure or any other answer → the concept page. Kept in memory a day per (locale, concept). The route answers `302` to that address; a title gone, not a game or without the link → the card. The web card's «Открыть в PlayStation Store» leads to this route when the game has a concept; without a concept the link is the search as now (no request). The bot's text line («PS Store: …») keeps the concept address.
- **Docs:** docstrings of the changed and new modules, `tools\code_map.py`, `docs/tests-map.md`, rule 7 table of `docs/coding-standards.md` if a module is added; `KNOWN_ISSUES.md` — KI-35, 36, 38 `fixed (test: …)`, KI-37 `fixed (test: …)` with «fixed for the web card; the bot's text link keeps the concept»; the PlayStation Store row of `PROJECT_CONTEXT.md`, «External services» (the `HEAD` check of a concept).

## Done when

- [ ] A date only in Japan gives «PS5 — дата не объявлена», no event, no Feed piece, the outside line «в Японии — 12 марта 2027» (web and bot) and the hint under it; the line is hidden when the platform's own date ends earlier.
- [ ] A game added with no date that later gets an old day, and a «2015» that becomes «19 мая 2015», stay silent; a release 20 days before the game was added is told in the late form; after «Вернуть в список» the since-day moves.
- [ ] Two platforms released on different late days give two lines (no folding); the same late day folds into «вышла на ПК и PS5 5 октября».
- [ ] A record with a missing or unknown `date_format` reads as a year and gives no message.
- [ ] The three answers of the route (`200`, `302 …/error`, failure) lead to the concept page, the search, the concept page; the second click within a day asks nothing; the route redirects a missing title, a non-game and a game without the link to the card; a logged-out request goes to the login.
- [ ] KI-35, 36, 37 (web), 38 are `fixed (test: …)`; pyflakes clean; the code map rebuilt; no core module over 400 lines (the facade 500); the full suite green (the known Windows failures are not new).

## Tests to add

- `pick` without outside regions; the outside line (shown; hidden when the own date is earlier; every region word; the older platform; cancelled platform and a platform the game is not on are left out).
- `from_igdb`: no `date_format`, `date_format` 8 and −1 → year; 7 stays «not announced»; the KI example.
- The since-rule on `detect_events`: today (as before), 20 days before adding, 40 days before adding, no date → old day, after `restored_at`; the late text on the day-before-yesterday, a day of another year; `fold_key` with `late`.
- `playstation_link` with a fake `HEAD`: `200`, `302 /error`, a timeout, `500`; the day cache (a second call asks nothing, another locale or concept asks again); the route: login required, title gone, not a game, no concept (the search, no request), the `302` address.
- The card lines: web row and hint, bot line, empty `outside_date`.

## Owner check

The session starts the bot and writes the launch result in one line. Then, in the browser at `http://localhost:8080`: open the card of a game on PS5 (for instance Bloodborne or Hades II), press «Открыть в PlayStation Store» — the store page of your country opens (a page of the game, not «Ошибка»). A Japan-only date, a late release and a record without precision have no live case: the tests show them.

«Не так»: the button leads to a store error page for a game the store has; an error page of the app instead of the store.
