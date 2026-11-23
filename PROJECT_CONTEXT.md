# Project context

Current state only; budget 20,000 bytes, `wc -c` (`docs/workflow.md`, "Documents"). Details of finished work live in `docs/history.md`. Updated: 2026-11-23.

## Next step

Session «Тикет 9.1d.03»: candidates — the middle name, «from» and `: N`, the companies of IGDB (KI-58, 60, 59), `.scratch/9-1d-inbox-copies-code/issues/03-*.md`. Medium ticket: model Sonnet 5.5, effort high (`docs/models.md`). Then tickets 04 (complex), 05 and the review of 9.1d, then 7.3, 9.2, 8.

## State

- Telegram bot, polling and web run as **one process** in Docker on the owner's PC (ADR 0006, 0007). Web: `http://localhost:8080` with password login; the bot is the delivery channel (ADR 0002). Commands — `CLAUDE.md`, "Run".
- Core in `app/tracker/` (entry only through the facade `core.py`), SQLite in WAL mode `data/tracker.db`, migrations up to 0018. Movies, series, anime and games are tracked: add, list, card, seasons and parts, scores, archive, sequels, polling with events, deduplication, delivery rules (summary at 15:00, work days, quiet hours), failure reports, copies of the database.
- Web is finished (stage 5, parts 5.1–5.4): Feed, List, Archive, Search, card, Settings, PWA manifest. The bot menu is «📚 Мои тайтлы», «📋 Сводка сейчас», «🧪 Тестовое событие»; «➕ Добавить» is gone (6.4.01): any other message is an inbox item.
- Games: 6.1 (IGDB, platforms, release events, «Пройдено»), 6.2 (Steam prices, `pollers/game_prices.py`, `price_events.py`; no PlayStation prices, ADR 0009), 6.3 (weekly expansions and sequels, `pollers/game_follow_ups.py`, ADR 0011) done. **Stage 6.4 «Входящие» done**: any message to the bot is an inbox item (`app/tracker/inbox.py`), a source link gives its card, else «Что это?» and up to three offers «Это оно?»; the rest in the web tab «Входящие». Details of all four in `docs/history.md`.
- **Stage 7 split** (2026-11-07, `.scratch/7-1-backups-export/description.md`; changed 2026-11-15 by `.scratch/7-2-access-phone/description.md` and ADR 0013): 7.1 backups and export, 7.2 the app address, the phone, bot links, a safer login, 7.3 NAS readiness and the move guide. Outside access (the owner's domain, Cloudflare Tunnel, Cloudflare Access) and the NAS move itself are the owner's separate NAS project for two apps; Tailscale dropped. Order (changed 2026-11-17): 7.1 → 7.2 → 9.1 every open known issue (9.1a–d, `.scratch/9-1-known-issues/description.md`) → 7.3 NAS → 9.2 real use → 8. **Stage 9.1a done** (2026-11-20, ADR 0015; details in `docs/history.md`): 17 known issues fixed; KI-78 (9.2) the rest. **Stage 9.1c done** (2026-11-23; migration 0017; KI-48, 72 won't fix). **9.1d spec accepted and sliced** (2026-11-23, `.scratch/9-1d-inbox-copies-code/`: five tickets in `issues/`, migrations 0018 and 0019; `docs/history.md`); **tickets 01, 02 done** (01 the code split, every module of `app/tracker/` within 400 lines, `core.py` 470; 02 the approximate anime premiere, migration 0018); 03 (candidates) in review. **Stage 9.1b done** (2026-11-22, ADR 0016): 12 fixed, KI-43, 46 won't fix; Russian in games (idea 002); KI-79, 80 open (9.2). **Stages 7.1 and 7.2 done** (2026-11-15, 11-17; ADR 0012, 0014; `docs/history.md`).
- Live check by the owner of early tickets (`release-tracker-v2`, except 02 and 25) waits for stage 9.2 (on the NAS).
- The owner works in Claude Code on the PC (`E:\LocalAI\Bionic\Telegram-bot`); a session starts the bot itself for the check (`docs/workflow.md`, "Session on the owner's PC"). Main branch is `master`.
- Repository root holds junk (debug `test_psn_*.py`, `test_steam*.py`, images, `PROMPT.txt`, `opencode.json`, `shikimori_anilist_agent_prompt.md`, `egg-info`); cleaned in stage 8. `.env` has six names the code does not read: KI-49, ticket 9.1d.05.
- The bot token and the TMDb key leaked in a chat and a console; **replace all keys once, at the end, before publishing** (stage 8).
- The code map `docs/code-map.md` is built from the module docstrings by `tools/code_map.py` (rule 11).

## Stages

| # | Stage | Status | Sessions (est.) | Ideas |
|---|---|---|---|---|
| 0–4 | Urgent fixes, data model, sources for movies/series/anime, events and delivery, bot | done | — | — |
| 5 | Web app: 5.1 Docker and skeleton, 5.2 search/list/card, 5.3 feed/archive/scores, 5.4 settings/PWA | done | — | — |
| 6.1 | Games in the list and release events (IGDB) | done | — | — |
| 6.2 | Steam prices, discounts, bundles | done | — | — |
| 6.3 | Expansions and sequels of games | done | — | — |
| 6.4 | «Входящие»: add from Telegram by post or name | done | — | 001 |
| 7.1 | Backups and export: CSV/JSON, Google Drive copy, restore | done | — | — |
| 7.2 | The app address, phone, bot buttons as links, a safer login | done | — | — |
| 9.1a | Known issues: start, stop, polling and delivery (17) | done | — | — |
| 9.1b | Known issues: games and Steam prices (14); Russian in games (idea 002) | done | — | 002 |
| 9.1c | Known issues: Лента, web and login (12, with KI-77) | done | — | — |
| 9.1d | Known issues: «Входящие», copies and code health (18, with KI-81, 83, 84 of 9.1c) | tickets 2/5 | 8 | — |
| 7.3 | NAS readiness and the move guide (the move — the NAS project) | not started | 3 | — |
| 9.2 | Fixes after real use on the NAS (1–2 weeks) | not started | 2+ | — |
| 8 | GitHub template: cleanup, new repo with clean history, MIT, README, key rotation | not started | 1 | — |

Rows in the order of work. Status values: not started · description · spec · tickets k/n · review · fix round k · done. Full plan: `docs/project-spec.md`.

## Environment

- Windows 11, PowerShell (Git Bash also available), Python 3.12.10 in `.venv/`, Docker 29.x. Runs in Docker on the owner's PC; later on a UGREEN DXP2800 NAS, moved and opened from outside (own domain, Cloudflare Tunnel and Access) by the owner's separate NAS project (ADR 0013).
- Tests: about 4900 in total. On the owner's PC (checked 2026-11-22): 4933 pass, 3 skipped; two process-launch tests (`test_app_main`, `test_runtime`) fail on Windows without any change (`test_runtime`'s not on every run) — known, do not count.
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
| `APP_URL` | no | the address of the app for the phone and Telegram (`http://<PC address>:8080` or `https://<name with a dot>`, a Cyrillic name too; no `localhost`, no path); valid — the bot is in link mode (its «Карточка» buttons open the app), empty or malformed — chat mode, with a warning and a line in Settings (`parse_app_url` in `app/config.py`) |
| `TRUSTED_PROXIES` | no | addresses and networks (`172.18.0.0/16`), comma-separated, whose `X-Forwarded-For` and `X-Forwarded-Proto` are believed (the public client address of a login, `Secure` under `https`); empty — the proxy headers are ignored; an item that is no address or network, `*` included, is skipped with a warning (`parse_trusted_proxies` in `app/web/proxy.py`) |
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
| Shikimori | works | anime franchises, seasons, Russian names; GraphQL `shikimori.io`, `User-Agent` required; season links via `related { relationKind }`; a link sent to the bot — the entry by its id (`animes(ids:)`), adding takes its chain; `airedOn.day` null — only the month known, `month` null too — the year (`date`: the period's 1st day) |
| IGDB | works | games (6.1): search, names, dates by platform and region, genres, covers (`images.igdb.com`); also the expansions and the series of a game (6.3: `expansions`, `standalone_expansions`, `collections`, nested fields, one request per game a week); the languages with the own query (`language_supports`, Russian is language 22); Client-ID + Twitch Bearer token obtained at run time; search runs outside the polling queue; a Steam link sent to the bot — one request `where external_games.uid = "<n>" & external_games.external_game_source = 1`; the companies among a post's candidates — one `/companies` request |
| Steam Store | works (unofficial) | `app/providers/steam.py`, no key: prices by `IStoreBrowseService/GetItems` (up to 100 apps per request, Russian, the store country; no currency code — the currency is how Steam writes the price; adapter `sources/steam_prices.py`), the languages (`include_supported_languages`, always in `US`, Russian `elanguage` 8, every 6 h), the Russian name and description at adding (`appdetails`), and the name of a Steam link IGDB does not know; link «Открыть в Steam» by the Steam id from IGDB — under the messages of Steam too (a link button, `https://store.steampowered.com/app/<id>/`) |
| PlayStation Store | links only | no prices: PlatPrices does not give a key for personal use (refusal 2026-10-30; ADR 0009 supersedes 0003); the card links to the store page by the country from Settings; at a click on the web link one `HEAD` of `/<locale>/concept/<n>` (`200` the page, a redirect to `/error` the search; kept a day; `app/tracker/playstation.py`, KI-37) |
| ZoG (zoneofgames.ru) | works (no API, pages read) | fan Russian of games (ADR 0016): `app/providers/zog.py`, `GET /games/<page>/` only, `windows-1251`, «Ошибка» is a 200 page; a page found by the original name (≤ 4 addresses, name and year match), weekly, 2 games a pass, 1 s apart; a failure — 6 h, log only; `robots.txt` allows game pages |
| Telegram Bot API (aiogram 3.31) | works | long polling |
| Google (OAuth, Drive API) | sign-in and copies work (live 2026-11-08) | the Google Drive copy: OAuth for a desktop client with PKCE, scope `drive.file`, the owner's own client; the return address `http://localhost:<port>/settings/google-drive/callback`; Drive errors carry `errors[0].reason` (`storageQuotaExceeded`, `rateLimitExceeded`); the `upload_id` of a resumable upload is masked in the log (the switch `google_drive.REDIRECT`; what Google accepted live — `.scratch/7-1-backups-export/checks.md`); `prompt=consent` for a refresh token every time; the app must be «In production», in «Testing» the token dies in 7 days |
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
- **Moments of aired anime episodes are known for 8 days, for the entries AniList knows:** the schedule request has a second root `recent` (airings `mediaId episode airingAt` of the last 8 days from the core's clock, the latest 50 per pack of 50 ids; `PartSchedule.aired`, spec 1.5 of 9.1c), and the episode takes that moment (`exact`). An older episode, an entry AniList does not know, or one past the 50 airings gets the moment of the check (`unknown`). A date, once recorded, never changes.
- **«Ubisoft» is no company name in IGDB:** the companies request asks each candidate alone and with each `COMPANY_WORDS` word, joined by `|` (an array after `~` is a 400).
- **Undeclared names:** `NameError` in rarely run branches is found by `pyflakes` (`.venv\Scripts\python.exe -m pyflakes app tests`).
- **GitHub Desktop can look at a copy of the project on drive C**, while the bot lives in `E:\LocalAI\Bionic\Telegram-bot` (`.env`, `data`, `.venv`). If files on E are old after a pull, choose the repository on E (File → Add local repository).
- **Scripts outside the project that read `.env` must not log without `MaskingFormatter`** — otherwise the token reaches the screen.
- **Telegram refuses `localhost` in links:** one refused button («Bad Request: wrong HTTP URL») stops the whole message, so `APP_URL` cannot be `http://localhost:8080`; it is the PC's address in the network, `127.0.0.1` (this PC only) or a name with a dot (`parse_app_url`). The mode of the bot (`AppLinks` or `None`) is fixed at start.
- **`data/google_drive_token.json`** is the connection of the Google Drive copy (refresh token, secret: never print or copy it); `data/google_drive_state.json` the state of its sending. Both outside the database on purpose (a restore does not bring an old connection back); a spoiled one counts as absent; «Отключить Google Drive» removes both.
- **`issued_ids` keeps the last number of a title** (migration 0015, `Titles._next_number`): a new title takes the bigger of it and `max(titles.id)`, plus one, so a deleted title's number never comes back. A restore of an old copy brings its own value (`docs/backups.md`).
- **`data/web_login.json`** holds the web sign-ins, the last login and the lock count (ADR 0014); deleting it signs every device out and zeroes the count; a hand-written sign-in in it works only with a cookie signed by `data/web_secret`. Never share it (it names devices).
- **The health check ends a hung app** (ADR 0015): the fourth `/health` timeout in a row (connected, no answer in 5 s; refused or 503 is none) kills the app, the child of Docker's init (`init: true`), and the container restarts. The count: `/tmp/release-tracker-health.json` in the container.
- **`data/startup_failure.json`** records the last startup failure (code, fingerprint, since when, when the report went; no error text). The same failure is reported at most once a day, the same place with another text at most once an hour, another place at once. When `data` cannot be written the record lives in the temp folder (`/tmp/release-tracker-startup_failure.json` in the container); both files are read, the later wins. A successful start deletes both; deleting by hand just makes the next failure report at once.
- **`docker compose` substitutes variables into `.env` values and reads `.env` for its own substitutions:** `$` spoils values, `${` without `}` breaks every `docker compose` command, even `.\stop-bot.ps1`. `format: raw` does not help (keeps quotes and trailing comments, and still reads substitutions for `docker-compose.yml`). So `.\start-bot.ps1` refuses such an `.env`.
- **«Не удалось проверить» once a day per title and source** (KI-45): the window is read from the `source_failure` events (`payload.source`), no column; the dedup key is `failure:<title>:<source>:<pass>`. A poll queues an event only while `checks.still_checked` holds in its write session (KI-22).
