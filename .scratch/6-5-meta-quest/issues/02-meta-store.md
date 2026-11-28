# 02: The Meta store — the link in the cards, the button under the release message, a store link sent to the bot

Status: accepted
Complexity: medium (one link built and shown in the places Steam's already is, one more link form in «Входящие» and its lookup; no migration)
Blocked by: 01

Spec: `../spec.md`, section 6 (the number of a game, the address, the cards, the release message), section 7 (the link sent to the bot), section 8 (the snapshot key `meta_store_id`), section 9, the rows of section 10 about the store number, the store link and the button (from «The owner unticks Meta Quest» to the end), the **The store**, **The button** and **The link** lines of section 11, and the «Магазин Meta» and «Страна магазинов» lines of the `CONTEXT.md` part of section 13. Terms — `CONTEXT.md` («Платформа», «Мои платформы», «Страна магазинов», «Входящие»). ADRs to read: 0009, 0010, 0011, 0018. Standards — `docs/coding-standards.md`, the rules on modules and tests. Live answers — `../answers/games.json`, `external_game_sources.json`, `by_meta_store_id.json`.

## What to do

1. **The number (6.1, 8).** `GameState.meta_store_id: str | None` from `external_games` of source 28, digits only, else None; stored `meta_store_id`; a snapshot without the key reads. Nothing is added to the game request.
2. **The address (6.2).** `platforms.meta_store_url(meta_store_id, original_name)`: the page `https://www.meta.com/experiences/<id>/`, else the search `https://www.meta.com/experiences/search/?q=<name>` with the original name (`title.original_name or title.name`), `quote(name, safe='')`. No country in either, no request to the Meta store.
3. **The cards (6.3).** `game_rows.store_links` adds «Открыть в магазине Meta» / «Магазин Meta» when Meta Quest is among «Мои платформы» and the game is on it, after Steam and PS Store: a web link in a new tab, not `checked`; a text line in the bot card.
4. **The release message (6.4).** «вышла» and «вышла в раннем доступе» on Meta Quest carry `meta_url` in the payload, no other event does; `actions.event_actions` adds the link button «🛒 Открыть в магазине Meta» (action `META`) after «📄 Карточка»; a folded message has it when any member has `meta_url`; in a summary «🛒 Открыть в магазине Meta: <name>», in the order of 6.4.
5. **The test event (6.4).** The sample «Игра: вышла на Meta Quest» — «🎮 Asgard's Wrath II вышла на Meta Quest» with the button to `https://www.meta.com/experiences/2603836099654226/`, no «Карточка».
6. **The link sent to the bot (section 7).** `candidates.source_links` reads the forms of 7.1 (source `meta`, kind «игра»), not the forms listed as not read; `IgdbGameSource.suggest_by_meta` asks the request of 7.2; found — «Это оно?» at once; not found — the analysis goes on with the text of the post, then «Входящие», «не нашёл»; no IGDB keys — «игры не подключены».
7. **Docs.** `CONTEXT.md`: the new term «Магазин Meta»; «Страна магазинов» — the Meta store link is the same in every country. Docstrings of changed modules; `tools\code_map.py`; `docs/tests-map.md`. No `KNOWN_ISSUES.md` and no `docs/nas-changes.md` entry (section 13).

## Done when

- [ ] A game with a store number of source 28 links to its page, one without to the search by the original name; spaces, `&` and Cyrillic are encoded.
- [ ] The web and bot cards show the link only with Meta Quest among «Мои платформы» and the game on it.
- [ ] A Quest release has `meta_url` and the button; an announcement, a moved date and a PC release have none; a folded PC and Quest release has it though ПК leads; the summary buttons keep the order of 6.4.
- [ ] «🧪 Тестовое событие» → «Игра: вышла на Meta Quest» sends the message with the working button.
- [ ] Every link form of 7.1 gives its number, the not-read forms give none; a found game is offered at once without «Что это?»; an unknown number goes on with the text and ends in «Входящие».
- [ ] No request goes to the Meta store; no migration; pyflakes clean; the code map rebuilt; the full suite green (the known Windows failures do not count).

## Tests to add

By the lines **The store**, **The button** and **The link** of spec section 11: `meta_store_id` from `external_games` (digits only), both addresses, the card links shown and hidden; `meta_url` on a Quest release only, the button in a single, a folded and a summary message, the test sample; every read and not-read link form, the lookup query, found and not found, no IGDB keys.

## Owner check

The session starts the bot (one line with the result) and sees to it that «Meta Quest» is ticked in «Мои платформы».

1. A game added before this ticket gets its store number only at its next poll, so first delete Batman: Arkham Shadow and Beat Saber if they are in the list, and add them again; add Supernatural if it is not there.
2. Web cards: Batman: Arkham Shadow — «Открыть в магазине Meta» opens the game's page in the store; Beat Saber — the links to Steam and to the Meta store; Supernatural — the link opens the store's search for «Supernatural» (IGDB has no store number for it).
3. Bot: «📚 Мои тайтлы» → Batman: Arkham Shadow — the line «Магазин Meta: https://…».
4. Bot: send `https://www.meta.com/experiences/asgards-wrath-2/2603836099654226/` — «Это оно?» with Asgard's Wrath II at once, without «Что это?».
5. Bot: «🧪 Тестовое событие» → «Игра: вышла на Meta Quest» — the message and the button «🛒 Открыть в магазине Meta», which opens the store page.
6. Delete the added games if they are not wanted.

«Не так»: no link or no button; the link opens another game or an error page; the bot asks «Что это?» for the store link; a red text in `.\logs-bot.ps1`.
