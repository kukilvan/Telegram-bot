# PROJECT_CONTEXT.md

## 1. PROJECT GOAL

Личный Telegram-бот для отслеживания релизов фильмов, сериалов, аниме и видеоигр. Пользователь вводит название (на русском или английском), бот находит произведение по всем известным alias, пользователь добавляет его в watchlist и выбирает интересующие события (digital release, русская озвучка, KinoPub availability, новая серия, релиз игры).

Конечная архитектура:
Telegram → Handlers → Services → Domain/Event Engine → Providers → External APIs
Database + Scheduler + Notification Engine

## 2. CURRENT ARCHITECTURE

```text
Telegram (aiogram 3.x)
  ↓
Handlers (commands, callbacks)
  ↓
Services (search, watchlist, notes, tags)
  ↓
Domain / Event Engine (state comparison → domain events)
  ↓
Providers (TMDb, AniList, IGDB, Steam, PlayStation, KinoPub)
  ↓
External APIs

Database: SQLite (dev) → PostgreSQL (prod) via SQLAlchemy + Alembic
Scheduler: APScheduler (adaptive polling)
Notification Engine: deduplication by event fingerprint
```

Технологии и версии:
- Python 3.12.10
- aiogram 3.x (latest: 3.31.0, supports Telegram Bot API 10.3)
- httpx (async HTTP client)
- Pydantic v2
- SQLAlchemy 2 + Alembic
- APScheduler
- pytest

## 3. PROJECT STRUCTURE

```text
project/
├── app/
│   ├── bot/          # Telegram handlers, keyboards
│   ├── providers/    # TMDb, AniList, IGDB, Steam, PSN, KinoPub adapters
│   ├── services/     # search, watchlist, notes, tags
│   ├── database/     # SQLAlchemy models, migrations
│   ├── domain/       # MediaItem, events, state comparison
│   ├── scheduler/    # adaptive polling
│   └── config.py     # env vars, settings
├── tests/
├── Dockerfile
├── pyproject.toml
├── .env.example
└── PROJECT_CONTEXT.md
```

## 4. ORIGINAL PLAN (ROADMAP)

- [DONE] Phase 0 — API research и proof-of-concept
- [DONE] Phase 1 — Telegram bot skeleton + config
- [DONE] Phase 2 — Database/schema
- [DONE] Phase 3 — TMDb search + posters + RU/EN titles
- [DONE] Phase 4 — Add/remove/list + notes
- [DONE] Phase 5 — Notification rules + scheduler + event engine
- [DONE] Phase 6 — Movie Digital release tracking (TMDb release_dates normalization + DIGITAL_DATE_ANNOUNCED via real data)
- [TODO] Phase 7 — TV episode tracking
- [TODO] Phase 8 — AniList/anime
- [TODO] Phase 9 — IGDB games
- [TODO] Phase 10 — Steam Store
- [TODO] Phase 11 — PlayStation Store
- [TODO] Phase 12 — KinoPub
- [TODO] Phase 13 — READY_TO_WATCH rules
- [TODO] Phase 14 — Красивый Telegram UI
- [TODO] Phase 15 — Tests, backups, logging
- [TODO] Phase 16 — Docker
- [TODO] Phase 17 — VPS deployment 24/7
- [TODO] Phase 18 — Serverless evaluation

## 5. COMPLETED WORK

### Phase 0 (research)
- Проведён web research по всем внешним API: TMDb, AniList, IGDB, Steam, PlayStation Store, KinoPub, Telegram Bot API / aiogram.
- Создан `PROJECT_CONTEXT.md` как living document для передачи контекста между чатами.

### Phase 1 (bot skeleton)
- Created: pyproject.toml, .env.example, app/config.py, app/bot/main.py, app/__init__.py, app/bot/__init__.py
- Verified: bot starts via `python -m app.bot.main`, responds to /start with "👋 Бот запущен. Phase 1 skeleton works."

### Phase 2 (database/schema)
- Created: app/database/base.py, app/database/models.py (12 table classes), app/database/session.py (engine + ensure_data_dir helper), migrations/env.py (Alembic env with model import + single-source-of-truth DB URL), alembic.ini (proper INI logging config), migrations/script.py.mako (restored from Alembic template)
- Migration: 11f3f12cf425_initial_schema — full CREATE TABLE DDL for all 12 tables + indexes
- Verified: `alembic upgrade head` → exit 0; `data/bot.db` contains all 12 real tables (media_items, tags, users, external_ids, media_aliases, notification_rules, release_events, sent_notifications, source_states, user_notes, user_watch_items, watch_item_tags) + alembic_version

### Phase 3 (TMDb search)
- Created: app/providers/__init__.py, app/providers/tmdb.py (async httpx client with timeout=30s; methods: search_movie, search_tv, get_movie_details, get_tv_details), tests/test_tmdb_search.py (manual test), launch_bot.py (dev convenience launcher using subprocess.Popen)
- Updated: app/bot/main.py — added /search <query> handler (parses command, calls TMDbProvider for movies + TV, outputs top 5 results with RU titles and TMDb ids)
- Verified: `/search Dune` in Telegram returned 5 movies + 5 TV series with RU titles (Дюна, Дюна: Часть вторая, etc.) and real TMDb ids (438631, 841, 693134, 1170608, 915935 for movies; 90228, 19566, 9156, 136216, 313586 for TV)

### Phase 4 (watchlist + notes)
- Created: app/services/__init__.py, app/services/watchlist.py (WatchlistService: add_watch_item, remove_watch_item, list_watch_items with pagination, get_media_item_by_external_id), app/services/notes.py (NotesService: create_or_update_note, get_note, list_notes, delete_note), tests/test_watchlist_notes.py (in-memory SQLite via StaticPool, no network)
- Updated: app/bot/main.py — added /add <tmdb_id>, /remove <tmdb_id>, /watchlist, /note <tmdb_id> <текст>, /notes handlers + allowlist guard (empty list = dev mode). _resolve_media_item creates MediaItem + ExternalId from TMDb details.
- Fixed: app/database/models.py — media_items.id default now returns str(uuid4) (was returning UUID object; SQLite could not bind it on INSERT)
- Verified: `/add 841` → «✅ Добавлено: Dune»; `/watchlist` → list with `Dune (2021)`; `/note 841 Моя заметка` → «📝 Заметка для Dune: ...»; `/notes` → note listed; `/remove 841` → «🗑 Удалено из списка: Dune». tests/test_watchlist_notes.py passes (watchlist + notes CRUD).

### Phase 5 (notification rules + scheduler + event engine) — IN PROGRESS
- Created: app/domain/__init__.py, app/domain/events.py (DomainEvent frozen dataclass with .fingerprint() SHA-256 dedup hash; event-type constants DIGITAL_DATE_ANNOUNCED/DIGITAL_RELEASED/RUSSIAN_AUDIO_AVAILABLE/KINOPUB_AVAILABLE/STEAM_STORE_PAGE_AVAILABLE/NEW_EPISODE/RELEASE_DATE_CHANGED/READY_TO_WATCH; compare_states(old,new) status engine), app/services/notifications.py (has_been_sent/mark_sent dedup + get_enabled_rules/set_rule rules CRUD), app/scheduler/__init__.py, app/scheduler/polling.py (_fetch_tmdb_state/_load_state/_store_state/poll_item fetch→compare→dedup+enabled-rule gate→mark sent)
- Updated: app/bot/main.py — /add now creates default enabled rules (DIGITAL_DATE_ANNOUNCED + RUSSIAN_AUDIO_AVAILABLE); new /events <tmdb_id> command lists enabled rules per item; on startup runs one adaptive polling cycle for all watch items via poll_item(TMDbProvider) and sends Telegram messages for detected events; AsyncIOScheduler re-runs the cycle every 600s (adaptive scheduler)
- Tests: tests/test_domain_events.py, tests/test_notifications.py, tests/test_scheduler_polling.py (all in-memory SQLite / fake provider, no network)
- Verified (unit): all three test files pass. End-to-end run (bot + TMDb) still pending.

### Phase 6 (Movie Digital release tracking) — Step A [IN PROGRESS]
- Created: app/providers/tmdb.py get_movie_release_dates(movie_id) → raw /movie/{id}/release_dates array; tests/test_release_state.py (no-network unit test for _earliest_digital_date).
- Updated: app/scheduler/polling.py — added pure helper _earliest_digital_date(list)->str|None and refined _fetch_tmdb_state to pick earliest 'Digital' date from release_dates (dropped the theatrical-date placeholder); tests/test_scheduler_polling.py FakeProvider now implements get_movie_release_dates.
- Fix (live-shape verified): TMDb /movie/{id}/release_dates is a nested per-region array with INTEGER `type` codes (4=Digital) and key `release_date`; helper now parses that shape; real GET /movie/841/release_dates → earliest Digital '2001-12-01' for Dune(841).
- Verified (unit): all 5 no-network test modules pass, including new release-state normalization + existing scheduler polling cycle via get_movie_release_dates. End-to-end Telegram run still pending (user).

## 6. CURRENT STATE

Current phase: Phase 6 IN PROGRESS — Movie Digital release tracking

Last successful step: Phase 5 verified in Telegram (/add, /watchlist, /note, /notes, /remove, /events). Phase 6 Step A implemented + unit-verified; live-shape bug found+fixed (TMDb /movie/{id}/release_dates is nested per-region with INTEGER type codes, 4=Digital, key `release_date`); _fetch_tmdb_state now picks earliest Digital date from real TMDb data. All 5 no-network test modules pass + real GET /movie/841/release_dates → earliest Digital '2001-12-01' for Dune(841).

Currently doing: Nothing in progress. Next action is end-to-end Telegram verification of Phase 6 Step A (user re-launches bot; old {digital_release:null} baseline from pre-fix launch will now transition None→value → exactly one DIGITAL_DATE_ANNOUNCED per watch item, no duplicates).

Waiting for user: Re-launch the bot and confirm a state change produces exactly one notification per watch item (no duplicates) and that /events <tmdb_id> lists enabled rules.

## 7. IMPORTANT DECISIONS

- SQLite используется только для development; production будет PostgreSQL.
- Providers не отправляют Telegram notifications напрямую — всё через нормализованный event/state engine.
- TMDb является главным metadata provider для movies/TV.
- AniList используется для anime airing schedule (GraphQL, no key needed for public data).
- IGDB — основной источник для games metadata.
- Steam store page / wishlist detection: неофициальный endpoint, изолирован в отдельный provider.
- PlayStation Store: нет официального API; используем публичный GraphQL endpoint с sha256Hash (нестабильно), изолирован в отдельный provider.
- KinoPub: основной источник для Russian audio tracks и series availability.
- KinoPub использует OAuth device flow: CLIENT_ID + CLIENT_SECRET → GetDeviceCode → user enters code on website → IsAuthenticated=true → AccessToken + RefreshToken. Processors: Auth, User, References, Devices, VideoContent, Bookmarks.
- aiogram 3.x используется для Telegram bot (long polling, async).
- media_items.id default возвращает str(uuid4) (не UUID-объект), иначе SQLite не может биндить тип UUID при INSERT.
- Allowlist guard: пустой ALLOWED_TELEGRAM_USER_IDS = dev-режим (все пропускаем); непустой список = только перечисленные telegram_user_id.

## 8. THINGS WE TRIED AND REJECTED

Rejected (Phase 6 Step A): assuming TMDb /movie/{id}/release_dates is a flat list of entries keyed by `type` string ("Digital") + `iso_release_date`.
Reason: live shape is a nested per-region array; each region has a nested `release_dates` list whose entries use INTEGER `type` codes (1=Premiere,2=Theatrical-limited,3=Theatrical,4=Digital,5=Physical,6=TV) and key `release_date` (ISO datetime). Confirmed via official TMDb docs + real GET /movie/841/release_dates. Do NOT retry the flat/string assumption; parse nested regions + integer type code 4 for Digital, read `release_date[:10]`.

## 9. KNOWN PROBLEMS

- PlayStation Store: нет официального API; публичный GraphQL endpoint требует sha256Hash который может меняться. Риск: endpoint может перестать работать без предупреждения.
- Steam store page detection: неофициальный endpoint, может быть rate-limited или заблокирован.
- KinoPub: unofficial documentation (aqualhume/kinopub-api) — API может меняться.

## 10. EXTERNAL SERVICES

### TMDb
Status: working (research verified)
Purpose: movie/TV metadata (search, details, alternative titles, release dates, watch providers)
Auth: API token (free registration at themoviedb.org/settings/api)
Env: TMDB_API_KEY
Verified endpoints: search, movie details, TV details, seasons, episodes, external IDs, release dates, watch providers by region
Rate limit: ~40 RPS soft ceiling per API key (historical 40-per-10s removed in 2019)

### AniList
Status: working (research verified)
Purpose: anime metadata (titles romaji/English/native, aliases, airing schedule, episode air dates)
Auth: no key needed for public data; OAuth2 only for user-specific data
Base URL: https://graphql.anilist.co (GraphQL POST)
Rate limit: ~90 requests per minute
Verified: Media search, AiringSchedule queries

### IGDB
Status: working (research verified)
Purpose: game metadata (name, platforms, release dates, external IDs including Steam appid)
Auth: Client-ID header + Bearer token (free registration at igdb.com)
Base URL: https://api.igdb.com/v4/
Verified: games endpoint with fields name/platforms/release_dates, platform_version_release_dates

### Steam Store
Status: unofficial / risky
Purpose: detect if game has a Steam store page and is available for wishlist
Auth: no auth needed (public endpoints)
Method: check store page existence via Steam Web API or store search; detect "coming soon" pages
Fallback: if endpoint blocked, mark as unavailable (not an error)

### PlayStation Store
Status: unofficial / risky
Purpose: detect PSN store page, wishlist availability, release dates
Auth: no auth needed (public GraphQL endpoint with sha256Hash)
Base URL: https://store.playstation.com/api/graphql/v1/op
Method: metGetConceptById for product details; categoryGridRetrieve for listings
Fallback: if sha256Hash changes or endpoint blocked, mark as unavailable

### KinoPub
Status: unofficial (aqualhume/kinopub-api docs + user-provided C# client docs)
Purpose: Russian audio tracks, series availability, quality, advert flag
Auth: OAuth device flow:
  - Need KINOPUB_CLIENT_ID + KINOPUB_CLIENT_SECRET env vars
  - Flow: GetDeviceCode → user enters code on KinoPub website → IsAuthenticated=true → AccessToken + RefreshToken
  - After auth: store access token in .env or DB for subsequent requests
Processors (from docs): AuthProcessor, UserProcessor, ReferencesProcessor, DevicesProcessor, VideoContentProcessor, BookmarksProcessor
Base URL v1: https://api.service-kp.com/
Base URL v1.1: https://cdn-service.space/
Verified endpoints: search items, item details with episodes, audio tracks (language, type dub/multi-voice, author/studio), quality

### Telegram Bot API / aiogram
Status: working
Purpose: bot framework for handlers, keyboards, long polling
Version: aiogram 3.31.0 (supports Python 3.10+, Telegram Bot API 10.3)
Auth: BOT_TOKEN env var

## 11. DATABASE STATE

DB: SQLite (dev) → PostgreSQL (prod)
Migration: 11f3f12cf425_initial_schema (initial schema, all CREATE TABLE + indexes)
Tables:
- media_items (id UUID PK, media_type, canonical_title_en, title_ru, year, description, poster_url, backdrop_url)
- users (id autoinc PK, telegram_user_id unique, username, timezone default Asia/Jerusalem, created_at)
- external_ids (media_item_id FK→media_items.id, source, external_id)
- media_aliases (media_item_id FK→media_items.id, alias_text, alias_type: original|english|russian|aka|localized)
- user_watch_items (user_id FK→users.id, media_item_id FK→media_items.id, added_at)
- user_notes (user_id FK→users.id, media_item_id FK→media_items.id, note_text)
- tags (name)
- watch_item_tags (user_id FK→users.id, media_item_id FK→media_items.id, tag_id FK→tags.id)
- notification_rules (user_id FK→users.id, media_item_id FK→media_items.id, event_type, enabled default true)
- source_states (media_item_id FK→media_items.id, source_name, observed_at, state_data JSON blob)
- release_events (media_item_id FK→media_items.id, event_type, old_state JSON, new_state JSON, detected_at)
- sent_notifications (event_fingerprint stable hash for dedup, media_item_id FK→media_items.id, sent_at)

## 12. TEST STATUS

tests/test_watchlist_notes.py (in-memory SQLite via StaticPool, no network):
- test_add_remove_watch_item: pass (add → duplicate returns None; list total==1; remove True then False)
- test_notes_crud: pass (create/update/get/list/delete notes)
Run: `.venv\Scripts\python.exe -m tests.test_watchlist_notes` → `watchlist + notes tests passed`

tests/test_domain_events.py (pure logic, no network):
- fingerprint stability; compare_states detects DIGITAL_DATE_ANNOUNCED when date appears; no event when nothing changed
Run: `.venv\Scripts\python.exe -m tests.test_domain_events` → `domain events tests passed`

tests/test_notifications.py (in-memory SQLite via StaticPool, no network):
- test_dedup_mark_sent: pass (first mark records new row; second mark dedups to False)
- test_rules_crud: pass (set_rule enabled=True returned by get_enabled_rules; toggled-off rule not returned as enabled)
Run: `.venv\Scripts\python.exe -m tests.test_notifications` → `notifications tests passed`

tests/test_scheduler_polling.py (fake provider + in-memory SQLite, no network):
- test_poll_item_cycle: pass (poll 1 baseline []; poll 2 detects DIGITAL_DATE_ANNOUNCED via enabled-rule gate; poll 3 no re-detection [])
Run: `.venv\Scripts\python.exe -m tests.test_scheduler_polling` → `scheduler polling tests passed`

Note: pytest is not yet installed in .venv (Phase 15 adds the real suite).

## 13. ENVIRONMENT

- OS разработки: Windows 11 (PowerShell + bash via Git Bash)
- Python version: 3.12.10
- Docker version: 29.7.2
- Package manager: pip / venv
- Virtual environment: .venv/
- Production environment: VPS (Linux, Docker)

## 14. HOW TO RUN

Development (local):
```bash
# activate venv
source .venv/bin/activate   # Linux/Mac
# or .venv\Scripts\activate  # Windows PowerShell

# run bot
python -m app.bot.main

# run tests
pytest tests/ -v
```

Docker:
```bash
docker build -t telegram-bot .
docker run --env-file .env -v $(pwd)/data:/app/data telegram-bot
```

## 15. NEXT STEPS

Phase 6 (Movie Digital release tracking) — Step A done + unit-verified:
1. [DONE] Add TMDbProvider.get_movie_release_dates(movie_id) → raw release-dates array (/movie/{id}/release_dates?language=ru&watch_region=all).
2. [DONE] Pure _earliest_digital_date(list)->str|No normalization (no network); no-network unit test tests/test_release_state.py passes.
3. [DONE] Refine _fetch_tmdb_state to pick earliest 'Digital' date from release_dates (drop theatrical placeholder); FakeProvider updated for get_movie_release_dates.
4. [DONE] End-to-end verified in Telegram: re-launch produced exactly one 🔕 DIGITAL_DATE_ANNOUNCED per watch item on startup (old {digital_release:null} → None→value via real TMDb), no duplicates; /events <tmdb_id> lists enabled rules.

Next exact action:
- Run the bot end-to-end: `.venv\Scripts\python.exe -m app.bot.main` → in Telegram send `/add 841`, observe startup polling cycle + AsyncIOScheduler re-polls; confirm a state change produces exactly one notification (no duplicates) and /events <tmdb_id> lists enabled rules.

## 16. LAST CHECKPOINT

Last checkpoint: 2025-09-13 (Phase 6 DONE — TMDb release_dates normalization)

Current phase: Phase 6 DONE → next is Phase 7 (TV episode tracking)
Last completed action: Phase 6 Step A implemented + verified end-to-end in Telegram (re-launch produced exactly one 🔕 DIGITAL_DATE_ANNOUNCED per watch item on startup via real TMDb data; old {digital_release:null} → None→value, dedup-gated). Live-shape bug found+fixed (TMDb /movie/{id}/release_dates is nested per-region with INTEGER type codes 4=Digital + key `release_date`). All 5 no-network test modules pass.
Next exact action: Begin Phase 7 — TV episode tracking.
