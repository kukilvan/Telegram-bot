# 03: Posters above the text in every bot card

Status: in review
Complexity: simple (one pure module moved, one sending function, one option on the message; the texts and buttons do not change)
Blocked by: —

Spec: `../spec.md`, sections 2.5, 8, 11 (rows `posters.py`, `tracker_handlers.py`), 14 (the cards part of the bot tests), 15 (rule 7 row `posters`). Terms — `CONTEXT.md`; standards — rules 7, 10, 11.

## What to do

- **`app/tracker/posters.py`** (pure, 8): `poster_url` and the sizes (`CARD_SIZE`: TMDb `w342`, IGDB `t_cover_big_2x`, Shikimori as stored) move here from `app/web/posters.py`; `core` re-exports them. `app/web/posters.py` keeps `image_sources` and imports the rest from `core` (rule 10: the web imports only `core` and the pure modules listed — add `posters` to that list). The web card must look byte-for-byte the same.
- **One sending function** in the bot for a card (the title card): the text and buttons as today, plus `link_preview_options = LinkPreviewOptions(url=<poster address>, show_above_text=True, prefer_large_media=True)`; no poster → `LinkPreviewOptions(is_disabled=True)`. A failed preview never fails the send (Telegram fetches the picture itself). All cards go through it: after adding, «Уже в списке», «Карточка» under an event, «📚 Мои тайтлы», «Готово» of the seasons, «Следить» (the title card of `send_card`). Event messages and the summary stay without posters. The offer card of ticket 04 will use the same function — keep its signature open for a card that is not a title card (an address, a text, a keyboard).
- **Docs:** module docstrings, `.venv\Scripts\python.exe tools\code_map.py`; rule 7 row `posters` and the pure list; rule 10 list; `docs/tests-map.md`.

## Done when

- [ ] Every card of the list above carries `link_preview_options` with the poster above the text and a large preview; a title with no stored poster carries `is_disabled=True`; event messages and the summary carry neither.
- [ ] The address is the one the web card makes (same function, same sizes) for TMDb, IGDB and Shikimori posters.
- [ ] The text and the buttons of the cards are unchanged; the web card tests pass unchanged.
- [ ] `app/web/posters.py` no longer holds `poster_url` or the sizes; the import rule of rule 10 holds; modules ≤ 400 lines; `pyflakes app tests` clean; the full suite green (the three known Windows failures are not new).

## Tests to add

- `posters`: the address per source and size; no poster → none.
- Bot (fake Telegram): each card path above sends `link_preview_options` as specified; no poster → `is_disabled`; an event message is sent without it.

## Owner check

The session starts the bot itself and writes the launch result in one line. The owner's check (Telegram, the bot's chat):

1. «📚 Мои тайтлы» → open the card of a film or series, then of a game, then of an anime. Each card shows the poster above the text, with the buttons below.
2. A title with no poster in the list (if there is one) shows the plain text card as before.

«Не так»: no picture, the picture below the text, a card with no buttons. Telegram may show the picture a second late; that is normal.
