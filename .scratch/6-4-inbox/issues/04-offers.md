# 04: Offers — search by candidates and links, «Это оно?», «Да» / «Нет», typos, games through the bot

Status: in review
Complexity: complex (four sources, a new lookup per source, ordering and typo rules, failures, and a bot flow that adds titles)
Blocked by: 01, 02, 03

Spec: `../spec.md`, sections 2.3, 2.5 (the offer card), 3 (the lookups of the links), 5 (all), 6 (all), 7.3–7.4, 11 (rows `offers.py`, `sources`, `inbox_handlers.py`, `core.py`), 12 (rows on «Да», «Нет», links, game without keys, double tap), 13 (the typo in another language), 14 (offers and bot tests), 15 (`CONTEXT.md` terms, rule 7 row `offers`). The saved answers of the services lie in `../answers/` — the tests feed fake sources with them. Terms — `CONTEXT.md`; standards — rules 1, 5, 7, 8, 9, 10, 11; ADR 0010. From 01 it takes the item and its states, from 02 the candidates and the links, from 03 the sending function.

## What to do

- **Sources** (11): `suggest_by_id` for TMDb movie and series, Shikimori (the entry; adding takes the chain) and IGDB; IGDB `suggest_by_steam` (one request by `external_games.uid` with source 1); TMDb provider `find_imdb` (`/find`, first of `movie_results`, else `tv_results`); `Suggestion.released` (the date the search answer gives, read softly, rule 9 of the dates). A Steam number IGDB does not know falls back to Steam `appdetails` for the name (a name candidate of weight 100, game). Requests go through the search of the kind (`Titles.search`: ahead of the paced polling, marks the records already in the list).
- **`app/tracker/offers.py`** (5, 6.1): which candidates are searched (at least half of the first weight, at most 3), which records of a candidate (exact, then prefix by the name key over every name of a record, at most 2), the weak offer for the first candidate only, the order (year of the item, new with a date, no date, the rest, then the order of the source; "new" counts from the same day two years ago on the owner's clock), at most 3 offers in all, the typo rule of 5.4 (`difflib` ratio 0.85, at most 3 extra searches, headings «Это оно?» / «Возможно, вы имели в виду:»), the request budget of 5.5, a failure after the first offer is only logged. The link offers come first, then the candidates, up to 3 in all; a link nobody knows leaves the item as one without links. The offer card text (6.1: heading, name, original name only when its key differs, the three date forms, details such as platforms).
- **The analysis** in `inbox.py` / `core.py`: `answer_kind` now runs it; an item with a link of a source skips «Что это?» (1.3, step 1) and gets the kind of its first link offer. Results of 2.3: an offer card waits; in the list → «Уже в списке» and the card, the item resolved; nothing found → «Не нашёл — сохранил во «Входящие». Разберите в веб-приложении.» (`not_found`); a failed source → «Не удалось связаться с <source> — сохранил во «Входящие».» (`source_failed`, `KINDS[kind].source_name`); a game without IGDB keys → «Игры не подключены: нет ключей IGDB в .env — сохранил во «Входящие».» (`not_connected`). The offers are stored in the item (10); the `query` of a link item is the name of its first offer (9.3). **The interim text of ticket 01 goes.**
- **Bot** (`inbox_handlers.py`, 6, 7.3–7.4): the offer card with the poster (through the shared function, ticket 03) and «✅ Да» `inb:<id>:y:<n>` / «❌ Нет» `inb:<id>:n:<n>`; «Да» answers «Добавляю…» at once (rule 8), then `add_title` — "Хочу", a game gets «играю здесь» on «Мои платформы» it has; new → «✅ Добавлено в список» and the card, a series or an anime asks the watched seasons as today; already there → «Уже в списке»; the source failed → the message of 6.2 and the buttons stay; `TitleNotFound` → as «Нет»; no keys → «Игры не подключены: нет ключей IGDB в .env.». «Нет» → the next offer, or after the last «Не нашёл — сохранил во «Входящие»…»; a waiting item goes to `inbox` with `not_found`. Offer numbers the item does not have → «Эта кнопка больше не работает.». Items already in «Входящие» keep their buttons working (7.3: the kind press runs the analysis, the item stays in `inbox`, it neither becomes `waiting` nor moves the waiting one). A new post may move the item meanwhile (7.4): the offers are still sent. Every change of an item is one write session.
- **Games through the bot:** `KindInfo.web_only` keeps "moved between statuses only on the web"; the game card in the bot keeps «Удалить» alone.
- **Docs:** module docstrings, `.venv\Scripts\python.exe tools\code_map.py`; `CONTEXT.md` — new «Кандидат» (candidate) and «Предложение» (offer; not a search suggestion `Suggestion`); rule 7 row `offers`; `docs/tests-map.md`; `PROJECT_CONTEXT.md`, External services: the lookups by Steam number, IMDb id and Shikimori id (written once, here); `KNOWN_ISSUES.md` — the entry of 13 "a typo in a name is not corrected when the source answers in another language than the name".

## Done when

- [ ] On the saved answers the 18 samples give the first offers of 5.6 (sample 12 gives "nothing found"; sample 15 says «Уже в списке» when the game was added before).
- [ ] The 7 typo rows of 5.4 give the offers and the counts of searches shown there; a one-word name is not corrected; the weak offer comes after the corrected ones.
- [ ] The request budget of 5.5 holds on every sample; a source failing before the first offer ends with «источник не ответил», after the first offer is only logged.
- [ ] Links: Steam, TMDb movie and tv, Shikimori, IMDb give an offer and no question; a Steam number IGDB does not know uses the Steam name; a game link without keys says «игры не подключены».
- [ ] «Да» adds as on the web (a game with «играю здесь»; a series or an anime asks the seasons), «Нет» goes to the end, the double tap behaves as in 12, the buttons of an item in «Входящие» work, a dead or foreign number answers «Эта кнопка больше не работает.».
- [ ] Every offer card has the poster above the text; "in the list" is checked again when the card is shown.
- [ ] No module of the core over 400 lines; kinds are compared only in `polling.py`/`KINDS` (rule 6); `pyflakes app tests` clean; the full suite green (the three known Windows failures are not new).

## Tests to add

- `offers` (fake sources fed from `../answers/`): the 18 samples; the order on made-up records; the limits (2 per candidate, 3 in all); the weak offer; the half-weight rule; the typos; failures before and after the first offer; the budget; the card text.
- Sources: `suggest_by_id`, `suggest_by_steam`, `find_imdb` on the saved answers; `Suggestion.released`.
- Bot (fake Telegram): every row of 2.3 and 6.2–6.3; the early answer before the source (`tests/test_tracker_early_answer.py`); a series asks the seasons; a game gets «играю здесь»; buttons after «Входящие» and after delete.

## Owner check

The session starts the bot itself and writes the launch result in one line. The owner's check (Telegram, the bot's chat; the tracker needs the keys of TMDb and IGDB in `.env`):

1. Forward a post about a game, press «Игра» → the card «Это оно?» with the poster; «Да» → «✅ Добавлено в список» and the card. Open «📚 Мои тайтлы» — the game is there.
2. Write «Реинкарнация безработнго» (with the typo), press «Аниме» → «Возможно, вы имели в виду:» «Реинкарнация безработного…».
3. Forward a post that names several games; press «Игра» and «Нет» on each card → the next one, and after the last «Не нашёл — сохранил во «Входящие»…».
4. Send a link `https://store.steampowered.com/app/1245620/` → the card of Elden Ring at once, no question.
5. Send the same post again after adding it → «Уже в списке» and the card.

«Не так»: a card with no buttons, a wrong game first when the post names the year, «Да» that adds nothing, a long silence with no «Ищу…».
