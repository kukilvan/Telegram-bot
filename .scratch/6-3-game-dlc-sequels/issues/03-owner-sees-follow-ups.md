# 03: What the owner sees on the web and in the bot card — blocks, «Следить», parent line, mark «дополнение»

Status: open
Complexity: medium (a view in the core, one row type for three lists, a moved block, a renamed route and facade method, two small lines; no new external behaviour)
Blocked by: 02

Spec: `../spec.md`, sections 7.1 (the view), 7.2 (web card), 7.3 (bot card), 7.4 (List and Archive), 7.7 (what does not change), 2.1 (row `card_blocks.py`), 2.2 (rows `cards.py`, `pollers/game.py` — `card_part`, `list_tags`; `pollers/base.py` — `list_tags`, `offers_follow_ups`; `polling.py` — `Pollers.follows`; `core.py` — `follow`; `titles.py`; `listing.py`, `results.py`; `app/web/card.py`, `card_body.html`, `title_rows.py`, `macros.html`, `style.css`), 8 (rows on the parent line, the blocks of expansions, a type-2 expansion, the state «not checked yet»), 9.1 («Card»), 9.2 steps 2–3. From ticket 02 it reads the follow-up snapshot; from 01 the rules (4) and the date texts. Terms — `CONTEXT.md` («Дополнение», «Продолжение», «Серия игр»); standards — `docs/coding-standards.md` (rules 1, 5, 7, 8, 10, 11); ADR 0011. `KNOWN_ISSUES.md`: KI-52 is known (an archived standalone expansion has no line and no mark until it is polled) — not fixed. Not touched here: the announcement buttons, the summary, the Feed, the bot texts of «Следить», the samples (ticket 04).

Mockups for the layout: `.scratch/6-3-game-dlc-sequels/mockups/`; where they differ from the spec, the spec wins (the texts of spec 0, «Where the spec refines the description»).

## What to do

- **The view of `cards.py`** (7.1): `FollowLine(external_id, name, when, title_id)` replaces `SequelLine` (a film's row gets `when` = `format_date` or «дата не объявлена»); `FollowUpsView(checked, checked_at, expansions, sequels, collections)`; `ParentGame(name, title_id)` (the title's name when the parent is in the list through `known_ids`, else the stored IGDB name; `title_id` None when it is not in the list); `TitleCard` and `CardPart` get `parent` and `follow_ups`. The game poller (`card_part`) fills `parent` for a game with `GameState.expansion`, and `follow_ups` for a game for the check (`for_follow_ups`) while the core has the follow-up source — `checked = False` when its snapshot does not exist yet — and None for any other title, and for every game when the core has no follow-up source. A number of reads that does not depend on the length of the lists. The rules of 4 come from ticket 01; `checked_at` is on the owner's clock.
- **`Poller.list_tags`** (7.4): the words after the name of a row, title → text; the game poller gives «дополнение» to a game with `GameState.expansion` (either kind); a constant number of reads; the default is none. `TitleSummary.tag` (`listing.py`, `results.py`) carries it; the List and the Archive both; the bot list is not changed.
- **`Poller.offers_follow_ups` and `Pollers.follows(kind)`** (2.2): `offers_follow_ups` default False, the game poller True while it has the follow-up source; `Pollers.follows(kind)` — the kind announces titles to follow (it has a sequel source, or its poller `offers_follow_ups`). `titles.follow` refuses a kind that `follows` does not name (`UnknownKind`). `polling.py` stays the one place that compares kinds.
- **`Tracker.follow(kind, external_id)`** (2.2): replaces `follow_sequel_of`, adds an expansion too (an IGDB id of any type goes through `add_title(GAME, id)`); `follow_sequel(event_id)` stays for the old movie buttons. Its callers (`web/pages.try_follow_sequel`, the bot handler) move to the new name with no change of behaviour; the Feed route and the bot texts change in ticket 04.
- **`app/web/card_blocks.py`** (2.1, 7.2): the blocks of the platforms of a game move out of `app/web/card.py` as they are (wish of review 6.2); the line «Дополнение к игре «…»» under the original name (a link to the card when the parent is in the list, plain text otherwise); `FollowRow` and `FollowBlock` — one row type and one macro for the three lists: the film's sequels, the game's expansions, the game's sequels; the three states «not checked yet» / «checked» with the exact headings and sentences of 7.2 (`format_past_moment` for «последняя проверка»; the series sentence for one, two or no series). A row: name, date, then «Следить» (a form) or «В списке» (a link to the card). An expansion of type 2 has no follow blocks; a standalone one has the line and the blocks. `card.py` keeps the routes and the parts every kind has.
- **`card_follow`** (7.2): `POST /titles/{id}/follow` replaces `card_sequels` (`/titles/{id}/sequels`) with `kind`, `external_id` and `block` (`sequels` | `expansions`); the owner stays on the card, the row says «В списке»; an error is the line of `pages.try_follow` (the texts of now) in the block the press came from.
- **The mark «дополнение»** (7.4): `title_rows.Row.tag` shows it after the name, class `row-tag` (small, muted) in `macros.html` and `style.css`.
- **Bot card** (7.3): `cards.py` prints «Дополнение к игре «…»» after the names line; the bot card lists no expansions or sequels.
- **Docs:** module docstrings, `tools\code_map.py`; `docs/coding-standards.md` — rule 7 (the actions of a poller `list_tags`, `offers_follow_ups`) and the web table of rule 10 if it lists the card modules; `docs/tests-map.md`; `PROJECT_CONTEXT.md`, External services: IGDB also gives expansions and series (one request per game a week, nested fields) — the ticket that writes this is the last one that touches it, so write it here once.

## Done when

- [ ] The three states of the block follow 7.2 to the word: «Ещё не проверял — проверю в ближайшие минуты» under «Дополнения и продолжения»; «Проверяю раз в неделю, последняя проверка — …» / «Дополнений пока нет. Проверяю раз в неделю, последняя проверка — …»; the series sentence for one series, two and none; «Продолжений пока нет. Проверяю раз в неделю».
- [ ] On the saved answers the lists of the card equal the table of 4.6 (PC + PS5, Israel); rows with the title in the list say «В списке» with a link to the card.
- [ ] «Следить» from the block of expansions and from the block of sequels adds the game, the row says «В списке», the owner stays on the card; an error shows in the block the press came from; the film's block of sequels works as before on the new row type.
- [ ] The line of the parent: with a link when the parent is in the list, plain text with the IGDB name when it is not (also after the parent is deleted); a type-2 expansion has no blocks; a standalone expansion has the line and both blocks; a game with no follow-up source in the core has no blocks.
- [ ] The List and the Archive show «дополнение» after the name of an expansion; the bot card shows the parent line; the bot list is unchanged.
- [ ] The blocks of the platforms are byte-for-byte the same after the move (the existing tests are unchanged); no module of the core over 400 lines, no kind compared outside `polling.py` (`test_tracker_core_split.py`).
- [ ] Reads on the card and in the List do not grow with the length of the lists (rule 7 check).
- [ ] Rules 1, 5, 7, 8, 10, 11; `pyflakes app tests` clean; the full test suite green (the three known Windows failures are not new).
- [ ] For the owner (the session walks it in the browser pane and by the log): steps 2–3 of spec 9.2.

## Tests to add

- Spec 9.1 «Card»: the three states and the texts of 7.2; the rows with «В списке»; «Следить» from both blocks with an error in its block; the line of the parent with and without a link; the movie block on the new row type; the blocks of the platforms unchanged after the move.
- The view in the core (`FollowUpsView`, `ParentGame`) on a game for the check, a game with no snapshot yet, an expansion of each kind and another title.
- `list_tags` and `TitleSummary.tag` for a game and an expansion, in the List and in the Archive; `Pollers.follows` and `UnknownKind` for a kind that does not follow.

## Owner check

The session starts the bot itself and writes the launch result in one line. The owner's check (browser, `http://localhost:8080`, login with `WEB_PASSWORD`; the first checks of the games need a few minutes after the start — if a card still says «Ещё не проверял…», wait and reload):

1. «Список» → open the card of «Ведьмак 3: Дикая охота» (it is in «Пройдено»). Under «Платформы» and «Steam»: «Дополнения» — «Каменные сердца» (12 октября 2015), «Кровь и Вино» (30 мая 2016), «Баллады прошлого» (2027); «Продолжения» — Gwent, The Witcher 3: Wild Hunt Remastered, The Witcher IV, The Witcher Remake. «Elden Ring»: Shadow of the Erdtree and Nightreign. «Hades II», «Grand Theft Auto VI», «Hunter»: «… пока нет».
2. In the card of «Ведьмак 3» press «Следить» at «Кровь и Вино». The row says «В списке» and the page does not jump to another card. Open that card (the link «В списке»): under the original name «Дополнение к игре «Ведьмак 3: Дикая охота»» — a link to the card of the game; the platforms with «играю здесь»; the block «Steam». The List shows the small word «дополнение» after the name.
3. Telegram, «📚 Мои тайтлы» → the card of «Кровь и Вино»: the line «Дополнение к игре «…»» after the names.

«Не так»: the blocks are missing on the card of a game in «Хочу», «В процессе» or «Пройдено» five minutes after the start; a press on «Следить» opens an error page; the mark is missing in the List. The followed expansion can be removed afterwards with «Удалить» on its card.
