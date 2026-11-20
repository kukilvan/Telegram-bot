# Stage 9.1b: games and Steam prices — the known issues and Russian in games

Status: accepted

Terms come from `CONTEXT.md`. The stage is part b of stage 9.1 (`docs/project-spec.md`); its 14 known issues and the direction of each fix were set by `.scratch/9-1-known-issues/description.md` (part 9.1b and decisions 2–4 there). Idea 002 (`docs/ideas/002-russian-in-games.md`) joined the part later, on 2026-11-20, so the part gets this description: the idea is a new feature, not a fix. ADRs it leans on: 0004 (no own JavaScript), 0007 (one process), 0009 (no PlayStation prices), 0011 (a followed expansion is a game of its own), 0015 (a hung app is ended by its health check, for the rule of every poll write — `checks.still_checked`).

## Goal

1. Close the 14 known issues of games, Steam prices and the follow-up check before the move to the NAS: rare cases where a release message is missed or wrong, a price check stops for every game, a message about a game comes after it left «Хочу».
2. Tell the owner whether a game can be played in Russian — today this is looked up by hand in Steam and on Zone of Games (ZoG) before buying or starting a game, and again later, because Russian often comes with a patch or a fan translation months after the release.

## What the owner will see at the end

Mockups: `mockups/game-card.html` (the web card: the new block «Русский язык» in seven states, the Japan line, the bundle note) and `mockups/bot.html` (the bot card and the messages).

**Russian in games (idea 002):**

- Every game in «Хочу» and «В процессе» gets the block «Русский язык» in the web card and the line «Русский: …» in the bot card:
  - «Русский: текст и озвучка — официально»; «Русский: текст — официально; озвучка — народная»; «Русский: текст — народный (ПК)»; «Русский: нет»; «Русский: нет данных» (no source has said anything yet — never shown as «нет»). The exact texts — the spec.
  - Official — from Steam (the store's own data), for a game with no Steam page from IGDB. Fan (народный перевод) — from the game's page on ZoG.
  - **The fan part fills only what the official lacks** (decision 1): Cyberpunk 2077 with official text and voice shows «текст и озвучка — официально» and nothing fan, though ZoG lists translations for it; Hollow Knight with official text and an old fan text translation shows «текст — официально».
  - «(ПК)» — the data is about the PC version only (it came from Steam, or the fan translation is for PC) and the owner has «играю здесь» on another platform too.
- The line is there **right after adding** (decision 2): the Steam request made at adding already returns the languages; ZoG is asked once. Adding stays as fast as now and never fails because of ZoG.
- The web card has the field «Страница на ZoG» with «Сохранить» and the button «Не та игра»; a link «Страница перевода» when the fan part is shown. A pasted address that is not a ZoG game page — a short error under the field, nothing saved. «Не та игра» clears the page; the app stops reading it for this game until the owner pastes another.
- The app finds the ZoG page by itself in most cases (decision 3); when it does not — «Страница на ZoG не найдена — вставьте ссылку, если перевод есть».
- Messages, only for a game in «Хочу» or «В процессе», by the delivery rules (the summary at 15:00, quiet hours, work days):
  - «🎮 В «Hollow Knight: Silksong» появилась русская озвучка» — official, under it «Карточка» and «🛒 Открыть в Steam»;
  - «🎮 Для «Baldur’s Gate 3» вышла народная русская озвучка» — fan, under it «Карточка» and «🌐 Страница перевода»;
  - only what is new since the last check; one appearance comes once; a fan translation of what is official already does not come (decision 1).
- No message: at the first check of a game (and for the games already in the list when the feature arrives), when Russian disappears, for games in «Пройдено», «Бросил» and the archive. No change of Search and the List.

**The known issues (visible part; the rest is fewer missing, repeated or wrong messages):**

- A date of a release in Japan only is not a release: no «вышла», no date of the platform; the card shows it on a line of its own «в Японии — 12 марта 2027» (KI-35).
- A release IGDB learned of late (over 30 days) still comes as «вышла» (KI-36).
- An IGDB record without date precision shows the month or the year it has, not «дата не объявлена» (KI-38).
- The PlayStation Store link no longer leads to an error page when the game is missing in the country's store (KI-37).
- A bundle in the card and in the message: «… — ₪250, цена набора целиком» (KI-43).
- A discount message no longer comes after the game left «Хочу» (KI-47); the discounts of one check come together (KI-51).
- One spoiled price record no longer stops the prices of every game (KI-50).
- Expansions and new games of a series: a standalone expansion completed before 6.3 learns that it is one (KI-52); «Бросил» and «Вернуть в список» in one minute work right (KI-53); an announcement withdrawn by «Бросил» can still come from another game of the series (KI-54); a game whose check cannot run is reported once a day (KI-55).
- Short Steam discounts stay as they are (KI-46, `won't fix`, decision 3 of 9.1).

## The known issues

The directions are those of `.scratch/9-1-known-issues/description.md`; the spec reads the full entries (Grep by `## KI-<n>`).

| KI | What | Direction of the fix |
|---|---|---|
| 35 | A release in Japan only counts as a release | regions outside the store country's table are not a release; the card shows the date on a line of its own |
| 36 | A release IGDB learned of over 30 days late comes without a message | a mark «release reported» per platform instead of the 30-day rule |
| 37 | The PlayStation Store link can lead to an error page | the link already falls back to the store search when the game has no concept; the case left is a concept missing in the country's store — the spec checks what PS Store answers and when to ask it |
| 38 | An IGDB record without date precision reads as «date not announced» | the precision from the fields the record has (`y`, `m`) when `date_format` is missing or unknown; a day is never guessed |
| 43 | The bundle price is for a buyer without the games of the set | **won't fix** (only a Steam sign-in knows what the owner has): the card and the message say «цена набора целиком» |
| 44 | The preorder is checked only on an assembled answer | the spec looks for a live preorder in Steam, saves its answer as a fixture, fixes the parsing if it differs |
| 46 | A short discount can pass without a message or with a wrong «до» | **won't fix**: checks every 6 hours and the delivery rules stay; a test pins it |
| 47 | A discount message can go out in the minute the game left «Хочу» | the price check queues through `checks.still_checked` in its write session (wish of review 9.1a), and the pending Steam messages are withdrawn by the status change |
| 50 | A spoiled price snapshot stops the price check of every game | that game is skipped with a log line once a day; the others are checked |
| 51 | The discounts of one check can come as separate messages | the events of one check are queued at once (one write session) |
| 52 | A standalone expansion completed before 6.3 never learns it is one | the follow-up check also stores the game's own type and parent |
| 53 | «Бросил» and «Вернуть в список» within a minute keep the old reference point | the follow-up check queues through `checks.still_checked` (wish of review 9.1a); «Бросил» removes the follow-up snapshot itself, or the return is compared with it |
| 54 | An announcement withdrawn by «Бросил» never comes from another game of the series | a withdrawn event frees its dedup key |
| 55 | An unreadable own snapshot logs every minute; a never-checked game is never told | one log line a day; both cases fail the check and report once a day |

## Russian in games — what is known already

Checked live on 2026-11-20 (the spec saves the answers as fixtures):

- **Steam.** `IStoreBrowseService/GetItems` — the request of the price check — returns the languages with `"data_request": {"include_supported_languages": true}`: a list of `{elanguage, supported, full_audio, subtitles}`; Russian is `elanguage` 8. Cyberpunk 2077: `full_audio` true, `subtitles` true; Stray: `full_audio` false, `subtitles` true. The languages are wanted for more games than the prices («Хочу» and «В процессе», a Steam page, any of the owner's platforms; prices — «Хочу» with «играю здесь» on PC), so the spec decides: one request for both sets, or two. At adding, `appdetails` (already asked for the Russian name) gives `supported_languages` as one HTML string, `*` marking full audio.
- **ZoG.** The site search is Google's (JavaScript), not usable by the app. A game page lives at `https://www.zoneofgames.ru/games/<name>/`: of 11 games tried, 9 opened by the original name (`cyberpunk_2077`, `baldurs_gate_3`, `elden_ring`, `disco_elysium`, `stalker_2_heart_of_chornobyl`, `clair_obscur_expedition_33`, `hollow_knight_silksong`, `prey`, `hades`). ZoG names games its own way: Hades II is `hades_2` (`hades_ii` is not found — the Roman ↔ Arabic variant finds it); The Witcher 3: Wild Hunt was not found by `the_witcher_3_wild_hunt`, `the_witcher_3`, `witcher_3` or `witcher_3_wild_hunt` — such a game needs the owner's link. A missing page answers `200` with the page title «Ошибка» (the title of a found one: «Hades 2 | Игровой архив на Zone of Games»). Pages are `windows-1251`. The fan translations are the list after «Переводы:» — «Русификатор (текст)», «Русификатор (звук)», with other languages beside («Українізатор (текст)», «Беларусізатар (текст)» — not counted) and sometimes the platform («- для ПК-версии»). `robots.txt` allows game pages.
- **IGDB.** `language_supports` (language, support type: audio, subtitles, interface) — not checked yet; the spec checks it with the owner's key.

## Parts and order

One stage, one spec (decision 4). The spec takes the 14 entries (directions fixed above, the spec adds what each needs) and idea 002 (the idea already has behaviour, edge cases and tests; the spec fixes the texts, the data and the checks of the sources). Tickets: the known issues first — they change the price check, the follow-up check and the game dates, which the Russian check then builds on — then Russian in games. Sessions (est.): spec 1, slicing 1, about 6 tickets, review 1 — 9 after this one.

## In scope · out of scope

In scope: the 14 entries above; idea 002 as in its file, with the decisions below; the wish of review 9.1a for 9.1b; every new entry the review of 9.1b defers goes to 9.1c.

Out of scope: Russian in Search and in the List; fan translation sites other than ZoG; Russian per console; other languages; downloading translations; anything of 9.1c and 9.1d.

## Pulled-in `KNOWN_ISSUES.md` entries and review wishes

- KI-35, 36, 37, 38, 43, 44, 46, 47, 50, 51, 52, 53, 54, 55 (all open, «Fix in 9.1»; part 9.1b by `.scratch/9-1-known-issues/description.md`). No other open entry is about games or Steam.
- Review 9.1a, «Wishes for later stages»: the price check and the follow-up check queue their events through `checks.still_checked` in their write session (with KI-47, KI-53). The Russian check follows the same rule from the start.
- Idea 002.

## Decisions taken with the owner

1. **The fan part fills only what the official lacks** (owner, 2026-11-20): fan voice beside official text is shown and told; fan text beside official text is neither shown nor told; the field «Страница на ZoG» stays. Rejected: show every translation, official and fan, even of the same thing.
2. **The line is filled right after adding** (owner, 2026-11-20): the Steam answer at adding gives the languages; ZoG is asked once; quiet, no messages; a failure of either leaves «нет данных» for its part, never fails adding. Rejected: wait for the regular checks (up to 6 hours for Steam, a week for ZoG with «нет данных» until then).
3. **The ZoG page by a few address variants** (owner, 2026-11-20): the original name, Roman ↔ Arabic numbers, without the subtitle after a colon (2–4 requests at most); a page is taken only when ZoG's name of it matches the game; else «не найдена» and the owner pastes a link. Rejected: the exact name only (fewer requests, more pasting by hand).
4. **9.1b stays one stage with one spec** (agent; confirmed by the owner's «ОК» of this description). What is checked above is not checked again. The estimate of 9.1b grows from 8 to 10 sessions with this description (`docs/project-spec.md`).
5. **Taken by the agent, confirmed by the owner's «ОК»:** the block «Русский язык» stands after «Платформы» in the web card; a fan part shown gives «🌐 Страница перевода» under the bot card and the fan message; the button of an official message is «🛒 Открыть в Steam» when the game has a Steam page; the Russian events go through `checks.still_checked` and are withdrawn like other game messages when the game leaves «Хочу» or «В процессе»; ZoG gets a polite `User-Agent` without the owner's details, one page per game a week spread in time.
6. **No wishes beyond the entries and the idea** (owner, 2026-11-20).

## Open questions for the spec

- Steam: one `GetItems` request for prices and languages or two; the languages at adding from `appdetails` (its HTML string) or from `GetItems`.
- ZoG: the rules of the address variants and of the name match; how a «Русификатор» entry tells text, voice, both and the platform; what «a changed layout» is (nothing parses — «нет данных», a log line a day); the check of a pasted link (only `zoneofgames.ru/games/<name>/`, the page exists).
- IGDB `language_supports`: the request and its answer, live with the owner's key.
- Where the Russian state lives — columns of the game or a snapshot of a source, as Steam prices are; the migration; the new event types and their dedup keys.
- The exact texts: the line in every state, the not-found and rejected states, the error of the field, the messages, the line «в Японии — …».
- The owner's check of a message: a sample in Settings «Тестовое событие».
- KI-36: where «release reported» lives (a migration); KI-37: the PS Store answer for a missing concept and its cost; KI-38: which IGDB fields give the precision; KI-44: a live Steam preorder.
