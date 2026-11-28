# Stage 6.5: Meta Quest as a platform of games

Status: accepted

Terms come from `CONTEXT.md`. This stage takes in idea 003 (`docs/ideas/003-meta-quest.md`); the idea stays the detailed reference for scenarios, edge cases and tests, this file is the source of truth where they differ. Decisions it leans on: ADR 0009 (no PlayStation prices — the same reasoning keeps Meta store prices out), ADR 0010 (the bot takes posts and links for adding), ADR 0011 (a followed expansion is a game of its own). Mockup: `mockups/quest-pieces.html` (no new screens; the pieces of existing ones that change). Done while stage 7.4 waits for the NAS project's report.

## Goal

The owner plays VR games on a Meta Quest 3 and buys them in the Meta store. Today the tracker knows only ПК, PS5, Xbox Series X|S, Switch 2 and Switch, so a Quest game cannot be followed. After this stage Meta Quest is a platform like the others: its date in the card, a message on the release day, a link to the store, and «Meta Quest» in the line of platforms of Search.

## What the owner will see at the end

- **Settings → «Мои платформы»:** a sixth checkmark «Meta Quest», last in the list. Defaults stay ПК and PS5.
- **Search and «Входящие» candidates:** the line of platforms under a game names «Meta Quest» once, whichever Quest headsets IGDB lists for it («ПК, PS4, Meta Quest»).
- **Card (web and bot):** a row «Meta Quest — <date>» with «играю здесь», last among the platform rows. A game IGDB lists only for Quest 2 or the first Quest shows that date with the version: «Meta Quest — 12 мая 2024 (версия для Quest 2)»; with dates of several headsets the earliest by the end of the period counts, as for PS5/PS4 (glossary «Обратная совместимость»). Next to the Steam and PlayStation Store links: «Открыть в магазине Meta» — the game's page in the store when IGDB knows it, otherwise the store's search by the game's name. Shown when Meta Quest is among «Мои платформы» and the game is on Quest.
- **Feed:** Quest releases stand among the others: «Выход на Meta Quest», «Выход на ПК и Meta Quest»; a date via an older headset in the form the Feed already uses for PS4 («Выход на Quest 2 (идёт на Meta Quest)», exact text by the spec).
- **Telegram, release message:** «🎮 <name> вышла на Meta Quest» by the usual delivery rules, with «Карточка» and the link button «Открыть в магазине Meta». A release on several platforms on one day stays one message («вышла на ПК и Meta Quest»), as today; the store button is there whenever Meta Quest is among its platforms.
- **Telegram, a link to the Meta store sent to the bot** (`meta.com/experiences/…`, a forward or a post with it): the bot skips «Что это?» and sends the card «Это оно?» at once, as for a Steam link today. IGDB does not know the game by that link — the post goes to «Входящие» as any link not found.
- **Expansions and series (6.3):** announcements of expansions and new games of a series coming out on Meta Quest come as usual, since Meta Quest is now one of «Мои платформы».

## In scope

- One platform `meta_quest` for every Quest headset: Meta Quest 3, Meta Quest 2 and the first Oculus Quest (and Quest 3S if IGDB has a number of its own); the two older headsets are older platforms of Meta Quest, so the shape of «the older platform» grows from one to several (rule 6 of `docs/coding-standards.md`: the table stays the one place).
- The label «Meta Quest» everywhere (Settings, card, messages, Feed); placed last in the platform table.
- The store link in the web card, the bot card and under the Quest release message; the page from IGDB `external_games`, else the store's search. No check of the address (unlike the PlayStation Store page, KI-37): both forms open something useful.
- The Meta store link recognised among the links of «Входящие» and looked up in IGDB by its `external_games` number.
- The glossary: «Платформа», «Обратная совместимость» and «Страна магазинов» (if the store address does not depend on the country) name Meta Quest; the JSON export carries `meta_quest`.
- Data from IGDB only: no new service, no key, no request to the Meta store itself. No migration expected (platform values are strings).

## Out of scope

- Prices and discounts of the Meta store (no official API; reading it unofficially is fragile) — the owner's choice.
- Languages and Russian from the Meta store; a Quest-only game keeps the mark «(ПК)» on Steam and ZoG data (idea 002).
- Separate checkmarks for Quest 2, Quest 3, Quest 3S; PC VR as a platform of its own (SteamVR games stay PC); other VR platforms (PlayStation VR2, Pico).

## Pulled-in known issues and review wishes

None fit: the open entries about games (KI-79, KI-80) are about Russian and wait for real use in 9.2; the wishes of the 7.3 review are for 7.4 and 9.2.

## Decisions taken with the owner

- Dates, release messages and a store link; no prices (idea 003).
- Quest 2 and first-Quest games count as Meta Quest games, with the version text (idea 003).
- The label «Meta Quest» everywhere, no model number (idea 003).
- The link text «Открыть в магазине Meta», not the store's current name «Meta Horizon Store»: shorter on a Telegram button and survives another rename (2026-11-28).
- A Meta store link sent to the bot gives «Это оно?» at once, like a Steam link (2026-11-28; added to idea 003).
- The link in the card and under the release message; the store's search when the page is unknown (idea 003).
- A stage of its own, done while 7.4 waits (idea 003).
- Changed by the spec, with the owner, on real IGDB answers (2026-11-28; `spec.md`, section 0): no version text for Quest — the three headsets are the platform's own numbers; SteamVR counts as ПК (IGDB writes the PC version of a VR game as SteamVR, not PC).
- By the agent: the platform last in the table, default platforms unchanged, «Meta Quest» once in the line of a suggestion — the least change to what the owner sees now. One release message per day for several platforms stays as today (idea 003 said "two messages" for a game on PC and Quest; that holds for different days only).

## Owner check at the end of the stage

The session prepares the list: which games to search (a Quest-only game, a game on PC and Quest, a game IGDB lists only for Quest 2 or the first Quest), what each card must show (dates, the version text, the link and where it leads), a Meta store link to send to the bot, and one faked release message on Meta Quest to see the button. The owner ticks «Meta Quest» in Settings and walks the list in the web and in the bot.

## Proposed split

About 2 tickets, the spec decides: 01 the platform — table and older platforms, dates in the card and the Feed, release events, the line of a suggestion, Settings and export; 02 the Meta store — the link in the cards and under the release message, the store link in «Входящие». Sessions: spec, slicing, 2 tickets, review — 5, as in `PROJECT_CONTEXT.md`.

## Open questions for the spec

- IGDB numbers of the Quest platforms (believed 471 Quest 3, 386 Quest 2, 384 Quest) and whether Quest 3S has its own; checked on real answers, saved next to the spec.
- The `external_game_source` number of the Meta / Oculus store in IGDB, the form of its `uid` and `url`, how many Quest games have one (5–10 real games); the address of a store page and of the store search, and whether they depend on the country.
- The forms of a Meta store link the bot must read (`meta.com/experiences/<id>`, `…/experiences/<slug>/<id>`, old `oculus.com/experiences/quest/<id>`, a locale in the path).
- How IGDB writes the dates of Quest games in practice (often only Quest 2, often without a region) and how that sits with the regions of «Страна магазинов».
- The data shape for several older platforms, and how `older_tells` (Switch 2 ← Switch: the older one, when itself the owner's, gives the message) reads with it — none of the Quest headsets is a platform of its own.
- The exact texts: the version words («версия для Quest 2» / «версия для Quest»), the Feed line via an older headset, the store link in the bot's text card.
