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
- [TODO] Phase 3 — TMDb search + posters + RU/EN titles
- [TODO] Phase 4 — Add/remove/list + notes
- [TODO] Phase 5 — Notification rules + scheduler + event engine
- [TODO] Phase 6 — Movie Digital release tracking
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

## 6. CURRENT STATE

Current phase: Phase 3 — TMDb search + posters + RU/EN titles (next)

Last successful step: Phase 2 complete — `alembic upgrade head` ran cleanly; `data/bot.db` contains all 12 tables.

Currently doing: Nothing in progress. Next action is to begin Phase 3 (TMDb search provider).

Waiting for user: Confirm whether to proceed directly to Phase 3 or make a Git commit for Phase 2 first.

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

## 8. THINGS WE TRIED AND REJECTED

(пока пусто — Phase 0 только что завершён)

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

(ещё нет тестов — Phase 15+)

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

Phase 3 (TMDb search + posters + RU/EN titles):
1. Create `app/providers/__init__.py` and `app/providers/tmdb.py` — TMDbProvider with async httpx client.
2. Implement `/search <query>` command handler in bot: call TMDbProvider.search(), return results with poster, RU/EN title, year, type.
3. Normalize search results into a domain model (MediaItemSearchResult) with id, media_type, canonical_title_en, title_ru, year, description, poster_url.
4. Verify: run bot, send `/search Dune`, confirm results appear with posters and titles.

## 16. LAST CHECKPOINT

Last checkpoint: 2025-09-13 (Phase 2 complete)

Current phase: Phase 2 → Phase 3 transition
Last completed action: `alembic upgrade head` ran cleanly; all 12 tables created in data/bot.db
Next exact action: Begin Phase 3 — TMDb search provider (search by RU/EN titles, posters, alternative titles)
