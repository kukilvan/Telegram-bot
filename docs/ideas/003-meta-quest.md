# Idea 003: Meta Quest as a platform of games

Status: taken in by `.scratch/6-5-meta-quest/description.md` (stage 6.5)
Added: 2026-11-28

## Why

The owner plays VR games on a Meta Quest 3 and buys them in the Meta store (Meta Horizon Store). Today the tracker knows only ПК, PS5, Xbox Series X|S, Switch 2 and Switch, so a Quest game cannot be followed: no Quest date in the card, no message when it comes out on Quest, and Search does not say a game is on Quest.

## Scenario

1. Settings → «Мои платформы»: the owner ticks «Meta Quest» and saves.
2. Search: the owner types a VR game; the line under its name says «Meta Quest» among its platforms («ПК, Meta Quest»).
3. The owner adds the game. The card has a row «Meta Quest — <date>» with the checkmark «играю здесь» (set by itself, as on any platform of the owner where the game exists) and the link «Открыть в магазине Meta».
4. A game IGDB lists only for Quest 2 or the first Quest shows its date with the version: «Meta Quest — 12 мая 2024 (версия для Quest 2)».
5. On the release day on Quest a message comes by the usual delivery rules (summary at 15:00, quiet hours, work days), with a link button «Открыть в магазине Meta» under it.
6. Expansions and new games of a series coming out on Meta Quest come as usual (stage 6.3), since Meta Quest is now one of «Мои платформы».
7. The owner forwards a post with a link to a game in the Meta store: the bot sends «Это оно?» at once, as for a Steam link (added by the description of 6.5).

## Behaviour

- New platform in the table `PLATFORMS` (`app/tracker/platforms.py`): label «Meta Quest» in Settings and in the card and messages alike (the owner's choice: no model number). Placed last in the table (after Switch), so last in Settings, in the card and in the line of platforms.
- One platform for every Quest headset: games IGDB lists for Meta Quest 3, Meta Quest 2 or the first Oculus Quest all count, like the older platforms of PS5 (glossary «Обратная совместимость»): the date of an older version, when it ends earlier, counts as the Meta Quest date, with «(версия для Quest 2)» / «(версия для Quest)» (exact texts by the spec). The current `OlderPlatform` holds one older platform; Meta Quest needs two (the spec decides the shape).
- The line of platforms of a suggestion (Search, «Входящие» candidates) shows «Meta Quest» once, whichever of the three IGDB platforms the game has — not «Meta Quest, Quest 2, Quest» (the spec fixes how it sits with the PS4 / Xbox One behaviour).
- Link «Открыть в магазине Meta» (text by the spec):
  - in the web card and the bot card, next to the Steam and PlayStation Store links, when Meta Quest is among «Мои платформы» and the game is on Quest;
  - as a link button under the message «вышла на Meta Quest» (like «Открыть в Steam» under the Steam messages);
  - leads to the game's page in the Meta store when IGDB knows it (IGDB `external_games` of the Oculus / Meta source — the spec checks the source number and the address form on real answers); otherwise to the store's search by the game's name.
- Default «Мои платформы» stay ПК and PS5.

## What changes in existing behaviour

- «Мои платформы» get one more checkmark. Ticking it gives the games already in the list that exist on Quest the checkmark «играю здесь» by itself (as for any platform added to «Мои платформы» today: a missing row reads as checked).
- The Russian line: a game played on Meta Quest only gets the mark «(ПК)» on Steam and ZoG data, by the rule of idea 002 (the data is about the PC version). No Russian source for Quest.
- Steam prices are unchanged: they depend only on PC.
- The glossary term «Платформа» and «Обратная совместимость» name Meta Quest (by the ticket that adds it).
- The JSON export carries the new platform value (`meta_quest`, the spec fixes it; values never change once stored).

## Data and external services

- IGDB only, no new service and no key: the Quest platforms are new numbers in the same requests (believed Meta Quest 3 = 471, Meta Quest 2 = 386, Oculus Quest = 384; the spec checks them on real answers, and whether Meta Quest 3S has a number of its own).
- The store page from IGDB `external_games` (one more field in the existing game request; the spec checks the source number). No requests to the Meta store itself.
- Database: no migration expected (platform values are strings in `game_platforms` and in the setting `my_platforms`); the spec confirms.

## Edge cases

- A Quest game with no date in IGDB: the row as for any platform with no date (the existing text).
- IGDB has only a Quest 2 or first-Quest date: the version text above; both a Quest 3 and a Quest 2 date: the earlier by the end of the period, as for PS5/PS4.
- A game both on PC (Steam, PC VR) and Quest: two rows, two checkmarks, two release messages, as for any two platforms.
- IGDB knows no store page: the search link. A store page that has since gone: the link opens Meta's own error page; the tracker does not check the address (spec may decide otherwise).
- The owner unticks Meta Quest: the Quest rows and the link hide, release messages on Quest stop — the existing behaviour of «Мои платформы».
- Two Quest IGDB platforms with different dates do not give two release messages: one platform, one release.
- IGDB names a Quest store id for a game that is not the same game (a wrong record): the owner sees the wrong page; not handled (rare; a `KNOWN_ISSUES.md` entry if met).

## Out of scope

- Prices and discounts of the Meta store (no official API; reading them unofficially is fragile — the owner's choice).
- Languages / Russian from the Meta store.
- Separate checkmarks for Quest 2, Quest 3, Quest 3S.
- PC VR as a platform of its own: SteamVR games stay PC.
- Other VR platforms (PlayStation VR2, Pico).

## Decisions

- Dates, release messages and a store link; no prices — with the owner.
- Quest 2 and first-Quest games count as Meta Quest games, with the version text — with the owner.
- The label «Meta Quest» everywhere — with the owner.
- The link in the card and under the release message; the store's search when the page is unknown — with the owner.
- A stage of its own, 6.5, done while stage 7.4 waits for the NAS project's report — with the owner.
- The platform last in the table; default platforms unchanged; the line of a suggestion says «Meta Quest» once — by the agent: the least change to what the owner sees now.
- No check of the store address (unlike the PlayStation Store HEAD of KI-37) — by the agent: the address comes from IGDB or is a search, both open something useful; the spec may revise if real answers show dead ids.

## Owner check

The session prepares the list (the owner's choice): which games to search, what each card must show (dates, version text, the link and where it leads), and one faked release message on Meta Quest («🧪 Тестовое событие» or the session's own way) to see the button. The owner ticks «Meta Quest» in Settings and walks the list in the web and in the bot.

## Tests

- The platform table: the new value, labels, IGDB numbers, its older platforms; `check_platforms` accepts it.
- Card rows: own Quest 3 date, a date via Quest 2 / Quest, the earlier of two; no date.
- The line of platforms of a suggestion: «Meta Quest» once for any mix of the three numbers.
- The store link: the page from `external_games`, the search by name (name with spaces and non-Latin letters encoded), hidden when Meta Quest is not among «Мои платформы».
- The release message on Meta Quest carries the link button; other platforms' messages do not.
- Settings save and read `meta_quest`; the export carries it.

## Open questions for the stage

- IGDB numbers of the Quest platforms and of the Meta store source in `external_games`; whether Quest 3S is separate; the address forms of a store page and of the store search (and whether they depend on the country).
- The data shape for two older platforms.
- How IGDB writes dates of Quest games in practice (often only Quest 2, often a date without region) — the spec looks at 5–10 real games.
- Whether the name of the store link should follow Meta's current store name («Meta Horizon Store») or stay «магазин Meta».
