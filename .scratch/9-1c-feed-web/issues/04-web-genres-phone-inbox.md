# 04: Web — genres in the Archive filter, the chosen filter on the phone, «Это оно — убрать запись» — KI-30, KI-74, KI-65

Status: open
Complexity: medium (three small independent changes in the web layer; no migration)
Blocked by: —

Spec: `../spec.md`, section 3 (3.1 the table, 3.2 where it applies), section 4 (the CSS rule), section 5 (the form in the suggestions), the Genres, KI-74 and KI-65 lines of the tests of section 14, the lines of section 13 about `?genre=Экшен`, a genre in lower case and «Это оно — убрать запись» pressed after the item was removed, the `CONTEXT.md` line **Жанр** of section 15, section 10 (no facade method). Terms — `CONTEXT.md` («Жанр», «Архив», «Входящие», «Найти»). ADRs to read: 0004 (no own JavaScript). Standards — rules 5, 7, 10, 11. Known issues: KI-30, 65, 74 (`fixed`). Fixture: `../answers/tmdb-genres-ru-2026-11-22.json` and the genre list of `../answers/shikimori-jjk-s4-and-genres-2026-11-22.json` → `tests/fixtures/tmdb/genres_ru.json` and `tests/fixtures/shikimori/genres_ru.json` (the table is checked against the live lists). Mockups: `../mockups/archive.html`, `../mockups/search-inbox.html`.

## What to do

- **KI-30, the table (3.1, 3.2).** An own table of synonyms in `genres` (`SYNONYMS`: a genre's key — `key_of`, case and «ё» do not matter — to the genres it counts as): «Экшен» → «Боевик»; «Тайна» → «Детектив»; «Боевик и Приключения» → «Боевик», «Приключения»; «НФ и Фэнтези» → «Фантастика», «Фэнтези»; «Война и Политика» → «Военный», «Политика». Every other genre counts as itself. The merged genre is named by the TMDb word with a capital letter (`label`). Left apart on purpose: «Романтика» and «мелодрама», «Детский» and «семейный», «Мыльная опера». `genres.merge` (the links of the genre row) and `genres.keys_of` (the match of a title) read every genre through the table, so choosing «Фэнтези» shows the series «НФ и Фэнтези» too. **The address:** `?genre=` is read through the table too — a synonym is its genre (`?genre=Экшен` is «Боевик» and the row marks «Боевик» chosen), a composite name is its first part (`?genre=НФ и Фэнтези` is «Фантастика»); an old bookmark keeps working. The card and the Search show the genres as the source names them; nothing stored changes; the List has no genre filter.
- **KI-74, the phone (4).** In `app/web/static/style.css`, inside the existing `@media (max-width: 40rem)` block of the filter rows: `.filters a[aria-current="true"] { order: -1; }`. No markup change, no JavaScript. Every row of filter links (the «Список» rows, the «Архив» rows) shows its chosen link first under 40rem; on a computer the order is as now.
- **KI-65 (5).** The suggestions of the Search opened from an inbox item (`inbox=<id>`, an item that is there): a row whose title is in the list shows «В списке» (as now) and, after it, a plain form (no `hx-` attributes) `POST /inbox/<id>/remove` with the button **«Это оно — убрать запись»**. It is the route of «Убрать»: the item is deleted, the answer is `303` to «Входящие»; an item gone already gives the same answer; no notice. `suggestions.html` gets the item's address from the page (`inbox_remove`), not built in the template. The Search without `inbox` (or with a number that is no item) shows «В списке» only; a row not in the list keeps «Добавить»; the «already in the list» branch of `add` stays. No new facade method (`forget_inbox_item` exists; section 10).
- **Docs.** Docstrings, `tools\code_map.py`, `docs/tests-map.md`; `CONTEXT.md` — **Жанр** (synonyms of different sources are merged by an own table in the Archive filter, a composite TMDb genre counts under each part, the card keeps the source's names; `In code: genres.SYNONYMS`); `KNOWN_ISSUES.md` — KI-30, 65, 74 `fixed (test: …)` with the index rows.

## Done when

- [ ] On a base with «Экшен», «боевик», «Тайна», «детектив», «НФ и Фэнтези», «Фэнтези» the Archive genre row shows «Боевик», «Детектив», «Фантастика», «Фэнтези» once each; choosing «Фэнтези» lists the series «НФ и Фэнтези» too; `?genre=Экшен` and `?genre=НФ и Фэнтези` work and mark the right link.
- [ ] A test reads `style.css` and finds the rule inside the `max-width: 40rem` block; a live look at 375 px in the browser pane shows the chosen link first in «Список» and «Архив».
- [ ] With `inbox` and a title in the list the row has «В списке» and the form with «Это оно — убрать запись» and no `hx-`; the press deletes the item and answers `303` to «Входящие»; an item gone already — the same; without `inbox` no form.
- [ ] pyflakes clean; code map rebuilt; no core module over 400 lines; the full suite green (the known Windows failures are not new).

## Tests to add

- The table: a synonym, a composite name, case and «ё»; the table against the two live genre lists (every key it names exists in a list); `merge` and the match on the owner's mix; the address read through the table; the card unchanged.
- KI-74: the CSS rule inside the 40rem block (none reads the CSS yet: a new small test).
- KI-65: the row with and without `inbox`, no `hx-` in the form, the press and the `303`, the item gone, a number that is no item.

## Owner check

The session starts the bot and writes the launch result in one line. In the browser at `http://localhost:8080`:

1. Tab «Архив» (needs a few titles there): in the row «Жанр» each genre stands once — no separate «Экшен» next to «Боевик», no «НФ и Фэнтези». Press «Фэнтези»: series that TMDb calls «НФ и Фэнтези» are listed.
2. On the phone (or the browser narrowed under 640 px; the session checks 375 px itself): choose a filter at the end of a row in «Список» or «Архив» — it jumps to the start of the row.
3. In «Входящие» take an item whose title is already in the list, press «Найти»: the suggestion shows «В списке» and the button «Это оно — убрать запись»; press it — you are back in «Входящие» and the item is gone.

«Не так»: two names for one genre; the chosen filter stays at the end of the row on the phone; no button in step 3, or an error page after it.
