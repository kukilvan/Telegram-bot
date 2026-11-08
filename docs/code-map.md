# Code map

What lives where. The list of the modules of `app/` at the bottom is built from their docstrings (the first sentence of each) by `tools/code_map.py`; nobody edits it by hand. When you add, rename or change what a module holds, write its docstring, then run `.venv\Scripts\python.exe tools\code_map.py`; `tests/test_code_map.py` fails when the list is out of date or a module has no docstring. Where to put new code — `docs/coding-standards.md`, rule 7. What each test module checks — `docs/tests-map.md` (read on need). Until 2026-11-01 this file was a hand-written table with a long row per file: `git show 142bc26:docs/code-map.md`.

## Architecture

```text
One process app.main (app/runtime.py: start, stop, self-check, watchdog; ADR 0007):
Telegram (aiogram 3.x) -> app/bot (thin handlers) --\
                                                      >-> app/tracker (core: events, delivery) -> sources -> app/providers -> external APIs
Browser -> app/web (FastAPI on uvicorn; app.py assembles; --/
           password login, /health; menu.py, pages.py, posters.py, one router per page)
Database: SQLite in WAL mode (SQLAlchemy 2 + Alembic), file data/tracker.db, schema only through Alembic (app/tracker/migrations/, alembic_tracker.ini)
Scheduler: APScheduler · events deduplicated by key
```

Stack: Python 3.12, aiogram >= 3.31, FastAPI on uvicorn (upper-bounded, ADR 0007) + HTMX (ADR 0004), httpx, Pydantic v2 + pydantic-settings, SQLAlchemy 2, Alembic, APScheduler, pytest (+asyncio). Models (titles, external ids, seasons, episodes, season parts, franchise movies, source snapshots, events, delivery queue, settings) — `app/tracker/models.py`. The old database `bot.db` and its copies lie in `data/archive/`; the bot does not read them. All tests run offline on fake sources and SQLite in memory.

## Not Python (written by hand)

- `app/web/templates/` — Jinja pages and fragments. One page per module of `app/web/` (`feed.html` with `feed_body.html`, `card.html` with `card_body.html`, `title_list.html`, `archive.html` and their `*_results.html`, `search.html` with `suggestions.html`, `inbox.html` with `inbox_removed.html` (the answer to «Убрать»), `settings.html`, `login.html`), `base.html` (status line, notice), `menu.html` (the menu with the number of «Входящие»; also sent out of band), `macros.html` (shared pieces: `filter_row`, `poster`, `title_main`, `search_box`, `score_select`), `message.html`, `failed.html`, `title_gone.html`. Templates compare no kind or status: Python decides.
- `app/web/static/` — `style.css` (light and dark theme, one column under 40rem, touch targets of 44 px), `htmx.min.js` (HTMX 2.0.4 from the npm package `htmx.org@2.0.4`, file `dist/htmx.min.js` unchanged; update the same way and fix this line), `manifest.webmanifest` and `icons/` (installation on PC and iPhone; the PNGs were made once from `icon.svg` with headless Edge; the folder is open without a login).
- `app/tracker/migrations/versions/` — Alembic revisions `NNNN_*.py` of the tracker database; the list below shows the newest number.
- Root: `Dockerfile`, `docker-compose.yml` (the web port on `127.0.0.1` unless `WEB_HOST` says otherwise), `start-bot.ps1`, `stop-bot.ps1`, `logs-bot.ps1`, `requirements.txt`, `pyproject.toml`, `.env.example`, `tools/code_map.py` (builds the list below).
- `data/` (not in git) — `tracker.db`, `backups/`, `logs/bot.log`, `web_secret`, `startup_failure.json`, `google_drive_token.json` (the refresh token of the Google Drive copy; secret) and `google_drive_state.json` (its sending, ticket 04).
- `docs/backups.md` — the owner's guide to the copies: what is copied where, turning the Google Drive copy on and off.

## Modules of `app/` (built)

<!-- code-map:start (built by tools/code_map.py from the docstrings; do not edit by hand) -->
- `app/bot/access.py` — Owner allowlist: one gate in front of every incoming Telegram update.
- `app/bot/card_message.py` — The one function that sends a card to the chat: the text and the buttons with the poster above the text.
- `app/bot/error_handler.py` — Error reporting to bot owner via Telegram Bot API.
- `app/bot/inbox_handlers.py` — Bot side of «Входящие»: taking in every other message of the owner, the pause after it, «Что это?», the offer cards and their buttons.
- `app/bot/inbox_message.py` — Reading a Telegram message of the owner into an `IncomingMessage` (spec 1.1 of stage 6.4), pure: no bot, no database.
- `app/bot/main.py` — The bot's assembly: the access gate and the tracker handlers (`build_dispatcher`), the scheduler's jobs (`add_jobs`).
- `app/bot/tracker_handlers.py` — Bot side of the tracker core: the menu, the buttons under messages and cards, and the Telegram sender.
- `app/config.py` — Application configuration loaded from environment variables.
- `app/container_start.py` — Start of the container (`python -m app.container_start`, KI-4).
- `app/healthcheck.py` — The health check for Docker (`python -m app.healthcheck`, KI-3): asks the application's own `/health`.
- `app/main.py` — Process entry point, `python -m app.main`: the bot, the scheduler and the web in one process (ADR 0007).
- `app/providers/anilist.py` — AniList provider: anime metadata + airing schedule via GraphQL.
- `app/providers/google_drive.py` — Google client of the Google Drive copy: the address of the sign-in page and the requests of the OAuth sign-in of a desktop client.
- `app/providers/igdb.py` — IGDB client: queries to `/games` in the Apicalypse language of IGDB, with the token of Twitch and the pace of IGDB.
- `app/providers/shikimori.py` — Shikimori API client: anime search, franchise grouping, season selection.
- `app/providers/steam.py` — Steam client: the prices of games from `IStoreBrowseService/GetItems` and the Russian name and description from `appdetails`.
- `app/providers/tmdb.py` — TMDb provider: search + details via async httpx, with Phase 7.5 adaptive throttling.
- `app/runtime.py` — One process: the web server, the scheduler and the bot run in one event loop (ADR 0007).
- `app/startup_report.py` — Whether a failure before the start is reported to the owner, and the record of it in `data/startup_failure.json`.
- `app/tracker/actions.py` — Buttons under a message or a card: the core decides which ones, the bot turns them into Telegram buttons.
- `app/tracker/anime_events.py` — Anime events: the episodes the two sources agree on, and the films of a franchise.
- `app/tracker/backup_events.py` — The event «copy not made» (pure): the reasons, the message, the once-a-day key and the sample of «Тестовое событие».
- `app/tracker/backup_rows.py` — What the owner reads about the copies (pure): the lines of the Settings block and the notice after «Сделать копию сейчас».
- `app/tracker/backups.py` — The copies of the database for the owner: the Settings block, «Сделать копию сейчас» and the report of a failed daily copy.
- `app/tracker/candidates.py` — Name candidates of an inbox item and the links of sources it carries (spec 3 and 4 of stage 6.4), pure: no database, no network, no clock.
- `app/tracker/cards.py` — Text card of a title: what the owner reads in the bot.
- `app/tracker/context.py` — What every part of the core shares: the session factory, the clock, the sender, the default time zone, the locks.
- `app/tracker/core.py` — Tracker core facade: the only door the bot (and later the web app) uses.
- `app/tracker/db.py` — Tracker database: engine (WAL), session factory and Alembic migrations.
- `app/tracker/dedup.py` — Pieces of dedup keys that several kinds of events share.
- `app/tracker/delivery.py` — Delivery rules: when a queued event may reach the owner, and how a summary reads.
- `app/tracker/delivery_service.py` — Delivery: sending what the queue holds to the owner, one message or one summary, and noting every attempt.
- `app/tracker/drive_rows.py` — What the owner reads about the Google Drive copy (pure): its line in Settings, the button under it and the notices of the sign-in and the sign-out.
- `app/tracker/errors.py` — Errors the tracker core raises to its callers (the bot, later the web app).
- `app/tracker/export_all.py` — The JSON document of the export «Скачать всё (JSON)»: every table the owner's data lives in, read from one session.
- `app/tracker/export_rows.py` — The files of the export as bytes (pure): the CSV list with its cell guard and the JSON values, the owner's dates, the file names.
- `app/tracker/exports.py` — The export of the owner's data, download only: the CSV list and the JSON of everything (spec 3 of stage 7.1).
- `app/tracker/failures.py` — Source failure notices: why a title could not be checked, and how the message to the owner reads.
- `app/tracker/feed.py` — The feed (`Tracker.feed()`): one read of the database for «Скоро», «Позже» and «Недавно».
- `app/tracker/feed_rows.py` — The rows of the feed (`Tracker.feed()`): what comes out in the next days, what comes later, and what happened in the last week.
- `app/tracker/follow_ups.py` — The follow-up check of a game (pure): its stored state, which expansions and games of its series are shown, their dates, what is new and the events.
- `app/tracker/game_events.py` — Game events: what changed between two snapshots of a game on the platforms the owner is told about, and how the message reads.
- `app/tracker/game_rows.py` — What the owner reads of a game: the lines of its platforms on the card, the links to the stores, the pieces of the feed.
- `app/tracker/game_scope.py` — What the owner sees of the games: the country of the stores, «Мои платформы» and the marks «играю здесь».
- `app/tracker/games.py` — The dates of a game: what a date of IGDB is, which record is ours, backward compatibility and a lost date.
- `app/tracker/genres.py` — Genres as the owner picks them: the same genre written in two cases or with «е» for «ё» is one genre.
- `app/tracker/google_drive.py` — The connection of the Google Drive copy: whether it is on, the sign-in to Google and the sign-out, and the files of the connection in `data/`.
- `app/tracker/inbox.py` — «Входящие»: taking in what the owner sends to the bot, the states of an item and its moves, the 12 hours, the list, the count and deleting.
- `app/tracker/inbox_answers.py` — The answers to an inbox item: the end of its pause, the analysis by its links or by the kind the owner chose, the offer cards, «Да» and «Нет» (spec 1.3, 2.3, 6 and 7 of stage 6.4).
- `app/tracker/kinds.py` — What each kind of title is for the owner: one table, so a new kind cannot be added half-way.
- `app/tracker/listing.py` — What the owner reads of the list: its rows, the numbers of the whole list and the card of a title.
- `app/tracker/migrations/env.py` — Alembic environment of the tracker database.
- `app/tracker/migrations/versions/0001_events_and_delivery_queue.py` — Events and delivery queue.
- `app/tracker/migrations/versions/0002_titles_external_ids_snapshots.py` — Titles, external ids and source snapshots.
- `app/tracker/migrations/versions/0003_snapshot_next_check.py` — Time of the next check on every source snapshot.
- `app/tracker/migrations/versions/0004_seasons_and_episodes.py` — Seasons of a series and their episodes.
- `app/tracker/migrations/versions/0005_settings.py` — Owner's settings (the threshold between parts of a season for now).
- `app/tracker/migrations/versions/0006_anime_parts_and_movies.py` — Parts of anime seasons (each with its own source ids) and movies of anime franchises.
- `app/tracker/migrations/versions/0007_failure_notified_at.py` — When the owner was last told that a title could not be checked (one notice per title in 24 hours).
- `app/tracker/migrations/versions/0008_events_foreign_keys.py` — Foreign keys with cascade: `events.title_id` → `titles.id`, `delivery_queue.event_id` → `events.id`.
- `app/tracker/migrations/versions/0009_code_speaks_glossary.py` — Names from the glossary: `titles.title` → `titles.name`, `titles.original_title` → `titles.original_name`, the setting `digest_at` → `summary_at`.
- `app/tracker/migrations/versions/0010_restored_at.py` — When the owner last brought a title back from the archive («Вернуть в список»): the first check of its own source after that moment records what it finds as the baseline, without events.
- `app/tracker/migrations/versions/0011_scores.py` — The owner's scores: of a title (a film's only one; a series' own one over the average of its seasons) and of a season.
- `app/tracker/migrations/versions/0012_game_platforms.py` — The platforms of a game and the owner's mark «играю здесь» on each (spec 6.2 of part 6.1).
- `app/tracker/migrations/versions/0013_price_history.py` — The price history of the games (spec 4.5 of part 6.2): a record of a Steam price each time a price check saw it change.
- `app/tracker/migrations/versions/0014_inbox.py` — «Входящие» (spec 10 of stage 6.4): the table `inbox_items`, one row per inbox item — what the owner sent to the bot.
- `app/tracker/models.py` — Tables of the tracker database: titles, seasons, episodes, source snapshots, events, the delivery queue, settings, game platforms, the price history and the inbox items.
- `app/tracker/moment_words.py` — A moment in words for the owner (pure): «сегодня в 07:58», «вчера в 18:32», «4 ноября в 07:58», «4 ноября 2025 в 07:58».
- `app/tracker/movie_events.py` — Movie events: what changed between two snapshots, how the message reads, how soon to look again.
- `app/tracker/offers.py` — Offers of an inbox item: the records the sources give for its links and its name candidates, in the order the owner sees them, and the text of an offer card (spec 3, 5 and 6.1 of stage 6.4).
- `app/tracker/platforms.py` — The platforms of the tracker and the countries of the stores: where a game comes out and whose region its dates are.
- `app/tracker/pollers/anime.py` — An anime franchise: two sources are put together (Shikimori for the seasons, AniList for the schedule), and the source entries behind the seasons and the franchise films are kept beside them.
- `app/tracker/pollers/base.py` — What every kind of title does when it is added and when it is polled: one object per kind, one set of actions.
- `app/tracker/pollers/game.py` — A game: the dates of its platforms are compared for the country of the stores, and the owner is told only about the platforms of «Мои платформы» marked «играю здесь».
- `app/tracker/pollers/game_follow_ups.py` — The weekly check of games for expansions and sequels at the end of a polling pass: which games, the reconciliation, the due games, the queueing, the store, the failures.
- `app/tracker/pollers/game_prices.py` — The price check at the end of a polling pass: which games have their Steam prices checked, the requests in packs of 100, the reference point, the price history and the failures (spec 4 of part 6.2).
- `app/tracker/pollers/game_steam.py` — What the owner reads of the Steam prices of games: the block of a card and the marks of the rows of the list.
- `app/tracker/pollers/movie.py` — A movie: its own release dates are compared, and its snapshot says when to look again; the feed and the card show the same two dates.
- `app/tracker/pollers/seasonal.py` — What a series and an anime share: their seasons decide when to look again, what the feed shows and what the card lists.
- `app/tracker/pollers/sequels.py` — An archived movie: its own release is no longer followed, only the collection it belongs to, for sequels.
- `app/tracker/pollers/series.py` — A series: the fresh seasons are compared with the stored ones, and the owner's season marks keep the status.
- `app/tracker/polling.py` — Polling: the pass over the titles whose check time has come, and the one table that says which poller serves a kind.
- `app/tracker/posters.py` — Poster addresses (pure): the address of a picture from the value a title stores, and the sizes of the places a poster is shown (the web page and the bot card).
- `app/tracker/price_events.py` — The events of Steam (pure): a discount and a bundle from two price looks, the page in Steam, texts, keys, folding.
- `app/tracker/price_rows.py` — What the owner reads of the Steam prices of a game: the block of the card, the line of the bot and the mark of the list.
- `app/tracker/prices.py` — Steam prices of a game: what one price check saw (`PriceLook`), an amount of money (`Money`) and «самая низкая с добавления».
- `app/tracker/progress.py` — The status a series takes by itself from the owner's season marks and the state of the show.
- `app/tracker/queue.py` — Putting events into the delivery queue: the events the polls find, the test events, the «could not check» messages.
- `app/tracker/results.py` — What the tracker core hands back to its callers.
- `app/tracker/scores.py` — The owner's score: ten points with «+» and «−».
- `app/tracker/seasons.py` — Seasons of a series: what the source says about them and how far each one has got.
- `app/tracker/sequel_events.py` — Sequel announcements for an archived movie: what is new in its collection, how the message reads.
- `app/tracker/series_events.py` — Series events: what changed between two looks at a series, how the message reads, how soon to look again.
- `app/tracker/settings_store.py` — The owner's settings in the `settings` table: the break that splits a season into parts, the delivery rules, the time zone, the platforms of the games and the country of the stores.
- `app/tracker/sources/anilist_schedule.py` — AniList adapter for anime: the airing schedule of one source entry (a season, or a part of it).
- `app/tracker/sources/dates.py` — Reading a date from text: two readers, and which one to use depends on who wrote the text.
- `app/tracker/sources/igdb_follow_ups.py` — IGDB adapter of the follow-up check: one request a game for its expansions and the games of its series, parsed into a `FollowUpsSnapshot`.
- `app/tracker/sources/igdb_games.py` — IGDB adapter for games: search suggestions and the game snapshot, with the Russian texts of Steam when a game is added.
- `app/tracker/sources/shikimori_anime.py` — Shikimori adapter for anime: search suggestions and the franchise built from the chain of sequels.
- `app/tracker/sources/steam_prices.py` — Steam adapter for prices: what Steam answered about each game becomes its price look (`PriceLook`), source `steam`.
- `app/tracker/sources/tmdb_find.py` — TMDb adapter for the IMDb links of «Входящие»: `/find` by an IMDb id gives the movie or the series it names.
- `app/tracker/sources/tmdb_movies.py` — TMDb adapter for movies: search suggestions and the movie snapshot.
- `app/tracker/sources/tmdb_sequels.py` — TMDb adapter for sequels of an archived movie: the franchise collection the movie belongs to.
- `app/tracker/sources/tmdb_series.py` — TMDb adapter for series: search suggestions and the series snapshot with its seasons.
- `app/tracker/statuses.py` — The owner's marks on a title (watched, started, dropped, restored, seasons, platforms, scores) and the status that follows from them.
- `app/tracker/storage.py` — What the parts of the core read and write together in one session: a title's seasons and episodes, its stored snapshots, and its status that follows from them.
- `app/tracker/test_samples.py` — «Тестовое событие»: samples of the messages the owner can ask for, and the check of the delivery rules.
- `app/tracker/text.py` — How the owner's text is compared: one function for the order «по названию», the search by name and the merging of genres.
- `app/tracker/titles.py` — The owner's list: searching, adding and deleting titles and «Следить».
- `app/tracker/zones.py` — The time zones the owner can choose from, and how each one reads in the list.
- `app/utils/backup.py` — Backups of the tracker database: the daily copy when the last one is over a day old, the manual copy, the reading of the folder as a list of copies, and the rotation of the old ones.
- `app/utils/logging_config.py` — Logging of the application: the console and the rotated file `data/logs/bot.log`, both with secrets masked.
- `app/utils/secrets_mask.py` — Mask secrets (API keys, tokens) in any text that is about to be logged or sent anywhere.
- `app/web/app.py` — The FastAPI app, assembled: the login and the guard in front of every address, the security headers, the pages behind them.
- `app/web/archive.py` — The archive: the titles with a final status («Просмотрено», «Пройдено», «Бросил») with a search by name, a filter by kind, by genre and by status, and an order (links, so «Назад» and bookmarks work).
- `app/web/auth.py` — The web login without the web framework: the password rules, the signing key, the lock after wrong tries.
- `app/web/card.py` — The card of a title: its details, the marks of seasons and platforms, «Следить» at a row of a follow list, the buttons.
- `app/web/card_blocks.py` — The blocks of the web card that depend on the kind: the platforms, the line of an expansion and the follow lists.
- `app/web/drive_sign_in.py` — The sign-in and the sign-out of the Google Drive copy from Settings: «Подключить Google Drive», Google's return and «Отключить Google Drive».
- `app/web/feed.py` — The feed, the main page after the sign-in: «Скоро» (the next two weeks, by days), «Позже» (the nearest date of the titles with nothing in those days) and «Недавно» (the events of the last week).
- `app/web/filters.py` — What the list and the archive share about their filters: a value read from the address, the row of links for the kind, the sentence of an empty page and the answer under the search field.
- `app/web/inbox.py` — The tab «Входящие»: the items the bot could not resolve, newest first, with «Найти» and «Убрать».
- `app/web/menu.py` — The menu of the app and the one list of the addresses that need no sign-in.
- `app/web/pages.py` — What every page shares: the page, a fragment, the answer to a press, the notice for the next page, «the title is gone» and the net under an unexpected error.
- `app/web/posters.py` — Posters for the browser: the sites the page may load pictures from (`img-src`).
- `app/web/search.py` — The search: the page with the switch of the kind, the suggestions as the owner types (a fragment for HTMX, or the whole page without it), and adding a suggestion to the list, which leads to its card.
- `app/web/server.py` — uvicorn for the runtime (`app/runtime.py`): no signal handling and no logging setup of its own.
- `app/web/settings.py` — The settings page: one form for the time zone, the working days, the hour of the summary, the quiet hours, the break between parts of a season, the platforms and the country of the stores.
- `app/web/status_line.py` — The line at the top of every page: how many titles are in the list and when the sources were last checked; under it, while the bot is not connected to Telegram, the sentence that says so.
- `app/web/title_list.py` — The list: the rows with a search by name, filters by kind and status and an order (links, so «Назад» and bookmarks work), and a mode of choosing that deletes several titles at once.
- `app/web/title_rows.py` — What the list and the archive share: a row of titles, a link of a row of filters and the search query.
<!-- code-map:end -->
