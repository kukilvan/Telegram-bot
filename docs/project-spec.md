# Release tracker — project spec

The product as agreed. Once a stage's description is approved, it overrides that stage's section here; a session that changes the plan of later stages updates this file. Stage ids are the roadmap numbers from before the move to this workflow (0–9, with parts 5.1–5.4 and 6.1–6.4).

## Vision

A personal tracker of releases of movies, series, anime and games for one owner. It tells about important events (a date is announced, an episode is out, a game is out on my platform, a discount), keeps the owner's progress and scores. The web app is the main interface (ADR 0002); the Telegram bot stays a delivery channel. Later the code goes to GitHub as a template «make yourself one» (a new repository with a clean history).

## Users and access

One owner per instance (ADR 0001). The web is protected by a password (`WEB_PASSWORD`); the bot answers only users from a whitelist. Anyone who wants can deploy their own instance on their own API keys.

## Core scenarios

1. Find a title in Search (movie · series · anime · game), add it to the list.
2. See what comes out soon in the Feed (soon · later · recently); get a Telegram message and a daily summary (15:00 by default; work days, quiet hours).
3. Open a title card: seasons and parts with checkmarks, status, score, platforms of a game, sequels.
4. Mark watched / started / finished / dropped; the title goes to the Archive; score 1–10 with «+» and «−».
5. Games: platforms «I play here», release dates by region, links to Steam and PS Store; Steam prices, discounts and bundles (6.2).
6. Settings: time zone, work days, summary hour, quiet hours, my platforms, store country.

## Features

- **Done:** everything in scenarios 1–4 and 6 for movies, series, anime, games (stages 0–6.1); prices, discounts and bundles of Steam for games in «Хочу» with the PC checkmark (6.2).
- **Next** (in this order; changed 2026-11-17: the known issues and the move come before real use): 9.1 every open known issue fixed before the move; 7.3 NAS readiness and the move guide (the move itself and outside access — the owner's separate NAS project, ADR 0013); 7.4 the NAS project's report taken in; 9.2 fixes after real use on the NAS; 8 template for GitHub. Done since 6.1: 6.3 expansions and sequels, 6.4 «Входящие» (ADR 0010), 7.1 backups and export, 7.2 the app address, the phone, bot links and a safer login.
- **Never:** notes and tags, the commands `/add`, `/remove`, `/watchlist`, `/note`, `/notes`, `/events`, `/search`, `/searchgame`, inline search, the events «Русская озвучка» and «KinoPub», RAWG and the unofficial PSN request, PlayStation prices (ADR 0009), anything hard-coded for one owner.

## Interface

Web (FastAPI + HTMX, no own JavaScript, ADR 0004), Russian UI, installable on phone (PWA manifest). Telegram bot: takes posts and names for «Входящие» (ADR 0010); menu «📚 Мои тайтлы», «📋 Сводка сейчас», «🧪 Тестовое событие», «Карточка» under events. In 7.2, once the address of the app is set: «Карточка» becomes a link to the web card, «Мои тайтлы» goes, «Сводка сейчас» stays; «Тестовое событие» moves to the web Settings; without the address the bot stays as it is.

## Running and data

Bot, polling and web in one process (ADR 0007), in Docker on the owner's PC until a NAS appears (ADR 0006); the web is open to the home network on request (ADR 0008). Data: SQLite in WAL mode `data/tracker.db` (ADR 0005); copies in `data/backups/` (at start, hourly if the last is older than a day, before a migration; 14 + 12 rotation). Sources: TMDb, AniList, Shikimori, IGDB, Steam; keys in `.env` (`PROJECT_CONTEXT.md`, "Environment").

## Quality

Automated tests run offline on fake sources and SQLite in memory (`docs/tests-map.md`). The owner checks live in the browser and in Telegram after every ticket. Secrets are masked in logs; the whitelist is closed by default; login is rate-limited; the bot and the web run as one instance only.

## Stages

Finished (details — `docs/history.md`, `.scratch/`):

- **0–4** urgent fixes, data model, sources for movies/series/anime, events and delivery, the cut-down bot.
- **5.1–5.4** the web app: Docker and skeleton with login, search/list/card, feed/archive/scores, settings and PWA manifest.
- **6.1** games in the list and release events (IGDB, my platforms, «Пройдено»).

### Stage 6.2. Steam prices, discounts and bundles (done)

- Goal: tell the owner about discounts, bundles and a Steam page for games he waits for.
- The owner sees at the end: a «Steam» block in the game card (price, discount with end day, lowest price since adding, bundles), a «−30 %» mark in the List, a price line in the bot card, messages «скидка», «бандл», «появилась страница в Steam».
- Contains: `.scratch/games-2-steam-prices/` — 01 cleanup (accepted), 02 Steam client + adapter + pure prices module (complex), 03 price check in the polling pass, history, migration 0013 (complex), 04 Steam events and sending (complex), 05 what the owner sees (medium); then the review.
- Sessions (est.): 4 tickets + review.

### Stage 6.3. Expansions and sequels of games

- Goal: know about big expansions and new games of a series the owner follows.
- The owner sees at the end: games in «Хочу», «В процессе», «Пройдено» checked in IGDB once a week; messages «Анонсировано дополнение» and «Анонсирована новая игра серии» (on «Мои платформы», remakes included) with «Следить»; card blocks «Дополнения» and «Продолжения»; an expansion followed is a game of its own (dates, «вышла», Steam prices), marked «дополнение» in the List.
- Contains: `.scratch/6-3-game-dlc-sequels/description.md` (accepted) → spec → tickets → review.
- Sessions (est.): 6 (spec, about 4 tickets, review).

### Stage 6.4. «Входящие» (idea 001)

- Goal: add a title from Telegram by a forwarded post or a name; a «Входящие» tab in the web; posters in bot cards; the «➕ Добавить» button goes away.
- The owner sees at the end: forward a post to the bot, find the title in «Входящие», confirm it.
- Contains: `.scratch/6-4-inbox/description.md` (accepted; takes in `docs/ideas/001-telegram-inbox.md` and its examples; ADR 0010) → spec → tickets → review.
- Sessions (est.): about 8 (spec, slicing, about 5 tickets, review).

### Stage 7. Backups, NAS and phone — split into 7.1, 7.2, 7.3

Split by `.scratch/7-1-backups-export/description.md` (2026-11-07). Changed by `.scratch/7-2-access-phone/description.md` (2026-11-15, ADR 0013): outside access by the owner's domain, Cloudflare Tunnel and Cloudflare Access instead of Tailscale, and the NAS move itself are done by the owner's separate NAS project for two apps; 7.3 here only prepares the move. Order: 7.1 → 7.2 → 9.1 → 7.3 → 7.4 → 9.2 → 8 (7.4 added 2026-11-24; changed 2026-11-17 by the owner: every known issue fixed and the app on the NAS before real use, so the fixes after real use are made where the app lives).

### Stage 7.1. Backups and export

- Goal: the data can be got back after a dead disk or a lost PC.
- The owner sees at the end: Settings block «Копии и выгрузка» (copies on the PC, the Google Drive copy state, «Сделать копию сейчас», «Скачать список (CSV)», «Скачать всё (JSON)», no import); an encrypted copy in Google Drive once a day, through the Google Drive API with the owner's own Google client (ADR 0012; rclone dropped by the spec), 30 kept, off by default, an archive 7-Zip opens by the password; `.\restore-bot.ps1` restores a local copy or a downloaded archive, keeping the current database aside.
- Contains: `.scratch/7-1-backups-export/description.md` → `spec.md` → tickets → review.
- Sessions (est.): about 8 (spec, slicing, 5 tickets, review).

### Stage 7.2. The app address, the phone, the bot as links, a safer login

- Goal: open the card of a bot message in the web on the PC or the phone; every screen fits a phone; the login ready for the internet.
- The owner sees at the end: the address of the app in `.env` (until the NAS — the PC's home address); bot buttons as links (see Interface); «Тестовое событие» and the delivery-rules check in the web Settings; the «Вход» block with «Выйти на всех устройствах»; a Telegram message on every login; every screen walked at phone width; PWA installability checked on the PC; KI-7, KI-8, KI-12, KI-13 fixed and trusted proxy headers; a short document of what the app needs behind a domain (for the NAS project). Not here: the domain and the tunnel (ADR 0013).
- Contains: `.scratch/7-2-access-phone/description.md` → spec → tickets → review.
- Sessions (est.): about 7 (spec, slicing, 4–5 tickets, review).

### Stage 9.1. Known issues before the move

- Goal: every open `KNOWN_ISSUES.md` entry is fixed before the app moves to the NAS (the owner's decision, 2026-11-17), so real use on the NAS starts from a clean base. KI-15 and KI-70 belong to 7.3.
- The owner sees at the end: each open entry `fixed (test: …)`. An entry that cannot be fixed within the app's rules (no JavaScript of its own, ADR 0004: KI-72, KI-74) or where a source gives no data (KI-48) gets a test that pins the behaviour and the owner's decision in the entry. The description groups the entries (anime and series, the start and stop of the app, statuses and polling, games, Steam prices, «Входящие», copies, the web, code health) and may split the stage.
- Split by `.scratch/9-1-known-issues/description.md` (2026-11-20) into four parts, each starting from its spec: 9.1a start, stop, polling and delivery (17 entries); 9.1b games and Steam prices (14); 9.1c Лента, web and login (11); 9.1d «Входящие», copies and code health (15). KI-43, KI-46, KI-72 (and KI-48 if no source has data) close as `won't fix` with a test and the owner's decision.
- Idea 002 (`docs/ideas/002-russian-in-games.md`, added 2026-11-20) joins 9.1b, taken in by `.scratch/9-1b-games-steam/description.md` (2026-11-20; 9.1b has a description of its own for it): the «Русский: …» line of the game card in the web and the bot (official from Steam, else IGDB; fan translations from ZoG; text, voice, both, none, no data; the «(ПК)» mark), the «Страница на ZoG» field, messages when Russian appears for a game in «Хочу» or «В процессе».
- 9.1c has a description of its own too (`.scratch/9-1c-feed-web/description.md`, 2026-11-22): the anime episode hour only when the source gave it (also in the card and the bot), «Недавно» with episodes and films out before adding, one name per genre in the Archive filter, the chosen phone filter first in its row, «Это оно — убрать запись» in the Search from «Входящие»; with KI-77 from spec 9.1a.
- 9.1d has a description of its own as well (`.scratch/9-1d-inbox-copies-code/description.md`, 2026-11-23): 18 entries with KI-81, 83, 84 of 9.1c. The approximate date of an offer reads «выйдет в 4 квартале 2027». An anime premiere known by the month or the year shows as such and sends no message until the exact day, as with games. The companies of a post come from IGDB. «Что это?» survives a restart. The copies show the time of Settings. The six unread names leave `.env`. The core's long modules are split first.
- Sessions (est.): about 32 (9.1a 7, 9.1b 10 with its description and idea 002, 9.1c 6–7 with its description, 9.1d 9 with its description).

### Stage 7.3. NAS readiness and the move guide

- Goal: the owner's separate NAS project can move the app to a UGREEN DXP2800 (Intel N100, NVMe SSD, 3 TB HDD) and everything keeps working; the move itself is not done here (ADR 0013).
- The owner sees at the end: the app proven to run in its container on the NAS (the same `amd64` image, the database on a local SSD volume, never on a network share; copies may go to the HDD), start, stop and restore by `docker compose` without PowerShell, KI-15, KI-70, and a guide: what to move (`data`, `.env`, the compose file), where, in what order, the one-instance rule, the checks after the move, the Google Drive connection, the app address.
- Comes after 9.1 and before real use (changed 2026-11-17; it used to come after stage 8). The guide names this repository (stage 8 changes the address).
- Changed by `.scratch/7-3-nas-readiness/description.md` (2026-11-24): this project does not touch the NAS; the checks run on the PC, and the guide `docs/nas-move.md` names every foreseeable problem with its solution and asks the NAS project for a report back. The copies may go to the HDD by a NAS-only compose file; the restore on the NAS is three `docker compose` commands; no code guard against two instances, only the rule in the guide.
- Sessions (est.): 6 (spec, slicing, about 3 tickets, review).

### Stage 6.5. Meta Quest (idea 003)

- Goal: follow VR games on Meta Quest like games on the other platforms.
- The owner sees at the end: «Meta Quest» in «Мои платформы»; in the card a row «Meta Quest — <date>» (Quest 2 and first-Quest versions count) with «играю здесь» and the link «Открыть в магазине Meta» (the game's page, else the store's search); the release message on Meta Quest with the same link button; «Meta Quest» in the line of platforms of Search. No Meta store prices.
- Contains: `docs/ideas/003-meta-quest.md` — taken in by the description of 6.5 (`.scratch/6-5-meta-quest/`). Done while stage 7.4 waits for the NAS project's report.
- Sessions (est.): about 5 (description, spec, slicing, about 2 tickets, review).

### Stage 7.4. The move taken in

- Goal: after the NAS project has moved the app and written its report, the sessions of this project work with the app on the NAS.
- The owner sees at the end: the NAS in `PROJECT_CONTEXT.md` («Environment»), «Run» of `CLAUDE.md` and «Session on the owner's PC» of `docs/workflow.md` rewritten by ADR 0017: checks run on a **test bot on the PC** (its own token from BotFather, its own `.env` and `data`, without the Google Drive connection), `.\start-bot.ps1` refuses the real token, the PC's real `data` and `.env` kept aside as the way back; the NAS gets only `master` after «ОК», by the NAS project's update command, which a session runs; the health and the log on the NAS read from the PC.
- Changed 2026-11-25 by the answer to the NAS project (`.scratch/7-3-nas-readiness/nas-answer.md`, ADR 0017): it used to send a session's branch to the NAS.
- Sessions (est.): 1 («Приём переезда»).

### Stage 9.2. Fixes after real use

- Goal: fix what 1–2 weeks of real use on the NAS show (outside access, the phone over `https`, the installed app); the live check of early tickets happens here.
- Contains: the owner's notes; the `KNOWN_ISSUES.md` entries found since 9.1.
- Sessions (est.): 2+.

### Stage 8. Template for GitHub

- Goal: anyone can deploy their own instance.
- The owner sees at the end: a cleaned repository (junk files), a new repository with a clean history, MIT licence, Russian README, description of keys and settings; the move guide of 7.3 points to the new repository. **Replace all API keys before publishing.** After the move the new values are set on the NAS by the NAS project's command (hidden input), not in the PC's `.env` (it is the stale way back). A final review on Fable 5.1.
- Sessions (est.): 1.

Risks to the estimates: Shikimori has no official «part of a season» link (a heuristic on names can err); realistic events do not come on schedule, so part of the checks runs on faked events; open question — how to tell reliably «closed or cancelled» for anime.
