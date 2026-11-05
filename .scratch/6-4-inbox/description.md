# Stage 6.4: «Входящие» — add a title from Telegram by a post or a name

Status: accepted

Terms come from `CONTEXT.md`. This stage takes in idea 001 (`docs/ideas/001-telegram-inbox.md`, the owner's 18 sample posts in `docs/ideas/001-telegram-inbox-examples.md`); the idea stays the detailed reference for texts and edge cases, this file is the source of truth where they differ. Decisions it leans on: ADR 0010 (the bot takes posts and names for adding; what is not resolved goes to «Входящие»), ADR 0002 (the web is the main interface: the list and the sorting of «Входящие» live there), ADR 0007 (bot, polling and web are one process). Mockups: `mockups/bot-messages.html`, `mockups/inbox-tab.html`.

## Goal

The owner learns about new movies, series, anime and games in Telegram channels. Today, to keep one, they open the web (or the temporary bot button «➕ Добавить»), pick the kind, type the name and pick from a list. After this stage the owner forwards the post (or writes a name) to the bot and is sure it is not lost: the bot either finds the title and offers to add it, or keeps the post in the web tab «Входящие» to sort out later.

## What the owner will see at the end

**Bot.**
- Any message to the bot except commands and the menu buttons is taken in: forwarded posts, posts with a picture and a caption, albums, plain names. It is written to the database at once, before any answer.
- The bot asks «Что это?» with «Фильм», «Сериал», «Аниме», «Игра» and «🗑 Не сохранять». «Не сохранять» forgets the message (it does not go to «Входящие»).
- A post with a link to the page of a title in a source (Steam, TMDb, Shikimori, IMDb) skips «Что это?»: the link says what and of which kind, the bot sends the card «Это оно?» at once.
- After the kind, the bot picks name candidates from the post by rules (no AI) and checks them in the source of the kind (TMDb, Shikimori, IGDB). It sends the card of the first one: the heading «Это оно?» (or «Возможно, вы имели в виду:» when the found name clearly differs from what was sent — this is the typo case), the poster, «✅ Да» / «❌ Нет».
- «Да» adds the title as adding does now: «✅ Добавлено в список», the card, for a series or an anime the question about watched seasons; for a game «играю здесь» is set on every platform of «Мои платформы» the game has. Games can now be added in the bot (in 6.1 only on the web); the statuses of a game are still changed only on the web.
- «Нет» shows the next candidate, three at most; after the last one the post goes to «Входящие» and the bot says so. A title already in the list: «Уже в списке» and its card, no «Да» / «Нет»; the post is resolved.
- Nothing found, the source did not answer, no IGDB keys, a message with no text — the post goes to «Входящие» with a line saying why (texts in the mockup).
- Only the last post waits for an answer. A new post sends the previous unanswered one to «Входящие» («Предыдущий пост без ответа ушёл во «Входящие».»); 12 hours without an answer send it there silently. Buttons of a post already in «Входящие» keep working; a post removed in the web answers «Эта запись уже разобрана.».
- Every card of the bot (after adding, «Карточка» under events, «📚 Мои тайтлы») shows the poster above the text, like a link preview: the card stays a text message of any length with the same buttons; if Telegram cannot load the picture, it is the text card of today.
- The menu loses «➕ Добавить»: «📚 Мои тайтлы», «Сводка сейчас», «Тестовое событие». The greeting of /start says how to add now.

**Web.**
- The sixth menu item «Входящие», with the number of items when there are any: «Входящие (3)».
- Items newest first; each shows the text of the post (a long one cut to its first lines with «показать всё») or the name, the kind or «тип не выбран», the date, why it is here («не нашёл», «без ответа», «нет текста», «источник не ответил»), and «Открыть пост ↗» when the post came from a public channel.
- «Найти» opens Search with the kind and the best candidate already filled in (no candidate — the start of the text); adding from that Search removes the item. «Убрать» removes it without a question. Empty: «Здесь пусто: всё, что вы присылали боту, разобрано.»

The owner's check at the end of the stage: the six steps of the idea («Проверка владельцем»), plus a post with a Steam link (card at once) and «🗑 Не сохранять».

## In scope

- Taking in messages: text, a caption of a picture or a video, an album (one item, not one per picture), a forward with a comment the owner typed (one item: Telegram sends the comment and the post as two messages a moment apart), a plain name; the origin of a forward (a public channel gives the link to the post).
- The rules that pick and order the candidates, built and tested on the 18 sample posts; signals besides the text: words in bold and links in the post (Telegram gives them with the message). Hidden links like «Підписатись» are not candidates. Comparisons in quotes («смесь «Разделения» и…», «как в «Геншине»») are not candidates first.
- Links to a source page: Steam (`store.steampowered.com/app/<id>`, via IGDB's Steam ids), TMDb (`/movie/<id>`, `/tv/<id>`), Shikimori (`/animes/<id>`), IMDb (`/title/tt…`, via TMDb's search by IMDb id). jut.su links give a name to search (`kikansha-no-mahou` → «kikansha no mahou»), not a kind.
- Order of candidates: new ones first — out within the last two years or not out yet — then the rest.
- The «Входящие» table (a migration after the last one, 0013 today), the states of an item (waits for an answer / in «Входящие» / resolved), the 12-hour move in the minute tick of polling.
- The web tab «Входящие», «Найти» (Search with the kind, the query and the item it came from), «Убрать».
- Posters in all bot cards.
- Removing «➕ Добавить» and its handlers (the name search of the bot, the list of suggestions).

## Out of scope

- AI for reading posts (the owner chose rules: ADR 0010).
- Reading text from pictures and videos.
- «Не знаю» and a search in every kind at once.
- Messages from anyone but the owner (the allowlist stays).
- Removing «📚 Мои тайтлы» — stage 7.
- Posters in event messages (releases, discounts): only cards get them.
- Changing statuses of games from the bot.

## Pulled-in known issues and review wishes

- **KI-24** (an id of a deleted last title goes to the next one, so old buttons act on another title): not fixed here — the fix rebuilds `titles`. But the new «Входящие» table takes the lesson: ids are never reused (`AUTOINCREMENT`), so an old «Да» / «Нет» never lands on another item.
- **KI-9** (stopping does not wait for started presses): stays open; the item is written to the database before anything else, so a restart in the middle loses no post, only the answer, and the buttons work after the restart.
- **Wish of the 6.3 review — keep modules small** (KI-56 for the core): the new code goes to modules of its own — the core of «Входящие» behind the `Tracker` facade, the rules of candidates as a pure module, the bot handlers of «Входящие» outside `app/bot/tracker_handlers.py` (715 lines today).
- No other open entry touches this stage.

## Decisions taken with the owner

From idea 001 (2026-10-31), unchanged: the bot stays a receiver for good and «➕ Добавить» goes in this stage; rules, not AI; the owner picks the kind (four buttons, no «Не знаю»); «Нет» — the next candidate, up to three, then «Входящие»; the tab is «Входящие» with «Найти» and «Убрать»; only the last post waits, the previous one goes to «Входящие» on a new post or after 12 hours; posters in every bot card; new titles first.

New, 2026-11-05:
- **A link to a source page skips «Что это?».** The link says exactly what it is and of which kind, so the bot sends «Это оно?» at once. Why: asking the kind of a Steam page is a question with one answer. This narrows «the owner always picks the kind» of the idea to posts without such a link.
- **The poster goes above the text, as a link preview**, not as a photo with a caption. Why: a caption is limited to 1024 characters, a card of a long series is longer; a text message keeps the whole card and the same buttons, and a picture that fails to load just leaves the text card.
- **«🗑 Не сохранять» under «Что это?».** Why: a message sent by mistake should not need a trip to the web to remove it. It is not «Не знаю»: it forgets the message instead of searching.
- **One stage, not two**, about five tickets (below). Why: every piece is checkable on its own, and the whole fits the estimate of 7–9 sessions.

By the agent:
- The item is written before the bot answers; buttons of an item in «Входящие» keep working; a title already in the list resolves the item; «Убрать» asks nothing (from the idea).
- An album and a forward with a comment are one item — otherwise one forward would make several «Что это?» and push each other to «Входящие».
- A typo is not checked by a dictionary: the heading «Возможно, вы имели в виду:» comes when the found name clearly differs from the sent one.

## Proposed tickets (the slicing decides)

1. Taking in and «Входящие» in the database: the table, writing a message at once, «Что это?» with «Не сохранять», the waiting rules (new post, 12 hours), the bot texts of saving; «➕ Добавить» removed. Candidates: only the whole text as one query.
2. The rules of candidates on the 18 samples, the links of sources, the order «new first».
3. Cards «Это оно?» / «Возможно, вы имели в виду:», «Да» / «Нет» up to three, «Уже в списке», games through the bot.
4. Posters in all bot cards.
5. The web tab «Входящие»: the list, the number in the menu, «Найти» into Search with the item, «Убрать».

Sessions: spec, slicing, five tickets, review — about 8.

## Open questions for the spec

- The exact rules of candidates: weights of Latin script, bold, quotes, the first line, the words after a kind («сериала», «гра», «фільм»); how comparisons and studios (MAPPA, A24, Enver) are kept from going first; the number of source checks per post (TMDb is limited to 30 requests a minute, IGDB about 4 a second).
- Which of the 18 samples have a page in their source (check by live requests and save the answers next to the spec); what is expected when a title has none.
- IGDB and Cyrillic: does a game search by a Russian or Ukrainian name find anything (it is weak in Russian)?
- When a found name «clearly differs» (the typo heading); the Russian and the original names both count.
- «The last two years» from which date of the source; titles without a date.
- One candidate with several records in the source (a remake, a remaster, Bleach and its parts): which comes first.
- How long to wait for the second message of a forward with a comment or of an album, and how to tell a comment from a new name.
- The poster as a link preview: is it shown for direct picture addresses of TMDb, IGDB and Shikimori (check live); what if Telegram fetches a picture slowly.
- «Да» pressed and the source fails while adding: the item stays waiting or goes to «Входящие».
- What the item of a link-only post stores as its text, and what «Найти» fills in for it.
