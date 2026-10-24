# PROJECT_CONTEXT.md

## ⚠️ GOLDEN RULE: NO COMMITS WITHOUT VERIFICATION ⚠️

**НИКОГДА НЕ ДЕЛАЙ GIT COMMIT БЕЗ ПРОВЕРКИ!**

Правило: ВСЕГДА сначала проверь исправление вручную (через Docker или напрямую), убедись что:
1. Баг исправлен
2. Все тесты проходят (`pytest tests/ -v`)
3. Ничего не сломалось
4. Бот запускается и работает

ТОЛЬКО после того как пользователь написал "можно комитить" или "ok" — делай commit.

**Нарушение этого правила запрещено.** Сначала проверка → потом подтверждение пользователя → потом commit.

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
- [DONE] Phase 7 — TV series episodes
- [DONE] Phase 7.5 — Optimization of TMDb API calls (rate limit, adaptive intervals, request staggering)
- [DONE] Phase 8 — AniList/anime
- [DONE] Phase 9 — IGDB games
- [DONE] Phase 10 — Steam Store
- [DONE] Phase 11 — PlayStation Store
- [ABANDONED] Phase 12 — Kinopoisk (API keys not provided)
- [ABANDONED] Phase 13 — READY_TO_WATCH rules (not relevant for use case)
- [DONE] Phase 14 — Красивый Telegram UI
- [DONE] Phase 15 — Tests, backups, logging
- [TODO] Phase 16 — Docker
- [TODO] Phase 17 — VPS deployment 24/7
- [TODO] Phase 18 — Serverless evaluation
- [DONE] Phase 19 — Bot response optimization (parallel requests + search cache)
- [FAILED] Phase 20 — Fuzzy search for typos: tried generating typo candidates (deletions, swaps, suffixes), but results were consistently irrelevant. API fuzzy matching doesn't align with user intent. Need different approach.
- [DONE] Phase 21 — Inline autocomplete search (@botname query returns results)
- [DONE] Phase 22 - Unified Game Entity (platform-agnostic media items with multi-platform tracking)
- [TODO] Phase 23 - Unified search by type + redesigned watchlist with details
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

### Phase 7.5 (TMDb API optimization) — DONE
- Created: app/scheduler/tiering.py (pure tier function: state → DAILY/WEEKLY interval; jitter + 429 backoff constants; due sort key)
- Updated: app/scheduler/polling.py — full-every-600s cycle replaced by poll_due_items() (due-item scan, tier-based deadlines, staggered calls)
- Updated: app/providers/tmdb.py — _throttle() enforces min_call_interval + rolling per-minute cap; _get() implements HTTP 429 exponential backoff; call_count/hit_429 observability
- Updated: app/config.py — added Phase 7.5 settings (tmdb_min_call_interval, tmdb_max_calls_per_minute, tmdb_429_backoff_base_seconds, tmdb_429_max_retries, poll_scan_interval_seconds)
- Updated: app/bot/main.py — _poll_due_items() replaces old startup poll; scheduler uses poll_scan_interval_seconds interval
- Updated: .env.example — added Phase 7.5 tuning variables
- Migration: a7c3e91f2d48 — adds next_check_at column to source_states
- Tests: tests/test_tiering.py (6 tests: movie/game known→weekly, no-info→daily, TV fully-aired→weekly, airing→daily, stub-announced→daily, due_sort_key)
- Verified: all 8 no-network test modules pass (watchlist_notes, domain_events, notifications, scheduler_polling, pre_add_check, media_resolve, tiering); py_compile OK; migration applied (alembic upgrade head → a7c3e91f2d48)

### Phase 8 (AniList/anime) — DONE
- Created: app/providers/anilist.py — AniList GraphQL client with throttling (same pacing as TMDbProvider), search_anime, get_anime_details, get_next_episode
- Updated: app/domain/events.py — added NEXT_EPISODE_AIRING event type + compare_anilist_states function (handles episode progression + status RELEASING→FINISHED → ALL_EPISODES_OUT)
- Updated: app/scheduler/polling.py — _fetch_anilist_state + _normalize_anilist_details; poll_item now accepts both tmdb_provider and anilist_provider (anime items polled from both sources)
- Updated: app/bot/main.py — AniList search results in /search; /add accepts AniList IDs (fallback when TMDb returns nothing); _ensure_anilist_item; _default_rules_for returns (NEXT_EPISODE_AIRING, ALL_EPISODES_OUT) for anime; _poll_due_items passes anilist provider
- Updated: app/scheduler/tiering.py — docstring reflects Phase 8
- Created: tests/test_anilist.py (5 tests: state normalization, episode airing detection, no-change, finished status, first poll)
- Updated: tests/test_scheduler_polling.py — all poll_item calls updated for new signature (anilist_provider=None)
- Verified: all 9 no-network test modules pass; py_compile OK

### Phase 7.5 (TMDb API optimization) — DONE
- Created/changed: app/providers/tmdb.py `get_tv_seasons(tv_id)` (GET /tv/{id}, season metadata only) + `get_tv_season_episodes(tv_id, n)` (GET /tv/{id}/season/{n} → episode air dates); app/scheduler/polling.py `_tv_state_from_seasons(seasons)` pure normalizer (latest_season, total_episodes_current_season, episodes_aired_current_season) + TV/anime branch in `_fetch_tmdb_state` (two calls per poll: seasons metadata + latest-season episodes); app/domain/events.py NEW_SEASON_ANNOUNCED and ALL_EPISODES_OUT events with per-season payload {"season": N}, fingerprint now includes payload → per-season re-detection possible, identical payloads still dedup; app/bot/main.py — /add creates default rules by media type (tv → NEW_SEASON_ANNOUNCED + ALL_EPISODES_OUT, otherwise DIGITAL_DATE_ANNOUNCED + RUSSIAN_AUDIO_AVAILABLE), notification text renders season for TV events («📺 … → title, сезон N»); tests/test_scheduler_polling.py — SequenceTVProvider fake mirroring the real two-call TMDb flow + 4 new TV tests.
- Bugs found+fixed this step (from previous agent's partial work): (1) polling called provider.get_tv_sections() but TMDbProvider only had get_tv_seasons → potential AttributeError on live TV polling; unified to get_tv_seasons (+ helper renamed _tv_state_from_seasons, log typo); (2) test asserted state key "total_episodes_current_session" instead of "...season" → failing unit test.
- Important live discovery: TMDb show-level endpoint (/tv/{id}) does NOT return the episodes array even with with_seasons/append_to_response — only season metadata with episode_count. Episode air dates come only from /tv/{id}/season/{n}. Provider reflects this (two calls per poll for TV items).
- Verified (unit): all 5 no-network test modules pass. Verified (live, real TMDb): _fetch_tmdb_state for The Last of Us (100088) → {'latest_season': 2, 'total_episodes_current_season': 7, 'episodes_aired_current_season': 7}. Verified (E2E Telegram by user): /search Silo → /add <tv_id> → «✅ Добавлено: Укрытие», no premature notification (silent baseline add on first poll — as designed). Committed as 5587645.

### NEW FEATURE: "already-released confirm-on-add" — implemented + unit-verified + E2E user-verified [TV aired-date fix pending final re-verification → then commit]
- app/domain/events.py: `PreAddCheck` frozen dataclass + pure classifier `pre_add_check(state, media_type, today)` with codes released / upcoming / season_complete / airing / no_data; new event SEASON_PROGRESSED = per-episode progression within the same TV/anime season (suppressed when NEW_SEASON_ANNOUNCED fires simultaneously — no double notification).
- app/bot/main.py: /add now pre-checks the current TMDb state BEFORE storing a baseline. Movie with past digital release date, or TV/anime whose latest season is fully aired → status line + inline buttons [✅ В список / ❌ Не нужно]. Airing season or no data yet → normal add plus one-line status info («Идёт сезон N, X/Y серий вышли»; announced-but-not-started season → «Сезон N анонсирован, серий ещё не вышло»). Duplicate /add for an already-tracked item → state summary + [🔄 Продолжить / ⏹ Остановить]. On "yes" the fetched state is stored immediately as baseline — old release dates and aired seasons do NOT retroactively fire notifications (fixes root cause of 🔕 DIGITAL_DATE_ANNOUNCED spam for long-released movies).
- Fixed during user E2E attempts: two consecutive aiogram markup bugs at both /add confirmation keyboards — parameter name `inline_keys=` instead of documented `inline_keyboard=`, and flat button list vs required `list[list[InlineKeyboardButton]]` (every button its own row). Both sites fixed to `[ [btn], [btn] ]`; in-venv probe reproduced the user's exact 28-error ValidationError for the flat form.
- TV episode-count fix (user-reported false «все серии вышли»): an episode counts as aired ONLY if air_date is non-null AND <= today; future scheduled/placeholder dates never count (`_tv_state_from_seasons(seasons, today)`). Root cause verified live: Silo(125988) S4 = single placeholder ep dated 2027-07-08 → was reported «Все серии сезона 4 уже вышли (1/1)»; Fonari(95350) S1 = 5 past + 3 future eps → was reported «8/8». After fix both classify as airing → normal /add with status line.
- tests/test_pre_add_check.py: announced-stub and mid-season TV cases pinned; test_scheduler_polling.py updated (today param + future-placeholder case); all 6 no-network modules pass.
- E2E verified by user in Telegram (chat log): /add 841 → «Дата цифрового релиза уже известна... — уже вышел» + buttons [✅/❌]; ✅ press → added, NO retroactive DIGITAL_DATE_ANNOUNCED; duplicate /add 841 → «📌 Уже в списке отслеживания: Дюна (1984)» + [🔄/⏹].
- Bug A fix — TMDb shares ONE numeric id space across movies and TV: the same number can be both /movie/{id} and /tv/{id}. Old movie-first resolution silently picked the wrong type for colliding ids (user logs prove it: 60625 → «Eye Contact» instead of Рик и Морти, 76479 → «Deceived» instead of Пацаны/The Boys, 287527 → «Witches Blood» instead of Заветы, 250307 → «Arcade Fire Live...» instead of Больница Питт; Silo/Fonari "worked" only because no movie exists at those ids — NOT hardcoded). New resolution in app/bot/main.py: _lookup_tmdb_details probes BOTH endpoints per /add; exactly one MediaItem per (tmdb, id); both live → pick keyboard [🎬 film / 📺 series] handled in confirm_handler via pick_movie/pick_tv callbacks; single hit → create/self-heal (_ensure_media_item deletes stale wrong-type rows + all dependent rows first).
- Bug B fix — button replies used cb.message.reply_text(...), which does NOT exist on aiogram 3.x Message (user log: AttributeError, "Did you mean: 'reply_photo'?") → every ✅/❌/🔄/⏹ action crashed AFTER its DB side effect. Replaced all four with cb.message.answer(); new tests/test_media_resolve.py pins pick-collision flow and self-heal via FakeDetailsProvider.
- One-off DB cleanup DONE: stale wrong-type rows 60625, 76479, 250307, 287527 deleted with all dependent rows (incl. 3 user_watch_items); temp inspect/cleanup scripts removed afterwards; data/bot.db now holds the 7 legitimate items only.

### Phase 11 (PlayStation Store) — DONE
- Created: app/providers/psn.py — PSN GraphQL client с поиском игр и ценами в ILS (₪), концепт ID фильтрация, кэширование 12 часов; app/scheduler/polling.py — удалён PSN polling (новая архитектура не использует state comparison).
- Updated: app/bot/main.py — PSN результаты в /search с ценами в ₪ (base_price/sale_price формат), PSN ID в unified /add flow.
- Updated: app/config.py — добавлены psn_graphql_hash, psn_hash_last_update.
- Verified: PSN GraphQL API работает с заголовком `x-psn-store-locale-override: en-IL`, цены парсятся из GraphQL ответа (формат "ILS ₪279.00"), фильтрация исключает DLC/музыку/ремастеры.
- Commit: `1503622` — Phase 11: PSN Store integration.

### Phase 15 (Tests, backups, logging) — DONE
- Created: app/utils/logging_config.py — структурированное логирование с RotatingFileHandler (10MB, 5 бэкапов); app/utils/backup.py — автоматический бэкап SQLite базы данных с timestamp; app/scheduler/polling.py — добавлена функция backup_database(); tests/test_integration.py — 8 integration тестов (watchlist, notes, events, backup, logging).
- Updated: app/bot/main.py — добавлен setup_logging() при старте, backup job в APScheduler (каждый день в 3 AM).
- Verified: все 42 теста проходят (41 existing + 8 new integration). py_compile OK.

### Phase 12 (Kinopoisk) — ABANDONED
- Reason: Kinopoisk API support (support@kino.pub) does not provide CLIENT_ID + CLIENT_SECRET to users without business partnership. OAuth Device Flow requires official API credentials.
- Research completed: studied API v1 (https://kinoapi.com), OAuth Device Flow, search/details endpoints, audios/seasons fields. Documentation updated with findings for future reference.
- No implementation done.

### Phase 13 (READY_TO_WATCH rules) — ABANDONED
- Reason: None of the monitored sources (TMDb, AniList, IGDB, Steam, PSN) provide Russian audio track information. "All episodes aired" is not relevant — user watches series episode by episode, not waiting for full completion.
- No implementation done.

## 7. KNOWN BUGS & ISSUES

All bugs discovered during Docker testing (2026-09-20). Do NOT fix until user gives explicit permission.

### BUG-1: TMDb ID collision — wrong item added when same ID exists as both movie and series
**Status:** FIXED (2026-09-20)
**Symptom:** User searches "Breaking Bad", sees "📺 Во все тяжкие (2008) [tmdb=1396]", runs `/add 1396`. Bot responds "✅ Добавлено: Зеркало (1975)" — completely wrong item.
**Root cause:** When TMDb ID 1396 had both movie and TV hits, the code checked existing DB items by media_type only (`m.media_type in hits`). If a stale/wrong-type item existed (e.g., "Зеркало" as movie with tmdb=1396), it was returned without verifying the title matched the API response.
**Fix:** Added title-based matching in the collision path. When both movie+tv exist in hits, the code now checks if an existing DB item's `canonical_title_en` matches the API title for that media_type. Only returns existing item if both media_type AND title match. Otherwise shows picker.
**Files:** `app/bot/main.py` (`_resolve_media_for_add`, lines ~365-385)
**Repro:** `/search Breaking Bad` → `/add 1396` → was adding wrong item, now shows picker or correct existing item

### BUG-2: Notes not persisting in database
**Symptom:** User runs `/note 693134 рандомный комент` → bot shows "📝 Заметка для Дюна: Часть вторая: рандомный комент". Next run `/note 693134` → bot shows "📝 Заметка для Дюна: Часть вторая: None".
**Root cause:** Notes appear to display correctly on save but `get_note()` returns None on retrieval. Likely the note is not being committed to the database session, or the session is closed before commit.
**Files:** `app/services/notes.py`, `app/bot/main.py` (note_handler)
**Repro:** `/note <id> <text>` → `/note <id>` → shows "None"

### BUG-3: No inline delete/edit buttons for notes
**Symptom:** No way to edit or delete notes through the UI. Only `/note <id>` to view. No inline keyboard with delete/edit buttons next to the note message.
**Status:** Feature not implemented. Needs inline keyboard with callback queries for edit/delete.
**Files:** `app/bot/main.py` (note handlers)

### BUG-4: No inline delete button in /watchlist
**Symptom:** Cannot delete items from watchlist via inline button. Must use `/remove <id>` command. No delete button shown next to each item in `/watchlist` output.
**Status:** Feature not implemented. Needs inline keyboard with callback queries for each watchlist item.
**Files:** `app/bot/main.py` (watchlist_handler)

### BUG-5: Steam game add crashes bot (KeyError on dict release_date)
**Status:** FIXED (2026-09-20)
**Commit:** `to be committed after user approval`
**Symptom:** User runs `/add 2636430` (Soggy Beans Steam ID). Bot crashes with:
```
KeyError: slice(None, 4, None)
  File "/app/app/bot/main.py", line 827, in add_handler
    year = (details.get("first_air_date") or details.get("release_date") or details.get("released") or "")[:4]
```
**Root cause:** Steam API returns `release_date` as a dict `{"date": "Sep 21, 2026", "coming_soon": true}`, not a string. Code tries to slice dict with `[:4]`.
**Fix:** Check if `release_date` is a dict, extract `date` field first, convert to string before slicing.
**Files:** `app/bot/main.py` (add_handler, line 827)
**Repro:** `/add 2636430` → crash (before fix), works after fix

### BUG-6: AniList not shown in "which service" picker
**Symptom:** User runs `/add 20789` (AniList ID for "Nanatsu no Taizai"). Bot responds "Найдено в 4 сервисах. Какой добавить?" but AniList is NOT in the list of options. Same for `/add 20850` (Tokyo Ghoul √A) — "Найдено в 3 сервисах" but AniList missing.
**Root cause:** The `resolve_media_for_add` function or the picker display logic does not include AniList results when building the service selection prompt. AniList items are found but filtered out before display.
**Files:** `app/bot/main.py` (add_handler), `app/services/media_resolve.py`
**Repro:** `/add 20789` → AniList option missing from picker

### BUG-7: PSN results lack clear addable ID
**Symptom:** User searches "last of us", sees "🎮 The Last of Us™ Part II Remastered 199.00₪ [psn=EP9000-CUSA00557_00-DLC5WEPSCROSSBOW]". Tries `/add EP9000-CUSA10249_00-THELASTOFUSPART2` → bot says "Нужно число TMDb, AniList, IGDB, Steam или PSN id, например: /add 841". Tries `/add 07642` → wrong result.
**Root cause:** PSN IDs are long alphanumeric strings (e.g., `EP9000-CUSA10249_00-THELASTOFUSPART2`), not numeric. The `/add` handler expects numeric IDs and rejects PSN format. Need to either: (a) accept full PSN ID strings, or (b) map PSN results to numeric IDs that can be used with /add.
**Files:** `app/bot/main.py` (add_handler), `app/providers/psn.py`
**Repro:** `/search last of us` → `/add <psn-id-from-result>` → rejected

### BUG-8: PSN search too strict (deferred fix)
**Symptom:** User searches "last of us 2" → no PSN results. PSN API requires exact title "The Last of Us Part II".
**Root cause:** PSN GraphQL search does fuzzy/exact matching that doesn't handle partial/misspelled queries. TMDb/IGDB/Steam search handles this better.
**Status:** DEFERRED — requires separate design decision on search strategy per provider. Do NOT fix in current phase.
**Files:** `app/providers/psn.py`

### BUG-9: Cannot verify notification system works
**Status:** IN PROGRESS (2026-09-20)
**Symptom:** No manual way to trigger or test notifications. Notifications are fired automatically by the event engine during polling, but there's no test command or debug mode to verify the full pipeline (event detection → rule matching → message send → dedup mark).
**Current approach:** Adding games with imminent release dates (IGDB The Rabbit Haul 265277 releases 2026-09-21) to test via polling.
**Files:** `app/domain/events.py`, `app/services/notifications.py`, `app/scheduler/polling.py`

### BUG-10: Backup scheduled at 3 AM — unreliable if bot not running 24/7
**Symptom:** Backup job runs at 3 AM daily via APScheduler cron. If bot is not running at 3 AM (e.g., user's computer sleeps, VPS reboots), backup is skipped until next day.
**Root cause:** `scheduler.add_job(_backup_database, "cron", hour=3, minute=0)` in `app/bot/main.py`.
**Fix needed:** Run backup on every startup (at least once) in addition to scheduled runs. Or use "interval" based backup (e.g., every 24 hours from last run) instead of fixed cron.
**Files:** `app/bot/main.py` (line ~1217)

### BUG-11: Anime season count includes non-season items (movies, OVAs, spin-offs, recaps)
**Status:** NOT FIXED — discovered 2026-09-27
**Symptom:** 
- One Piece shows "сезонов: 4" but only 3 TV seasons exist (plus remakes/recaps)
- JJK shows "сезонов: 4" but should be 3 (Seasons 1-3, with Season 4 announced)
- Kusuriya shows "сезонов: 4" but should be 3
**Root cause:** `get_seasons()` in `shikimori.py` likely includes ALL items from franchise: movies, OVAs, spin-offs, recaps, special episodes. These are counted as "seasons" in `total_seasons`.
**Investigation needed:** Check `get_seasons()` function — it probably filters by `type == "anime"` but doesn't exclude `kind` values like "movie", "ova", "special", "summary", "alternative_version".
**Possible fix:** Filter seasons to only include TV/ONA with duration >= 15 min. Use Shikimori `related` field with `relationKind` (sequel, prequel, summary, etc.) to build proper season chain. Exclude items where `kind` is "movie", "ova", "special", "summary", "alternative_version", "spin_off".
**Files:** `app/providers/shikimori.py` (`get_seasons`, `build_franchise_summary`)
**Repro:** Any anime franchise with movies/OVAs shows inflated season count

### BUG-12: TV series episode count shows "0 из 1" for trailers/specials
**Status:** NOT FIXED — discovered 2026-09-27
**Symptom:** Silo ("Укрытие") shows "Выпущено: 0 из 1" — likely counting a trailer or special episode as a regular episode.
**Root cause:** TMDb `/tv/{id}/season/{number}/episodes` may include special episodes (episode_number=0 or type="special") that are not real episodes. The code counts all episodes returned by API without filtering.
**Investigation needed:** Check how episodes are counted in the TV details handler. Are special episodes (episode_number=0, type="special") being counted?
**Possible fix:** Filter out special episodes when counting. Only count episodes where `episode_number >= 1` and `type != "special"`.
**Files:** `app/bot/main.py` (TV details handler, episode counting logic)
**Repro:** Any TV series with special/trailer episodes shows incorrect episode count

### BUG-13: One Piece current season detection wrong — shows "сезон 1 из 4"
**Status:** NOT FIXED — discovered 2026-09-27
**Symptom:** One Piece shows "Статус: Выходит сезон 1 из 4" but current season should be much higher (12+).
**Root cause:** `pick_current_season()` in `shikimori.py` is likely picking the first season in the list instead of the actual current/ongoing season. Or the season ordering is wrong (not sorted by year/air date).
**Investigation needed:** Check `pick_current_season()` logic — does it correctly identify the ongoing season? Does it handle franchises where seasons overlap or have no clear boundaries?
**Possible fix:** Sort seasons by air date or year. Pick the season with `status == "released"` and highest episode count, or the season with `status == "releasing"`. For One Piece (which has no clear season boundaries), use the most recent season by year.
**Files:** `app/providers/shikimori.py` (`pick_current_season`)
**Repro:** One Piece details handler

### BUG-14: JJK (Jujutsu Kaisen) details show minimal information — no episode progress
**Status:** NOT FIXED — discovered 2026-09-27
**Symptom:** JJK details show only:
```
Магическая битва
Аниме
  сезонов: 4
  Статус: Анонсирован сезон 4
```
No episode progress, no airing schedule, no season details.
**Root cause:** JJK Season 3 is finished, Season 4 is announced but not airing. AniList query may return no data for Season 4 (not yet released). Shikimori franchise data may not have `nextAiringEpisode` for announced seasons.
**Investigation needed:** 
1. Check what AniList returns for JJK Season 4 MAL ID (if available)
2. Check what Shikimori returns for JJK franchise — does it have data for Season 4?
3. Check if `pick_current_season()` correctly identifies Season 4 as "announced"
**Possible fix:** For announced but not-yet-airing seasons, show season announcement info without episode data. Use Shikimori franchise data to show "Сезон N анонсирован, дата не объявлена". Don't require AniList data for announced seasons.
**Files:** `app/bot/main.py` (anime details handler), `app/providers/shikimori.py` (`pick_current_season`, `build_franchise_summary`)
**Repro:** JJK details, any anime with announced but not-yet-airing season

### BUG-15: Game details don't show release dates
**Status:** NOT FIXED — discovered 2026-09-27
**Symptom:** Games show only platform names without release dates:
```
Call of Duty: Warzone
Игра

Платформы:
  IGDB ✅
  PSN ✅
```
Should show:
```
Call of Duty: Warzone
Игра

Платформы:
  IGDB ✅ (2020-03-10)
  PSN ✅ (2020-06-10)
  STEAM ✅ (2022-12-07)
```
**Root cause:** Game details handler in `main.py` doesn't display release dates from `GamePlatform` table. The `release_date` field exists in `GamePlatform` but is not shown in the details output.
**Investigation needed:** Check game details handler — does it query `GamePlatform` table? Does it format and display `release_date`?
**Possible fix:** Query `GamePlatform` table for the item, format release dates as DD.MM.YYYY, show alongside platform names.
**Files:** `app/bot/main.py` (game details handler)
**Repro:** Any game with release dates in `GamePlatform` table — e.g., "Call of Duty: Warzone" (IGDB+PSN+Steam), "No Man's Sky" (IGDB+PSN+Steam)


## 6. CURRENT STATE

Current phase: Phase 22 — Unified Game Entity (platform-agnostic media items with multi-platform tracking). BUG-1 through BUG-5 fixed.

Last successful steps:
- Docker image builds and runs successfully
- Bot starts, connects to Telegram, scheduler runs, backup job scheduled
- All 42 tests pass
- 10 bugs found during manual testing (see Section 7)

Expected next action:
1. User gives permission to fix bugs from Section 7 (one by one).

## 15. NEXT STEPS

### PHASE 12 ACTION PLAN — Kinopoisk [RESEARCH DONE, AWAITING API KEYS]

Goal: Добавить Kinopoisk как основной источник для русскоязычного контента (фильмы/сериалы на русском языке, русская озвучка, Kinopoisk Premium availability).

Research results (Kinopoisk API v1 — https://kinoapi.com):
- Auth: OAuth Device Flow (CLIENT_ID + CLIENT_SECRET от support@kino.pub)
  - POST `https://api.service-kp.com/oauth2/device?grant_type=device_code&client_id=xxx&client_secret=xxx`
  - User enters code on https://kino.pub/device
  - Poll `https://api.service-kp.com/oauth2/device?grant_type=device_token&code=xxx` → access_token + refresh_token
  - Refresh: `https://api.service-kp.com/oauth2/token?grant_type=refresh_token&refresh_token=xxx`
- Search: `GET /v1/items/search?q=term&perpage=40` (search by title, director, cast)
- Details: `GET /v1/items/<item_id>` (movies/series with seasons, episodes, audios, quality)
- Types: movie, serial, 3D, concert, documovie, docuserial, tvshow
- Key fields: title, type, year, quality, genres, countries, posters, kinopoisk_rating, audios (lang: rus/ukr, type: MVO/AVO), seasons (for series)
- Status: Ждём ответ от support@kino.pub на запрос CLIENT_ID + CLIENT_SECRET

Implementation plan (pending API keys):
1. [ ] Create app/providers/kinopoisk.py — Kinopoisk v2 API client (search, details, seasons, auth)
2. [ ] Update app/domain/events.py — добавить KINOPOISK_RUS_AVAILABLE, KINOPOISK_PREMIUM_AVAILABLE event types
3. [ ] Update app/domain/events.py — добавить compare_kinopoisk_states function
4. [ ] Update app/scheduler/polling.py — _fetch_kinopoisk_state + _normalize_kinopoisk_details, integrate into poll_item
5. [ ] Update app/bot/main.py — Kinopoisk search in /search, Kinopoisk ID support in /add, _ensure_kinopoisk_item
6. [ ] Update app/config.py — добавить kinopoisk_api_key setting
7. [ ] Create tests/test_kinopoisk.py (unit tests: state normalization, event detection)
8. [ ] End-to-end verification in Telegram

Files this touches:
- app/providers/kinopoisk.py (новый провайдер)
- app/domain/events.py (новые event types + compare function)
- app/scheduler/polling.py (kinopoisk polling)
- app/bot/main.py (search + /add integration)
- app/config.py (kinopoisk_api_key)
- tests/test_kinopoisk.py (unit tests)

Verification criteria:
- /search <название> возвращает фильмы/сериалы из Kinopoisk с русскими названиями
- /add <kinopoisk_id> добавляет item с Kinopoisk source
- KINOPOISK_RUS_AVAILABLE fires when Russian audio becomes available
- KINOPOISK_PREMIUM_AVAILABLE fires when content becomes available on Kinopoisk Premium

Requirements (user-approved): when adding ANY item (movie/game/TV/anime) that already has known release dates or is fully out/completed → show current state and ask whether to track it. No exceptions: all media types follow the same flow since the user uses the bot exclusively for tracking not-yet-released media.

Phase 7 E2E in Telegram — DONE (user confirmed): /search Silo → took 📺 id → /add <tv_id> → «✅ Добавлено: Укрытие», no premature notification; silent baseline add on first poll is by design, not an error.

Expected next action:
1. User picks the next phase: Phase 7.5 (TMDb API call optimization — plan in §15, user-approved) or Phase 8 (AniList/anime).
2. The checklist below is retained as a regression checklist for future changes to /add resolution.

User verification checklist (Telegram):
1) Kill stale bot instances and start fresh:
   `cd E:\LocalAI\Bionic\Telegram-bot`
   `Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*app.bot.main*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }`
   `.\.venv\Scripts\Activate.ps1`
   `python -m app.bot.main`  (no console output on start is normal by design; handler errors print as ERROR:aiogram.event tracebacks)
2) `/add <id of old released movie>` (e.g. Dune 841): expect «Дата цифрового релиза уже известна: ... — уже вышел» + [✅ В список / ❌ Не нужно]. ✅ → added, NO retroactive DIGITAL_DATE_ANNOUNCED; ❌ → «Не добавлено».
3) `/add <airing series or movie without date yet>`: normal add + status line. Specifically: /add 95350 (Фонари) → «✅ Добавлено: Фонари (2026)» + «Идёт сезон 1, 5/8 серий вышли», no prompt; /add 125988 (Укрытие) → normal add with «Сезон 4 анонсирован, серий ещё не вышло».
4) Ambiguous TMDb id — the same number exists as BOTH a movie and a TV show (e.g. /add 60625 after cleanup): bot asks «Этот TMDb id совпадает с двумя произведениями» + [🎬 film / 📺 series]; pressing one resolves to that type and continues the normal add flow.
5) Repeat /add for an already-tracked item → «📌 Уже в списке отслеживания: ...» + [🔄 Продолжить / ⏹ Остановить]; every button action must produce a visible chat reply (Bug B fixed — previously buttons crashed silently).

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
- SEASON_PROGRESSED — событие выхода серии внутри текущего сезона TV/аниме; по умолчанию НЕ включается при /add (можно включить через правила вручную). Новые сезоны по-прежнему уведомляются NEW_SEASON_ANNOUNCED, завершение сезона — ALL_EPISODES_OUT.
- TV/anime эпизоды считаются вышедшими ТОЛЬКО если air_date не null и <= сегодня; future-даты (плейсхолдерные эпизоды анонсированных сезонов) никогда не считаются вышедшими — иначе анонсированный сезон ошибочно сообщается как полностью вышедший.
- aiogram 3.x InlineKeyboardMarkup: поле `inline_keyboard` требует вложенный список рядов `list[list[InlineKeyboardButton]]` (каждая кнопка — отдельный ряд), плоский список кнопок даёт pydantic ValidationError.
- TMDb использует ОДНО общее числовое пространство id для фильмов и сериалов: одно число может существовать одновременно как /movie/{id} и /tv/{id}. Поэтому /add обязан опрашивать ОБА эндпоинта; в БД ровно один MediaItem на (tmdb, id).
- Self-heal при резолвинге: если для того же tmdb id осталась старая строка неверного типа, она удаляется вместе со всеми зависимыми строками до создания нового MediaItem.
- aiogram 3.x: у Message НЕТ метода reply_text — только .answer() (message.answer / cb.message.answer); вызов .reply_text падает с AttributeError в рантайме.
- Phase 7.5: adaptive polling replaces full-every-600s cycle — each item keeps its own next_check_at deadline; tiers computed from observed state (known release → WEEKLY, no info → DAILY; airing TV → DAILY, completed season → WEEKLY); TMDb calls staggered by min_call_interval (default 1.5s) with rolling per-minute cap (default 30); HTTP 429 triggers exponential backoff.
- Phase 8: anime items now polled from BOTH TMDb and AniList (dual-source); AniList provides NEXT_EPISODE_AIRING events with episode number + air date; /search returns anime from AniList with 🎌 icon; /add accepts AniList IDs as fallback when TMDb returns nothing; default rules for anime: NEXT_EPISODE_AIRING + ALL_EPISODES_OUT.

## 8. THINGS WE TRIED AND REJECTED

Rejected (Phase 6 Step A): assuming TMDb /movie/{id}/release_dates is a flat list of entries keyed by `type` string ("Digital") + `iso_release_date`.
Reason: live shape is a nested per-region array; each region has a nested `release_dates` list whose entries use INTEGER `type` codes (1=Premiere,2=Theatrical-limited,3=Theatrical,4=Digital,5=Physical,6=TV) and key `release_date` (ISO datetime). Confirmed via official TMDb docs + real GET /movie/841/release_dates. Do NOT retry the flat/string assumption; parse nested regions + integer type code 4 for Digital, read `release_date[:10]`.

Rejected (aiogram InlineKeyboardMarkup at /add confirm keyboards): passing buttons as a flat list or using parameter name `inline_keys=`.
Reason: aiogram 3.x field is `inline_keyboard: list[list[InlineKeyboardButton]]` — every button must be its own row `[ [btn1], [btn2] ]`; a flat list raises pydantic ValidationError (reproduced the user's exact 28-error log in-venv). Both /add keyboard sites now use row form.

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
Rate limit: legacy "40 requests / 10 s" disabled since Dec 16, 2019; soft upper limits sit around ~40–50 req/s and ≤20 concurrent connections per IP; no documented daily cap. Respect HTTP 429 with backoff (official docs: https://developer.themoviedb.org/docs/rate-limiting).
Batch: NO bulk endpoint to fetch details of multiple ids in one request — confirmed by TMDb staff on Talk forum ("You can only get the movie details one movie at a time"). Daily export files exist but are unsuitable for live per-id tracking.

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
Status: implemented (Phase 11 DONE — GraphQL search with ILS prices)
Purpose: detect PSN store page, wishlist availability, prices in ILS (₪)
Auth: no auth needed (public GraphQL endpoint with sha256Hash)
Base URL: https://web.np.playstation.com/api/graphql/v1/op
Method: getSearchResults (GraphQL) with persisted query sha256Hash; x-psn-store-locale-override: en-IL для цен в ILS
Cache: 12 часов по нормализованному запросу
Filtering: только Product с ценой, все слова запроса в name, исключены DLC/музыка/ремастеры/бандлы
Fallback: если GraphQL 400 (sha256Hash истёк) — ERROR лог с текстом "требуется обновить sha256Hash для getSearchResults"

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
- TV tests: test_tv_baseline_no_event, test_tv_new_season_announced (payload {"season": 2}), test_tv_all_episodes_out (fires exactly once), test_tv_state_normalization — all pass against the real two-call TMDb flow (seasons metadata + per-season episodes)
Run: `.venv\Scripts\python.exe -m tests.test_scheduler_polling` → `scheduler polling tests passed`

tests/test_pre_add_check.py (pure logic, no network):
- pre_add_check classification for movies (released/upcoming/no_data) and TV/anime (season_complete/airing/no_data), including announced-but-not-started stub season ({latest_season:4,total:1,aired:0} → airing, NOT complete — live Silo S4 shape) and mid-season with future eps ({latest:1,total:8,aired:5} → airing — live Fonari S1 shape); SEASON_PROGRESSED within same season (suppressed on season transition; no events when state unchanged)
Run: `.venv\Scripts\python.exe -m tests.test_pre_add_check` → `pre add check tests passed`

tests/test_media_resolve.py (in-memory SQLite via StaticPool + FakeDetailsProvider, no network):
- _make_media_item field mapping; _lookup_tmdb_details both/one/neither hits (real collision case id=60625); _ensure_media_item create / same-type hit / self-heal with dependent-row deletion; _resolve_media_for_add none / single-hit create / collision pick / existing-preferred / stale-residue
Run: `.venv\Scripts\python.exe -m tests.test_media_resolve` → `media resolve tests passed`

tests/test_tiering.py (pure logic, no network):
- test_movie_with_known_date_is_weekly, test_movie_without_any_info_is_daily, test_empty_state_is_daily_for_every_type, test_tv_fully_aired_season_is_weekly, test_tv_airing_or_stubbed_announced_season_is_daily, test_due_sort_key_puts_missing_deadlines_first
Run: `.venv\Scripts\python.exe -m tests.test_tiering` → `tiering tests passed`

All 9 no-network modules (watchlist_notes, domain_events, notifications, scheduler_polling, pre_add_check, media_resolve, tiering, anilist) pass — re-verified after Phase 8 implementation.

tests/test_integration.py (in-memory SQLite via StaticPool + tmp_path, no network):
- test_add_and_remove_watch_item: pass (add → list total==1; remove True then list total==0)
- test_get_media_item_by_external_id: pass (existing tmdb id returns item; nonexistent returns None)
- test_notes_crud: pass (create → get → list → update → delete → get returns None)
- test_compare_states_detects_digital_date: pass (old={digital:null} → new={digital:date} → DIGITAL_DATE_ANNOUNCED)
- test_compare_states_no_event_on_no_change: pass (same dates → no events)
- test_dedup_mark_sent: pass (first mark True; second mark False; has_been_sent True)
- test_backup_creates_file: pass (backup file exists with timestamp in name)
- test_setup_logging_creates_directory: pass (logs dir + bot.log created)
Run: `.venv\Scripts\python.exe -m pytest tests/test_integration.py -v` → 8 passed

All 42 tests pass (34 existing + 8 new integration).

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

Phase 6 (Movie Digital release tracking) — DONE:
1. [DONE] Add TMDbProvider.get_movie_release_dates(movie_id) → raw release-dates array (/movie/{id}/release_dates?language=ru&watch_region=all).
2. [DONE] Pure _earliest_digital_date(list)->str|No normalization (no network); no-network unit test tests/test_release_state.py passes.
3. [DONE] Refine _fetch_tmdb_state to pick earliest 'Digital' date from release_dates (drop theatrical placeholder); FakeProvider updated for get_movie_release_dates.
4. [DONE] End-to-end verified in Telegram: re-launch produced exactly one 🔕 DIGITAL_DATE_ANNOUNCED per watch item on startup (old {digital_release:null} → None→value via real TMDb), no duplicates; /events <tmdb_id> lists enabled rules.

NEW FEATURE (planned, not yet implemented): "Already released" confirmation on add — when user adds ANY item that already has known release dates or is fully out/completed, show notification about current state + ask whether to track it. No exceptions: all media types follow the same flow since the user uses the bot exclusively for tracking not-yet-released media.

Details:
- Movies/Games (already released): show "Фильм/игра уже вышел" + ask add to watchlist? yes/no
- TV/Anime (partial-season): detect all episodes of current season are out → notification "Все серии сезона N уже вышли" + ask whether to track
- Completed series/anime: same flow as movies/games — show completion + ask whether to track (no special exception)
- Pre-check before storing baseline; if already tracked → show state summary + ask keep/stop tracking

Files this touches:
- app/bot/main.py — /add handler pre-check
- app/domain/events.py — new event types for TV/anime season-completeness
- app/scheduler/polling.py — extend _fetch_tmdb_state with per-season episode counts
- app/services/watchlist.py — confirmation flow (ask if not tracked; show state summary if already tracked)

- [DONE] Phase 7 committed after user's E2E confirmation in Telegram.
- [DONE, unit verified] "already-released confirm-on-add" implemented; awaiting user E2E verification → then commit.

Next exact action:
- After user confirms the section 6 checklist in Telegram — commit this feature.

### PHASE 7 ACTION PLAN (TV Episode Tracking) — detailed steps [steps 1–5 DONE + unit/live verified; step 6 (Telegram E2E) pending user confirmation]

Goal: Track TV series episodes: new season announcements, per-season episode counts, Russian audio availability for new seasons. Avoid duplicate notifications when metadata updates but no new episode appears.

Steps:
1. TMDb TV details extension — extend get_tv_details / _fetch_tmdb_state to return latest season number, total episodes per season, air dates per episode (TMDb /tv/{id}/seasons or /tv/{id} with with_seasons=true)
2. Normalized state for TV — add fields: latest_season, total_episodes_current_season, episodes_aired_current_season, rus_audio_latest_season; detect "all episodes of season N are out" vs "not all yet"
3. New event types — NEW_SEASON_ANNOUNCED (new season announced), ALL_EPISODES_OUT (all episodes of a season have aired), SERIES_COMPLETED (series has completed flag, no more episodes)
4. compare_states extension — detect transitions: old state has no latest_season → new state has it; old state has fewer episodes → new state has more (new episode aired); wire into existing dedup + enabled-rule gate
5. Tests — in-memory SQLite unit tests for TV state comparison, NEW_SEASON_ANNOUNCED, ALL_EPISODES_OUT detection; no-network fake provider with real TMDb shape
6. End-to-end verify — add a TV series in Telegram → confirm "all episodes out" confirmation dialog (new feature) or silent baseline-store if already tracked; confirm NEW_SEASON_ANNOUNCED fires exactly once per real new season

Verification criteria:
- /add <tv_tmdb_id> for an already-completed season shows the partial-season confirmation
- NEW_SEASON_ANNOUNCED fires exactly once per real new season (no duplicates)
- No false positives: metadata update without new episode → no event

### PHASE 7.5 ACTION PLAN — Optimization of TMDb API calls (rate limit / adaptive intervals) [DONE]

Implemented:
1. [DONE] Pure tier function (state → interval) + 6 no-network unit tests in tests/test_tiering.py
2. [DONE] next_check_at column on source_states (migration a7c3e91f2d48)
3. [DONE] Reworked scheduler: poll_due_items() processes only "due" items, staggered by min_call_interval (1.5s default)
4. [DONE] HTTP 429 handling with exponential backoff in TMDbProvider._get()
5. [DONE] All 8 test modules pass; py_compile OK; migration applied

Tier rules:
- Movie/game with known digital release → WEEKLY (604800s)
- Movie/game with no release info → DAILY (86400s)
- TV/anime: current season airing or waiting → DAILY
- TV/anime: season fully aired, no next-season activity → WEEKLY

Configurable via env vars:
- TMDB_MIN_CALL_INTERVAL=1.5
- TMDB_MAX_CALLS_PER_MINUTE=30
- TMDB_429_BACKOFF_BASE_SECONDS=5.0
- TMDB_429_MAX_RETRIES=3
- POLL_SCAN_INTERVAL_SECONDS=120

### PHASE 8 ACTION PLAN — AniList/anime [DONE]

Implemented:
1. [DONE] AniListProvider (app/providers/anilist.py): GraphQL search_anime, get_anime_details, get_next_episode with throttling
2. [DONE] NEXT_EPISODE_AIRING event + compare_anilist_states in events.py
3. [DONE] _fetch_anilist_state + _normalize_anilist_details in polling.py
4. [DONE] poll_item accepts both tmdb_provider and anilist_provider (dual-source for anime)
5. [DONE] main.py: AniList search in /search, AniList ID support in /add, _ensure_anilist_item
6. [DONE] tests/test_anilist.py (5 tests: state normalization, episode airing, no-change, finished, first poll)
7. [DONE] All 9 test modules pass; py_compile OK

AniList API: https://graphql.anilist.co (GraphQL POST), no key needed for public data, ~90 req/min soft limit.
Anime items now polled from BOTH TMDb and AniList — TMDb for season/episode tracking, AniList for NEXT_EPISODE_AIRING events.

### PHASE 11 ACTION PLAN — PlayStation Store [DONE]

Implemented:
1. [DONE] PSNProvider (app/providers/psn.py): GraphQL search with ILS prices, concept ID filtering, 12h cache
2. [DONE] main.py: PSN results in /search with ILS prices (₪ format), PSN ID in unified /add flow
3. [DONE] polling.py: removed PSN polling (new architecture doesn't use state comparison)
4. [DONE] config.py: added psn_graphql_hash, psn_hash_last_update
5. [DONE] All verified with real API — cyberpunk 2077 returns 199₪, god of war returns 96₪

PSN GraphQL API: https://web.np.playstation.com/api/graphql/v1/op, requires sha256Hash persisted query, x-psn-store-locale-override: en-IL for ILS prices.

### PHASE 15 ACTION PLAN — Tests, backups, logging [DONE]

Implemented:
1. [DONE] pytest + pytest-asyncio installed in .venv
2. [DONE] app/utils/logging_config.py — structured logging with RotatingFileHandler (10MB max, 5 backups)
3. [DONE] app/utils/backup.py — automatic SQLite backup with timestamp
4. [DONE] app/scheduler/polling.py — backup_database() function
5. [DONE] app/bot/main.py — setup_logging() at startup, backup job daily at 3 AM via APScheduler
6. [DONE] tests/test_integration.py — 8 integration tests (watchlist, notes, events, backup, logging)
7. [DONE] All 42 tests pass (34 existing + 8 new)

### PHASE 12 (Kinopoisk) — ABANDONED
- Reason: Kinopoisk API support (support@kino.pub) does not provide CLIENT_ID + CLIENT_SECRET to users without business partnership. OAuth Device Flow requires official API credentials.
- Research completed: studied API v1 (https://kinoapi.com), OAuth Device Flow, search/details endpoints, audios/seasons fields. Documentation updated with findings for future reference.

### PHASE 13 (READY_TO_WATCH rules) — ABANDONED
- Reason: None of the monitored sources (TMDb, AniList, IGDB, Steam, PSN) provide Russian audio track information. "All episodes aired" is not relevant — user watches series episode by episode, not waiting for full completion.

Goal: reduce the number of TMDb requests so we do not get blocked by rate limits as the watchlist grows; make re-check frequency depend on item "freshness"; spread checks in time instead of one full cycle every 600 s.

Problem with current behavior: one full polling cycle for ALL items every 600 s. Movies: ~2 TMDb calls per item per cycle (details + release_dates); TV/anime: 2 calls (season metadata + latest-season episodes). OK now, but it grows linearly with list size and will multiply when more providers are added (Phases 8–13).

Research results (verified via official docs + TMDb staff statements):
- Legacy limit "40 req / 10 s" disabled since Dec 16, 2019. Soft upper limits sit around ~40–50 req/s and ≤20 concurrent connections per IP; no documented daily cap (staff: "no daily maximum"). Must respect HTTP 429 with backoff (official docs: https://developer.themoviedb.org/docs/rate-limiting).
- NO batch endpoint to fetch details of multiple ids in one request — TMDb staff confirmed on Talk forum: "You can only get the movie details one movie at a time" (https://www.themoviedb.org/talk/65cef6b09ac5350162dfa262). Daily export files exist but are unsuitable for live per-id tracking.
- Conclusion: requests go per-item and must be staggered in time with a minimum interval between consecutive calls, not fired simultaneously.

Planned design:
1. Tiering by item state (based on the latest observed state):
   - Release date known (or "digital" announced without an exact date) → re-check weekly (~604800 s), verify the date has not changed;
   - No release information at all yet (nothing announced) → once a day (86400 s);
   - TV/anime: current season is airing or waiting for new-season announcement — daily; season fully aired with no next-season activity — weekly.
2. Per-item scheduling: store next_check_at per item (a column on user_watch_items, or derive from source_states.observed_at + tier). Scheduler processes only items whose deadline has arrived — instead of a full cycle every 600 s.
3. Request staggering: minimum interval between consecutive TMDb calls ~1–2 s; spread checks for many items across the day (queue with jitter).
4. Global cap and backoff: upper bound on requests per minute/hour; on HTTP 429 — exponential backoff and move the item to the next slot.
5. Observability: count real TMDb calls in logs, verify the reduction over a day with the same watchlist.

Steps:
1. [ ] Define pure tier function (state → interval) + no-network unit tests
2. [ ] Per-item next_check_at storage (DB column or derived value; Alembic migration if needed)
3. [ ] Rework scheduler: process only "due" items, staggered by the minimum call interval
4. [ ] 429 handling with exponential backoff in TMDbProvider
5. [ ] Unit tests (no network) + E2E check: add several items and count requests over a day

When to do: recommended before Phase 8+ (AniList/IGDB/KinoPub), when polling load grows; exact moment at user's discretion.

## 15b. PROJECT MAINTENANCE RULES

All project data, plans, decisions, and state are updated and appended ONLY in this file (PROJECT_CONTEXT.md). No separate PLAN.md or other planning files should be created. If a new plan/decision/state needs to be recorded, it goes into this file immediately.

This rule exists because: the project is small enough that one well-maintained context file is sufficient; splitting across multiple files risks confusion when reading PROJECT_CONTEXT.md but missing PLAN.md or other files.

## 16. PHASE 22 — UNIFIED GAME ENTITY (PLATFORM-AGNOSTIC)

### Problem
Currently, "The Rabbit Haul" on IGDB (id=265277) and "The Rabbit Haul" on Steam (id=2514330) are stored as TWO separate MediaItem records. The bot doesn't know they're the same game. User sees them as separate entries in /watchlist. /events command only works with TMDb IDs.

### Goal
- One MediaItem per game/title (not per platform)
- Platforms stored as separate records linked to MediaItem
- User sees game name + year, not IDs
- /watchlist shows all tracked platforms with release dates
- /events removed — all info in watchlist
- Platform selection UI when adding a game

### New Schema

```sql
-- New table: GamePlatform
CREATE TABLE game_platforms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_item_id TEXT NOT NULL,           -- FK → media_items.id
    platform TEXT NOT NULL,                -- steam | igdb | psn | epic
    platform_id TEXT NOT NULL,             -- 2514330 / 265277 / EP9000-...
    release_date TEXT,                     -- ISO date or NULL
    store_url TEXT,                        -- Steam store URL, etc.
    FOREIGN KEY (media_item_id) REFERENCES media_items(id)
);

-- Existing ExternalId table stays (for TMDb/AniList mapping)
-- Existing MediaItem table stays (no changes)
-- Existing WatchItem table: add `tracked_platforms` JSON column
ALTER TABLE watch_items ADD COLUMN tracked_platforms TEXT DEFAULT '[]';
-- tracked_platforms example: '["steam", "psn"]'
```

### UI Flow

**Search:**
```
/search The Rabbit Haul
→ 🎮 The Rabbit Haul (2026) [igdb=265277, steam=2514330]
```

**Add:**
```
/add 265277
→ The Rabbit Haul (2026) — где отслеживать?
  [✓] Steam — 21 Sep 2026
  [✓] IGDB — 21 Sep 2026
  [ ] PSN — не найдена
  [Confirm]
```

**Watchlist:**
```
📚 Отслеживаю:
• The Rabbit Haul (2026)
  ├─ Steam: 21 Sep 2026 [ON]
  ├─ IGDB: 21 Sep 2026 [ON]
  └─ PSN: не найдена
• Soggy Beans (2026)
  └─ Steam: 21 Sep 2026 [ON]
```

### Implementation Steps

1. **[DONE]** Create `app/database/models.py` — add `GamePlatform` model
2. **[DONE]** Create migration / init_db update
3. **[DONE]** Steam/IGDB/PSN search methods — already exist
4. **[DONE]** Create `app/services/media_resolve.py` — unified resolver
5. **[DONE]** Add `/searchgame` command with platform buttons
6. **[DONE]** Add `add_platform` callback handler
7. **[DONE]** Fix DB commit in `db()` context manager
8. **[DONE]** Update `watchlist_handler` — show platforms for games
9. **[TODO]** Show release date in search header (instead of "Выберите платформу...")
   - If all platforms share same date → show "📅 21.09.2026 — The Rabbit Haul"
   - If different dates → show "📅 Steam: 21.09.2026, IGDB: 21.09.2026"
   - Clean button labels: remove dates, keep only game name + version tags (Demo, Complete Edition) + platform
10. **[TODO]** Replace emoji platform icons with custom icons
    - Steam: 🏪 → Steam logo (Unicode or custom emoji)
    - PSN: 🎯 → PlayStation logo
    - IGDB: 🎮 → keep gamepad
11. **[TODO]** Fix PSN search — currently returns 400 (graphql_hash issue)
12. **[TODO]** Update `app/scheduler/polling.py` — game polling for GamePlatform
13. **[TODO]** Remove `/events` command
14. **[TODO]** Update `_ensure_*_item` functions — merge into single `_ensure_game_item`
15. **[TODO]** Update `add_source` callback — use unified resolver

### Files to modify
- `app/database/models.py` — add GamePlatform model
- `app/database/session.py` — update init_db
- `app/bot/main.py` — add_handler, watchlist_handler, remove events_handler
- `app/scheduler/polling.py` — update game polling logic
- `app/services/notes.py` — no changes needed
- `app/domain/events.py` — no changes needed (still used by polling)

### Migration strategy
- New tables don't affect existing data
- Existing MediaItems without GamePlatform entries will show as "no platforms tracked"
- Need migration script to backfill GamePlatform from existing ExternalId records (igdb/steam/psn sources)

### Why this is the best approach
1. Correct data model — game is entity, platforms are attributes
2. No duplicate entries in watchlist
3. User never sees internal IDs
4. Easily extensible (add Epic/GOG/Xbox = one new table row)
5. /events becomes redundant — all info in watchlist
6. Works for movies/TV too (TMDb is the "platform" for them)

## 17. PHASE 23 — UNIFIED SEARCH BY TYPE + REDESIGNED WATCHLIST

### Problem
Current search requires separate commands: `/search` for movies/TV/anime and `/searchgame` for games. User has to remember which command to use. Watchlist shows all items in one flat list with emoji prefixes, no grouping by type, no season/episode progress, no release dates.

### Goal
1. Unified search: user types any text → bot asks "What are we looking for?" with 4 buttons (Movie/TV Series/Anime/Game) → shows results in buttons
2. Redesigned watchlist: grouped by type (Сериалы/Фильмы/Аниме/Игры), compact format with season/episode progress, release dates, platform info
3. Details on demand: each watchlist item has [Подробнее] [Удалить] buttons

### UI Flow

**Search:**
```
User: убежище
Bot: Что ищем?
  [🎬 Фильм] [📺 Сериал] [🎌 Аниме] [🎮 Игра]
User clicks [📺 Сериал]
Bot: 📅 2023.03.15
Убежище
[🎬 Убежище (2023) — TMDb]
[📺 Убежище: Season 2 (2024) — TMDb]
```

**Watchlist:**
```
Сериалы:
• Фонари (2026) — 1 сезон 6/8
  [Подробнее] [Удалить]
• Убежище (2023) — 3 сезон 10/10
  [Подробнее] [Удалить]

Фильмы:
• Дюна 3 (2026)
  [Подробнее] [Удалить]

Аниме:
• One Piece (1999) — 13 сезон 18/24
  [Подробнее] [Удалить]

Игры:
• The Witcher 3 — Steam, PSN, IGDB
  [Подробнее] [Удалить]
```

**Details (on [Подробнее] click):**
```
Фонари (2026)
Сериал, 2 сезон
1 сезон: 8 серий — 6 просмотрено
2 сезон: не анонсирован

Даты:
- Премьера: 15 марта 2026
- Цифровой релиз: не обьявлен

Платформы:
- TMDb: 12345
```

### API Data Mapping

**TMDb Movies:**
- title, release_date, poster_url, overview, genres
- release_dates endpoint → theatrical_date, digital_date

**TMDb TV Series:**
- name, first_air_date, backdrop_url, overview
- /tv/{id}/aggregate_season_details → seasons with episode counts
- /tv/{id}/next_episode_to_air → next episode date
- status: "Returning Series" / "Ended" / "Canceled" / "Planning"

**AniList:**
- title.romaji, episodes, status, nextAiringEpisode {episode, airingAt}
- format: "TV" / "MOVIE" / "ONA" / "OVA"

**Games (IGDB/Steam/PSN):**
- name, first_release_date, platforms (from GamePlatform table)

### Implementation Steps

1. **Add message handler for text messages (non-commands)**
   - In main.py, add `@dp.message()` handler that catches all text messages
   - Check if message starts with "/" — if yes, let existing command handlers process it
   - If not a command, check if bot is in "search mode" for this user
   - If not in search mode → save query, send "Что ищем?" with 4 buttons, set search mode
   - If in search mode → process as search query with selected type

2. **Add search type selection handler**
   - Callback handler for 4 buttons: `search_type:movie`, `search_type:tv`, `search_type:anime`, `search_type:game`
   - Look up saved query for this user
   - Call appropriate search function (tmdb.search_movie/tv, anilist.search_anime, media_resolve.search_games)
   - Show results as inline keyboard buttons
   - Clear search mode

3. **Create unified search result display**
   - For movies: button text = `Title (YYYY)` or `Title (DD.MM.YYYY)` if date available
   - For TV: button text = `Name (YYYY)` 
   - For anime: button text = `Name (YYYY)`
   - For games: use existing searchgame button format
   - Each button callback: `add_watch:{type}:{id}` where type=movie/tv/anime/game and id=external_id
   - No truncation if possible, max 60 chars

4. **Update add_watch callback handler**
   - Parse type and id from callback
   - Create/fetch MediaItem based on type
   - Add to watchlist
   - Show confirmation message

5. **Redesign watchlist_handler**
   - Query all watch items grouped by media_type
   - For each type, show header (Сериалы:/Фильмы:/Аниме:/Игры:)
   - For each item, show compact format:
     - Movies: `• Title (year)`
     - TV: `• Name (year) — S{season} {aired}/{total}`
     - Anime: `• Name (year) — {format} {aired}/{total}`
     - Games: `• Name — Platform1, Platform2, Platform3`
   - Add [Подробнее] [Удалить] buttons under each item
   - Button callbacks: `details:{media_item_id}`, `remove:{media_item_id}`

6. **Add details handler**
   - For movies: show title, year, release dates (theatrical, digital), genres, overview
   - For TV: show name, year, status, seasons with episode counts, next episode date
   - For anime: show name, year, format, episodes, next airing date
   - For games: show name, platforms with dates

7. **Add remove handler**
   - Remove item from watchlist
   - Show confirmation

8. **Update TV status logic**
   - If status == "Returning Series" and no next_episode_date → "следующий сезон не анонсирован"
   - If status == "Ended" → "сериал завершён"
   - If status == "Canceled" → "сериал отменён"

9. **Update polling for TV/anime**
   - Already works for TMDb movies/TV and AniList
   - Need to ensure next_episode_date is tracked

10. **Remove old /search and /searchgame commands**
    - After new search is working, remove /search and /searchgame
    - Keep inline search (@botname query) as is

### Files to modify
- `app/bot/main.py` — add text message handler, search type callback, redesigned watchlist, details handler
- `app/bot/main.py` — update add_watch callback
- `app/services/media_resolve.py` — no changes needed (already has search_games)
- `app/providers/tmdb.py` — no changes needed (already has search_movie, search_tv)
- `app/providers/anilist.py` — no changes needed (already has search_anime)

### Edge cases
- Long titles: truncate at 60 chars with "..."
- No release date: show year only, or omit date section in details
- No episode data: show "информация отсутствует"
- Multiple results: split into multiple messages if >12 buttons
- Game with no platforms: show "нет платформ"

### Testing
1. Test search for each type (movie/tv/anime/game)
2. Test adding each type to watchlist
3. Test watchlist display for each type
4. Test details button for each type
5. Test remove button
6. Test long titles
7. Test items with no dates/episode data
8. Test TV status display (Returning, Ended, Canceled)

### Why this approach
1. Single search flow for all types — no command memorization
2. Compact watchlist — easy to scan
3. Details on demand — no clutter
4. Grouped by type — logical organization
5. Uses existing APIs — no new integrations needed
6. Backward compatible — old /search and /searchgame can coexist during transition

## 18. LAST CHECKPOINT

Last checkpoint: 2026-09-27 (Phase 23 P0.1-P0.4 DONE, P1.1 IN PROGRESS)

Current state: Phase 22 DONE — Unified Game Entity. Phase 23 Steps 1-6 DONE — unified search, watchlist redesign, details handlers for all types. P0.1-P0.4 DONE. P1.1 IN PROGRESS — fixing anime season counting.

Last completed action: P0.4 DONE — added `display_title()` helper, updated all user-facing displays to use `title_ru` when available. Fixed "Already in list" bug — now checks UserWatchItem instead of just checking if item exists in DB.

Next exact action: P1.1 — Fix anime season counting. Currently filtering by name prefix to exclude crossovers/unrelated entries incorrectly grouped in Shikimori franchise. `relationKind` field doesn't exist in Shikimori API — need alternative approach.

## 19. PHASE 23 — COMPLETE STATUS

### P0 — Critical (Priority fixes)

#### P0.1: APScheduler misfire — ✅ DONE
- Added `misfire_grace_time=90, coalesce=True, max_instances=1` to scheduler job
- Added same to backup job
- Verified: no more "missed" warnings in logs, `poll scan done` every 2 minutes

#### P0.2: Anime franchises not polling episodes — ✅ DONE
- Created `_poll_anime_episodes()` function extracted from `poll_item`
- Updated `poll_due_items` to call both `_refresh_anime_season` and `_poll_anime_episodes` for anime franchises
- Record `next_check_at` in SourceState "anilist"
- Added anime branch to `tier_interval()` in `tiering.py`:
  - Next episode <24h → 1 hour
  - Season airing → 6 hours
  - FINISHED/announced → 24 hours

#### P0.3: Notification rules not created on search_add — ✅ DONE
- Added rule creation loop after `add_watch_item()` in `search_add` handler
- Updated `_default_rules_for("anime")` to include: `NEXT_EPISODE_AIRING`, `ALL_EPISODES_OUT`, `NEW_SEASON_ANNOUNCED`, `NEW_SEASON_STARTED`, `SEASON_START_DATE`

#### P0.4: Russian title display — ✅ DONE
- `MediaItem.title_ru` field already exists in model and DB (from initial migration)
- For anime, `title_ru` is populated from Shikimori `build_franchise_summary()` (Russian title of first season)
- Created `display_title(item)` helper in `app/bot/main.py:65-70`: returns `title_ru` if available, else `canonical_title_en`, else "Unknown"
- Updated ALL user-facing displays to use `display_title()`:
  - "✅ Добавлено" (search_add, ap callback)
  - "🗑 Удалено" (remove callback, /remove command)
  - "Уже в списке" (search_add anime)
  - Watchlist (tv, movie, anime, game categories)
  - Details handler (all types)
  - Notes handler
  - Events handler
  - Notification messages (polling loop)
  - /remove command
- For movies/TV/games: `title_ru` is NOT populated — shows English title (fallback)
- For anime: `title_ru` populated from Shikimori — shows Russian title

#### P0.5: "Already in list" bug after delete — ✅ DONE
- Bug: After deleting anime from watchlist, trying to re-add showed "Уже в списке"
- Root cause: Code checked `ExternalId` table (item exists in DB) instead of `UserWatchItem` (user tracks it)
- Fix: Changed check to query `UserWatchItem` table — only shows "Already in list" if user actually has it in watchlist
- File: `app/bot/main.py` (search_add anime branch, ~line 1508)

### P1 — Correctness & Consistency (IN PROGRESS)

#### P1.1: Seasons counted incorrectly — 🔄 IN PROGRESS
**Symptoms:**
- One Piece showed "4 seasons" (should be 1 continuous series)
- JJK showed "4 seasons" (actually correct: 3 released + 1 announced)
- Kusuriya showed "4 seasons" (should be 3)

**Root cause:** Shikimori groups ALL items into a single `franchise` field, including:
- Crossovers/unrelated anime (e.g., "Monsters: Ippyaku Sanjou Hiryuu Jigoku" incorrectly in One Piece franchise)
- TV specials (kind="tv_special")
- OVAs (kind="ova")
- Movies (kind="movie")
- Arcs treated as separate entries (e.g., "One Piece: Gyojin Tou-hen")

**Investigation:** Tested Shikimori GraphQL API — `relationKind` field does NOT exist on `Anime` type. Cannot use it for filtering.

**Solution implemented:**
1. Added `_extract_base_title()` — extracts base title from first TV/ONA item (main series)
2. Added `_name_matches_base()` — checks if item name starts with base title (handles "Season N", "Part N", "2", "3" suffixes)
3. Updated `get_seasons()` to filter by name prefix — excludes crossovers and unrelated entries
4. Still filters by `kind in {"tv", "ona"}` and `duration >= 15`

**Results after fix:**
- One Piece: 2 seasons (main series + Gyojin Tou-hen arc) — improved from 4, but Gyojin Tou-hen is an arc not a separate season
- JJK: 4 seasons — correct (Seasons 1-3 released, Season 4 announced)
- Kusuriya: 3 seasons — correct

**Remaining issue:** One Piece has no clear season divisions — it's one continuous TV series since 1999. "Gyojin Tou-hen" is an arc within the main series, not a separate season. Shikimori's data model doesn't support season divisions for One Piece. This is a known limitation.

**Files modified:** `app/providers/shikimori.py` (`get_seasons`, `_extract_base_title`, `_name_matches_base`)

#### P1.2: Unified anime status model — ❌ TODO
- Create `app/domain/anime_status.py` with `AnimeStatus` dataclass
- Rules: AniList priority over Shikimori
- Phase mapping: RELEASING→airing, HIATUS→hiatus, NOT_YET_RELEASED→upcoming/announced, FINISHED→finished
- `aired`: `episode - 1` when airing, `total` when finished, `episodesAired` from Shikimori
- `total`: AniList `episodes`, else Shikimori, else `None` (never 0)
- Create `fmt_dt_ru()` helper for consistent date formatting with correct day-of-week
- Replace all `dt.fromtimestamp()` without timezone

#### P1.3: Unified anime card format — ❌ TODO
- `format_anime_card(title_ru, title_romaji, status: AnimeStatus) -> str`
- Always same order, missing lines skipped
- Examples:
  - Airing (1 season): "Ван-Пис (One Piece) / 🎌 Аниме / Статус: 🟢 Выходит / Серии: 1179 из ? / Следующая: серия 1180 — вс, 27.09 в 03:30"
  - Airing (multi): "Магическая битва (Jujutsu Kaisen) / 🎌 Аниме / Статус: 🟢 Выходит / Сезон: 4 из 4 — Смертельная миграция. Часть 2 / Серии: 5 из 12 / Следующая: серия 6 — чт, 08.10 в 18:00"
  - Upcoming: "Монолог фармацевта (Kusuriya no Hitorigoto) / 🎌 Аниме / Статус: 🟡 Скоро старт / Сезон: 3 из 3 / Старт: пт, 02.10 в 17:00 (через 6 дн.) / Предыдущий сезон: 2 — завершён, 24 серии"
  - Announced: "Статус: 🟡 Анонсирован / Сезон: 4 из 4 — Смертельная миграция. Часть 2 / Старт: дата не объявлена / Предыдущий сезон: 3 — завершён, 12 серий"
  - Finished: "Созданный в Бездне (Made in Abyss) / 🎌 Аниме / Статус: ⚪ Завершено / Сезонов: 2, продолжение не анонсировано / Последний сезон: 12 из 12"
- Remove English season titles from card (only show in "Сезон" line)
- Use `AnimeStatus` in "✅ Added" message and notifications

#### P1.4: `_refresh_anime_season` issues — ❌ TODO
1. Season change ignored if AniList has no data (fresh announcement)
2. On season change, don't reset baseline AniList state
3. `"anilist_id": None` always written — write real id
4. Missing: `anons` with `start_at <= now` → immediate resync
5. Missing: `SEASON_START_DATE` event
6. Store `phase` and `start_at` in Shikimori state, not raw `current_status`

#### P1.5: AniList events (`events.py`) — ❌ TODO
- `_normalize_anilist_details`: add `"anilist_id"` and `"next_airing_at"` (timestamp), `total_episodes` without `or 0`
- `compare_anilist_states`: skip events if `anilist_id` differs, don't fire `ALL_EPISODES_OUT` when `total_episodes is None`
- `fingerprint()`: include `anilist_id` or `shiki_id` + episode number for episode events; `shiki_id` for season events
- Unified payload: `season_index`, `episode`, `airing_at` (timestamp), `shiki_id`, `anilist_id`

#### P1.6: `search_add` for anime — ❌ TODO (partially done: P0.5 fixed "Already in list")
- Don't fail if AniList returns no data (announcement)
- Use `_ensure_anime_franchise_item()` instead of `_ensure_anilist_item()`
- Search existing franchise by `shikimori_franchise` only (not cross join)
- If franchise exists but user doesn't track: add watch + rules, not "Already in list" ✅ (P0.5)
- "✅ Added" message via `AnimeStatus`

### P2 — Improvements

#### P2.1: Watchlist with status — ❌ TODO
- Show brief status from cached `SourceState` (no API calls)
- Example: "• Ван-Пис — выходит, след. серия вс 27.09"

#### P2.2: Card with fewer requests — ❌ TODO
- Use Shikimori state if <6h old, skip franchise re-fetch
- Remove first AniList call (for English title)

#### P2.3: Notification texts — ❌ TODO
- Create `format_event_text(event, item, status)` with Russian texts
- Events: `NEXT_EPISODE_AIRING`, `ALL_EPISODES_OUT`, `NEW_SEASON_ANNOUNCED`, `NEW_SEASON_STARTED`, `SEASON_START_DATE`

#### P2.4: Game release dates in details — ❌ TODO (BUG-15)
- Game details handler doesn't show release dates from `GamePlatform` table
- Should show: "IGDB ✅ (2020-03-10)", "STEAM ✅ (2022-12-07)", etc.
- Files: `app/bot/main.py` (game details handler)

#### P2.5: TV series episode count — ❌ TODO (BUG-12)
- TV series shows "Выпущено: 0 из 1" for trailers/specials
- Need to filter out special episodes (episode_number=0, type="special")
- Use Shikimori state if <6h old, skip franchise re-fetch
- Remove first AniList call (for English title)

#### P2.3: Notification texts — ❌ TODO
- Create `format_event_text(event, item, status)` with Russian texts
- Events: `NEXT_EPISODE_AIRING`, `ALL_EPISODES_OUT`, `NEW_SEASON_ANNOUNCED`, `NEW_SEASON_STARTED`, `SEASON_START_DATE`

#### P2.4: Minor fixes — ❌ TODO
- Move `from app.domain.events import DomainEvent` to top of `polling.py`
- `_refresh_anime_season` called per `UserWatchItem` — should poll once per item, distribute events to all subscribers (TODO for multi-user)

## 20. PHASE 23 STEP 6 — DETAILS HANDLER SUB-TASKS

### API Data Availability

**TMDb (movies/TV):**
- ✅ `runtime` — movie details
- ✅ `release_dates` — theatrical, digital dates
- ✅ `seasons` — TV season list
- ✅ `season_episodes` — episodes per season
- ✅ `next_episode_to_air` — TV next air date
- ✅ `status` — TV series status
- ✅ `first_air_date` — TV premiere
- ✅ `credits` — IMPLEMENTED (`get_movie_credits`, `get_tv_credits`)
- ✅ `watch/providers` — IMPLEMENTED (`get_movie_watch_providers`)

**AniList (anime):**
- ✅ `episodes` — total episodes
- ✅ `status` — RELEASING, FINISHED, etc.
- ✅ `nextAiringEpisode` — episode number + airingAt timestamp
- ✅ `seasonYear` — year only
- ✅ `format` — TV, MOVIE, ONA, etc.
- ✅ Current season number — via Shikimori franchise
- ✅ Season status — via Shikimori franchise
- ✅ Staff/credits — NOT available in basic query

**IGDB/Steam/PSN (games):**
- ✅ `first_release_date` — IGDB
- ✅ `release_date` — Steam
- ✅ `released` — PSN/RAWG
- ✅ Platform names from GamePlatform table
- ✅ Full title from MediaItem.canonical_title_en

### Sub-task 6.1: Movies (DONE)
**Final output:**
```
Название на русском (Year)
Title in English
Фильм
  Длительность: 120 мин
  Режиссёр: Name
  В ролях: Actor1, Actor2, Actor3

Даты:
  - Премьера в кинотеатрах: 2026-03-15
  - Цифровой релиз: не обьявлена
```

### Sub-task 6.2: TV Series (DONE)
**Final output:**
```
Название сериала (Year)
Series Name in English
Сериал
  Статус: Идёт
  Текущий сезон: 3 из 5
  Последняя серия: 5 из 8
  Премьера: 2023-03-10
  Следующая серия: 18.10.2026 (чт)
```

### Sub-task 6.3: Anime (DONE - but needs P0.4, P1.2-P1.6 fixes)
**Current output:**
```
Название (Year)
English Title
Аниме
  сезонов: N
  Статус: Выходит/Анонсирован/Завершён
  Следующая серия: YYYY-MM-DD (день)
  Серии сезона: X из Y
```

**Target output (after P1.2-P1.6):**
```
Название (Romaji)
🎌 Аниме
Статус: 🟢 Выходит / 🟡 Скоро старт / ⚪ Завершено
Сезон: N из M — Название части (если есть)
Серии: X из Y
Следующая: серия N — пн, 27.09 в 03:30
```

### Sub-task 6.4: Games (TODO)
**Target output:**
```
Full Game Title Here
Игра

Платформы:
  Steam ⌨️ - 19.05.2015 ✅
  IGDB 🕹️ - 19.05.2015 ✅
  PSN 🎮 - 15.08.2016 ⬜
```

## 21. KEY FILES (Detailed)

### `app/bot/main.py` (~2122 lines)
**Purpose:** Main Telegram bot handlers, keyboard definitions, scheduler setup, details handlers.

**Key sections:**
- Lines 1-60: Imports, `display_title()` helper (new), `db()` session manager
- Lines 65-250: `_ensure_*_item()` functions — create MediaItem from API responses (movie, tv, anime, game)
- Lines 250-400: `_resolve_media_for_add()` — resolve TMDb/AniList/IGDB/Steam/PSN IDs to MediaItem
- Lines 405-550: `_perform_add_flow()` — shared /add flow (duplicate check, release confirmation)
- Lines 550-800: `/add` handler — main add flow with service picker
- Lines 800-1000: Inline search handlers (`/search` text, type selection, add from search)
- Lines 1000-1400: Watchlist handlers (`/watchlist`, remove callback, details callback)
- Lines 1400-1600: `search_add` handler — add from inline search results (movie/tv/anime/game branches)
- Lines 1600-1800: Details handler — show full info for movie/tv/anime/game
- Lines 1800-2000: Notes handlers (`/note`, `/notes`), events handler (`/events`)
- Lines 2000-2122: `_poll_due_items()` — adaptive polling loop, notification dispatch

**Recent changes (Phase 23):**
- Added `display_title()` helper (line 65-70)
- Updated all title displays to use `display_title()`
- Fixed "Already in list" bug in anime search_add (line ~1508) — now checks UserWatchItem

### `app/providers/shikimori.py` (~303 lines)
**Purpose:** Shikimori GraphQL API client for anime search, franchise grouping, season selection.

**Key sections:**
- Lines 1-30: Imports, constants (`SEASON_KINDS`, `MIN_SEASON_DURATION`)
- Lines 35-40: `FranchiseSummary` dataclass
- Lines 42-90: `get_seasons()`, `_extract_base_title()`, `_name_matches_base()` — season filtering (NEW)
- Lines 92-110: `pick_current_season()` — select current/ongoing season from franchise
- Lines 112-130: `get_total_seasons()` — count seasons
- Lines 132-150: `_aired_date()` — extract aired date from item
- Lines 152-260: `ShikimoriClient` class — GraphQL client with throttling
- Lines 260-290: `search_anime()` — search by name
- Lines 292-310: `get_by_id()` — get single anime by ID
- Lines 312-350: `get_franchise()` — get all items in franchise
- Lines 352-380: `build_franchise_summary()` — build summary from franchise data

**Recent changes (Phase 23 P1.1):**
- Added `_extract_base_title()` and `_name_matches_base()` for name-based filtering
- Updated `get_seasons()` to filter by name prefix — excludes crossovers

**GraphQL queries:**
- Search: `animes(search: $search)` — returns id, name, russian, english, kind, status, episodes, episodesAired, nextEpisodeAt, airedOn, franchise
- By ID: `animes(ids: $ids)` — same fields + duration
- Franchise: `animes(franchise: $franchise)` — same fields, paginated

**Important:** Shikimori API does NOT have `relationKind` field. Cannot filter by relation type.

### `app/providers/anilist.py`
**Purpose:** AniList GraphQL API client for anime airing schedules.

**Key queries:**
- `BY_MAL_QUERY` — fetch anime by MAL ID (used with Shikimori MAL ID)
- Returns: title, status, episodes, nextAiringEpisode, seasonYear, coverImage

### `app/scheduler/polling.py`
**Purpose:** Adaptive polling — checks watchlist items at per-item intervals.

**Key functions:**
- `poll_due_items()` — scan due items, distribute TMDb calls
- `poll_item()` — poll single item, detect state changes, fire events
- `_refresh_anime_season()` — refresh anime season from Shikimori + AniList
- `_poll_anime_episodes()` — poll anime episodes from AniList (NEW, P0.2)
- `_earliest_theatrical_date()`, `_earliest_digital_date()` — helper for movie dates

### `app/scheduler/tiering.py`
**Purpose:** Compute polling interval per item based on state.

**Key function:**
- `tier_interval(item_type, state)` — returns seconds until next check
- Anime branch: next episode <24h → 1h, airing → 6h, finished/announced → 24h

### `app/database/models.py` (~210 lines)
**Purpose:** SQLAlchemy ORM models.

**Key models:**
- `User` — Telegram user (id, telegram_user_id, username, timezone)
- `MediaItem` — core entity (id, media_type, canonical_title_en, title_ru, year, description, poster_url, backdrop_url)
- `ExternalId` — external IDs per item (media_item_id, source, external_id)
- `SourceState` — cached state per item (media_item_id, source, state, details, next_check_at)
- `UserWatchItem` — user's watchlist (user_id, media_item_id, added_at)
- `NotificationRule` — notification preferences (user_id, media_item_id, event_type, enabled)
- `ReleaseEvent` — detected events (media_item_id, event_type, payload, created_at)
- `Note` — user notes (user_id, media_item_id, note_text, updated_at)
- `Tag` — tags (id, name)
- `UserTag` — user-tagged items (user_id, media_item_id, tag_id)
- `GamePlatform` — platform release info (media_item_id, platform, platform_id, release_date, store_url)

### `app/services/watchlist.py`
**Purpose:** Watchlist CRUD operations.

**Key functions:**
- `add_watch_item(session, user_id, media_item_id)` — add to watchlist
- `remove_watch_item(session, user_id, media_item_id)` — remove from watchlist
- `list_watch_items(session, user_id)` — list with pagination
- `get_watch_item(session, user_id, media_item_id)` — get single item

### `app/domain/events.py`
**Purpose:** Domain event detection — compares states, fires events.

**Key functions:**
- `DomainEvent` — event dataclass (event_type, payload, timestamp)
- `compare_tmdb_states()` — detect movie/TV events
- `compare_anilist_states()` — detect anime events
- `compare_igdb_states()` — detect game events
- `fingerprint()` — dedup key for events

### `app/services/media_resolve.py`
**Purpose:** Resolve titles to MediaItems — search, dedup, title matching.

**Key functions:**
- `add_game_to_watchlist()` — add game from platforms
- `get_game_platforms()` — get platforms for item
- `get_user_tracked_platforms()` — get user's tracked platforms
- `search_and_resolve()` — search across all providers

### `migrations/versions/`
**Purpose:** Alembic database migrations.

**Current migrations:**
- `11f3f12cf425_initial_schema.py` — initial schema (all tables)
- `a7c3e91f2d48_phase_75_source_states_next_check_at.py` — added next_check_at to source_states

**Migration command:** `alembic upgrade head` (run inside Docker container)

### `Dockerfile`
**Purpose:** Docker image for bot.

**Base:** python:3.12-slim
**Dependencies:** installs from pyproject.toml
**Entry:** `python -m app.bot.main`
**Volume:** `/app/data` — persists SQLite database

### `.env`
**Purpose:** Environment variables.

**Key vars:**
- `BOT_TOKEN` — Telegram bot token
- `TMDb_BASE_URL`, `TMDb_KEY` — TMDb API
- `ANILIST_GRAPHQL_URL` — AniList GraphQL endpoint
- `SHIKIMORI_BASE_URL`, `SHIKIMORI_USER_AGENT` — Shikimori API
- `IGDB_CLIENT_ID`, `IGDB_CLIENT_SECRET` — IGDB API
- `STEAM_API_KEY` — Steam API
- `PSN_CLIENT_ID`, `PSN_CLIENT_SECRET` — PSN API
- `DATABASE_URL` — SQLite file path
- `BOT_TIMEZONE` — user timezone (default: Asia/Jerusalem)
- `ALLOWED_USER_IDS` — comma-separated Telegram user IDs

## 17. END-OF-SESSION VERIFICATION PROCEDURE

At the END of EVERY work session (before telling the user the task is done), perform these steps:

1. Stop all current bot processes:
   `Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*app.bot.main*' } | ForEach-Object { Stop-Process -Id $_.ProcessId }`

2. Restart the bot:
   ```
   cd E:\LocalAI\Bionic\Telegram-bot
   .venv\Scripts\Activate.ps1
   python -m app.bot.main
   ```

3. Watch console output for 10-15 seconds after startup — ensure no tracebacks or errors.

4. Tell the user the bot has been restarted and is ready for testing. Ask them to manually send test messages/commands related to what was changed in this session.

5. If NO error notification arrived in Telegram during testing AND no tracebacks in console — the session is considered successfully completed.
   If an error arrived — debug and fix it before marking the session as complete.

This procedure must be followed at the end of EVERY session, not just this one.
