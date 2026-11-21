# 02: The price check — KI-43, 44, 46, 47, 50, 51; the press hook for prices

Status: in review
Complexity: complex (a check in three phases, a hook in every press, a new queue method)
Blocked by: —

Spec: `../spec.md`, section 2 (2.1–2.5), section 3.1 (the hook, the price part, the Settings hook, the rule «new snapshots only by the reconciliation»), section 3.2 (the price check's `still_checked`: «the snapshot exists»), section 8 (the lines on a discount withdrawn by a deeper one, Steam answering for some games of a pack), the Prices and The press lines of the tests of section 9, the Steam prices row of section 7, the `won't fix` rule of section 10. Terms — `CONTEXT.md` («Бандл», «Проверка цен»); ADRs to read: 0009, 0011, 0015. Standards — rules 1, 3, 7, 9, 10, 11. Known issues: KI-43, 44, 46, 47, 50, 51. Fixture: `../answers/getitems_preorder_il_live.json` → copy to `tests/fixtures/`.

## What to do

- **The rule for `won't fix`.** Add to the rules at the top of `KNOWN_ISSUES.md`: «`won't fix (test: …)` — the app cannot fix it; the entry says why and what the owner decided; the test pins the behaviour».
- **KI-43 (2.1), won't fix.** The price stays the full price of the set. The texts gain «, цена набора целиком»: the bundle row of the web block «Steam» (««Hades + Hades II» (2 игры) — ₪250, цена набора целиком»), the message («🎮 Hades II продаётся в бандле «Hades + Hades II» (2 игры) — ₪250, цена набора целиком») and the sample «Игра: бандл в Steam». Entry → `won't fix (test: …)`.
- **KI-44 (2.2).** A test on the live fixture: the parser reads the three games unchanged; card lines «Предзаказ со скидкой −10 %: ₪238 → ₪214,20, до 3 декабря» (Dawn of War IV) and «Предзаказ: ₪209» (DRAGON QUEST MONSTERS). No parser change; entry → `fixed (test: …)`.
- **KI-46 (2.3), won't fix.** A test pins it: `PRICE_INTERVAL` is 6 hours; a discount found on a work day at 22:00 that ends at 08:00 next day is old by the 15:00 summary and is not sent; one that ends after 15:00 is sent in the summary. Entry → `won't fix (test: …)`.
- **KI-50 (2.4).** The reconciliation reads each price snapshot on its own; one that `PriceLook.from_state` cannot read is left out of the plan (not reset, not asked) unless the game is no longer for prices — then it is dropped as any. Such a game counts as a failure of its check («неизвестная ошибка») each time its snapshot is due: the `ValueError` joins the failures of the pass, the snapshot waits 30 minutes, the owner gets «could not check» once a day by the usual window. The log line «title N: its price snapshot cannot be read» comes once a day per game through the new `failures.DailyLog` (a log line per key at most once a day, in memory). The other games are checked as usual.
- **KI-51 and the wish of review 9.1a (2.5).** `GamePrices.check` in three phases: (1) all packs asked, events detected in a read session for every game answered; (2) one write session queues the events of every game of the check through the new `EventQueue.enqueue_all` (a game no longer checked per `checks.still_checked`, or a fact already known — the keys of the batch are read first — is skipped without a rollback; a new discount takes the undelivered discount of its game out of the queue only when it is queued itself; one commit); (3) each look stored in a write session of its own. `EventQueue.enqueue` stays for one event. The delivery job then sees all events of a check or none: two discounts of one check fold into «🎮 Скидки в Steam:».
- **The press hook (3.1, prices and Settings).** `Poller.after_marks(session, title_ids)` — base: nothing. `GamePoller.after_marks`, price part: for the given games (None — all games of the kind) the price snapshots of games no longer «игра для цен» (`steam_number`) go with their undelivered Steam events (`price_events.TYPES`) — the same rule as the reconciliation, in one place. Called in the write session of «Прошёл» (`_set_watched`), «Начал играть», the mark «играю здесь», «Бросил», and the save of Settings (the hook is given to `SettingsStore` by the core; `title_ids` None for every kind) — «Мои платформы» without PC ends every price check at once. New snapshots are made only by the reconciliation at the start of a pass, never by a press. The follow-up and Russian parts of the hook come in tickets 03 and 04; leave the place for them in `GamePoller.after_marks`.
- **`still_checked` for prices (3.2).** For the price check «the snapshot exists» is enough (the press drops it at once). Change the docstring of `pollers/game_prices.py` («No button touches the … snapshots»): the rule still lives in one place, a press only applies it.
- **Docs:** docstrings, `tools\code_map.py`, `docs/tests-map.md`, rule 7 table (`pollers/game_prices`, `queue`: `enqueue_all`; `failures`: `DailyLog`); `CONTEXT.md` — «Бандл»: «the price is of the whole set», «Проверка цен»: a press ends it at once; `KNOWN_ISSUES.md` — KI-47, 50, 51 `fixed (test: …)`, KI-44 `fixed`, KI-43 and 46 `won't fix`, with the index rows.

## Done when

- [ ] A bundle row and a bundle message end with «, цена набора целиком»; the preorder fixture gives the two card lines above; the KI-46 test passes.
- [ ] A spoiled price snapshot: the other games are checked, one «неизвестная ошибка» failure per due time, one log line a day, the snapshot waits 30 minutes; when the game is no longer for prices it is dropped.
- [ ] Two discounts of one check are queued in one write session; a delivery started between the two games sees none or both; a game dropped meanwhile queues nothing and rolls nothing back; a deeper discount takes the older undelivered one out of the queue only when it is queued itself.
- [ ] «Начал играть», «Прошёл», «Бросил», the PC mark and a Settings save without PC drop the price snapshot and its undelivered Steam events in the press's own session; a check answering after the press queues nothing.
- [ ] `KNOWN_ISSUES.md` has the `won't fix` rule and the 6 statuses; pyflakes clean; code map rebuilt; no core module over 400 lines (the facade 500); the full suite green (the known Windows failures are not new).

## Tests to add

- The bundle texts (web row, message, sample); the preorder fixture; the KI-46 pin (`PRICE_INTERVAL`, 22:00 → 08:00 not sent, ends after 15:00 sent in the summary).
- A spoiled snapshot (others checked, one failure, one log line a day through `DailyLog`, dropped when no longer for prices); `DailyLog` itself (same key twice in a day, another key, the next day).
- `enqueue_all`: a batch queued in one session; a known key skipped; a dropped game skipped without a rollback; the delivery sees all or none; two discounts fold; a withdrawn older discount.
- The hook: every press listed (including the PC mark and the Settings save), the undelivered Steam events go, delivered ones stay; a late check queues nothing; no press makes a snapshot.

## Owner check

The session starts the bot and writes the launch result in one line. In the web «Настройки» press «Тестовое событие» (a form in the block) and choose «Игра: бандл в Steam»: the message in Telegram reads «🎮 Hades II продаётся в бандле «Hades + Hades II» (2 игры) — ₪250, цена набора целиком» (the sum may differ by your store country). Nothing else to press: the rest is about the minute of a delivery and the tests show it.

«Не так»: the message has no «цена набора целиком»; an error message instead of the sample.
