# Project context

Current state only; budget 20,000 bytes, `wc -c` (`docs/workflow.md`, "Documents"). Details of finished work live in `docs/history.md`. Updated: 2026-11-08.

## Next step

Session «Тикет 7.1.03»: ticket `.scratch/7-1-backups-export/issues/03-drive-connection.md` — the Google Drive connection (variables, sign-in and sign-out, the first lines of Settings, `docs/backups.md`); needs the owner's Google account and client for the live check. Complexity complex: model Opus 5.5, effort high (`docs/models.md`: ticket, complex). Tickets after it: 04 Google Drive copies (complex), 05 restore (complex).

## State

- Telegram bot, polling and web run as **one process** in Docker on the owner's PC (ADR 0006, 0007). Web: `http://localhost:8080` with password login; the bot is the delivery channel (ADR 0002). Commands — `CLAUDE.md`, "Run".
- Core in `app/tracker/` (entry only through the facade `core.py`), SQLite in WAL mode `data/tracker.db`, migrations up to 0014. Movies, series, anime and games are tracked: add, list, card, seasons and parts, scores, archive, sequels, polling with events, deduplication, delivery rules (summary at 15:00, work days, quiet hours), failure reports, copies of the database.
- Web is finished (stage 5, parts 5.1–5.4): Feed, List, Archive, Search, card, Settings, PWA manifest. The bot menu is «📚 Мои тайтлы», «📋 Сводка сейчас», «🧪 Тестовое событие»; «➕ Добавить» is gone (6.4.01): any other message is an inbox item.
- Games: part 6.1 done (IGDB, platforms, release events, «Пройдено»). **Part 6.2 done** (review accepted 2026-11-04, `.scratch/games-2-steam-prices/`; details in `docs/history.md`): Steam prices of games in «Хочу» with PC marked, every 6 hours at the end of a pass (`pollers/game_prices.py`, price history of migration 0013), messages «скидка», «бандл», «страница в Steam» (`price_events.py`, folded discounts, «🛒 Открыть в Steam»), the card block «Steam», the mark «−30 %» in the List, «Цена в Steam» in the bot card; PlayStation has no prices (ADR 0009). **Stage 6.3 done** (review accepted 2026-11-05, `.scratch/6-3-game-dlc-sequels/`; details in `docs/history.md`): a weekly IGDB check (`pollers/game_follow_ups.py`, snapshots `igdb_follow_ups`, 10 a pass at the end of a pass after the prices, first check silent) of «Хочу», «В процессе», «Пройдено» games for big expansions and new games of the series on «Мои платформы»; one message per announcement with «Следить» and «Карточка» (`actions.FOLLOW_TYPES`); web card blocks «Дополнения» / «Продолжения» (`app/web/card_blocks.py`); a followed expansion is a game of its own with the line «Дополнение к игре «…»» and the word «дополнение» in the List (ADR 0011); KI-52…56 deferred. **Stage 6.4 «Входящие» done** (review accepted 2026-11-06, `.scratch/6-4-inbox/`; details in `docs/history.md`): any message to the bot is an inbox item, written at once (`app/tracker/inbox.py`, table `inbox_items`, migration 0014); a link of a source (Steam, TMDb, IMDb, Shikimori) gives its card at once, otherwise «Что это?» with the kinds and «🗑 Не сохранять»; the name candidates of a post (`candidates.py`, pure) are searched in the source of the kind (`offers.py`: half the first weight, exact then prefix, «new first», the typo of a name message), up to three offers «Это оно?» / «Возможно, вы имели в виду:» with «Да» / «Нет» (`inbox_answers.py`); «Да» adds as the web does, games too; the rest goes to the web tab «Входящие» (`app/web/inbox.py`: the number in the menu, «Найти» through Search with `inbox=<id>`, «Убрать»); every bot card carries the poster above the text (`app/bot/card_message.py`, `posters.py`); «➕ Добавить» is gone; KI-57…65 deferred.
- **Stage 7 split** (description accepted 2026-11-07, `.scratch/7-1-backups-export/description.md`): 7.1 backups and export (Settings block «Копии и выгрузка», CSV/JSON download without import, an encrypted Google Drive copy by rclone daily, 30 kept, off by default, `restore-bot.ps1`), 7.2 outside access by Tailscale and the phone (bot buttons become links to the web card, «Мои тайтлы» goes, «Тестовое событие» to the web; KI-7, 8, 12, 13; a new ADR supersedes «until the NAS» of ADR 0006/0008), 7.3 the NAS move (KI-15). Order 7.1 → 7.2 → 9 → 8 → 7.3; the NAS is not bought yet. Mockups of 7.2 are in `.scratch/7-2-access-phone/mockups/`. **Spec 7.1 accepted** (2026-11-07, `.scratch/7-1-backups-export/spec.md`, checks in `checks.md`): rclone dropped — the app sends the `.7z` archive (py7zr, AES-256, `BACKUP_PASSWORD`) to Google Drive itself through its API with the owner's own Google client «Desktop app» (`GOOGLE_DRIVE_CLIENT_ID/SECRET`, scope `drive.file`, sign-in by a button in Settings; ADR 0012); manual copies `_manual` (10 kept); restore runs in a one-off container (`app.utils.restore`); KI-66 deferred. **Slicing 7.1 accepted** (2026-11-07, `.scratch/7-1-backups-export/issues/`): 01 Settings block and manual copies (medium), 02 export (medium), 03 Google Drive connection (complex, needs the owner's Google account), 04 Google Drive copies (complex), 05 restore (complex); strict order 01 → 02 → 03 → 04 → 05. **Ticket 01 accepted** (2026-11-08): the Settings block «Копии и выгрузка» with manual copies (`_manual`, 10 kept), one lock for the hourly job and the press, the event `backup_failed` (local), `moment_in_words`; details in `docs/history.md`. **Ticket 02 accepted** (2026-11-08): the downloads `/settings/export.csv` and `/settings/export.json` (`Tracker.export_list`, `export_all`; modules `exports`, `export_all`, `export_rows`), no import; details in `docs/history.md`.
- Live check by the owner of early tickets (`release-tracker-v2`, except 02 and 25) waits for stage 9.
- The owner works in Claude Code on the PC (`E:\LocalAI\Bionic\Telegram-bot`); a session starts the bot itself for the check (`docs/workflow.md`, "Session on the owner's PC"). Main branch is `master`.
- Repository root holds junk (debug `test_psn_*.py`, `test_steam*.py`, images, `PROMPT.txt`, `opencode.json`, `shikimori_anilist_agent_prompt.md`, `egg-info`); cleaned in stage 8. `.env` has variables the code does not read (`PSN_API_KEY`, `SHIKIMORI_CLIENT_ID/SECRET`, lower-case `psn_api_key`); also stage 8.
- The bot token and the TMDb key leaked in a chat and a console; **replace all keys once, at the end, before publishing** (stage 8).
- Docs were moved onto the kickoff workflow on 2026-11-01 (`docs/history.md`); this file is the result. The code map `docs/code-map.md` is built from the module docstrings by `tools/code_map.py` (rule 11 of the coding standards): a ticket writes the docstring and runs the script.

## Stages

| # | Stage | Status | Sessions (est.) | Ideas |
|---|---|---|---|---|
| 0–4 | Urgent fixes, data model, sources for movies/series/anime, events and delivery, bot | done | — | — |
| 5 | Web app: 5.1 Docker and skeleton, 5.2 search/list/card, 5.3 feed/archive/scores, 5.4 settings/PWA | done | — | — |
| 6.1 | Games in the list and release events (IGDB) | done | — | — |
| 6.2 | Steam prices, discounts, bundles | done | — | — |
| 6.3 | Expansions and sequels of games | done | — | — |
| 6.4 | «Входящие»: add from Telegram by post or name | done | — | 001 |
| 7.1 | Backups and export: CSV/JSON, Google Drive copy, restore | tickets 2/5 (sliced, accepted 2026-11-07) | 6 | — |
| 7.2 | Access from outside the home (Tailscale), phone, bot buttons as links | not started | 6 | — |
| 9 | Fixes after real use (1–2 weeks) | not started | 2+ | — |
| 8 | GitHub template: cleanup, new repo with clean history, MIT, README, key rotation | not started | 1 | — |
| 7.3 | The move to the NAS (waits for the NAS) | not started | 3+ | — |

Rows in the order of work. Status values: not started · description · spec · tickets k/n · review · fix round k · done. Full plan: `docs/project-spec.md`.

## Environment

- Windows 11, PowerShell (Git Bash also available), Python 3.12.10 in `.venv/`, Docker 29.x. Runs in Docker on the owner's PC; later on a NAS (stage 7), access from outside the home via Tailscale or Cloudflare Tunnel (decided then).
- Tests: 3543 in total. On the owner's PC (checked 2026-11-08): 3538 pass, 2 skipped; three process-launch tests (`test_app_main`, `test_docker_files`, `test_runtime`) fail on Windows without any change — known, do not count.
- `.env` (values never printed; read by `Settings` in `app/config.py` unless noted):

| Variable | Required | Meaning |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | yes | bot token |
| `ALLOWED_TELEGRAM_USER_IDS` | yes | whitelist, comma-separated numbers; empty — the bot does not start |
| `OWNER_CHAT_ID` | no | chat for events and error reports; not a number or empty — first of the whitelist |
| `TMDB_API_KEY` | yes | TMDb key |
| `IGDB_CLIENT_ID`, `IGDB_CLIENT_SECRET` | for games | Twitch/IGDB credentials; without them games are "not connected" (Search says so; polling of added games reports «IGDB не принял ключ» once a day) |
| `SHIKIMORI_BASE_URL`, `SHIKIMORI_USER_AGENT` | no | Shikimori |
| `BOT_TIMEZONE` | no | owner's zone, e.g. `Europe/Moscow` (default `UTC` with a warning at start); in Docker it also sets `TZ` |
| `WEB_PASSWORD` | for web | login password, at least 8 characters (outer spaces ignored); without it the login page shows a hint and the bot works as usual; changing it ends all sessions; session signing key is `data/web_secret` (created itself) |
| `WEB_PORT` | no | web port on the PC (default 8080); read by `docker compose` |
| `WEB_HOST` | no | `127.0.0.1` (default) — this PC only; `0.0.0.0` — also the home network, e.g. a phone at `http://<PC address>:8080` (ADR 0008); read by `docker compose` |
| `BACKUP_PASSWORD` | for the Google Drive copy | the password of its archives, at least 12 characters (outer spaces ignored); keys set but no or a short password — Settings says the copy will not turn on, a warning at start; masked |
| `GOOGLE_DRIVE_CLIENT_ID`, `GOOGLE_DRIVE_CLIENT_SECRET` | for the Google Drive copy | the owner's own Google client «Desktop app» (`docs/backups.md`); without them the copy is off; the secret is masked |
| `PUID`, `PGID` | no | user and group of the process in the container (default 1000); on a NAS the owner of `data`; read by `app/container_start.py` |
| `TMDB_MIN_CALL_INTERVAL`, `TMDB_MAX_CALLS_PER_MINUTE`, `TMDB_429_BACKOFF_BASE_SECONDS`, `TMDB_429_MAX_RETRIES` | no | TMDb request rate (1.5 s / 30 per minute / 5 s / 3); AniList and IGDB have fixed limits in their clients; polling runs once a minute (`TRACKER_BEAT_SECONDS` in `app/bot/main.py`) |

  The `$` sign is forbidden in `.env` values: `docker compose` substitutes variables (`Qwe$rty` becomes `Qwe`), and `.\start-bot.ps1` refuses such a file.
- External services:

| Service | Status | Notes |
|---|---|---|
| TMDb | works | movies and series; no batch request, so requests go one by one, spread in time; soft limits ~40–50 req/s; back off on 429; the links sent to the bot: `/movie/<id>`, `/tv/<id>` and an IMDb id by `/find/<tt…>?external_source=imdb_id` (`movie_results` first, else `tv_results`), at once like the search |
| AniList | works | anime schedule and next episode; GraphQL `graphql.anilist.co`, no key, ~90 req/min |
| Shikimori | works | anime franchises, seasons, Russian names; GraphQL `shikimori.io`, `User-Agent` required; season links via `related { relationKind }`; a link sent to the bot — the entry by its id (`animes(ids:)`), adding takes its chain |
| IGDB | works | games (6.1): search, names, dates by platform and region, genres, covers (`images.igdb.com`); also the expansions and the series of a game (6.3: `expansions`, `standalone_expansions`, `collections`, nested fields, one request per game a week); Client-ID + Twitch Bearer token obtained at run time; search runs outside the polling queue; a Steam link sent to the bot — one request `where external_games.uid = "<n>" & external_games.external_game_source = 1` |
| Steam Store | works (unofficial) | `app/providers/steam.py`, no key: prices by `IStoreBrowseService/GetItems` (up to 100 apps per request, Russian, the store country; no currency code — the currency is how Steam writes the price; adapter `sources/steam_prices.py`), the Russian name and description at adding (`appdetails`), and the name of a Steam link IGDB does not know; link «Открыть в Steam» by the Steam id from IGDB — under the messages of Steam too (a link button, `https://store.steampowered.com/app/<id>/`) |
| PlayStation Store | not used | no prices: PlatPrices does not give a key for personal use (refusal 2026-10-30; ADR 0009 supersedes 0003); the card links to the store page by the country from Settings (KI-37) |
| Telegram Bot API (aiogram 3.31) | works | long polling |
| Google (OAuth, Drive API) | sign-in works (live 2026-11-08) | the Google Drive copy: OAuth for a desktop client with PKCE, scope `drive.file`, the owner's own client; the return address `http://localhost:<port>/settings/google-drive/callback` (the switch `google_drive.REDIRECT`; what Google accepted live — `.scratch/7-1-backups-export/checks.md`); `prompt=consent` for a refresh token every time; the app must be «In production», in «Testing» the token dies in 7 days |
| KinoPub / Kinopoisk | not used | no partner contract, no `CLIENT_ID`/`CLIENT_SECRET` |

## Gotchas

- **TMDb has one numeric id space for movies and series.** The same number can be `/movie/{id}` and `/tv/{id}`; poll both endpoints. External ids in the database are bound to `tmdb_movie` / `tmdb_tv`, not `tmdb`; one title per (source, id). A wrong-type old record is deleted with its dependent rows before the new one is created.
- **Movie dates from `release_dates`:** a nested array by region with integer types (1 premiere, 2 limited, 3 theatrical, 4 digital, 5 physical, 6 TV) and key `release_date`. Cinema date = earliest type 3 over all regions, digital = type 4; types 1 and 2 are ignored.
- **An episode is out only if `air_date` is set and not later than today.** Placeholder episodes of an announced season have future dates.
- **TMDb `/tv/{id}` has no episode list**, only season metadata with `episode_count`. Episode dates come in batches: `/tv/{id}?append_to_response=season/1,…` (up to 20 seasons per request; keys `season/N`).
- **SQLite:** timestamps are stored as naive UTC.
- **aiogram 3.x:** `Message` has no `reply_text`, only `.answer()`; `InlineKeyboardMarkup(inline_keyboard=[[btn], …])` needs a list of rows (a flat list gives `ValidationError`); `event_from_user` is available already in `dp.update` middleware; `start_polling` asks Telegram only for update types that have handlers, so inline queries no longer arrive.
- **Shikimori:** one `franchise` mixes crossovers, specials, OVA and films, so title filtering is approximate. `relationKind` (sequel, prequel, summary…) lives inside `related { relationKind relationText anime { id kind } }`, not on `Anime`. `animes(franchise:)` is no basis for a season chain (some records have an empty franchise, crossovers come in); walk by id: `animes(ids:)` with `related`, following only `prequel`/`sequel`. "Part N" is searched in the original name (the Russian name of «Магическая битва: Смертельная миграция. Часть 2» says "Часть 2", the original `Kouhen` does not; it is season 4). A running anime has `episodes: 0` (unknown), aired episodes count by `episodesAired`; `nextEpisodeAt` has an offset (`+03:00`), stored as UTC.
- **AniList, id by MAL id:** a query with several `Media(idMal: …)` under different names answers 404 as a whole if one MAL id is unknown; use `Page { media(idMal_in: […]) }` — unknown ids are just absent. Several records by id: `Page { media(id_in: […]) }`.
- **AniList schedule:** `Media` gives `status` (`RELEASING`, `FINISHED`, `NOT_YET_RELEASED`), `episodes` (null while running) and `nextAiringEpisode { episode airingAt }` (unix UTC). Episode numbers are per record, from 1, as in Shikimori. AniList and Shikimori can disagree (24 Oct 2026, One Piece: Shikimori expects episode 1181 on 25 Oct, AniList on 3 Jan 2027); the schedule trusts AniList, and keeps the saved one if AniList is silent.
- **Moments of aired anime episodes are unknown** (our AniList query does not return them). A date, once recorded (from Shikimori or the moment of the check), never changes; an episode found later than it aired gets the moment of finding — so "episode out" can be late by up to the polling interval (≤ 1 h when an episode is near).
- **Undeclared names:** `NameError` in rarely run branches is found by `pyflakes` (`.venv\Scripts\python.exe -m pyflakes app tests`).
- **GitHub Desktop can look at a copy of the project on drive C**, while the bot lives in `E:\LocalAI\Bionic\Telegram-bot` (`.env`, `data`, `.venv`). If files on E are old after a pull, choose the repository on E (File → Add local repository).
- **Scripts outside the project that read `.env` must not log without `MaskingFormatter`** — otherwise the token reaches the screen.
- **`data/google_drive_token.json`** is the connection of the Google Drive copy (refresh token, secret: never print or copy it); `data/google_drive_state.json` the state of its sending. Both outside the database on purpose (a restore does not bring an old connection back); a spoiled one counts as absent; «Отключить Google Drive» removes both.
- **`data/startup_failure.json`** records the last startup failure (fingerprint, since when, when the report went; no error text). While it exists the same failure is reported to Telegram at most once a day; a successful start deletes it; deleting it by hand just makes the next failure report at once.
- **`docker compose` substitutes variables into `.env` values and reads `.env` for its own substitutions:** `$` spoils values, `${` without `}` breaks every `docker compose` command, even `.\stop-bot.ps1`. `format: raw` does not help (keeps quotes and trailing comments, and still reads substitutions for `docker-compose.yml`). So `.\start-bot.ps1` refuses such an `.env`.
