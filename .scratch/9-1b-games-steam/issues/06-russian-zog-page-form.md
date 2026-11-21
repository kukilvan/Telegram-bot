# 06: Russian in games — «Страница на ZoG», the owner's page

Status: accepted
Complexity: medium (two presses that go to the network, a form, error texts)
Blocked by: 05 (`page_of`, the client, the page parse, the state of `zog`, the hints)

Spec: `../spec.md`, section 5.3 (item 4: the form, the routes), section 5.7, section 8 (the lines on «Не та игра» then a link, a deleted title, a title that left «Хочу»/«В процессе», an owner's page that answers «Ошибка»), the owner's link and «Не та игра» lines of the tests of section 9, the owner checks about «Страница на ZoG». Terms — `CONTEXT.md` («Народный перевод»: `zog page`, `set_zog_page`, `reject_zog_page`); ADRs to read: 0004 (no own JavaScript), 0016 (written by ticket 05). Standards — rules 1, 3, 7, 8, 9, 10, 11. Mockup: `../mockups/game-card.html` (the form states).

## What to do

- **`Tracker.set_zog_page(title_id, link)` (5.7).** Through the facade (rule 1). The link is read by `zog_pages.page_of(link)`; then the page is asked once (a press that goes to the network: answer first, work, report — rule 8; the web awaits it, 10 s). Answers, with the error under the field and nothing saved:
  - empty — «Вставьте ссылку на страницу игры на ZoG»;
  - not such an address — «Это не страница игры на ZoG. Нужна ссылка вида https://www.zoneofgames.ru/games/…/»;
  - the page is «Ошибка» — «На ZoG нет такой страницы — проверьте ссылку»;
  - ZoG did not answer — «ZoG не ответил — попробуйте позже»;
  - a game not in «Хочу» or «В процессе» (a card open from before) — the card comes back without the form.
  Saved: `{"page": …, "by": "owner", …}` with the Support read now (no name or year check: the owner's choice wins), next check in 7 days, a reference point (no message); the undelivered fan events of the game are withdrawn (they were about another page). The same link twice — the same state.
- **`Tracker.reject_zog_page(title_id)` («Не та игра»).** `{"page": null, "by": "rejected"}`, the undelivered fan events withdrawn; no finding by itself until the owner saves a link; twice — the same. «Не та игра» then a link of the same page: saved as the owner's page (reference point).
- **The form (5.3 item 4).** Only in «Хочу» and «В процессе»: label «Страница на ZoG», a URL field (value: `https://www.zoneofgames.ru/games/<page>/` or empty; placeholder «https://www.zoneofgames.ru/games/…/»), the button «Сохранить», and «Не та игра» when a page is set. The error stands under the field and the typed text stays in it. Routes: POST `/titles/<id>/zog` (field `link`, `card_zog`) and POST `/titles/<id>/zog/reject` (`card_zog_reject`); both answer like the other presses of the card (`_press`: the fresh card fragment; a title gone — the fragment of «title gone»), behind the login (rule 10); no own JavaScript (ADR 0004), the HTMX of the other card forms.
- **Hints.** The hints about the page that ticket 05 wrote now sit next to a working form; check the three texts («не найдена», «не указана», «не удалось прочитать») against the states the form creates.
- **Docs:** docstrings, `tools\code_map.py`, `docs/tests-map.md`; `PROJECT_CONTEXT.md` — nothing new. At the end of the stage the review fills `KNOWN_ISSUES.md`; here only the rows the stage has not touched stay as they are.

## Done when

- [ ] Every answer of 5.7 is shown as written, the typed text stays in the field after an error, and nothing is saved on an error.
- [ ] A good link saves the page as the owner's, reads its Support at once, shows the line and the link «Страница перевода», sets a reference point (no message) and withdraws the undelivered fan events; the same link twice changes nothing.
- [ ] «Не та игра» sets «rejected» (the hint «Страница на ZoG не указана — вставьте ссылку, если перевод есть»), withdraws fan events, asks nothing from ZoG; twice — the same; a link after it is saved as the owner's page.
- [ ] A press for a deleted title shows «title gone»; one for a title that left «Хочу»/«В процессе» shows the card without the form.
- [ ] pyflakes clean; code map rebuilt; no core module over 400 lines (the facade 500); the full suite green (the known Windows failures are not new).

## Tests to add

- `set_zog_page` with a fake client: every answer of 5.7 (empty, a foreign address, «Ошибка», a timeout, a wrong status of the game), the save, the same link twice, the withdrawal of fan events, the reference point, «next check in 7 days».
- `reject_zog_page`: the state, twice, a link after it, the withdrawal.
- The routes: login required, the fresh fragment, the error text and the typed value in the fragment, a title gone, a game that left the statuses, a non-game.
- The form in every state (no page, a page found, a page by the owner, rejected, unreadable, the game in another status).

## Owner check

The session starts the bot and writes the launch result in one line. Then, in the browser at `http://localhost:8080`, open the card of a game in «Хочу» (for example Stray) and find the block «Русский язык»:
1. In the field «Страница на ZoG» type `привет` and press «Сохранить»: under the field «Это не страница игры на ZoG. Нужна ссылка вида https://www.zoneofgames.ru/games/…/» appears and `привет` stays in the field.
2. Paste `https://www.zoneofgames.ru/games/baldurs_gate_3/` and press «Сохранить»: the line gets «озвучка — народная» (or what that page says), the link «Страница перевода» appears, the field shows the address, and the button «Не та игра» appears.
3. Press «Не та игра»: the fan part goes, the grey hint says «Страница на ZoG не указана — вставьте ссылку, если перевод есть».

«Не так»: an error page of the app; the typed text disappears after an error; «Сохранить» hangs longer than ten seconds without an answer.
