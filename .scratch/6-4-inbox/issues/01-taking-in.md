# 01: «Входящие» in the database and taking in a message — migration 0014, the bot handler, «Что это?», «Не сохранять»

Status: accepted
Complexity: complex (migration, a new core module with write sessions, a bot handler with a timer and joining, the old «➕ Добавить» flow removed)
Blocked by: —

Spec: `../spec.md`, sections 1 (all), 2.1, 2.2, 2.4, 7 (all), 10, 11 (rows `inbox.py`, `core.py`, `inbox_handlers.py`, `tracker_handlers.py`, `main.py`), 12 (rows about messages, albums, forwards, restarts, two waiting items, old `tadd:` / `tpick:`), 13 (the restart within the pause), 15 (`CONTEXT.md`, rule 7 row `inbox`, `KINDS`). Not here: 2.3 and 2.5, candidates (ticket 02), posters (03), offers and the analysis (04), the web tab (05). Terms — `CONTEXT.md`; standards — `docs/coding-standards.md` (rules 1, 2, 3, 5, 6, 7, 8, 9, 11); ADR 0002, 0007, 0010. Read the tests of the old «➕ Добавить» flow (`tadd:` / `tpick:`) before removing them.

## What to do

- **Migration `0014_inbox.py`** (10): table `inbox_items`, `sqlite_autoincrement=True`, every column of the spec table, an index on `state`. The copy of the database before the migration is made by the start as usual.
- **`app/tracker/inbox.py`** (1, 7, 10): the model and the functions — take in a message (text, bold under 1–8 words, links from `url` / `text_link`, media word, post link of a public channel only, forwarded, received; text cut to 10,000), join into the newest item (1.2: 2 seconds, same `media_group_id`, or a comment followed by a forward; the comment first), the states `waiting` / `inbox` and the reasons, "a new item moves every other `waiting` one to `inbox` with `no_answer`" (one write session together with writing the new item, 7.4), `expire_inbox` (12 hours from `received_at`, 11:59 stays and 12:00 moves), the list for the web, the count, delete. Every change is one write session (rule 9). The pure parsing of a Telegram message into the item's fields lives apart from the database code, so it is tested without a bot.
- **`core.py`** (11): facade methods `take_in`, `answer_kind`, `forget_inbox_item`, `resolve_inbox`, `inbox_items`, `inbox_count`, `expire_inbox`, with result types in `results.py`. `answer_kind` here stores the kind and moves the item to `inbox` with `not_found` — the interim reply «Тип запомнил — сохранил во «Входящие».»; ticket 04 replaces it with the analysis. The `query` column is filled with the first 60 characters of the text cut at a word (ticket 05 switches it to the first candidate).
- **`app/bot/inbox_handlers.py`** (1.1, 1.3, 2.1, 2.2): the taking-in handler registered last on the owner router; skips commands, the three menu texts and «➕ Добавить» (its answer text and the new keyboard, 1.1); `edited_message` not handled. The pause of 2 seconds in the bot's memory, restarted by a joined message; after it: no text → «В сообщении нет текста — сохранил во «Входящие».» (reason `no_text`), else «Что это?» with the buttons of 2.1 (`KINDS[kind].label`, «🗑 Не сохранять»). The line «Предыдущий пост без ответа ушёл во «Входящие».» before the first message about the new item when any waiting item moved. A link of a source is **not** recognised yet (ticket 04): every item with text asks «Что это?». Presses by 2.2: early answer «Ищу…» (rule 8), the kind stored, buttons taken off; «🗑 Не сохранять» deletes with the popup «Не сохраняю.»; dead items «Эта запись уже разобрана.»; unreadable data «Эта кнопка больше не работает.».
- **`tracker_handlers.py` and `main.py`** (2.4, 11): «➕ Добавить», its kind menu (`tadd:`), the name request, the list of suggestions (`tpick:`) and `awaiting_name` go; an old `tadd:` / `tpick:` button answers «Эта кнопка больше не работает.»; the keyboard has three rows; the `/start` text and the empty-list text of 2.4; `KindInfo.ask_name` goes from `KINDS`; the comment of `web_only` loses «added» (6.2 of the spec). `app/bot/main.py` gets the job of `expire_inbox` every `TRACKER_BEAT_SECONDS` in a job of its own (`add_jobs`).
- **Tests of the old flow** are removed or rewritten for the new texts. The handlers of «Входящие» stay out of `tracker_handlers.py` (wish of the 6.3 review).
- **Docs:** module docstrings, `.venv\Scripts\python.exe tools\code_map.py`; `CONTEXT.md` — «Входящие» (In code: `inbox`; an entry — `inbox item`, table `inbox_items`; the states and reasons); rule 7 row `inbox` in `docs/coding-standards.md`; `docs/tests-map.md`; `KNOWN_ISSUES.md` — the entry of 13 "a restart within the 2-second pause leaves the item without «Что это?» until the next post or 12 hours".

## Done when

- [ ] A text, a forward from a public channel (post link kept), a forward from a private channel / a user (no link), an album, a forward with a comment — each becomes the item of 1.1–1.2; a sticker, a voice or a video without a caption gives «нет текста» at once.
- [ ] The item is in the database before the bot answers (a restart in the middle loses no post); after a restart an item with buttons still works, and `expire_inbox` counts 12 hours from arrival.
- [ ] A command, a menu button and «➕ Добавить» are never taken in; «➕ Добавить» answers with the text of 1.1 and the new keyboard; `tadd:` / `tpick:` answer «Эта кнопка больше не работает.».
- [ ] A new item moves the waiting ones to «Входящие» (`no_answer`) with the line «Предыдущий…»; five posts in a row leave four in `inbox` and one `waiting`; an id is never reused after the last item is deleted.
- [ ] A kind press stores the kind, takes the buttons off and ends in «Тип запомнил — сохранил во «Входящие».»; «Не сохранять» deletes; any button of a deleted item answers «Эта запись уже разобрана.».
- [ ] `/start`, the empty list and the keyboard have the texts of 2.4.
- [ ] No module of the core over 400 lines (`test_tracker_core_split.py`); the web does not import the new modules except through `core` (rule 10); `pyflakes app tests` clean; the full suite green (the three known Windows failures are not new); `test_code_map.py` green.

## Tests to add

- `inbox` (database in memory): take in and join (album, comment + forward, exactly 2 seconds, not joined after); every move of 7.2; 12 hours at the edge; delete; ids not reused; the item survives a new core on the same file; two waiting items found at start are both moved by the next new one.
- The parsing of a message into fields: bold limits, `url` and `text_link`, media words, post link rules, the 10,000 cut.
- Bot (fake Telegram): commands, menu texts and «➕ Добавить» not taken in; the pause and the restart of the pause by a joined message; the «Предыдущий…» line; the buttons and callback data (at most 64 bytes); every row of 2.2; the early answer before the source (`tests/test_tracker_early_answer.py`, rule 8); the keyboard, `/start`, the empty list.

## Owner check

The session starts the bot itself and writes the launch result in one line. The owner's check (Telegram, the bot's chat):

1. Write «Привет» → «Что это?» with «Фильм» «Сериал» / «Аниме» «Игра» and «🗑 Не сохранять». Press «🗑 Не сохранять» → the message says «Не сохраняю.»; press the old buttons of that message again if they are still there → «Эта запись уже разобрана.».
2. Write «Тест один», press «Игра» → «Тип запомнил — сохранил во «Входящие».». (The web tab arrives in ticket 05; the record waits in the database.)
3. Write «Тест два», then at once «Тест три» (before pressing anything) → «Предыдущий пост без ответа ушёл во «Входящие».» above the new «Что это?».
4. Send a sticker → «В сообщении нет текста — сохранил во «Входящие».». Press «➕ Добавить» on the old keyboard → «Кнопки «Добавить» больше нет…» and a keyboard of three buttons.

«Не так»: no answer for a text, two answers for one album, the old «➕ Добавить» menu still opens. Nothing is added to the list in this ticket: that is ticket 04.
