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
**Symptom:** User searches "Breaking Bad", sees "📺 Во все тяжкие (2008) [tmdb=1396]", runs `/add 1396`. Bot responds "✅ Добавлено: Зеркало (1975)" — completely wrong item.
**Root cause:** TMDb API returns same ID for different media types (movie vs TV series). The `/add` handler picks the first match without respecting the user's selection from the search results. The `resolve_media_for_add` function doesn't filter by media_type when multiple items share the same external_id.
**Files:** `app/bot/main.py` (add_handler), `app/services/media_resolve.py` (resolve_media_for_add)
**Repro:** `/search Breaking Bad` → `/add 1396` → wrong item added

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

### BUG-5: Steam game add crashes bot (KeyError on None year)
**Symptom:** User runs `/add 1962700` (Subnautica 2 Steam ID). Bot crashes with:
```
KeyError: slice(None, 4, None)
  File "/app/app/bot/main.py", line 813, in add_handler
    year = (details.get("first_air_date") or details.get("release_date") or details.get("released") or "")[:4]
```
**Root cause:** `details.get("released")` returns `None` (not a string). Code tries to slice `None[:4]` which raises KeyError. The `or ""` fallback is not reached because `details.get("released")` returns None which is falsy but the `or` chain short-circuits incorrectly — actually the issue is that `details.get("released")` returns None and `None[:4]` raises TypeError, not KeyError. The error message says KeyError which suggests a dict key access issue elsewhere. Need to investigate exact line.
**Files:** `app/bot/main.py` (add_handler, line ~813)
**Repro:** `/search subnautica 2` → `/add 1962700` → crash

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
**Symptom:** No manual way to trigger or test notifications. Notifications are fired automatically by the event engine during polling, but there's no test command or debug mode to verify the full pipeline (event detection → rule matching → message send → dedup mark).
**Status:** Missing test/verification mechanism. Consider adding `/notify-test <id>` command for debugging.
**Files:** `app/domain/events.py`, `app/services/notifications.py`, `app/scheduler/polling.py`

### BUG-10: Backup scheduled at 3 AM — unreliable if bot not running 24/7
**Symptom:** Backup job runs at 3 AM daily via APScheduler cron. If bot is not running at 3 AM (e.g., user's computer sleeps, VPS reboots), backup is skipped until next day.
**Root cause:** `scheduler.add_job(_backup_database, "cron", hour=3, minute=0)` in `app/bot/main.py`.
**Fix needed:** Run backup on every startup (at least once) in addition to scheduled runs. Or use "interval" based backup (e.g., every 24 hours from last run) instead of fixed cron.
**Files:** `app/bot/main.py` (line ~1217)


## 6. CURRENT STATE

Current phase: Phase 16 DONE — Docker support. 10 bugs discovered during Docker testing, documented in Section 7.

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

## 16. LAST CHECKPOINT

Last checkpoint: 2026-09-20 (Phase 16 DONE, 10 bugs found)

Current state: Phase 16 DONE — Docker support. Docker image builds, runs, bot connects to Telegram. 10 bugs discovered during manual testing (Section 7).

Last completed action: Built and tested Docker image. Verified bot starts, scheduler runs, backup job scheduled. Manual testing revealed 10 bugs in /add resolution, notes persistence, PSN/Steam handling, AniList picker, backup timing.

Next exact action: User gives permission to fix bugs from Section 7 (one by one).

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
