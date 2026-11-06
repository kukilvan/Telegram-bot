# 05: The web tab «Входящие» — the page, «Найти», «Убрать»

Status: in review
Complexity: medium (a page, a menu number, one parameter threaded through Search; the data and the facade methods already exist)
Blocked by: 01, 02

Spec: `../spec.md`, section 9 (all), 10 (the `query` column), 11 (rows `web/inbox.py`, `search.py`, `menu.py` / `pages.py`), 12 (rows on the web), 14 (the web part), 15 (`CONTEXT.md` «Поиск», `docs/code-map.md` templates line). The mockup `../mockups/inbox-tab.html` shows the layout; where it differs from the spec, the spec wins. From 01 it uses `inbox_items`, `inbox_count`, `resolve_inbox`, `forget_inbox_item`; from 02 the function of the item query. Terms — `CONTEXT.md`; standards — rules 1, 2, 5, 7, 10, 11.

Note: the table of section 16 says "blocked by 01" only; this ticket also needs 02 because the query of an item is its first candidate (9.3), which 02 provides.

## What to do

- **The query of an item:** the taking-in code of ticket 01 now stores `query` with the function of ticket 02 (the first candidate; none — the first 60 characters cut at a word). An item of links keeps the offer name that ticket 04 writes; do not overwrite it.
- **Menu** (9.1): `SECTIONS` gets «Входящие» (`/inbox`, code `inbox`) between «Поиск» and «Настройки»; the label «Входящие (N)» when N > 0 items are in `inbox` (the `waiting` one is not counted), read by `Tracker.inbox_count()` on every page; a failed read leaves the label without a number and a log line (rule 9 of soft reads).
- **`app/web/inbox.py`, `templates/inbox.html`** (9.2): the heading, the items newest `received` first; each with the head line (the date on the owner's clock — «Сегодня, 14:20», «Вчера, 22:41», «3 ноября, 09:12», another year with the year; the kind with its icon or «тип не выбран»; the reason in words), the text cut to 4 lines / 300 characters at a word with «…» and `<details>` «показать всё» (no script), «(картинка без подписи)» and the like for an item with no text, the buttons «Найти» (not for an item with no text and no kind) and «Убрать», the link «Открыть пост ↗» (`target="_blank"`, `rel="noopener"`) when there is a post link. Empty: «Здесь пусто: всё, что вы присылали боту, разобрано.»
- **«Найти»** (9.3): a link to `/search?kind=<kind>&q=<query>&inbox=<item id>` (no kind — without `kind`). The Search page with the `inbox` of an existing item shows under the field «Из «Входящих»: добавленный тайтл уберёт эту запись.»; the suggestions and the add form carry `inbox`; after `add_title` succeeds (new or already in the list) `Tracker.resolve_inbox(id)` deletes the item (an item gone already is no error). An unknown or garbage `inbox` is ignored.
- **«Убрать»** (9.4): `POST /inbox/<id>/remove` deletes without a question; with HTMX the row goes and the menu number is updated out of band; without HTMX — a redirect back to `/inbox`; a removed item answers the same; behind the sign-in like every page.
- **Docs:** module docstrings, `.venv\Scripts\python.exe tools\code_map.py` (the templates line gets `inbox.html`); `CONTEXT.md` — «Поиск»: the line «Из «Входящих»»; `docs/tests-map.md`; `PROJECT_CONTEXT.md` — State: the tab exists.

## Done when

- [ ] The menu shows «Входящие» between «Поиск» and «Настройки», with the number only when there are items in `inbox`; the waiting item is not counted.
- [ ] The page shows each reason, each date form, a long text cut with «показать всё», an item without text, the post link; the empty state has its sentence.
- [ ] «Найти» opens Search filled with the kind and the query; adding there removes the item, whether the title is new or already in the list; a garbage `inbox` changes nothing.
- [ ] «Убрать» works with and without HTMX; the number in the menu follows; a second press does nothing wrong; an unsigned request is sent to the login page.
- [ ] The web imports only `core` and the pure modules of rule 10; modules ≤ 400 lines; `pyflakes app tests` clean; the full suite green (the three known Windows failures are not new).
- [ ] For the owner (the session walks it in the browser pane): the check below.

## Tests to add

- Web: the menu with and without the number; the page (empty, each reason, cut text, no text, post link); the «Найти» address with and without a kind; Search with `inbox` (the line, adding deletes the item, garbage ignored); «Убрать» with and without HTMX; the sign-in required; rule 10 imports.
- The query of an item stored at taking-in (first candidate, fallback) with the fake core.

## Owner check

The session starts the bot itself and writes the launch result in one line. The owner's check (the browser, `http://localhost:8080`, login with `WEB_PASSWORD`; Telegram, the bot's chat):

1. In Telegram write «Тестовая запись» and press «Игра»; write «Ещё запись» and leave it. Then send a sticker. (Ticket 04 is accepted by now, so «Игра» may find something: a name the sources do not know is best.)
2. In the browser, the menu shows «Входящие (N)». Open it: the records are newest first, with date, kind, reason, text and the buttons «Найти» and «Убрать». The sticker record has «(стикер без подписи)» or the like and no «Найти».
3. Press «Найти» on a record about a real film or game → Search opens with the name filled and the line «Из «Входящих»: добавленный тайтл уберёт эту запись.»; add the title → the record is gone from «Входящие», the number in the menu drops.
4. Press «Убрать» on another record → the row disappears without a page reload, the number drops. With the last one gone the page says «Здесь пусто…».

«Не так»: the number in the menu does not change until a reload, «Найти» opens an empty Search, an error page after «Убрать».
