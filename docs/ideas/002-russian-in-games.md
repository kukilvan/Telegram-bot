# Idea 002: Russian in games — text, voice, official and fan

Status: planned — stage 9.1b, taken in by its spec
Added: 2026-11-20

## Why

Before buying or starting a game the owner wants to know whether it can be played in Russian: is there Russian text (interface, subtitles), Russian voice, both, or nothing — and if the game itself has none, whether a fan translation exists. Today this is looked up by hand in Steam and on Zone of Games (ZoG). Russian is often added by a patch after the release, or a fan translation comes months later, so a game once checked has to be checked again.

## Scenario

1. The owner adds a game as usual. Nothing new is asked.
2. Within the next checks (Steam — up to 6 hours, IGDB and ZoG — up to a week; the first fill may be done at once after adding, the spec decides) the card of the game in the web and in the bot gets a line «Русский: …».
3. The owner opens the card and reads, for example, «Русский: текст — официально; озвучка — народная (ПК)», with a link to the translation's page on ZoG.
4. If ZoG gave the wrong game or found none, the owner pastes the right ZoG link into the field «Страница на ZoG» of the web card, or presses «Не та игра» — then the app stops reading that page for this game.
5. Later, for a game in «Хочу» or «В процессе», Russian text or voice appears — official (a patch) or fan (a new translation on ZoG). A message comes by the usual delivery rules (the summary at 15:00, quiet hours, work days).

## Behaviour

The line of the card (web card and bot card), official and fan shown apart:

- Official, from the game itself:
  - «текст» — Russian interface or subtitles (either one counts as text);
  - «озвучка» — full Russian voice (in Steam: «полная озвучка»);
  - «текст и озвучка» — both.
- Fan (народный перевод), from ZoG: «текст» or «озвучка» or «текст и озвучка», with the link «Страница перевода» to the game's page on ZoG.
- Wording examples (the spec fixes the exact texts):
  - «Русский: текст и озвучка — официально»
  - «Русский: текст — официально; озвучка — народная»
  - «Русский: текст — народный (ПК)»
  - «Русский: нет» — the sources answered and there is no Russian, neither official nor fan;
  - «Русский: нет данных» — no source has said anything yet (an announced game that has not listed its languages; no Steam page, IGDB silent, nothing on ZoG). Never shown as «нет».
- The mark «(ПК)»: the data is about the PC version only (it came from Steam, or the fan translation is for PC — almost all are), and the owner has «играю здесь» on a platform other than PC for this game. With «играю здесь» on PC only, no mark. IGDB data is not per platform: no mark.
- Web card: the field «Страница на ZoG» (the found address or empty) with «Сохранить», and the button «Не та игра». A pasted address that is not a ZoG game page — a short error under the field, nothing saved. «Не та игра» clears the page and the fan part shows «народный — не найден» (exact text by the spec) until the owner pastes a link.
- Messages (game in «Хочу» or «В процессе» only):
  - «В «<game>» появилась русская озвучка» / «…русский текст» / «…русский текст и озвучка» — official;
  - «Для «<game>» вышла народная русская озвучка» / «…народный русский перевод текста» — fan, with the link to the ZoG page;
  - only when something new appears compared with the last check; one appearance comes once.
- No search change, no list mark.

## What changes in existing behaviour

- The game card (web) gets the «Русский» line and the «Страница на ZoG» field; the bot card of a game gets the «Русский» line.
- The Steam request asks for the supported languages too. The price check today covers only games in «Хочу» with «играю здесь» on PC; the languages are needed for games in «Хочу» and «В процессе» with a Steam page on any platform the owner plays — so the language check is a wider set of games than the price check (the spec decides whether it is one `GetItems` request with both sets, or two).
- The weekly IGDB request of a game (the follow-up check) or another IGDB request asks for its language support (`language_supports`) — for games without a Steam page.
- A new weekly check of ZoG pages for games in «Хочу» and «В процессе».
- New event types for the appearance of Russian (official, fan) in the game events and their messages; they go through the delivery queue like the other game events.
- Games already in the list when the feature arrives: their first check only records what exists — no messages.

## Data and external services

- **Steam** (`IStoreBrowseService/GetItems`, already used, no key): the supported languages of each app — per language whether the interface, subtitles and full audio are supported (the request flag for languages and the exact answer shape — the spec checks against a live answer and saves it as a fixture). Fallback: `appdetails` gives `supported_languages` as one HTML string where `*` marks full audio.
- **IGDB** (already used, the Twitch key): `language_supports` of a game — language (Russian, locale `ru-RU`) and the support type (audio, subtitles, interface). For games with no Steam page (console-only, not yet in Steam).
- **ZoG**, `https://www.zoneofgames.ru` (new, no key, no API): the game page lists «Русификаторы и другие файлы → Переводы:» with entries like «Русификатор (текст)», «Русификатор (звук)» (checked 2026-11-20 on the Stray page: «Українізатор (текст)»). Pages are in `windows-1251`. The game's page is found by its name (ZoG search or the address scheme `/games/<slug>/` — the spec checks which works); `robots.txt` allows game pages. One request per game a week, spread in time, a polite `User-Agent` without the owner's details.
- Stored per game: the official Russian (text, voice; source; whether PC-only), the fan Russian (text, voice), the ZoG page address and whether the owner set it or rejected it, the moment of the last check of each source. A migration (the spec decides: columns or a snapshot of a new source, as Steam prices are).
- No new keys, no cost.

## Edge cases

- Steam, IGDB or ZoG unreachable or answering garbage: the last known value stays; a failure goes to the log, with a Telegram report no more than other sources do (the spec follows the existing failure rules). A failure is never shown as «нет».
- ZoG changed its page layout and nothing parses: «нет данных» for the fan part, not «нет»; a log line once a day so the breakage is seen.
- Several games of one name on ZoG: take the page only on an exact match of the name (original or Russian), otherwise no page — the owner can paste one.
- Russian disappeared (Steam removed it, a translation was taken down): the card updates, no message.
- The same appearance seen twice (two checks, a restart): one message.
- Steam and IGDB disagree: Steam wins (it is the store's own data); IGDB only for games without a Steam page.
- A game leaves «Хочу» / «В процессе» (completed, dropped, archived): checks stop, the card keeps the last known line; pending messages of Russian for it are withdrawn like other game messages.
- An expansion followed as a game of its own: checked like any game.
- Many games: Steam in packs of 100 per request; ZoG one page per game spread over the week.
- The owner pastes the same ZoG link twice or presses «Не та игра» twice: nothing breaks, the state is the same.

## Out of scope

- Russian in Search results and a mark in the List.
- Fan translation sites other than ZoG (GamesVoice, Mechanics VoiceOver and others separately) — ZoG usually lists their translations anyway.
- Exact Russian per console: no source has it.
- Downloading or installing translations.
- Other languages than Russian.

## Decisions

- With the owner: card in the web and the bot, no search, no list mark; messages for «Хочу» and «В процессе»; official and fan translation both counted and shown apart; fan messages like official ones; a wrong or missing ZoG page fixed by pasting a link or «Не та игра»; «нет данных» shown distinct from «нет»; the «(ПК)» mark when the data is about PC only and the owner plays elsewhere too; placed in stage 9.1b (the same code: the Steam client and the price check, the game card, the game events).
- By the agent: Steam first for the official part (the store's own data, comes in the request already made), IGDB only without a Steam page; ZoG for the fan part — the biggest catalog of Russian fan translations, the only one with a per-game page that says «текст» / «звук»; text = interface or subtitles; the first check of a game is quiet; weekly ZoG checks (translations change slowly, the site is a small community site).

## Owner check

1. Open the web card of a game with official Russian voice (e.g. Cyberpunk 2077) — «Русский: текст и озвучка — официально».
2. A game with official text only (e.g. Stray) — «Русский: текст — официально».
3. A game without official Russian but with a fan translation on ZoG — the fan part and the link «Страница перевода» opening the right ZoG page.
4. An announced game with no languages yet — «Русский: нет данных».
5. Paste a ZoG link into «Страница на ZoG», save — the fan part updates on the next check; press «Не та игра» — the fan part shows not found.
6. The bot card of the same game has the same line.
7. The appearance message: by a faked event (Settings «Тестовое событие» or the spec's way), since a real patch cannot be waited for.

## Tests

- Parsing: Steam languages (live fixture), IGDB `language_supports`, ZoG page (saved pages: with text, with voice, with both, with none, a changed layout), `windows-1251`.
- The line of the card for every state and the «(ПК)» mark rule.
- Events: appearance gives one message; disappearance none; the first check none; only «Хочу» and «В процессе»; a repeat check none.
- Failure of each source keeps the last value and never gives «нет».
- The ZoG field: a valid link saved, an invalid one refused, «Не та игра» twice.

## Open questions for the stage

- The Steam `GetItems` flag for languages and its answer shape — check live; one request for prices and languages or two.
- How to find a game's ZoG page by name reliably (search page or address scheme) and its cost.
- Where the Russian state lives — columns of the game or a snapshot of a new source; the migration.
- The exact texts of the line, the not-found state and the messages; the faked event for the owner's check.
- Whether the first fill runs right after adding the game or waits for the regular checks.
