Status: accepted

# Review of part 6.2: Steam prices, discounts and bundles

## What was reviewed

- Commits `4397d3c..76d55fd`, tickets 01–05 of `issues/`: b9f2d63 (01), 7381339 + eda5af9 (02), 2a75e39 (03), c3af30b (04), b59356f (05), and their «accepted» commits. The docs-workflow commits 142bc26, 776805e, 248da8d are not part of the stage and were left out.
- Against `spec.md` (sections 0–12) and `docs/coding-standards.md` (rules 1–11, with `CONTEXT.md` for rule 5), with the `code-review` skill: one pass for the standards, one for the spec, each in its own sub-agent; their reports are below, lightly cleaned. The findings and the decisions are in «Findings».

## Tests

- At the start: 2798 passed, 2 skipped, 3 failed — the three known Windows failures (`test_app_main`, `test_docker_files`, `test_runtime`), nothing new. `pyflakes app tests` clean, `docs/code-map.md` current.
- At the end (after the fixes): 2801 passed (three new tests), 2 skipped, the same 3 known Windows failures; `pyflakes` clean, the code map current.

## What was verified by running

- **The live bot** (Docker, the owner's PC): container `healthy`, `/health` — `{"status":"ok"}`, no red text in the log; the database is at migration `0013`; two games of «Хочу» with PC marked have price snapshots (Elden Ring — `price`, ₪249, one record of the price history; Hunter: The Reckoning — `coming_soon`), the next check six hours after the first one.
- **What the owner sees, on a copy of the real database** (the real core and web on a `TestClient`, no network): the block «Steam» of Elden Ring — «Цены для страны «Израиль» · проверено в 17:11 · Цена: ₪249» (the owner's clock), of Hunter — «Ещё не продаётся — скоро выйдет»; the bot card — «Цена в Steam: ₪249» before «Steam: https://…»; no block for the games out of «Хочу» or without PC marked; no marks in the list (no discount today).
- **Real Steam** (`GetItems`, 8 apps, Israel and Ukraine) read by the adapter: `price` (Elden Ring ₪249 / 1 799₴, Hades II ₪110,95 with its bundle, «Ведьмак 3» ₪179,95 with its bundle, Cyberpunk ₪249, RE Requiem ₪279 — its sale of 3 November is over), `free` (CS2), `coming_soon`, `unknown_app` (999999999). The field names of the spec still hold.
- **A probe of the spec pass** (in-memory core): after a change of the store country, with Steam answering 503, Steam was asked 5 times in 5 minutes; without the change — once (F1). A core without a source of prices queued «появилась страница в Steam» (F2).

## Standards (report of the standards pass)

Guard tests pass (core split, glossary, kinds and statuses, logs, web skeleton, dates, code map, one rule). Clean: every core module under 400 lines; every `commit` inside `write_session()`, no second session inside one; our own data read strictly (`PriceLook.from_state`, `parse_moment`, `delivery.expired`), Steam's discount end through the soft reader; no `TitleKind.` comparisons outside `polling.py`; web imports unchanged; log calls with `%s`; new comments in English.

Hard (documented rules):
- Rule 7, one rule — one place: the Steam store address twice (`price_events.store_url`, `game_rows.STEAM_URL`); «the look is of this Steam number and country» three times (`is_baseline`, `_due`, `current_look`); «records of the same number, country and currency» twice (`prices.lowest`, `price_rows`).
- Rule 5: the Steam number is `steam_id` in the glossary, but `appid` in `PriceLook` and `PriceRecord` (a stored key and a column), `steam_number` for the rule «игра для цен», which the glossary does not name.
- Rule 7 table: `game_scope` (ticket 01) is not listed.
- The commit message of b9f2d63 is Russian (written the day the English rule came; history, not fixable).
- A wrong error text: `dates.parse_moment` says «has no time zone» when the moment has one.

Judgement calls (smells): duplicated text helpers between `price_events` and `price_rows` (`_FREE_PCT`, `_until`, the edition in brackets, «, до …»); `games_word` copies the plural rule of `cards.titles_word`; the read «games for prices» twice (`game_prices._plan`, `game_steam.marks`) and the price-history query twice; `STEAM_EVENTS` a second name of `price_events.TYPES`; `web/card.SteamBlock` copies `SteamView` field by field (with a wrong comment); duplicated test helpers in `test_tracker_steam_events.py`; `price_snapshot` next to `storage.stored_snapshot`; `price_source` given to the poller of every kind (refused bequest); `Price.original/pct/ends_at` a `Discount` waiting to be born; `PriceLook.answer` and `Bundle.id` as strings; `delivery.fold` tests its string tags twice; the names `GameSteam` / `GamePrices` do not say which reads and which checks; `app/web/card.py` at 440 lines (the 400-line rule is for the core only).

## Spec (report of the spec pass)

The 11 test files of the stage pass. Checked and right: the texts of 5.2, 5.4 and table 6.1 character by character (U+2212, no-break spaces before «%» and in thousands, «», «,00» dropped, zero «бесплатно», `games_word` 1/2/5/11/21/111); table 5.1 (the end «наступил» as `ends_at <= now`), the lowest-price rule, the keys of 5.3 with `moved_key(…:none, observed_at)`, table 4.1, the baseline 4.3, the history 4.5, migration 0013; `expires_at` drops a message on every path; a new discount withdraws the undelivered one; the buttons of 5.5 (order, 10, the 30-character cut); section 7.

Findings: (c) a failed check after a new country or Steam number is retried every minute, not in 30 minutes (4.4); (c) «появилась страница в Steam» is queued by a core without a source of prices (section 8); (a) spec 7.1 says the date tests of part 6.1 pass unchanged, but two rows of `test_the_own_date_or_the_older_one` were flipped — the new rule needs it; (c) one button per Steam number, not per game (two titles with one number — one button); (c) 400/403 carry no `cause` (the reason is the same); (b) small extras: the `line` of a discount payload (for folding), the `prefix` of samples, a made-up sample bundle, the modules `price_rows` and `pollers/game_steam` (the split was the ticket's to decide), `dates.response_moment_of_timestamp` taken out of the AniList adapter; a note: a game that gets its Steam number has its silent first price check in the same pass, not the next minute.

Summary: standards — 5 hard findings and about 15 judgement calls, the worst is rule 7 (three rules written two or three times); spec — 7 findings, the worst is the retry every minute after a new country or number (F1).

## Findings

| # | What, where | Decision | Why |
|---|---|---|---|
| F1 | A check of another store country or Steam number (`pollers/game_prices._due`) is due whatever `next_check_at` says, so when Steam fails it the game is asked about every minute, not in 30 minutes (spec 4.4) | fix now | The reconciliation now empties such a snapshot (`_Plan.reset`): it is due at once, its check is the reference point as before, and a failure waits 30 minutes like any; `_due` reads only the time. Test `test_a_failed_check_of_a_new_country_or_number_waits_thirty_minutes_too` (both cases) |
| F2 | «Появилась страница в Steam» without a source of prices (`pollers/game.py`, `apply`), against section 8 | fix now | One condition; test `test_without_a_source_of_prices_the_page_in_steam_does_not_come`. No effect in production: `build_tracker` always gives the source |
| F3 | Spec 7.1 «тесты дат части 6.1 проходят без изменений» — two rows of `test_the_own_date_or_the_older_one` were flipped | no change | The code follows the new rule of 7.1 (a day ends before its year); the six examples of the spec of part 6.1 hold. The spec line was inexact |
| F4 | One button «🛒 Steam: …» per Steam number, not per game (`price_events.steam_ids`, the summary) | no change | Two titles of one number (an IGDB duplicate) open the same page; one button is enough |
| F5 | `SteamError` of 400/403 has no `cause` (spec 3.1 «status=None с cause») | no change | There is no exception to carry; the reason the owner reads is the same «неизвестная ошибка» |
| F6 | Extras: `line` in a discount payload, `prefix` of samples, the made-up sample bundle, the module split, the moved soft reader; the first price check of a new Steam number in the same pass | no change | All needed or harmless; the split was the ticket's to decide (spec 2.1) |
| F7 | Rule 7: the Steam store address in two places | fix now | `platforms.steam_url` for the card link and the buttons (`game_rows` cannot be it: `actions` → `game_rows` → `feed_rows` → `actions` is a cycle) |
| F8 | Rule 7: «the look is of this number and country» three times | fix now | `PriceLook.is_of` |
| F9 | Rule 7: «records of the same number, country, currency» twice | fix now | `prices.comparable`, used by `lowest` and the line «Сейчас — самая низкая…» |
| F10 | Duplicated text helpers of `price_events` and `price_rows` | fix now | `prices.FREE_PCT`, `prices.until` (with `comma`), `prices.edition_note` |
| F11 | `games_word` copies the plural rule; spec 5.2 puts it next to `titles_word` | fix now | `cards.games_word` and `cards.titles_word` over one `_plural` |
| F12 | The read «games for prices» and the price-history query, twice each | fix now | `game_prices.priced_games` and `game_prices.price_history`, used by the check and by the reads of the card and the list |
| F13 | `STEAM_EVENTS`, a second name of `price_events.TYPES` | fix now | Removed; the withdrawal and the test use `price_events.TYPES` |
| F14 | `web/card.SteamBlock` copies `SteamView` field by field, with a wrong comment | fix now | Removed: the template gets `card.steam` (`cards` is allowed to the web, rule 10) |
| F15 | Rule 7 table: no `game_scope` | fix now | Row added; the row of `prices` says what it holds now |
| F16 | Rule 5: `appid` beside `steam_id`; «игра для цен» not in the glossary | fix now | `CONTEXT.md`: `appid` is the Steam number where the core keeps what Steam was asked (a stored key and a column — rule 5 keeps data values); «игра для цен» is `steam_number`, without the number `reports_prices`. A rename to `steam_id` would need a migration of stored keys — a wish below |
| F17 | `dates.parse_moment`: «a stored moment has no time zone» when it has one | fix now | Text fixed |
| F18 | Test helpers repeated in `test_tracker_steam_events.py` (`run`, `naive`, `FakeClock`, `MadeUpGames`) | fix now | Imported from `test_tracker_game_prices`, as `test_web_steam_card` does; `FakeSender` differs and stays |
| F19 | The discounts of one check can come as separate messages: the check queues them one game after another and the delivery job does not wait for it | defer KI-51 | Rare (the queueing takes milliseconds; a titles pass of about a minute is needed); harm — two messages instead of one |
| F20 | `PROJECT_CONTEXT.md` says 2610 tests | fix now | Updated with the count of the end run |
| F21 | The Russian commit message of b9f2d63 | no change | History is never rewritten |

No finding needs a fix round: the part is closed by this review once the owner accepts it.

## Fixes made in this session

The findings marked «fix now» above; code in `app/tracker/` (`prices`, `price_events`, `price_rows`, `cards`, `platforms`, `game_rows`, `actions`, `pollers/game_prices`, `pollers/game_steam`, `pollers/game`, `sources/dates`) and `app/web/card.py`; docs `CONTEXT.md`, `docs/coding-standards.md`, `KNOWN_ISSUES.md` (KI-51), `PROJECT_CONTEXT.md` (the number of tests). New tests: F1 (two cases) and F2; the 430 tests of the stage's files pass unchanged in meaning (only imports moved).

## Wishes for later stages

- When the price snapshot changes anyway: `appid` → `steam_id` in `PriceLook` and `PriceRecord` (with a migration of the stored key and the column), one word for one concept.
- A `Discount` type for `Price.original/pct/ends_at`; `PriceLook.answer` as an enumeration (rule 6 style); clearer names for `GameSteam` (the reads) and `GamePrices` (the check).
- The price source given only to the poller of games, not to every kind.
- `delivery.fold`: one table of fold tags instead of tests of strings in two places.
- `app/web/card.py` is 422 lines: when the card grows again, the game blocks (platforms, Steam) can go into a module of their own.
- Specs: a line «the tests of part N pass unchanged» should be checked against the unit tests of the very rule that changes (F3).
