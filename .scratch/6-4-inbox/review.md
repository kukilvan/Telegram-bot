Status: accepted

# Review of stage 6.4: «Входящие» — add a title from Telegram by a post or a name

## What was reviewed

- Commits `975132f..4605d5b` (after the accepted slicing), tickets 01–05 of `issues/`: f1be0ec (01), 164ac48 (02), 3525269 (03), 4b8e1fe (04), d9c31cc (05), and their «in review» / «accepted» commits.
- Against `spec.md` (sections 1–16) and `docs/coding-standards.md` (rules 1–11, with `CONTEXT.md` for rule 5 and ADRs 0002, 0007, 0010), with the `code-review` skill: one pass for the standards, one for the spec, each in its own sub-agent; their reports are below, lightly cleaned. The tickets have no Comments, so no agreed deviations. The findings and the decisions are in «Findings».

## Tests

- At the start: 3456 passed, 2 skipped, 3 failed — the three known Windows failures (`test_app_main`, `test_docker_files`, `test_runtime`), nothing new. `pyflakes app tests` clean, `docs/code-map.md` current.
- At the end (after the fixes): 3458 passed (two new tests), 2 skipped, the same 3 known Windows failures; `pyflakes` clean, the code map current.

## What was verified by running

- **The real sources through the real core** (2026-11-06; a copy of the owner's database made by the sqlite backup API, the bot's own file only read; TMDb, IGDB, Shikimori, Steam live):
  - the 18 samples, kind pressed as in 4.6 — the first offers of table 5.6 exactly; sample 5 gives Phantom Blade Zero, Black Myth: Wukong, then «Уже в списке» (Elden Ring is in the owner's list), sample 14 «Уже в списке» at once (in the list), sample 12 «Не нашёл»;
  - the typos of 5.4: «Phantom Blad Zero» → Phantom Blade Zero, «Cyberpnk 2077» → Киберпанк 2077 and Cyberpunk 2077: Turf Wars, «Игра в кальмра» → Игра в кальмара and «…: вызов», «Eldn Ring» → Elden Ring (2028), all under «Возможно, вы имели в виду:»; «Реинкарнация безработнго» and «Ведьмак 3 Дикая охта» → «Уже в списке» (both in the list); «Dead-End Job» → the weak offer «Работа с призрачными перспективами»;
  - links: Steam 1245620 → «Уже в списке», 2622380 → Elden Ring Nightreign at once, 4000000 → «Что это?»; TMDb movie 1485839 and tv 289517; IMDb tt0111161 → «Побег из Шоушенка»; Shikimori z39535 → «Уже в списке»; a YouTube link → «Что это?»;
  - dates of announced titles: found F9 (The Witcher IV → «выйдет 31 декабря 2028»).
- **The live web** (HTTP with the login): `/inbox` without the login → 303 to `/login?next=/inbox`; the menu «Входящие» without a number (the one waiting item is not counted) and the empty sentence; Search with `inbox=12` shows «Из «Входящих»…» and carries the number in the form; `inbox=abc` is ignored; «Убрать» of a missing item: 303 to `/inbox` without HTMX, 200 with the out-of-band menu with HTMX.
- **The live bot** (Docker, the owner's PC): container `healthy`, `/health` 200; `Tracker.expire_inbox` runs every minute in a job of its own and succeeds; no warning in the log since the start.
- **The spec pass** ran the 18 samples on the saved answers (candidates of 4.6 with their weights, offers of 5.6, 1–3 searches each), 11:59 / 12:00, a comment followed by a forward, a double «Нет», a kind press on an item in «Входящие», a Steam link without the keys of IGDB, the cut text and the dates of the web page.
- **The fixes**: the new tests of F7 and F8 fail without the fix and pass with it.

## Standards (report of the standards pass)

Tooling clean: `pyflakes`, `test_tracker_core_split`, `test_code_map`, `test_code_speaks_glossary`, `test_web_skeleton`, `test_tracker_early_answer`. Rules 1, 2, 3, 4 and 9 hold in the new code (one write session per change, no session inside a write session, the stored offers read strictly by `parse_date`, the zone read in the session); ADRs 0002, 0007, 0010 not contradicted («➕ Добавить» is gone, any text but a command or a menu button is taken in, the item is written before any answer).

Documented rules:
- Rule 8: `inbox_handlers.press` reads the item (and its number of offers) from the database before the early answer; the rule says «без сети и базы». Spec 2.2 asks for the popup «Эта запись уже разобрана.», so the code follows the spec against the rule.
- Rule 5: `Candidate` names two concepts — the name candidate of `candidates` (the glossary's «Кандидат») and the expansion or game of `follow_ups` (6.3); «offer» is the inbox `Offer` and also `FollowOffer` / `offers_follow_ups`.
- Rule 7: `sources/shikimori_anime.py` 464 lines (457 before; KI-63); `posters` is pure in rule 7 but missing from `PURE` of `test_tracker_core_split.py`.
- Rules 7 and 10: `core` re-exports the names of `posters`, and the web and the bot import them from `core`, while rule 10 now lets the web import `posters` directly — two doors.

Judgement calls (smells): the data clump `(text, bold, links, forwarded)` passed to `candidates`, `query_of`, `is_name_message`, `source_links`; `SourceLink.source` a string switched on in `offers._look_up`; the media keys as strings in three places; «the core has no source of that kind» as `KeyError` in five places, two of which could ask `Pollers.reader_of`; «why no offer» in three forms (`Found` flags, `InboxOutcome`, `_REASONS`); `web/inbox.when_text` close to `cards.format_past_moment`; `suggest_by_id` the same in the two TMDb adapters; texts of `inbox_handlers` copied from `tracker_handlers`; `forget_inbox_item` and `resolve_inbox` both delete; `SourceLink.prefix` never read; the menu texts passed to the inbox handlers; two imports from `core` in `web/search.py`; `bot/tracker_handlers.py` 659 lines (715 before).

## Spec (report of the spec pass)

Checked and right: 1.1–1.3 (fields, the 10,000 cut, the post link of a public channel only, joining, the pause, «нет текста», «Предыдущий…»), 2.1–2.4 (texts, buttons, data, dead `tadd:` / `tpick:`, keyboard, `/start`), 3 (every link form, 3 at most, Steam `appdetails`, IMDb `/find`, without keys), 4 and table 4.6, 5.1–5.6 and table 5.6 (half weight, exact / prefix / weak, «new first» from the same day two years back on the owner's clock, the typos with their counts, the budget, a failure before / after the first offer), 6.1–6.3 (card text, «Да» with `TitleNotFound` as «Нет» and a failure keeping the buttons, «Нет» to the end, double tap), 7 (states, reasons, moves, 12 hours in a job of its own, ids not reused), 8 (posters on every card path, `is_disabled`), 9 (menu number, page, «Найти» address, Search with `inbox`, «Убрать» with and without HTMX), 10 (migration), 13 (KI-57, 58, 59, 61), `CONTEXT.md` and `PROJECT_CONTEXT.md`.

Findings: (a) a title already in the list shows «В списке» in Search with no add form, so «Найти» of its item can never remove it (9.3); `docs/code-map.md`'s templates line lacks `inbox.html` (15), the pure list of rule 7 lacks `posters` (15); (c) a Steam number IGDB does not know sets the item's kind to game before any link gave an offer: with a TMDb link after it the kind is game and the text is searched in IGDB (3: «the kind of the first link that gave an offer»); a message joined after the pause began answering starts a second pause — a second «Что это?» (1.2–1.3, rare); a kind press on an item in «Входящие» that finds an offer keeps the old reason (7.3, no reason of 7.1 fits); table 4.6 lists «Meta Horizon (1)» for sample 11 while 4.5 puts it on the stop list (the code follows 4.5); (b) beyond the spec, all small: Shikimori's English name matched too, a link takes any IGDB record type, two failure texts, the `shown` flag of a stored offer (it makes the double «Нет» of 12 work).

Summary: standards — 4 findings of documented rules and about 14 judgement calls, the worst is rule 8 (a database read before the early answer, which the spec asked for); spec — 7 findings, the worst is the second «Что это?» of a late joined message (rare), and the made-up day of an announced date found by running (F9) is the one the owner will see most.

## Findings

| # | What, where | Decision | Why |
|---|---|---|---|
| F1 | Rule 8: `inbox_handlers.press` reads the item before the early answer | fix now | Spec 2.2 (accepted by the owner) wants the popup «Эта запись уже разобрана.», which only the database knows. Rule 8 gets the exception in its text: a read of the database without the network may come before the early answer when the spec wants a popup for a dead button; the reason of the rule is the minute of Telegram lost to the sources, a read of SQLite takes milliseconds |
| F2 | Rule 5: `Candidate` of `follow_ups` (6.3) and of `candidates` (the glossary's «Кандидат») | fix now | The class of `follow_ups` is `FollowUp` (`FOLLOW_UP_FIELDS`, `_follow_up` in `sources/igdb_follow_ups`, the tests' helper `follow_up`); `CONTEXT.md` «Проверка дополнений…» names it. Nothing stored changes (the class name is not in the snapshot) |
| F3 | Rule 5: «offer» in `Offer` and in `FollowOffer` / `offers_follow_ups` | fix now | `CONTEXT.md` «Предложение»: the «Следить» of an announcement keeps `offer` only inside a longer name, never alone. A rename of the 6.3 names would touch the Feed for no reader's gain |
| F4 | `posters` missing from `PURE` of `test_tracker_core_split.py` and from the pure list of rule 7 (spec 15) | fix now | Both added; the test now checks that `posters` imports no database |
| F5 | «No source of that kind» as `KeyError`: `inbox_answers._show` and `titles._known_suggestions` | fix now | Both ask `Pollers.reader_of(kind).known_ids` (every kind has a reader). The other three places need the source itself and keep the `KeyError` |
| F6 | `docs/code-map.md` templates line lacks `inbox.html`, `inbox_removed.html`, `menu.html` (spec 15); two imports from `core` in `web/search.py` | fix now | The line names them (and `base.html` no longer holds the menu); the imports are one |
| F7 | Spec 3: a Steam number IGDB does not know made the kind game before any offer; with a TMDb link after it the item was a game and its text was searched in IGDB | fix now | `OfferSearch.by_links`: the kind of the first link that gave an offer; none — the kind of a Steam name. Test `test_the_kind_of_an_item_is_that_of_the_first_link_that_gave_an_offer_not_of_a_steam_name` |
| F8 | Spec 1.2–1.3: a message joined when the pause of its item was already answering (the core joins by its clock, the bot ends the pause by its own) started a second pause: a second «Что это?» | fix now | `take_in` of the bot: a joined message whose item is answered or being answered starts no pause; its text is in the item. Test `test_a_message_joined_after_the_pause_is_over_gets_no_second_question` |
| F9 | Spec 6.1: a future date the source knows only to the year or the quarter shows a made-up day — IGDB the last day («выйдет 31 декабря 2028», The Witcher IV), Shikimori the 1st of January | defer `KI-64` | Not a minute's work: the adapters must say whether the day is known (IGDB `release_dates.date_format`, Shikimori `airedOn { day }`), the stored offer keep it, and the text of a date without a day is a choice (the year alone, or the precision of `games.GameDate`). Nothing is stored wrong. The one the owner will meet most: first in line for stage 9, or a fix round if the owner wants it now |
| F10 | Spec 9.3: «Найти» of an item whose title is in the list: Search shows «В списке» with no add form, nothing removes the item | defer `KI-65` | Rare (the bot resolves such an item itself with «Уже в списке»); «Убрать» works. The fix needs a new button and its text |
| F11 | Spec 7.3: a kind press on an item in «Входящие» that finds an offer keeps the old reason | no change | No reason of 7.1 fits «an offer was shown»; the reason says why the item went there, and «Нет» to the end sets «не нашёл» |
| F12 | Table 4.6 lists «Meta Horizon (1)» for sample 11; 4.5 puts it on the stop list | no change | The stop list wins (spec 4.5), the test says so; a slip of the table |
| F13 | Rule 7: `sources/shikimori_anime.py` 464 lines | no change | Already `KI-63` (ticket 04) |
| F14 | Other smells: the data clump `(text, bold, links, forwarded)`, `SourceLink.source` and the media keys as strings, «why no offer» in three forms, `when_text`, `suggest_by_id` twice, texts copied between the two bot modules, `forget_inbox_item` / `resolve_inbox`, `SourceLink.prefix` unread, the menu texts passed on, `posters` through `core` and allowed directly | no change | Each is two or three copies or follows the spec: `when_text` has the texts of 9.2, not of `format_past_moment`; the two facade methods are spec 11's (two reasons, one action); the letter of a Shikimori link was asked by ticket 02; `inbox_handlers` cannot import from `tracker_handlers` (it is imported by it). Noted as wishes |
| F15 | Beyond the spec: Shikimori's English name matched, a link takes any IGDB record type, two failure texts, the `shown` flag of a stored offer | no change | Each helps: a match by the English name, an expansion followed by its link (ADR 0011), a failure said in the chat (rule 8), the double «Нет» of 12 |
| F16 | `bot/tracker_handlers.py` 659 lines | no change | Rule 7 is for the core; the inbox handlers stayed out of it as the 6.3 review wished. A wish below |

## Wishes for later stages

- KI-64 early in stage 9: the offer card is what the owner reads for every announcement.
- Split `bot/tracker_handlers.py` (the cards, the statuses and the menu apart) when it grows again.
- One type for the media of an item (a `StrEnum` as `InboxReason`), one value from `offers` for «why no offer», and the four fields of a post passed as one value to `candidates`.
