# Project context

Current state only; budget 20,000 bytes, `wc -c` (`docs/workflow.md`, "Documents"). Details of finished work live in `docs/history.md`. Updated: 2026-11-01.

## Next step

Session «Тикет 6.2.02»: ticket 02 of part 6.2 (Steam prices, discounts and bundles) — the Steam `GetItems` client, the adapter and the pure prices module. Start from `.scratch/games-2-steam-prices/issues/02-steam-client-and-prices.md`. Model: Opus 5.5, effort high (`docs/models.md`: complex ticket). After it: 03 (complex) → 04 (complex) → 05 (medium), then «Ревью 6.2».

## State

- Telegram bot, polling and web run as **one process** in Docker on the owner's PC (ADR 0006, 0007). Web: `http://localhost:8080` with password login; the bot is the delivery channel (ADR 0002). Commands — `CLAUDE.md`, "Run".
- Core in `app/tracker/` (entry only through the facade `core.py`), SQLite in WAL mode `data/tracker.db`, migrations up to 0012 (0013 comes with 6.2 ticket 03). Movies, series, anime and games are tracked: add, list, card, seasons and parts, scores, archive, sequels, polling with events, deduplication, delivery rules (summary at 15:00, work days, quiet hours), failure reports, copies of the database.
- Web is finished (stage 5, parts 5.1–5.4): Feed, List, Archive, Search, card, Settings, PWA manifest. The temporary bot buttons «➕ Добавить» and «📚 Мои тайтлы» stay until stage 6.4 / 7.
- Games: part 6.1 done (IGDB, platforms, release events, «Пройдено»). **Part 6.2 in progress**: description, spec and slicing accepted (5 tickets in `.scratch/games-2-steam-prices/issues/`), ticket 01 accepted (`GameScope`, KI-39 and KI-40 fixed, sequel snapshot by source, `search_games` removed). Tickets 02–05 open. PlayStation has no prices (ADR 0009).
- Live check by the owner of early tickets (`release-tracker-v2`, except 02 and 25) waits for stage 9.
- The owner works in Claude Code on the PC (`E:\LocalAI\Bionic\Telegram-bot`); a session starts the bot itself for the check (`docs/workflow.md`, "Session on the owner's PC"). Main branch is `master`.
- Repository root holds junk (debug `test_psn_*.py`, `test_steam*.py`, images, `PROMPT.txt`, `opencode.json`, `shikimori_anilist_agent_prompt.md`, `egg-info`); cleaned in stage 8. `.env` has variables the code does not read (`PSN_API_KEY`, `SHIKIMORI_CLIENT_ID/SECRET`, lower-case `psn_api_key`); also stage 8.
- The bot token and the TMDb key leaked in a chat and a console; **replace all keys once, at the end, before publishing** (stage 8).
- Docs were moved onto the kickoff workflow on 2026-11-01 (`docs/history.md`); this file is the result.

## Stages

| # | Stage | Status | Sessions (est.) | Ideas |
|---|---|---|---|---|
| 0–4 | Urgent fixes, data model, sources for movies/series/anime, events and delivery, bot | done | — | — |
| 5 | Web app: 5.1 Docker and skeleton, 5.2 search/list/card, 5.3 feed/archive/scores, 5.4 settings/PWA | done | — | — |
| 6.1 | Games in the list and release events (IGDB) | done | — | — |
| 6.2 | Steam prices, discounts, bundles | tickets 1/5 | 4 tickets + 1 review left | — |
| 6.3 | DLC and sequels of games | not started | not estimated | — |
| 6.4 | «Входящие»: add from Telegram by post or name | not started | 7–9 | 001 |
| 7 | Backups, NAS move, access from outside the home, install on phone | not started | 1+ | — |
| 8 | GitHub template: cleanup, new repo with clean history, MIT, README, key rotation | not started | 1 | — |
| 9 | Fixes after real use (1–2 weeks) | not started | 2+ | — |

Status values: not started · description · spec · tickets k/n · review · fix round k · done. Full plan: `docs/project-spec.md`.

## Environment

- Windows 11, PowerShell (Git Bash also available), Python 3.12.10 in `.venv/`, Docker 29.x. Runs in Docker on the owner's PC; later on a NAS (stage 7), access from outside the home via Tailscale or Cloudflare Tunnel (decided then).
- Tests: 2449 in total. On the owner's PC (checked 2026-11-01): 2444 pass, 2 skipped; three process-launch tests (`test_app_main`, `test_docker_files`, `test_runtime`) fail on Windows without any change — known, do not count.
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
| `PUID`, `PGID` | no | user and group of the process in the container (default 1000); on a NAS the owner of `data`; read by `app/container_start.py` |
| `TMDB_MIN_CALL_INTERVAL`, `TMDB_MAX_CALLS_PER_MINUTE`, `TMDB_429_BACKOFF_BASE_SECONDS`, `TMDB_429_MAX_RETRIES` | no | TMDb request rate (1.5 s / 30 per minute / 5 s / 3); AniList and IGDB have fixed limits in their clients; polling runs once a minute (`TRACKER_BEAT_SECONDS` in `app/bot/main.py`) |

  The `$` sign is forbidden in `.env` values: `docker compose` substitutes variables (`Qwe$rty` becomes `Qwe`), and `.\start-bot.ps1` refuses such a file.
- External services:

| Service | Status | Notes |
|---|---|---|
| TMDb | works | movies and series; no batch request, so requests go one by one, spread in time; soft limits ~40–50 req/s; back off on 429 |
| AniList | works | anime schedule and next episode; GraphQL `graphql.anilist.co`, no key, ~90 req/min |
| Shikimori | works | anime franchises, seasons, Russian names; GraphQL `shikimori.io`, `User-Agent` required; season links via `related { relationKind }` |
| IGDB | works | games (6.1): search, names, dates by platform and region, genres, covers (`images.igdb.com`); Client-ID + Twitch Bearer token obtained at run time; search runs outside the polling queue |
| Steam Store | works (unofficial) | `app/providers/steam.py`: Russian name and description at adding (`appdetails`); link «Открыть в Steam» by the Steam id from IGDB; prices — part 6.2 (`IStoreBrowseService/GetItems`) |
| PlayStation Store | not used | no prices: PlatPrices does not give a key for personal use (refusal 2026-10-30; ADR 0009 supersedes 0003); the card links to the store page by the country from Settings (KI-37) |
| Telegram Bot API (aiogram 3.31) | works | long polling |
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
- **`data/startup_failure.json`** records the last startup failure (fingerprint, since when, when the report went; no error text). While it exists the same failure is reported to Telegram at most once a day; a successful start deletes it; deleting it by hand just makes the next failure report at once.
- **`docker compose` substitutes variables into `.env` values and reads `.env` for its own substitutions:** `$` spoils values, `${` without `}` breaks every `docker compose` command, even `.\stop-bot.ps1`. `format: raw` does not help (keeps quotes and trailing comments, and still reads substitutions for `docker-compose.yml`). So `.\start-bot.ps1` refuses such an `.env`.
