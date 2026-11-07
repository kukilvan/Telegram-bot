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
- **Next** (in this order): 7.1 backups and export; 7.2 access from outside the home and the phone; 9 fixes after real use; 8 template for GitHub; 7.3 the move to the NAS when it appears. Done since 6.1: 6.3 expansions and sequels, 6.4 «Входящие» (ADR 0010).
- **Never:** notes and tags, the commands `/add`, `/remove`, `/watchlist`, `/note`, `/notes`, `/events`, `/search`, `/searchgame`, inline search, the events «Русская озвучка» and «KinoPub», RAWG and the unofficial PSN request, PlayStation prices (ADR 0009), anything hard-coded for one owner.

## Interface

Web (FastAPI + HTMX, no own JavaScript, ADR 0004), Russian UI, installable on phone (PWA manifest). Telegram bot: takes posts and names for «Входящие» (ADR 0010); menu «📚 Мои тайтлы», «📋 Сводка сейчас», «🧪 Тестовое событие», «Карточка» under events. In 7.2, once the address of the app is set: «Карточка» becomes a link to the web card, «Мои тайтлы» goes, «Тестовое событие» moves to the web Settings, «Сводка сейчас» stays; without the address the bot stays as it is.

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

Split by `.scratch/7-1-backups-export/description.md` (2026-11-07), which also holds the decisions for 7.2 and 7.3. Order: 7.1 → 7.2 → 9 → 8 → 7.3 (the NAS is not bought yet).

### Stage 7.1. Backups and export

- Goal: the data can be got back after a dead disk or a lost PC.
- The owner sees at the end: Settings block «Копии и выгрузка» (copies on the PC, the Google Drive copy state, «Сделать копию сейчас», «Скачать список (CSV)», «Скачать всё (JSON)», no import); an encrypted copy in Google Drive by rclone once a day, 30 kept, off by default, an archive 7-Zip opens by the password; `.estore-bot.ps1` restores a local copy or a downloaded archive, keeping the current database aside.
- Contains: `.scratch/7-1-backups-export/description.md` → spec → tickets → review.
- Sessions (est.): about 6 (spec, slicing, 3–4 tickets, review).

### Stage 7.2. Access from outside the home and the phone

- Goal: open the app from the phone anywhere and from the bot's messages.
- The owner sees at the end: Tailscale with an `https` address (on the PC; a new ADR supersedes the «until the NAS» part of ADR 0006 and 0008); the address of the app in `.env`; bot buttons as links (see Interface); «Тестовое событие» and the delivery-rules check in the web Settings; the phone installation (PWA) checked; the login hardened for the outside (KI-7, KI-8, KI-12, KI-13).
- Contains: description (decisions already in 7.1's description; mockups in `.scratch/7-2-access-phone/mockups/`) → spec → tickets → review.
- Sessions (est.): about 6.

### Stage 9. Fixes after real use

- Goal: fix what 1–2 weeks of real use show; the live check of early tickets happens here.
- Contains: open `KNOWN_ISSUES.md` entries each get a test before the final polishing.
- Sessions (est.): 2+.

### Stage 8. Template for GitHub

- Goal: anyone can deploy their own instance.
- The owner sees at the end: a cleaned repository (junk files, unused `.env` variables), a new repository with a clean history, MIT licence, Russian README, description of keys and settings. **Replace all API keys before publishing.** A final review on Fable 5.1.
- Sessions (est.): 1.

### Stage 7.3. The move to the NAS

- Goal: the app lives on the NAS and works while the PC is off.
- The owner sees at the end: `data` and the container on the NAS (preliminary UGREEN DXP2800), rights on files (`PUID`/`PGID`, KI-15), start, stop and restore without PowerShell, Tailscale on the NAS, the NAS instructions in the template's README.
- Waits for the NAS; comes after stage 8.
- Sessions (est.): 3+.

Risks to the estimates: Shikimori has no official «part of a season» link (a heuristic on names can err); realistic events do not come on schedule, so part of the checks runs on faked events; open question — how to tell reliably «closed or cancelled» for anime.
