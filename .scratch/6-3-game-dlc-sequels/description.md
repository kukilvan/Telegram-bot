# Stage 6.3: expansions and sequels of games

Status: accepted

Terms come from `CONTEXT.md`. Decisions this stage leans on: ADR 0002 (the web is the main interface, the bot is a channel), ADR 0007 (bot, polling and web are one process). The plan of stage 6 comes from the description of 6.1 (`.scratch/games-1-list-and-releases/description.md`, «Как поделить кусок 6»): 6.3 is the third part. Stage 6.4 («Входящие») comes after it.

## Goal

After 6.1 and 6.2 the tracker follows a game's own release and its Steam prices, but it says nothing about what comes after the game:

- a big expansion of a game the owner plays or has finished (Blood and Wine, Shadow of the Erdtree) passes unnoticed;
- a new game of the series (The Witcher IV after The Witcher 3) is not offered the way a movie sequel is.

After this stage the tracker checks a game's expansions and its series in IGDB once a week. A new one comes as a message with «Следить»; the game card shows the known ones. An expansion the owner follows becomes a game of its own in the list, with release dates, release messages and Steam prices like any game.

## Checked on 2026-11-04 against live IGDB answers

Live requests for The Witcher 3 (1942), Elden Ring (119133) and Hades (113112). The spec saves the answers next to itself and builds on them.

- **IGDB's "DLC" is mostly small stuff.** The Witcher 3 has five records of `game_type` 1 (DLC): single quests and gear ("Fool's Gold", "Wolf School Gear"). Hearts of Stone, Blood and Wine and Songs of the Past are `game_type` 2 (expansion), in the field `expansions`. Elden Ring: Shadow of the Erdtree is an expansion, "Tarnished Pack" is a DLC.
- **The series is the field `collections`** (and `franchises`, which differ slightly: Thronebreaker is only in the franchise). The Witcher series holds a lot of noise: mobile games (Monster Slayer, Roach Race), a board game, Gwent and its expansions, Battle Arena, mods and DLC of every game. Filtering by game type and by «Мои платформы» removes nearly all of it.
- **Remakes and remasters** have their own fields (`remakes`, `remasters`: The Witcher 3: Wild Hunt Remastered) and also appear in the series (The Witcher Remake, `game_type` 8).
- **Hades:** the series «Hades» holds Hades and Hades II.
- **Announced games often have no date** (The Witcher Remake, Project Sirius).

## What the owner will see at the end

Mockups in `mockups/` (rough layout, real texts): `game-card.html`, `feed-and-list.html`, `bot-messages.html`.

1. **Which games are checked.** Games in «Хочу», «В процессе» and «Пройдено», once a week. «Бросил» is not checked. Games already in the list are checked right after the update. The first check of every game only records what exists, without messages (the same as a movie after «Посмотрел»).
2. **Expansions** (`дополнение`): only big ones, the IGDB `expansions` and standalone expansions. Small DLC (quests, gear, cosmetics, soundtracks) do not count. A new expansion of a checked game comes as a message «🎮 Анонсировано дополнение: …» with «Следить» and «Карточка».
3. **Sequels** (`продолжение`, a new game of the series): a game of the same IGDB series that comes out on «Мои платформы», including remakes and remasters; mobile, browser and board games are left out. Games of the series that came out before this game are not sequels. A new one comes as «🎮 Анонсирована новая игра серии: …» with «Следить» and «Карточка». A game the owner already follows is not offered.
4. **Game card:** the block «Дополнения» (all known expansions, with date and «Следить» or «В списке») and the block «Продолжения» (sequels found so far). The blocks also have an empty state («… пока нет. Проверяю раз в неделю») and a not-checked-yet state.
5. **«Следить» on an expansion** adds it to the list as a game in «Хочу», a title of its own. It gets its platforms with «играю здесь», release dates, the «вышла» messages and, on PC, Steam prices and discounts. Its card says «Дополнение к игре «…»» (a link when that game is in the list); the List shows the mark «дополнение». An expansion has no blocks «Дополнения» and «Продолжения» of its own.
6. **«Следить» on a sequel** adds it as an ordinary game in «Хочу».
7. **Feed, «Недавно»:** the announcements are rows with «Следить», like movie sequels now.
8. **Bot:** each announcement is a message of its own with its own «Следить» button. Delivery rules (summary, work days, quiet hours) are the same as for every event. «Тестовое событие» gets two samples: «Игра: анонсировано дополнение», «Игра: новая игра серии».

## In scope

- An IGDB source of a game's expansions and series, and a weekly check of it for games in «Хочу», «В процессе» and «Пройдено». Status changes start and stop the check; «Вернуть в список» makes the next check a reference point.
- Events «анонсировано дополнение» and «новая игра серии», their texts, «Следить», «Недавно», the test samples.
- Adding an expansion by its IGDB id (not through Search: Search keeps showing only games), with its link to the parent game.
- The card blocks «Дополнения» and «Продолжения», the line «Дополнение к игре …», the List mark, the line in the bot card.
- Glossary: «Дополнение» (expansion) as a new term; «Продолжение» widened to games.

## Out of scope

- Small DLC, mods, updates, editions (an edition stays as defined in `CONTEXT.md`).
- Expansions and sequels of a game in «Бросил».
- Expansions or games of the series in Search suggestions.
- A new sequel check for movies in statuses other than «Просмотрено» (movies keep their current rule).
- Steam DLC lists (Steam is asked only for prices, as in 6.2).
- The open `KNOWN_ISSUES.md` entries about games and Steam prices (KI-35…38, KI-43…47, KI-50, KI-51): this stage does not touch them; the owner chose to leave them for stage 9, where each gets a test and a fix after real use.

## Pulled-in wishes

- Review of 6.2: "the price source given only to the poller of games, not to every kind". 6.3 gives the game poller a second source (expansions and series), so the sources of games are wired to the game poller only.
- Review of 6.2: "`app/web/card.py` is 422 lines: when the card grows again, the game blocks (platforms, Steam) can go into a module of their own". 6.3 adds two blocks to the card, so the game blocks move into their own module.
- Review of 6.2: "`delivery.fold`: one table of fold tags": taken only if the spec folds several announcements into one message. It does not (decision 5).
- Description of 6.1 / review of 5.3: "a sequel as a pair (kind, id) instead of `SequelOffer`", left to 6.3 together with the sequels of games.

## Decisions taken with the owner (2026-11-04)

1. **Expansions are only the big ones** (IGDB `expansions` and standalone expansions), not every DLC. Why: in IGDB "DLC" means small quests and gear; announcing them would be noise.
2. **Checked statuses: «Хочу», «В процессе», «Пройдено»; not «Бросил».** Why: an expansion matters most for the game the owner plays now; a dropped game's follow-ups are not wanted.
3. **Sequels are new games of the series on «Мои платформы», remakes and remasters included.** Why: the IGDB series is noisy (mobile and board games), and the platforms filter removes that noise with a rule the owner already knows.
4. **«Следить» on an expansion makes it a separate game in the list.** Why: the owner then gets its release on «Мои платформы» and its Steam discounts with no new mechanics, through what games already have.
5. **One message per announcement, each with its own «Следить»** (my proposal, shown in the mockups). Why: a folded message cannot carry a button per game.
6. **No `KNOWN_ISSUES.md` entry is taken into 6.3**; the game and Steam entries wait for stage 9.
7. **The stage is not split:** spec, about 4 tickets, review.

## Open questions for the spec

1. Series: `collections`, `franchises` or both? Which `game_type` counts as a game of the series (0 main, 4 standalone expansion, 8 remake, 9 remaster, 10 expanded, 11 port; 12 spin-off and 13 pack?)? Check against the saved answers of several series.
2. "Came out before this game": the date to compare by when the checked game is not out yet (a «Хочу» game without a date).
3. A game of the series announced with no platforms yet, or one that later gets a platform of mine: when does it become "new" for the owner, and is it announced then?
4. Is a standalone expansion (Thronebreaker) an expansion or a game of the series? Which parent does it have in IGDB? Does it get the mark «дополнение»?
5. One request per game for expansions and series (nested fields), or separate requests; one weekly snapshot of its own source, or a part of the game's release check for «Хочу» and «В процессе».
6. Adding an expansion by id: does the current game snapshot (`GAME_QUERY`) read an expansion record as is (dates, platforms, Steam number); how the link to the parent game is stored.
7. Games already in the list: how they get their first (reference) check: a migration or a reconciliation at the polling pass, as the price check does.
8. The announcement key of deduplication: one announcement per expansion or sequel, not per checked game (two games of one series must not announce The Witcher IV twice).
9. The pair (kind, id) instead of `SequelOffer` in the Feed and the card, shared by movies and games.

## Estimate

Spec, then about 4 tickets (IGDB source and snapshot; the check, events and «Следить»; card, Feed, List and bot card; adding an expansion as a title), then the review: about 6 sessions.
