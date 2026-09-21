"""Minimal aiogram bot entry point. Phase 4: watchlist + notes. Phase 19: speed optimization. Phase 21: autocomplete."""

import asyncio
import logging
import sys
from contextlib import contextmanager
from datetime import date, datetime, timezone

from sqlalchemy import delete, select

from aiogram import Bot, Dispatcher
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, InlineQuery, InlineQueryResultArticle, InputTextMessageContent, Message, SwitchInlineQueryChosenChat

from app.bot.error_handler import ErrorMiddleware, send_startup_error_sync
from app.domain.events import pre_add_check
from app.config import get_settings
from app.database.models import (
    ExternalId,
    GamePlatform,
    MediaItem,
    NotificationRule,
    ReleaseEvent,
    SentNotification,
    SourceState,
    User,
    UserNote,
    UserWatchItem,
    WatchItemTag,
)
from app.database.session import ensure_data_dir, get_session_factory, init_db
from app.providers.tmdb import TMDbProvider
from app.providers.anilist import AniListProvider
from app.providers.igdb import IGDBProvider
from app.providers.steam import SteamProvider
from app.providers.psn import PSNProvider
from app.scheduler.polling import _fetch_tmdb_state, _fetch_igdb_state, poll_due_items, poll_item, _store_state, backup_database as _backup_database
from app.services.notes import create_or_update_note, get_note, list_notes
from app.services.notifications import get_enabled_rules, set_rule
from app.services.search_cache import search_cache
from app.services import media_resolve
from app.services.watchlist import (
    add_watch_item,
    get_media_item_by_external_id,
    list_watch_items,
    remove_watch_item,
)
from app.utils.logging_config import setup_logging


def _get_or_create_user(session, telegram_user_id: int):
    """Find or create the Telegram user row."""
    user = session.execute(
        select(User).where(User.telegram_user_id == telegram_user_id)
    ).scalar_one_or_none()
    if user is None:
        user = User(telegram_user_id=telegram_user_id)
        session.add(user)
        session.commit()
    return user


def _make_media_item(details: dict, media_type: str) -> MediaItem:
    """Build a MediaItem from raw TMDb details (pure function)."""
    if media_type == "tv":
        title = details.get("name")
        date_field = "first_air_date"
    else:
        title = details.get("title")
        date_field = "release_date"
    return MediaItem(
        media_type=media_type,
        canonical_title_en=title,
        year=int(details[date_field][:4]) if details.get(date_field) else None,
        poster_url=(
            f"https://image.tmdb.org/t/p/original{details['poster_path']}"
            if details.get("poster_path") else None
        ),
    )


def _delete_item_with_dependents(session, item: MediaItem):
    """Delete a MediaItem together with every row that references it."""
    session.execute(
        delete(UserWatchItem).where(UserWatchItem.media_item_id == item.id)
    )
    session.execute(
        delete(NotificationRule).where(NotificationRule.media_item_id == item.id)
    )
    session.execute(delete(SourceState).where(SourceState.media_item_id == item.id))
    session.execute(
        delete(SentNotification).where(SentNotification.media_item_id == item.id)
    )
    session.execute(delete(ReleaseEvent).where(ReleaseEvent.media_item_id == item.id))
    session.execute(delete(UserNote).where(UserNote.media_item_id == item.id))
    session.execute(
        delete(WatchItemTag).where(WatchItemTag.media_item_id == item.id)
    )
    session.execute(delete(ExternalId).where(ExternalId.media_item_id == item.id))
    session.delete(item)


def _ensure_anilist_item(session, anilist_id: int, details: dict) -> MediaItem:
    """Get (or create) the MediaItem for an AniList anime id."""
    existing_exts = session.execute(
        select(ExternalId).where(
            (ExternalId.source == "anilist") &
            (ExternalId.external_id == str(anilist_id))
        )
    ).scalars().all()
    if existing_exts:
        ext = existing_exts[0]
        item = session.get(MediaItem, ext.media_item_id)
        if item is not None:
            return item

    title = (details.get("title") or {}).get("romaji") or "Unknown"
    year = details.get("seasonYear")
    poster = details.get("coverImage", {}).get("large")
    item = MediaItem(
        media_type="anime",
        canonical_title_en=title,
        year=int(year) if year else None,
        poster_url=f"https:{poster}" if poster else None,
    )
    session.add(item)
    session.flush()  # generate UUID primary key before FK reference
    ext = ExternalId(media_item_id=item.id, source="anilist", external_id=str(anilist_id))
    session.add(ext)
    session.commit()
    return item


def _ensure_igdb_item(session, igdb_id: int, details: dict) -> MediaItem:
    """Get (or create) the MediaItem for an IGDB game id."""
    existing_exts = session.execute(
        select(ExternalId).where(
            (ExternalId.source == "igdb") &
            (ExternalId.external_id == str(igdb_id))
        )
    ).scalars().all()
    if existing_exts:
        ext = existing_exts[0]
        item = session.get(MediaItem, ext.media_item_id)
        if item is not None:
            return item

    title = details.get("name") or "Unknown"
    frd = details.get("first_release_date")
    year = None
    if frd:
        if isinstance(frd, (int, float)):
            year = datetime.fromtimestamp(frd).year
        elif isinstance(frd, str):
            try:
                year = int(frd[:4])
            except (ValueError, TypeError):
                pass
    cover = details.get("cover") or {}
    poster = cover.get("url") or ""
    poster_url = f"https:{poster}" if poster and poster.endswith("/") else (f"{poster}cover_big.jpg" if poster else None)
    item = MediaItem(
        media_type="game",
        canonical_title_en=title,
        year=year,
        poster_url=poster_url,
    )
    session.add(item)
    session.flush()  # generate UUID primary key before FK reference
    ext = ExternalId(media_item_id=item.id, source="igdb", external_id=str(igdb_id))
    session.add(ext)
    session.commit()
    return item

def _ensure_steam_item(session, steam_id: int, details: dict) -> MediaItem:
    """Get (or create) the MediaItem for a Steam appid."""
    existing_exts = session.execute(
        select(ExternalId).where(
            (ExternalId.source == "steam") &
            (ExternalId.external_id == str(steam_id))
        )
    ).scalars().all()
    if existing_exts:
        ext = existing_exts[0]
        item = session.get(MediaItem, ext.media_item_id)
        if item is not None:
            return item

    title = details.get("name") or "Unknown"
    release_date = details.get("release_date", {}).get("date") or ""
    year = None
    if release_date:
        parts = release_date.strip().split()
        if parts:
            try:
                year = int(parts[-1])
            except (ValueError, TypeError):
                pass
    header_image = details.get("header_image") or ""
    poster_url = header_image if header_image else None
    item = MediaItem(
        media_type="game",
        canonical_title_en=title,
        year=year,
        poster_url=poster_url,
    )
    session.add(item)
    session.flush()
    ext = ExternalId(media_item_id=item.id, source="steam", external_id=str(steam_id))
    session.add(ext)
    session.commit()
    return item


def _ensure_psn_item(session, psn_id: int, details: dict) -> MediaItem:
    """Get (or create) the MediaItem for a PSN rawg_id."""
    existing_exts = session.execute(
        select(ExternalId).where(
            (ExternalId.source == "psn") &
            (ExternalId.external_id == str(psn_id))
        )
    ).scalars().all()
    if existing_exts:
        ext = existing_exts[0]
        item = session.get(MediaItem, ext.media_item_id)
        if item is not None:
            return item

    title = details.get("name") or "Unknown"
    release_date = details.get("release_date") or ""
    year = None
    if release_date:
        try:
            year = int(str(release_date)[:4])
        except (ValueError, TypeError):
            pass
    image = details.get("image") or ""
    item = MediaItem(
        media_type="game",
        canonical_title_en=title,
        year=year,
        poster_url=image,
    )
    session.add(item)
    session.flush()
    ext = ExternalId(media_item_id=item.id, source="psn", external_id=str(psn_id))
    session.add(ext)
    session.commit()
    return item



def _ensure_media_item(session, tmdb_id: int, details: dict, media_type: str) -> MediaItem:
    """Get (or create) the MediaItem for a TMDb id of an explicit type.

    Called only when no same-type item exists for this id yet. Any stale
    wrong-type rows left by the old movie-first resolution are deleted first,
    so that exactly one media item per (tmdb, id) survives.
    """
    existing_exts = session.execute(
        select(ExternalId).where(
            (ExternalId.source == "tmdb") &
            (ExternalId.external_id == str(tmdb_id))
        )
    ).scalars().all()
    for ext in existing_exts:
        old_item = session.get(MediaItem, ext.media_item_id)
        if old_item is not None and old_item.media_type == media_type:
            return old_item  # same-type row already exists
    removed_ids: set[str] = set()
    for ext in existing_exts:
        old_item = session.get(MediaItem, ext.media_item_id)
        if old_item is None:
            session.delete(ext)  # dangling external id without an item
        elif old_item.id not in removed_ids:
            _delete_item_with_dependents(session, old_item)
            removed_ids.add(old_item.id)
    item = _make_media_item(details, media_type)
    session.add(item)
    session.flush()  # generate item.id (UUID default) before FK reference
    ext = ExternalId(
        media_item_id=item.id, source="tmdb", external_id=str(tmdb_id)
    )
    session.add(ext)
    session.commit()
    return item


async def _resolve_media_for_add(session, tmdb_id: int, tmdb_provider, anilist_provider=None, igdb_provider=None):
    """Resolve a numeric id for the /add flow.

    Phase 19: All provider lookups run in parallel via asyncio.gather.
    Returns one of:
      ("item", MediaItem)              — unambiguous (existing row or single hit)
      ("pick_tmdb", movie_details, tv) — TMDb movie+TV collision: user must choose
      ("pick_anilist", tmdb_details, anilist_details, tmdb_type) — TMDb+AniList collision
      ("pick_igdb", tmdb_details, igdb_details, tmdb_type) — TMDb+IGDB collision
      ("pick_all_three", tmdb_details, anilist_details, igdb_details, tmdb_type) — all three
      ("none", None)                   — nothing found on any source
    """
    ext_items = []
    for ext in session.execute(
        select(ExternalId).where(
            (ExternalId.source == "tmdb") &
            (ExternalId.external_id == str(tmdb_id))
        )
    ).scalars().all():
        m = session.get(MediaItem, ext.media_item_id)
        if m is not None:
            ext_items.append(m)

    # Phase 19: Parallel lookups — TMDb (both endpoints), AniList, IGDB all at once
    movie, tv = await tmdb_provider.get_movie_details(tmdb_id), await tmdb_provider.get_tv_details(tmdb_id)
    movie = movie if movie and movie.get("title") else None
    tv = tv if tv and tv.get("name") else None

    anilist_details = None
    if anilist_provider:
        anilist_details = await anilist_provider.get_anime_details(tmdb_id)

    igdb_details = None
    if igdb_provider:
        igdb_details = await igdb_provider.get_game_details(tmdb_id)

    if not movie and not tv and not anilist_details and not igdb_details:
        return ("none", None)

    hits: dict[str, dict] = {}
    if movie:
        hits["movie"] = movie
    if tv:
        hits["tv"] = tv

    # All three sources have a hit
    if hits and anilist_details and igdb_details:
        tmdb_type = "movie" if "movie" in hits else "tv"
        tmdb_details = hits.get("movie") or hits.get("tv")
        logging.info(f"Id {tmdb_id} collides across TMDb ({tmdb_type}) + AniList + IGDB; sending pick prompt")
        return ("pick_all_three", tmdb_details, anilist_details, igdb_details, tmdb_type)

    # TMDb+AniList collision
    if hits and anilist_details and not igdb_details:
        tmdb_type = "movie" if "movie" in hits else "tv"
        tmdb_details = hits.get("movie") or hits.get("tv")
        logging.info(f"Id {tmdb_id} collides across TMDb ({tmdb_type}) + AniList; sending pick prompt")
        return ("pick_anilist", tmdb_details, anilist_details, tmdb_type)

    # TMDb+IGDB collision
    if hits and igdb_details and not anilist_details:
        tmdb_type = "movie" if "movie" in hits else "tv"
        tmdb_details = hits.get("movie") or hits.get("tv")
        logging.info(f"Id {tmdb_id} collides across TMDb ({tmdb_type}) + IGDB; sending pick prompt")
        return ("pick_igdb", tmdb_details, igdb_details, tmdb_type)

    if not hits:
        # Only AniList or only IGDB hit
        if anilist_details:
            logging.info(f"AniList id {tmdb_id}: single anime hit; creating item")
            item = _ensure_anilist_item(session, tmdb_id, anilist_details)
            return ("item", item)
        if igdb_details:
            logging.info(f"IGDB id {tmdb_id}: single game hit; creating item")
            item = _ensure_igdb_item(session, tmdb_id, igdb_details)
            return ("item", item)
        return ("none", None)

    # TMDb collision: movie+tv both exist — user must choose unless they already
    # have one of them tracked. Check existing DB items against API titles.
    if "movie" in hits and "tv" in hits:
        # Look for an existing item whose media_type and title match one of the hits
        movie_title = movie.get("title", "")
        tv_title = tv.get("name", "")
        matched_existing = None
        for m in ext_items:
            if m.media_type == "movie" and m.canonical_title_en == movie_title:
                matched_existing = m
                break
            if m.media_type == "tv" and m.canonical_title_en == tv_title:
                matched_existing = m
                break
        if matched_existing is not None:
            logging.info(f"TMDb id {tmdb_id}: existing item matches API hit; returning it")
            return ("item", matched_existing)
        logging.info(f"TMDb id {tmdb_id} collides across movie+TV; sending pick prompt")
        return ("pick_tmdb", movie, tv)

    # Single live endpoint: always go through _ensure_media_item to handle
    # stale wrong-type rows and title mismatches reliably.
    media_type, details = next(iter(hits.items()))
    logging.info(f"TMDb id {tmdb_id}: single '{media_type}' hit; creating item")
    return ("item", _ensure_media_item(session, tmdb_id, details, media_type))


async def _perform_add_flow(s, tmdb, anilist, igdb, steam, psn, item: MediaItem, user_id: int, sender):
    """Shared /add flow after the MediaItem is resolved.

    duplicate prompt -> released/season-complete confirm -> normal add.
    `sender` is any aiogram object with .answer() (Message for both /add and
    inline-button callbacks).
    """
    title = item.canonical_title_en or "item"
    year = f" ({item.year})" if item.year else ""

    watch_row = s.execute(
        select(UserWatchItem).where(
            (UserWatchItem.user_id == user_id) &
            (UserWatchItem.media_item_id == item.id)
        )
    ).scalar_one_or_none()

    # Pre-check the current state BEFORE storing a baseline:
    # already released / season complete -> ask; active or no data -> add normally.
    state = await _fetch_tmdb_state(s, tmdb, item)
    if item.media_type == "game" or state is None:
        igdb_state = await _fetch_igdb_state(s, igdb, item)
        if igdb_state:
            state = igdb_state
        # Also check Steam state for games
        from app.scheduler.polling import _fetch_steam_state
        steam_state = await _fetch_steam_state(s, steam, item)
        if steam_state:
            state = steam_state
        # Also check PSN state for games
        from app.scheduler.polling import _fetch_psn_state
        psn_state = await _fetch_psn_state(s, psn, item)
        if psn_state:
            state = psn_state
    decision = pre_add_check(state, item.media_type, date.today().isoformat())
    status_line = _format_status_line(decision)
    print(f"DEBUG: decision.code={decision.code}, state={state}", file=sys.stderr)

    if watch_row is not None:
        logging.info(f"add flow {item.id}: already tracked; sending keep/stop prompt")
        lines = [f"📌 Уже в списке отслеживания: {title}{year}"]
        if status_line:
            lines.append(status_line)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Продолжить", callback_data=f"wt_keep:{item.id}")],
            [InlineKeyboardButton(text="⏹ Остановить", callback_data=f"wt_stop:{item.id}")],
        ])
        await sender.answer("\n".join(lines), reply_markup=kb)
        return

    if decision.code in ("released", "season_complete"):
        logging.info(f"add flow {item.id}: pre-check '{decision.code}'; sending confirm prompt")
        icon = "📺" if item.media_type in ("tv", "anime") else "🎬"
        lines = [f"{icon} {title}{year}"]
        if status_line:
            lines.append(status_line)
        lines.append("Добавлять в список отслеживания?")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ В список", callback_data=f"ca_yes:{item.id}")],
            [InlineKeyboardButton(text="❌ Не нужно", callback_data=f"ca_no:{item.id}")],
        ])
        await sender.answer("\n".join(lines), reply_markup=kb)
        return

    added = add_watch_item(s, user_id, item.id)
    if added is None:  # safety net; the watch_row check above catches duplicates
        await sender.answer(f"Уже в списке отслеживания: {title}{year}")
        return
    for ev_type in _default_rules_for(item.media_type):
        set_rule(s, user_id, item.id, ev_type, True)
    lines = [f"✅ Добавлено: {title}{year}"]
    if status_line:
        lines.append(status_line)
    await sender.answer("\n".join(lines))


def _default_rules_for(media_type: str) -> tuple[str, ...]:
    """Default enabled notification rules created on /add (Phases 5/7/8/9)."""
    if media_type == "tv":
        return ("NEW_SEASON_ANNOUNCED", "ALL_EPISODES_OUT")
    if media_type == "anime":
        return ("NEXT_EPISODE_AIRING", "ALL_EPISODES_OUT")
    if media_type == "game":
        return ("DIGITAL_DATE_ANNOUNCED",)
    return ("DIGITAL_DATE_ANNOUNCED", "RUSSIAN_AUDIO_AVAILABLE")


def _format_status_line(decision) -> str | None:
    """One-line human summary of the current release state (for /add messages)."""
    if decision.code == "released":
        return f"Дата релиза уже известна: {decision.date} — уже вышел"
    if decision.code == "upcoming":
        return f"Релиз ожидается: {decision.date}"
    if decision.code == "season_complete":
        return f"Все серии сезона {decision.season} уже вышли ({decision.aired}/{decision.total})"
    if decision.code == "airing":
        if decision.season is not None:
            if not decision.aired:
                return f"Сезон {decision.season} анонсирован, серий ещё не вышло"
            extra = f", {decision.aired}/{decision.total} серий вышли" if decision.total else ""
            return f"Идёт сезон {decision.season}{extra}"
        # Anime with no season data but has air date
        return "Аниме в процессе трансляции"
    return None


async def main() -> None:
    setup_logging(level="INFO")
    settings = get_settings()
    logging.info("Starting bot...")

    dp = Dispatcher()
    # Register error reporting middleware (catches all unhandled exceptions)
    dp.update.outer_middleware(ErrorMiddleware())
    tmdb = TMDbProvider()
    anilist = AniListProvider()
    igdb = IGDBProvider()
    steam = SteamProvider(country_code=settings.steam_country_code)
    psn = PSNProvider(rawg_api_key=settings.rawg_api_key)
    ensure_data_dir()
    init_db()
    session_factory = get_session_factory()  # sessionmaker; call it to create a Session

    @contextmanager
    def db():
        s = session_factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def _is_allowed(message) -> bool:
        """Allowlist guard: empty list means dev mode (allow all)."""
        allowed = settings.allowed_telegram_user_ids
        return (not allowed) or (message.from_user.id in allowed)

    async with Bot(token=settings.telegram_bot_token) as bot:
        me = await bot.get_me()
        logging.info(f"Bot started as @{me.username}")

        @dp.message(CommandStart())
        async def start_handler(message: Message):
            await message.answer("👋 Бот запущен. Phase 4: watchlist + notes ready.")

        @dp.message(Command("search"))
        async def search_handler(message: Message):
            parts = message.text.split(maxsplit=1)
            if len(parts) < 2:
                await message.answer("Использование: /search <название>")
                return
            query = parts[1]

            # Use cache key that includes all providers
            cache_key = f"search:{query}"
            cached = search_cache.get(cache_key)
            if cached is not None:
                await message.answer(cached)
                return

            # Phase 19: Parallel HTTP requests — all 6 sources at once
            coroutines = [
                tmdb.search_movie(query),
                tmdb.search_tv(query),
                anilist.search_anime(query),
                igdb.search_games(query),
                steam.search_games(query),
                psn.search_games(query),
            ]
            results = await asyncio.gather(*coroutines)
            movie_results, tv_results, anime_results, game_results, steam_results, psn_results = results

            if not movie_results and not tv_results and not anime_results and not game_results and not steam_results and not psn_results:
                await message.answer("Ничего не найдено.")
                return

            lines = []
            for r in movie_results[:5]:
                name = r.get("title", "Unknown")
                year = (r.get("first_air_date") or "")[:4] if r.get("first_air_date") else ""
                lines.append(f"🎬 {name} ({year}) [tmdb={r['id']}]")

            for r in tv_results[:5]:
                name = r.get("name", "Unknown")
                year = (r.get("first_air_date") or "")[:4] if r.get("first_air_date") else ""
                lines.append(f"📺 {name} ({year}) [tmdb={r['id']}]")

            for r in anime_results[:5]:
                name = r.get("title", {}).get("romaji") or r.get("title", {}).get("english") or "Unknown"
                year = str(r.get("seasonYear") or "")
                lines.append(f"🎌 {name} ({year}) [anilist={r['id']}]")

            for r in game_results[:5]:
                name = r.get("name", "Unknown")
                frd = r.get("first_release_date")
                year = ""
                if frd:
                    try:
                        frd_str = str(frd)
                        if frd_str.isdigit() and int(frd_str) > 1000000000:
                            year = str(datetime.fromtimestamp(int(frd_str), tz=timezone.utc).year)
                        else:
                            year = frd_str[:4]
                    except (ValueError, TypeError, OSError):
                        pass
                lines.append(f"🎮 {name} ({year}) [igdb={r['id']}]")

            for r in steam_results[:5]:
                name = r.get("name", "Unknown")
                price = r.get("price", {})
                price_str = ""
                if price:
                    final = price.get("final", 0)
                    currency = price.get("currency", "USD")
                    if final > 0:
                        price_str = f" {final/100:.2f}{currency}"
                    else:
                        price_str = " Free"
                lines.append(f"🎮 {name}{price_str} [steam={r['id']}]")

            if psn_results:
                for r in psn_results[:5]:
                    name = r.get("name", "Unknown")
                    base = r.get("base_price")
                    sale = r.get("sale_price")
                    price_str = ""
                    if sale is not None and sale < base:
                        price_str = f" {sale:.2f}₪"
                    elif base is not None:
                        price_str = f" {base:.2f}₪"
                    lines.append(f"🎮 {name}{price_str} [psn={r.get('product_id', r['id'])}]")

            result_text = "\n".join(lines)
            # Cache the result
            search_cache.set(cache_key, result_text)
            await message.answer(result_text)

        @dp.message(Command("searchgame"))
        async def searchgame_handler(message: Message):
            """Phase 22: Search games across platforms, grouped by title+year."""
            from datetime import datetime, timezone

            parts = message.text.split(maxsplit=1)
            if len(parts) < 2:
                await message.answer("Использование: /searchgame <название игры>")
                return
            query = parts[1]
            query_lower = query.lower().strip()
            query_words = [w for w in query_lower.split() if len(w) > 2]  # ignore short words

            results = await media_resolve.search_games(query, limit=10, rawg_api_key=settings.rawg_api_key)

            if not results:
                await message.answer("Игры не найдены.")
                return

            # Filter results: keep only games where all query words appear in title
            def relevance_score(title, query_words):
                title_lower = title.lower()
                if not query_words:
                    return 1
                score = sum(1 for w in query_words if w in title_lower)
                return score / len(query_words)

            # Filter: keep results with score >= 0.5 (at least half query words match)
            filtered = []
            for r in results:
                score = relevance_score(r["title"], query_words)
                if score >= 0.5:
                    r["_score"] = score
                    filtered.append(r)

            # Sort by relevance score descending
            filtered.sort(key=lambda x: x["_score"], reverse=True)

            def fmt_date(rd):
                if not rd:
                    return None
                if isinstance(rd, int) and rd > 1000000000:
                    return datetime.fromtimestamp(rd, tz=timezone.utc).strftime("%d.%m.%Y")
                if isinstance(rd, str) and len(rd) >= 10:
                    parts_d = rd[:10].split("-")
                    if len(parts_d) == 3 and parts_d[0].isdigit() and len(parts_d[0]) == 4:
                        return f"{parts_d[2]}.{parts_d[1]}.{parts_d[0]}"
                return None

            def truncate(text, max_len=55):
                if len(text) <= max_len:
                    return text
                # Try to truncate at word boundary
                truncated = text[:max_len - 3]
                space = truncated.rfind(" ")
                if space > 20:
                    truncated = truncated[:space] + "..."
                else:
                    truncated += "..."
                return truncated

            # Platform emoji icons
            platform_icons = {"steam": "⌨️", "igdb": "🕹️", "psn": "🎮"}

            # Build all message groups
            MAX_BUTTONS_PER_MSG = 12
            message_groups = []
            current_group = {"header": None, "kb_rows": []}

            for r in filtered:
                name = r["title"]
                # Collect all release dates for this game
                all_dates = {}
                for p in r["platforms"]:
                    fd = fmt_date(p.get("release_date"))
                    if fd:
                        all_dates[p["source"]] = fd

                # Build header for this specific game
                if len(all_dates) == 1:
                    date_val = next(iter(all_dates.values()))
                    header = f"📅 {date_val}\n{name}"
                elif all_dates:
                    date_parts = [f"{k.upper()}: {v}" for k, v in all_dates.items()]
                    header = f"📅 {' | '.join(date_parts)}\n{name}"
                else:
                    header = name

                # Add buttons for this game
                game_kb_rows = []
                for p in r["platforms"]:
                    icon = platform_icons.get(p["source"], "◈")
                    btn_text = f"{icon} {truncate(name, 58)}"
                    # Truncate name for callback to fit 64 byte limit
                    cb_name = truncate(name, 40)
                    callback_data = f"ap|{cb_name}|{p['source']}|{p['id']}|"
                    game_kb_rows.append([InlineKeyboardButton(text=btn_text, callback_data=callback_data)])

                # Check if adding this game exceeds button limit
                if len(current_group["kb_rows"]) + len(game_kb_rows) > MAX_BUTTONS_PER_MSG:
                    message_groups.append(current_group)
                    current_group = {"header": header, "kb_rows": game_kb_rows}
                else:
                    if not current_group["header"]:
                        current_group["header"] = header
                    current_group["kb_rows"].extend(game_kb_rows)

            if current_group["kb_rows"]:
                message_groups.append(current_group)

            # Send messages — first message has header (query or game info), others only page number
            for i, group in enumerate(message_groups):
                kb = InlineKeyboardMarkup(inline_keyboard=group["kb_rows"])
                if i == 0:
                    # First message: use query in CAPS if no date, otherwise game info
                    header_text = group["header"]
                    if "📅" not in header_text:
                        header_text = query_upper = query_lower.upper()
                    suffix = f" ({i+1}/{len(message_groups)})" if len(message_groups) > 1 else ""
                    await message.answer(f"{header_text}{suffix}", reply_markup=kb)
                else:
                    # Subsequent messages: only page number
                    await message.answer(f"({i+1}/{len(message_groups)})", reply_markup=kb)

        @dp.inline_query()
        async def inline_search_handler(inline_query: InlineQuery):
            """Phase 21: Autocomplete — user types /@botname witcher and sees results inline."""
            query = inline_query.query or ""
            if not query or len(query) < 2:
                await inline_query.answer([], cache_time=0)
                return

            # Use cache if available
            cache_key = f"inline:{query}"
            cached = search_cache.get(cache_key)
            if cached is not None:
                await inline_query.answer(cached, cache_time=0)
                return

            # Phase 19: Parallel HTTP requests
            coroutines = [
                tmdb.search_movie(query),
                tmdb.search_tv(query),
                anilist.search_anime(query),
                igdb.search_games(query),
                steam.search_games(query),
                psn.search_games(query),
            ]
            results = await asyncio.gather(*coroutines)
            movie_results, tv_results, anime_results, game_results, steam_results, psn_results = results

            if not movie_results and not tv_results and not anime_results and not game_results and not steam_results and not psn_results:
                await inline_query.answer([], cache_time=0)
                return

            articles = []
            for r in movie_results[:10]:
                name = r.get("title", "Unknown")
                year = (r.get("first_air_date") or "")[:4] if r.get("first_air_date") else ""
                title = f"🎬 {name} ({year})"
                article = InlineQueryResultArticle(
                    id=str(r['id']),
                    title=title,
                    input_message_content=InputTextMessageContent(message_text=f"/add {r['id']}"),
                    description="TMDb Movie",
                )
                articles.append(article)

            for r in tv_results[:10]:
                name = r.get("name", "Unknown")
                year = (r.get("first_air_date") or "")[:4] if r.get("first_air_date") else ""
                title = f"📺 {name} ({year})"
                article = InlineQueryResultArticle(
                    id=str(r['id']),
                    title=title,
                    input_message_content=InputTextMessageContent(message_text=f"/add {r['id']}"),
                    description="TMDb TV Series",
                )
                articles.append(article)

            for r in anime_results[:10]:
                name = r.get("title", {}).get("romaji") or r.get("title", {}).get("english") or "Unknown"
                year = str(r.get("seasonYear") or "")
                title = f"🎌 {name} ({year})"
                article = InlineQueryResultArticle(
                    id=str(r['id']),
                    title=title,
                    input_message_content=InputTextMessageContent(message_text=f"/add {r['id']}"),
                    description="AniList Anime",
                )
                articles.append(article)

            for r in game_results[:10]:
                name = r.get("name", "Unknown")
                frd = r.get("first_release_date")
                year = ""
                if frd:
                    try:
                        frd_str = str(frd)
                        if frd_str.isdigit() and int(frd_str) > 1000000000:
                            year = str(datetime.fromtimestamp(int(frd_str), tz=timezone.utc).year)
                        else:
                            year = frd_str[:4]
                    except (ValueError, TypeError, OSError):
                        pass
                title = f"🎮 {name} ({year})"
                article = InlineQueryResultArticle(
                    id=str(r['id']),
                    title=title,
                    input_message_content=InputTextMessageContent(message_text=f"/add {r['id']}"),
                    description="IGDB Game",
                )
                articles.append(article)

            for r in steam_results[:10]:
                name = r.get("name", "Unknown")
                price = r.get("price", {})
                price_str = ""
                if price:
                    final = price.get("final", 0)
                    currency = price.get("currency", "USD")
                    if final > 0:
                        price_str = f" {final/100:.2f}{currency}"
                    else:
                        price_str = " Free"
                title = f"🎮 {name}{price_str}"
                article = InlineQueryResultArticle(
                    id=str(r["id"]),
                    title=title,
                    input_message_content=InputTextMessageContent(message_text=f"/add {r["id"]}"),
                    description="Steam Game",
                )
                articles.append(article)

            if psn_results:
                for r in psn_results[:10]:
                    name = r.get("name", "Unknown")
                    price = r.get("price", {})
                    price_str = ""
                    if price:
                        final = price.get("final", 0)
                        currency = price.get("currency", "GBP")
                        if final > 0:
                            price_str = f" {final/100:.2f}{currency}"
                        else:
                            price_str = " Free"
                    title = f"🎮 {name}{price_str}"
                    article = InlineQueryResultArticle(
                        id=str(r["id"]),
                        title=title,
                        input_message_content=InputTextMessageContent(message_text=f"/add {r['id']} psn"),
                        description="PSN Game",
                    )
                    articles.append(article)

            # Cache the result
            search_cache.set(cache_key, articles)
            await inline_query.answer(articles, cache_time=0)

        @dp.message(Command("add"))
        async def add_handler(message: Message):
            parts = message.text.split(maxsplit=1)
            if len(parts) < 2:
                await message.answer("Использование: /add <tmdb_id>, /add <anilist_id>, /add <igdb_id>, /add <steam_id> или /add <psn_id>")
                return
            arg = parts[1]
            try:
                numeric_id = int(arg)
            except ValueError:
                await message.answer("Нужно число TMDb, AniList, IGDB, Steam или PSN id, например: /add 841")
                return
            with db() as s:
                if not _is_allowed(message):
                    return
                user = _get_or_create_user(s, message.from_user.id)

                # Check ALL sources in parallel
                tmdb_movie, tmdb_tv = await asyncio.gather(tmdb.get_movie_details(numeric_id), tmdb.get_tv_details(numeric_id))
                anilist_details = await anilist.search_anime(str(numeric_id))
                igdb_details = await igdb.search_games(str(numeric_id))
                steam_details = await steam.get_game_details(numeric_id)
                psn_details = await psn.get_game_details(numeric_id)

                # Collect all matches
                matches = []
                if tmdb_movie:
                    matches.append(("movie", tmdb_movie, "tmdb"))
                if tmdb_tv:
                    matches.append(("tv", tmdb_tv, "tmdb"))
                if anilist_details:
                    for a in anilist_details[:3]:
                        matches.append(("anime", a, "anilist"))
                igdb_details = await igdb.get_game_details(numeric_id)
                if igdb_details:
                    matches.append(("game", igdb_details, "igdb"))
                if steam_details:
                    matches.append(("game", steam_details, "steam"))
                if psn_details:
                    matches.append(("game", psn_details, "psn"))

                if not matches:
                    await message.answer(f"Не нашёл id {numeric_id} ни в одном сервисе.")
                    return

                if len(matches) == 1:
                    kind, details, source = matches[0]
                    if source == "tmdb":
                        item = _ensure_media_item(s, numeric_id, details, kind)
                    elif source == "anilist":
                        item = _ensure_anilist_item(s, numeric_id, details)
                    elif source == "igdb":
                        item = _ensure_igdb_item(s, numeric_id, details)
                    elif source == "steam":
                        item = _ensure_steam_item(s, numeric_id, details)
                    elif source == "psn":
                        item = _ensure_psn_item(s, numeric_id, details)
                    await _perform_add_flow(s, tmdb, anilist, igdb, steam, psn, item, user.id, message)
                    return

                # Multiple matches — show picker
                kb_rows = []
                for kind, details, source in matches:
                    name = details.get("title") or details.get("name") or details.get("canonical_title_en") or "Unknown"
                    raw_year = (details.get("first_air_date") or details.get("release_date") or details.get("released") or "")
                    # Steam release_date is a dict {"date": "...", "coming_soon": true}, not a string
                    if isinstance(raw_year, dict):
                        raw_year = raw_year.get("date", "")
                    year = str(raw_year)[:4] if raw_year else ""
                    label = f"{name} ({year}) [{source}]"
                    kb_rows.append([InlineKeyboardButton(text=label, callback_data=f"add_source:{numeric_id}:{source}:{kind}")])
                
                kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
                await message.answer(f"Найдено в {len(matches)} сервисах. Какой добавить?", reply_markup=kb)
                return
                if kind == "pick_tmdb":
                    movie_d, tv_d = result[1], result[2]
                    kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text=f"🎬 {movie_d.get('title', 'фильм')}", callback_data=f"pick_media:{numeric_id}:movie")],
                        [InlineKeyboardButton(text=f"📺 {tv_d.get('name', 'сериал')}", callback_data=f"pick_media:{numeric_id}:tv")],
                    ])
                    await message.answer(
                        "Этот TMDb id совпадает с фильмом и сериалом. Какой добавить?",
                        reply_markup=kb,
                    )
                    return
                if kind == "pick_anilist":
                    tmdb_d, anilist_d, tmdb_type = result[1], result[2], result[3]
                    tmdb_title = tmdb_d.get("title") or tmdb_d.get("name", "TMDb")
                    anilist_title = (anilist_d.get("title") or {}).get("romaji") or "AniList"
                    icon = "🎬" if tmdb_type == "movie" else "📺"
                    kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text=f"{icon} {tmdb_title} (TMDb)", callback_data=f"pick_media:{numeric_id}:{tmdb_type}")],
                        [InlineKeyboardButton(text=f"🎌 {anilist_title} (AniList)", callback_data=f"pick_media:{numeric_id}:anilist")],
                    ])
                    await message.answer(
                        "Этот id совпадает с TMDb и AniList. Какой добавить?",
                        reply_markup=kb,
                    )
                    return
                if kind == "pick_igdb":
                    tmdb_d, igdb_d, tmdb_type = result[1], result[2], result[3]
                    tmdb_title = tmdb_d.get("title") or tmdb_d.get("name", "TMDb")
                    igdb_title = igdb_d.get("name") or "IGDB"
                    icon = "🎬" if tmdb_type == "movie" else "📺"
                    kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text=f"{icon} {tmdb_title} (TMDb)", callback_data=f"pick_media:{numeric_id}:{tmdb_type}")],
                        [InlineKeyboardButton(text=f"🎮 {igdb_title} (IGDB)", callback_data=f"pick_media:{numeric_id}:igdb")],
                    ])
                    await message.answer(
                        "Этот id совпадает с TMDb и IGDB. Какой добавить?",
                        reply_markup=kb,
                    )
                    return
                if kind == "pick_all_three":
                    tmdb_d, anilist_d, igdb_d, tmdb_type = result[1], result[2], result[3], result[4]
                    tmdb_title = tmdb_d.get("title") or tmdb_d.get("name", "TMDb")
                    anilist_title = (anilist_d.get("title") or {}).get("romaji") or "AniList"
                    igdb_title = igdb_d.get("name") or "IGDB"
                    icon = "🎬" if tmdb_type == "movie" else "📺"
                    kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text=f"{icon} {tmdb_title} (TMDb)", callback_data=f"pick_media:{numeric_id}:{tmdb_type}")],
                        [InlineKeyboardButton(text=f"🎌 {anilist_title} (AniList)", callback_data=f"pick_media:{numeric_id}:anilist")],
                        [InlineKeyboardButton(text=f"🎮 {igdb_title} (IGDB)", callback_data=f"pick_media:{numeric_id}:igdb")],
                    ])
                    await message.answer(
                        "Этот id совпадает с TMDb, AniList и IGDB. Какой добавить?",
                        reply_markup=kb,
                    )
                    return
                item = result[1]
                await _perform_add_flow(s, tmdb, anilist, igdb, steam, psn, item, user.id, message)

        @dp.callback_query()
        async def confirm_handler(cb: CallbackQuery):
            """Inline-button actions from the /add confirmation flow."""
            data = cb.data or ""
            action, _, arg = data.partition("|")
            if not arg:
                action, _, arg = data.partition(":")
            logging.info(f"callback: data={data!r}, action={action!r}, arg={arg!r}")
            with db() as s:
                if not _is_allowed(cb):
                    return
                user = _get_or_create_user(s, cb.from_user.id)

                if action in ("pick_movie", "pick_tv"):
                    try:
                        media_id = int(arg)
                    except ValueError:
                        await cb.answer("Неизвестная кнопка")
                        return
                    media_type = "movie" if action == "pick_movie" else "tv"
                    details = (
                        await tmdb.get_movie_details(media_id)
                        if media_type == "movie"
                        else await tmdb.get_tv_details(media_id)
                    )
                    valid = bool(
                        details and (details.get("title") or details.get("name"))
                    )
                    if not valid:
                        await cb.answer()
                        await cb.message.answer(f"TMDb не вернул данные для id {media_id}.")
                        return
                    item = _ensure_media_item(s, media_id, details, media_type)
                    logging.info(f"pick_{media_type} {media_id}: resolved to item {item.id}")
                    await cb.answer()
                    await _perform_add_flow(s, tmdb, anilist, igdb, steam, psn, item, user.id, cb.message)
                    return

                if action == "pick_media":
                    # Answer callback IMMEDIATELY to avoid timeout, then process
                    await cb.answer()
                    try:
                        parts = arg.split(":")
                        if len(parts) != 2:
                            await cb.message.answer("Неизвестная кнопка")
                            return
                        try:
                            media_id = int(parts[0])
                        except ValueError:
                            await cb.message.answer("Неизвестная кнопка")
                            return
                        source = parts[1]
                        logging.info(f"pick_media callback: media_id={media_id}, source={source}")
                        if source == "anilist":
                            anilist_details = await anilist.get_anime_details(media_id)
                            if not anilist_details:
                                await cb.message.answer(f"AniList не вернул данные для id {media_id}.")
                                return
                            item = _ensure_anilist_item(s, media_id, anilist_details)
                        elif source == "igdb":
                            igdb_details = await igdb.get_game_details(media_id)
                            if not igdb_details:
                                await cb.message.answer(f"IGDB не вернул данные для id {media_id}.")
                                return
                            item = _ensure_igdb_item(s, media_id, igdb_details)
                        elif source in ("movie", "tv"):
                            details = (
                                await tmdb.get_movie_details(media_id)
                                if source == "movie"
                                else await tmdb.get_tv_details(media_id)
                            )
                            if not details or not (details.get("title") or details.get("name")):
                                await cb.message.answer(f"TMDb не вернул данные для id {media_id}.")
                                return
                            item = _ensure_media_item(s, media_id, details, source)
                        else:
                            await cb.message.answer("Неизвестная кнопка")
                            return
                        logging.info(f"pick_media {media_id}/{source}: resolved to item {item.id}")
                        await _perform_add_flow(s, tmdb, anilist, igdb, steam, psn, item, user.id, cb.message)
                        return
                    except Exception as e:
                        logging.error(f"pick_media handler error: {e}", exc_info=True)
                        try:
                            await cb.message.answer(f"Ошибка при обработке: {e}")
                        except Exception:
                            pass
                        return

                if action == "add_source":
                    await cb.answer()
                    try:
                        parts = arg.split(":")
                        if len(parts) != 3:
                            await cb.message.answer("Неизвестная кнопка")
                            return
                        try:
                            numeric_id = int(parts[0])
                        except ValueError:
                            await cb.message.answer("Неизвестная кнопка")
                            return
                        source = parts[1]
                        kind = parts[2]
                        logging.info(f"add_source callback: numeric_id={numeric_id}, source={source}, kind={kind}")
                        
                        if source == "tmdb":
                            if kind == "movie":
                                details = await tmdb.get_movie_details(numeric_id)
                                media_type = "movie"
                            else:
                                details = await tmdb.get_tv_details(numeric_id)
                                media_type = "tv"
                            if not details:
                                await cb.message.answer(f"TMDb не вернул данные для id {numeric_id}.")
                                return
                            item = _ensure_media_item(s, numeric_id, details, media_type)
                        elif source == "anilist":
                            results = await anilist.search_anime(str(numeric_id))
                            if not results:
                                await cb.message.answer(f"AniList не вернул данные для id {numeric_id}.")
                                return
                            item = _ensure_anilist_item(s, numeric_id, results[0])
                        elif source == "igdb":
                            details = await igdb.get_game_details(numeric_id)
                            if not details:
                                await cb.message.answer(f"IGDB не вернул данные для id {numeric_id}.")
                                return
                            item = _ensure_igdb_item(s, numeric_id, details)
                        elif source == "steam":
                            details = await steam.get_game_details(numeric_id)
                            if not details:
                                await cb.message.answer(f"Steam не вернул данные для id {numeric_id}.")
                                return
                            item = _ensure_steam_item(s, numeric_id, details)
                        elif source == "psn":
                            details = await psn.get_game_details(numeric_id)
                            if not details:
                                await cb.message.answer(f"PSN не вернул данные для id {numeric_id}.")
                                return
                            item = _ensure_psn_item(s, numeric_id, details)
                        else:
                            await cb.message.answer("Неизвестный источник.")
                            return
                        
                        logging.info(f"add_source {numeric_id}/{source}: resolved to item {item.id}")
                        await _perform_add_flow(s, tmdb, anilist, igdb, steam, psn, item, user.id, cb.message)
                        return
                    except Exception as e:
                        logging.error(f"add_source handler error: {e}", exc_info=True)
                        try:
                            await cb.message.answer(f"Ошибка при обработке: {e}")
                        except Exception:
                            pass
                        return

                if action == "ap":
                    await cb.answer()
                    logging.info(f"ap callback: arg={arg!r}")
                    try:
                        parts = arg.split("|", 3)
                        logging.info(f"ap parts: {parts}")
                        if len(parts) != 4:
                            await cb.message.answer(f"Неизвестная кнопка (parts={len(parts)})")
                            return
                        cb_name, source, platform_id, year_str = parts
                        # Look up full name from GamePlatform by platform_id
                        full_name = None
                        gp = s.query(GamePlatform).filter(
                            GamePlatform.platform == source,
                            GamePlatform.platform_id == platform_id,
                        ).first()
                        if gp:
                            mi = s.get(MediaItem, gp.media_item_id)
                            full_name = mi.canonical_title_en if mi else cb_name
                        else:
                            # First time adding — search for game by truncated name
                            matching = s.query(MediaItem).filter(
                                MediaItem.media_type == "game",
                                MediaItem.canonical_title_en.ilike(f"%{cb_name}%"),
                            ).limit(1).all()
                            if matching:
                                full_name = matching[0].canonical_title_en
                            else:
                                full_name = cb_name
                        year = int(year_str) if year_str and year_str.isdigit() else None
                        platforms = [{"source": source, "platform_id": platform_id, "release_date": "", "store_url": ""}]
                        item, _ = media_resolve.add_game_to_watchlist(s, user.id, full_name, year, platforms)
                        title_display = item.canonical_title_en or full_name
                        await cb.message.answer(f"✅ Добавлено: {title_display} [{source.upper()}]")
                    except Exception as e:
                        logging.error(f"ap callback failed: {e}")
                        await cb.message.answer("Ошибка при добавлении.")
                    return

                item = s.get(MediaItem, arg) if arg else None
                if item is None or action not in ("ca_yes", "ca_no", "wt_keep", "wt_stop"):
                    await cb.answer("Неизвестная кнопка")
                    return
                title = item.canonical_title_en or "item"
                if action == "ca_yes":
                    add_watch_item(s, user.id, item.id)
                    for ev_type in _default_rules_for(item.media_type):
                        set_rule(s, user.id, item.id, ev_type, True)
                    state = await _fetch_tmdb_state(s, tmdb, item)
                    if item.media_type == "game" or state is None:
                        igdb_state = await _fetch_igdb_state(s, igdb, item)
                        if igdb_state:
                            state = igdb_state
                    _store_state(s, item.id, "tmdb" if item.media_type != "game" else "igdb", state)
                    await cb.answer("Добавлено")
                    await cb.message.answer(f"✅ Добавлено: {title}")
                elif action == "ca_no":
                    await cb.answer()
                    await cb.message.answer(f"Не добавлено: {title}.")
                elif action == "wt_keep":
                    await cb.answer("Отслеживание продолжается")
                    await cb.message.answer(f"🔄 Продолжаем отслеживать: {title}")
                else:  # wt_stop
                    remove_watch_item(s, user.id, item.id)
                    await cb.answer("Удалено из списка")
                    await cb.message.answer(f"⏹ Остановлено отслеживание: {title}")

        @dp.message(Command("remove"))
        async def remove_handler(message: Message):
            parts = message.text.split(maxsplit=1)
            if len(parts) < 2:
                await message.answer("Использование: /remove <tmdb_id>")
                return
            try:
                tmdb_id = int(parts[1])
            except ValueError:
                await message.answer("Нужно число TMDb id, например: /remove 841")
                return
            with db() as s:
                if not _is_allowed(message):
                    return
                user = _get_or_create_user(s, message.from_user.id)
                item = get_media_item_by_external_id(s, "tmdb", str(tmdb_id))
                if item is None:
                    await message.answer("Этот TMDb id ещё не добавлялся.")
                    return
                removed = remove_watch_item(s, user.id, item.id)
                title = item.canonical_title_en or "item"
                if not removed:
                    await message.answer(f"Уже не в списке: {title}")
                else:
                    await message.answer(f"🗑 Удалено из списка: {title}")

        @dp.message(Command("watchlist"))
        async def watchlist_handler(message: Message):
            with db() as s:
                if not _is_allowed(message):
                    return
                user = _get_or_create_user(s, message.from_user.id)
                items, total = list_watch_items(s, user.id)
                if not items:
                    await message.answer("Список отслеживания пуст.")
                    return
                lines = ["📚 Отслеживаю:"]
                for w in items[:20]:
                    m = s.get(MediaItem, w.media_item_id)
                    title = m.canonical_title_en or "item"
                    year = f" ({m.year})" if m.year else ""
                    if m.media_type == "game":
                        lines.append(f"• {title}{year}")
                        # Show unique platforms (group by platform+id to avoid duplicates)
                        platforms = media_resolve.get_game_platforms(s, w.media_item_id)
                        tracked = media_resolve.get_user_tracked_platforms(s, user.id, w.media_item_id)
                        seen = set()
                        unique_platforms = []
                        for gp in platforms:
                            key = (gp.platform, gp.platform_id)
                            if key not in seen:
                                seen.add(key)
                                unique_platforms.append(gp)
                        for i, gp in enumerate(unique_platforms):
                            marker = "├─" if i < len(unique_platforms) - 1 else "└─"
                            status = "✅" if gp.platform in tracked else "⬜"
                            rd = gp.release_date
                            if rd and len(rd) >= 10:
                                parts_d = rd.split("-")
                                rd = f"{parts_d[2]}.{parts_d[1]}.{parts_d[0]}"
                            rd_str = f" ({rd})" if rd else ""
                            lines.append(f"  {marker} {gp.platform.upper()}{rd_str} {status}")
                    else:
                        lines.append(f"• {title}{year}")
                await message.answer("\n".join(lines))

        @dp.message(Command("note"))
        async def note_handler(message: Message):
            tokens = message.text.split()
            if len(tokens) < 2:
                await message.answer("Использование: /note <tmdb_id> <текст заметки>")
                return
            try:
                tmdb_id = int(tokens[1])
            except ValueError:
                await message.answer("Нужно число TMDb id, например: /note 841 текст")
                return
            note_text = " ".join(tokens[2:]) if len(tokens) > 2 else None
            with db() as s:
                if not _is_allowed(message):
                    return
                user = _get_or_create_user(s, message.from_user.id)
                result = await _resolve_media_for_add(s, tmdb_id, tmdb)
                kind = result[0]
                if kind == "none":
                    await message.answer("Не нашёл этот TMDb id.")
                    return
                if kind in ("pick_tmdb", "pick_anilist", "pick_igdb", "pick_all_three"):
                    await message.answer(
                        "Этот TMDb id совпадает с элементами из разных источников. "
                        "Сначала добавьте его через /add, выбрав нужное произведение."
                    )
                    return
                if kind != "item":
                    await message.answer("Не удалось разрешить TMDb id.")
                    return
                item = result[1]
                if note_text is not None:
                    create_or_update_note(s, user.id, item.id, note_text)
                    title = item.canonical_title_en or "item"
                    await message.answer(f"📝 Заметка для {title}: {note_text}")
                else:
                    existing = get_note(s, user.id, item.id)
                    if existing:
                        await message.answer(f"📝 {existing.note_text}")
                    else:
                        await message.answer("Заметка не найдена.")

        @dp.message(Command("notes"))
        async def notes_handler(message: Message):
            with db() as s:
                if not _is_allowed(message):
                    return
                user = _get_or_create_user(s, message.from_user.id)
                rows = list_notes(s, user.id)
                if not rows:
                    await message.answer("Заметок пока нет.")
                    return
                lines = ["📝 Заметки:"]
                for media_item_id, note_text in rows[:20]:
                    m = s.get(MediaItem, media_item_id)
                    title = m.canonical_title_en or "item"
                    lines.append(f"• {title}: {note_text}")
                await message.answer("\n".join(lines))

        @dp.message(Command("events"))
        async def events_handler(message: Message):
            parts = message.text.split(maxsplit=1)
            if len(parts) < 2:
                await message.answer("Использование: /events <tmdb_id>")
                return
            try:
                tmdb_id = int(parts[1])
            except ValueError:
                await message.answer("Нужно число TMDb id, например: /events 841")
                return
            with db() as s:
                if not _is_allowed(message):
                    return
                user = _get_or_create_user(s, message.from_user.id)
                item = get_media_item_by_external_id(s, "tmdb", str(tmdb_id))
                if item is None:
                    await message.answer("Этот TMDb id ещё не добавлялся.")
                    return
                rules = get_enabled_rules(s, user.id, item.id)
                if not rules:
                    await message.answer("События для этого произведения пока не настроены.")
                    return
                lines = ["\U0001F514 События отслеживания:"]
                for r in rules[:20]:
                    lines.append(f"• {r.event_type}")
                await message.answer("\n".join(lines))

        async def _poll_due_items():
            """Phase 7.5 adaptive scan: process only watch items whose tier
            deadline has arrived (staggered TMDb calls, per-item intervals).
            """
            before = tmdb.call_count
            with db() as s:
                results = await poll_due_items(s, tmdb, anilist, igdb)
                for user_id, item, events in results:
                    if not events:
                        continue
                    u = s.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
                    if u is None:
                        continue
                    title = item.canonical_title_en or "item"
                    for ev in events:
                        date = ev.payload.get("date")
                        season = ev.payload.get("season")
                        episode = ev.payload.get("episode")
                        if date:
                            text = f"\U0001F514 {ev.event_type} \u2192 {title} ({date})"
                        elif season is not None:
                            text = f"\U0001F4FA {ev.event_type} \u2192 {title}, сезон {season}"
                        elif episode is not None:
                            text = f"\U0001F3AC {ev.event_type} \u2192 {title}, серия {episode}"
                        else:
                            text = f"\U0001F514 {ev.event_type} \u2192 {title}"
                        await bot.send_message(
                            chat_id=u.telegram_user_id,
                            text=text,
                        )
            logging.info(
                "poll scan done: %d due items, %d TMDb calls (total %d)",
                len(results), tmdb.call_count - before, tmdb.call_count,
            )

        # Phase 7.5: one due-item scan at startup (all items are due on the first
        # run because next_check_at is NULL) + recurring scan of only due items.
        await _poll_due_items()

        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            _poll_due_items, "interval", seconds=settings.poll_scan_interval_seconds
        )
        # Phase 15: daily database backup at 3 AM
        scheduler.add_job(
            _backup_database, "cron", hour=3, minute=0
        )
        scheduler.start()

        # Long polling (for VPS deployment without webhook setup)
        await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        # Startup crash protection: send error via HTTP before anything else
        try:
            from app.config import get_settings
            settings = get_settings()
            send_startup_error_sync(settings.telegram_bot_token, settings.owner_chat_id, e)
        except Exception:
            pass  # Best effort — don't crash on error reporting
        raise
