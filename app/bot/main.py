"""Minimal aiogram bot entry point. Phase 4: watchlist + notes. Phase 19: speed optimization. Phase 21: autocomplete."""

import asyncio
import json
import logging
import sys
from contextlib import contextmanager
from datetime import date, datetime as dt, timezone

from sqlalchemy import delete, select

from aiogram import Bot, Dispatcher
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, InlineQuery, InlineQueryResultArticle, InputTextMessageContent, Message, SwitchInlineQueryChosenChat

from app.bot.access import AccessMiddleware
from app.bot.error_handler import ErrorMiddleware, send_startup_error_sync
from app.bot.tracker_handlers import TelegramSender, main_keyboard, owner_chat_id, register_tracker_handlers
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
from app.providers.shikimori import ShikimoriClient, pick_current_season, get_total_seasons
from app.providers.igdb import IGDBProvider
from app.providers.steam import SteamProvider
from app.providers.psn import PSNProvider
from app.scheduler.polling import _fetch_tmdb_state, _fetch_igdb_state, poll_item, _store_state, backup_database as _backup_database, _earliest_digital_date, _earliest_theatrical_date
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.sources.tmdb_movies import TmdbMovieSource
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


def display_title(item) -> str:
    """Return the best Russian or English title for display."""
    if hasattr(item, 'title_ru') and item.title_ru:
        return item.title_ru
    if hasattr(item, 'canonical_title_en') and item.canonical_title_en:
        return item.canonical_title_en
    return "Unknown"


DELIVERY_RETRY_SECONDS = 60  # how often the tracker retries events that could not be sent
INLINE_MAX_RESULTS = 50  # Telegram rejects more than 50 results in one answerInlineQuery


def _balance_inline(articles: list, limit: int = INLINE_MAX_RESULTS) -> list:
    """Cap inline results at `limit`, taking them round-robin from each source (grouped by
    description) so a chatty source cannot crowd out the rest, and make ids unique."""
    groups: dict[str, list] = {}
    for a in articles:
        groups.setdefault(a.description, []).append(a)
    queues = list(groups.values())
    balanced, seen = [], set()
    for rank in range(max((len(q) for q in queues), default=0)):
        for q in queues:
            if rank < len(q) and len(balanced) < limit:
                a = q[rank]
                if a.id in seen:  # e.g. a TMDb movie and series share one numeric id
                    a = a.model_copy(update={"id": f"{a.id}-{len(balanced)}"})
                seen.add(a.id)
                balanced.append(a)
    return balanced


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
            year = dt.fromtimestamp(frd, tz=timezone.utc).year
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
    title = display_title(item)
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
        return ("NEXT_EPISODE_AIRING", "ALL_EPISODES_OUT", "NEW_SEASON_ANNOUNCED", "NEW_SEASON_STARTED", "SEASON_START_DATE")
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

    allowed_ids = settings.allowed_telegram_user_ids
    if not allowed_ids:
        logging.critical("ALLOWED_TELEGRAM_USER_IDS is empty: refusing to start an open bot")
        raise SystemExit(1)

    dp = Dispatcher()
    # Allowlist goes first so strangers never reach the handlers or the error reporter
    dp.update.outer_middleware(AccessMiddleware(allowed_ids))
    # Register error reporting middleware (catches all unhandled exceptions)
    dp.update.outer_middleware(ErrorMiddleware())
    tmdb = TMDbProvider()
    anilist = AniListProvider()
    shikimori = ShikimoriClient()
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
        """Second line of defence behind AccessMiddleware; empty list allows nobody."""
        return getattr(message.from_user, "id", None) in allowed_ids

    async with Bot(token=settings.telegram_bot_token) as bot:
        me = await bot.get_me()
        logging.info(f"Bot started as @{me.username}")

        # Release tracker v2: new core with its own database, running beside the legacy handlers.
        # Registered before them, so «Тестовое событие» is not swallowed by the catch-all text handler.
        tracker = Tracker(
            create_session_factory(),
            clock=lambda: dt.now(tz=timezone.utc),
            sender=TelegramSender(bot, owner_chat_id(settings.owner_chat_id, allowed_ids)),
            sources={"movie": TmdbMovieSource(tmdb)},  # the same throttled TMDb client as the legacy code
        )
        register_tracker_handlers(dp, tracker, allowed_ids)

        @dp.message(CommandStart())
        async def start_handler(message: Message):
            await message.answer("👋 Бот запущен. Phase 4: watchlist + notes ready.", reply_markup=main_keyboard())

        # Phase 23: unified search state storage
        _search_state: dict[int, dict] = {}

        async def _send_with_pagination(msg, kb_rows, header=None):
            """Send inline keyboard buttons with pagination (12 per message)."""
            MAX_BUTTONS = 12
            groups = [kb_rows[i:i+MAX_BUTTONS] for i in range(0, len(kb_rows), MAX_BUTTONS)]
            for j, group in enumerate(groups):
                kb = InlineKeyboardMarkup(inline_keyboard=group)
                if len(groups) > 1:
                    suffix = f" ({j+1}/{len(groups)})"
                    if j == 0 and header:
                        await msg.answer(f"{header}{suffix}", reply_markup=kb)
                    else:
                        await msg.answer(suffix, reply_markup=kb)
                else:
                    if header:
                        await msg.answer(header, reply_markup=kb)
                    else:
                        await msg.answer(reply_markup=kb)

        class _NotCommand:
            """Filter that matches messages that are NOT commands."""
            def __call__(self, message: Message) -> bool:
                text = message.text or ""
                if text.startswith("/"):
                    return False
                if "@" in text:
                    first_part = text.split("@")[0]
                    if first_part.startswith("/"):
                        return False
                return True

        @dp.message(_NotCommand())
        async def text_message_handler(message: Message):
            """Phase 23: unified search — catch non-command text messages."""
            if not _is_allowed(message):
                return
            # Skip if not private chat
            if message.chat.type != "private":
                return
            logging.info(f"text_handler: processing message '{(message.text or '')[:50]}'")
            user_id = message.from_user.id
            text = message.text or ""
            # If bot is waiting for type selection, this is the query
            if user_id in _search_state and _search_state[user_id].get("waiting_for_type"):
                query = text.strip()
                if len(query) < 2:
                    await message.answer("Введите название (минимум 2 символа).")
                    return
                _search_state[user_id]["query"] = query
                _search_state[user_id]["waiting_for_type"] = False
                # Send type selection buttons
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text="🎬 Фильм", callback_data="search_type:movie"),
                        InlineKeyboardButton(text="📺 Сериал", callback_data="search_type:tv"),
                    ],
                    [
                        InlineKeyboardButton(text="🎌 Аниме", callback_data="search_type:anime"),
                        InlineKeyboardButton(text="🎮 Игра", callback_data="search_type:game"),
                    ],
                ])
                await message.answer("Что ищем?", reply_markup=kb)
                return
            # If not waiting for type, check if this is a search query
            query = text.strip()
            if len(query) < 2:
                return
            _search_state[user_id] = {"query": query, "waiting_for_type": True}
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="🎬 Фильм", callback_data="search_type:movie"),
                    InlineKeyboardButton(text="📺 Сериал", callback_data="search_type:tv"),
                ],
                [
                    InlineKeyboardButton(text="🎌 Аниме", callback_data="search_type:anime"),
                    InlineKeyboardButton(text="🎮 Игра", callback_data="search_type:game"),
                ],
            ])
            await message.answer("Что ищем?", reply_markup=kb)

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
                            year = str(dt.fromtimestamp(int(frd_str), tz=timezone.utc).year)
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
                            year = str(dt.fromtimestamp(int(frd_str), tz=timezone.utc).year)
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

            articles = _balance_inline(articles)
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

                if action == "search_type":
                    await cb.answer()
                    try:
                        user_id = cb.from_user.id
                        if user_id not in _search_state:
                            await cb.message.answer("Сначала введите название для поиска.")
                            return
                        state = _search_state[user_id]
                        query = state.get("query", "")
                        if not query:
                            await cb.message.answer("Сначала введите название для поиска.")
                            return
                        media_type = arg  # movie, tv, anime, game
                        # Clear state
                        del _search_state[user_id]
                        # Perform search based on type
                        if media_type == "movie":
                            results = await tmdb.search_movie(query)
                            if not results:
                                await cb.message.answer("Ничего не найдено.")
                                return
                            kb_rows = []
                            for r in results[:10]:
                                name = r.get("title", "Unknown")
                                rd = r.get("release_date") or ""
                                year = rd[:4] if rd else ""
                                display = f"{name} ({year})" if year else name
                                if len(display) > 60:
                                    display = display[:57] + "..."
                                kb_rows.append([InlineKeyboardButton(text=display, callback_data=f"search_add:movie:{r['id']}:tmdb")])
                            await _send_with_pagination(cb.message, kb_rows, query.upper())
                        elif media_type == "tv":
                            results = await tmdb.search_tv(query)
                            if not results:
                                await cb.message.answer("Ничего не найдено.")
                                return
                            kb_rows = []
                            for r in results[:10]:
                                name = r.get("name", "Unknown")
                                rd = r.get("first_air_date") or ""
                                year = rd[:4] if rd else ""
                                display = f"{name} ({year})" if year else name
                                if len(display) > 60:
                                    display = display[:57] + "..."
                                kb_rows.append([InlineKeyboardButton(text=display, callback_data=f"search_add:tv:{r['id']}:tmdb")])
                            await _send_with_pagination(cb.message, kb_rows, query.upper())
                        elif media_type == "anime":
                            results = await shikimori.search_anime(query)
                            if not results:
                                await cb.message.answer("Ничего не найдено.")
                                return
                            # Group by franchise
                            franchises = {}
                            for r in results:
                                franchise = r.get("franchise") or f"single:{r['id']}"
                                if franchise not in franchises:
                                    franchises[franchise] = r
                            kb_rows = []
                            for franchise, r in list(franchises.items())[:10]:
                                name = r.get("russian") or r.get("name") or "Unknown"
                                year = str(r.get("airedOn", {}).get("year") or r.get("seasonYear") or "")
                                display = f"{name} ({year})" if year else name
                                if len(display) > 60:
                                    display = display[:57] + "..."
                                # Store franchise and MAL ID in a way that fits 64 bytes
                                # Use Shikimori ID as key, compute franchise in handler
                                kb_rows.append([InlineKeyboardButton(text=display, callback_data=f"search_add:anime:{r['id']}")])
                            await _send_with_pagination(cb.message, kb_rows, query.upper())
                        elif media_type == "game":
                            from datetime import datetime, timezone as _tz
                            results = await media_resolve.search_games(query, limit=10, rawg_api_key=settings.rawg_api_key)
                            if not results:
                                await cb.message.answer("Игры не найдены.")
                                return

                            # Filter results: keep only games where all query words appear in title
                            query_lower = query.lower().strip()
                            query_words = [w for w in query_lower.split() if len(w) > 2]

                            def relevance_score(title, query_words):
                                title_lower = title.lower()
                                if not query_words:
                                    return 1
                                score = sum(1 for w in query_words if w in title_lower)
                                return score / len(query_words)

                            filtered = []
                            for r in results:
                                score = relevance_score(r["title"], query_words)
                                if score >= 0.5:
                                    r["_score"] = score
                                    filtered.append(r)

                            filtered.sort(key=lambda x: x["_score"], reverse=True)

                            def fmt_date(rd):
                                if not rd:
                                    return None
                                if isinstance(rd, int) and rd > 1000000000:
                                    return datetime.fromtimestamp(rd, tz=_tz.utc).strftime("%d.%m.%Y")
                                if isinstance(rd, str) and len(rd) >= 10:
                                    parts_d = rd[:10].split("-")
                                    if len(parts_d) == 3 and parts_d[0].isdigit() and len(parts_d[0]) == 4:
                                        return f"{parts_d[2]}.{parts_d[1]}.{parts_d[0]}"
                                return None

                            def truncate(text, max_len=55):
                                if len(text) <= max_len:
                                    return text
                                truncated = text[:max_len - 3]
                                space = truncated.rfind(" ")
                                if space > 20:
                                    truncated = truncated[:space] + "..."
                                else:
                                    truncated += "..."
                                return truncated

                            platform_icons = {"steam": "⌨️", "igdb": "🕹️", "psn": "🎮"}

                            MAX_BUTTONS_PER_MSG = 12
                            message_groups = []
                            current_group = {"header": None, "kb_rows": []}

                            for r in filtered:
                                name = r["title"]
                                all_dates = {}
                                for p in r["platforms"]:
                                    fd = fmt_date(p.get("release_date"))
                                    if fd:
                                        all_dates[p["source"]] = fd

                                if len(all_dates) == 1:
                                    date_val = next(iter(all_dates.values()))
                                    header = f"📅 {date_val}\n{name}"
                                elif all_dates:
                                    date_parts = [f"{k.upper()}: {v}" for k, v in all_dates.items()]
                                    header = f"📅 {' | '.join(date_parts)}\n{name}"
                                else:
                                    header = name

                                game_kb_rows = []
                                for p in r["platforms"]:
                                    icon = platform_icons.get(p["source"], "◈")
                                    btn_text = f"{icon} {truncate(name, 58)}"
                                    cb_name = truncate(name, 40)
                                    callback_data = f"ap|{cb_name}|{p['source']}|{p['id']}|"
                                    game_kb_rows.append([InlineKeyboardButton(text=btn_text, callback_data=callback_data)])

                                if len(current_group["kb_rows"]) + len(game_kb_rows) > MAX_BUTTONS_PER_MSG:
                                    message_groups.append(current_group)
                                    current_group = {"header": header, "kb_rows": game_kb_rows}
                                else:
                                    if not current_group["header"]:
                                        current_group["header"] = header
                                    current_group["kb_rows"].extend(game_kb_rows)

                            if current_group["kb_rows"]:
                                message_groups.append(current_group)

                            for i, group in enumerate(message_groups):
                                kb = InlineKeyboardMarkup(inline_keyboard=group["kb_rows"])
                                if i == 0:
                                    header_text = group["header"]
                                    if "📅" not in header_text:
                                        header_text = query_lower.upper()
                                    suffix = f" ({i+1}/{len(message_groups)})" if len(message_groups) > 1 else ""
                                    await cb.message.answer(f"{header_text}{suffix}", reply_markup=kb)
                                else:
                                    await cb.message.answer(f"({i+1}/{len(message_groups)})", reply_markup=kb)
                        return
                    except Exception as e:
                        logging.error(f"search_type handler error: {e}", exc_info=True)
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

                if action == "search_add":
                    await cb.answer()
                    try:
                        parts = arg.split(":")
                        if len(parts) < 2:
                            await cb.message.answer("Неизвестная кнопка")
                            return
                        media_type = parts[0]  # movie, tv, anime, game
                        if media_type == "anime":
                            external_id = parts[1] if len(parts) > 1 else ""
                            platform = ""
                        else:
                            platform = parts[-1]  # last part is platform
                            external_id = ":".join(parts[1:-1])  # everything in between

                        if media_type == "movie":
                            details = await tmdb.get_movie_details(int(external_id))
                            if not details:
                                await cb.message.answer(f"TMDb не вернул данные.")
                                return
                            item = _ensure_media_item(s, int(external_id), details, "movie")
                        elif media_type == "tv":
                            details = await tmdb.get_tv_details(int(external_id))
                            if not details:
                                await cb.message.answer(f"TMDb не вернул данные.")
                                return
                            item = _ensure_media_item(s, int(external_id), details, "tv")
                        elif media_type == "anime":
                            shiki_id = external_id
                            # Get Shikimori item to find franchise
                            shiki_item = await shikimori.get_by_id(shiki_id)
                            if not shiki_item:
                                await cb.message.answer(f"Shikimori не нашёл тайтл.")
                                return
                            franchise_key = shiki_item.get("franchise") or f"single:{shiki_id}"
                            # Build franchise summary
                            summary = await shikimori.build_franchise_summary(franchise_key)
                            if not summary:
                                await cb.message.answer(f"Не удалось построить сводку франшизы.")
                                return
                            current = summary.current
                            mal_id = current.get("malId")
                            if not mal_id:
                                await cb.message.answer(f"Нет MAL ID в Shikimori.")
                                return
                            anilist_details = await anilist.get_anime_by_mal(int(mal_id))
                            if not anilist_details:
                                await cb.message.answer(f"AniList не вернул данные по MAL ID {mal_id}.")
                                return
                            # Check for existing item by shikimori_franchise
                            existing_franchise_ext = s.query(ExternalId).filter(
                                ExternalId.media_item_id == MediaItem.id,
                                ExternalId.source == "shikimori_franchise",
                                ExternalId.external_id == franchise_key,
                            ).first()
                            # Check if user already tracks this franchise
                            if existing_franchise_ext:
                                existing_watch = s.execute(
                                    select(UserWatchItem).where(
                                        (UserWatchItem.user_id == user.id) &
                                        (UserWatchItem.media_item_id == existing_franchise_ext.media_item_id)
                                    )
                                ).scalar_one_or_none()
                                if existing_watch:
                                    existing_item = s.get(MediaItem, existing_franchise_ext.media_item_id)
                                    if existing_item:
                                        await cb.message.answer(f"Уже в списке: {display_title(existing_item)}")
                                        return
                            item = _ensure_anilist_item(s, int(anilist_details["id"]), anilist_details)
                            # Update title_ru if available
                            if summary.title_ru:
                                item.title_ru = summary.title_ru
                            # Store ExternalIds
                            ext_franchise = ExternalId(media_item_id=item.id, source="shikimori_franchise", external_id=franchise_key)
                            ext_shiki = ExternalId(media_item_id=item.id, source="shikimori", external_id=str(current.get("id")))
                            ext_anilist = ExternalId(media_item_id=item.id, source="anilist", external_id=str(anilist_details["id"]))
                            s.add_all([ext_franchise, ext_shiki, ext_anilist])
                            s.flush()
                        elif media_type == "game":
                            if platform == "igdb":
                                details = await igdb.get_game_details(int(external_id))
                                if not details:
                                    await cb.message.answer(f"IGDB не вернул данные.")
                                    return
                                item = _ensure_igdb_item(s, int(external_id), details)
                            elif platform == "steam":
                                details = await steam.get_game_details(int(external_id))
                                if not details:
                                    await cb.message.answer(f"Steam не вернул данные.")
                                    return
                                item = _ensure_steam_item(s, int(external_id), details)
                            elif platform == "psn":
                                details = await psn.get_game_details(external_id)
                                if not details:
                                    await cb.message.answer(f"PSN не вернул данные.")
                                    return
                                item = _ensure_psn_item(s, external_id, details)
                            else:
                                await cb.message.answer("Неизвестная платформа.")
                                return
                        else:
                            await cb.message.answer("Неизвестный тип.")
                            return

                        add_watch_item(s, user.id, item.id)
                        # Create default notification rules
                        for ev_type in _default_rules_for(item.media_type):
                            set_rule(s, user.id, item.id, ev_type, enabled=True)
                        await cb.message.answer(f"✅ {display_title(item)} добавлено в отслеживание.")
                        return
                    except Exception as e:
                        logging.error(f"search_add handler error: {e}", exc_info=True)
                        try:
                            await cb.message.answer(f"Ошибка при добавлении: {e}")
                        except Exception:
                            pass
                        return

                if action == "details":
                    await cb.answer()
                    try:
                        media_item_id = arg
                        m = s.get(MediaItem, media_item_id)
                        if not m:
                            await cb.message.answer("Элемент не найден.")
                            return
                        lines = []
                        title = display_title(m)
                        year = f" ({m.year})" if m.year else ""
                        lines.append(f"{title}{year}")

                        if m.media_type == "movie":
                            ext = s.query(ExternalId).filter(
                                ExternalId.media_item_id == m.id,
                                ExternalId.source == "tmdb",
                            ).first()
                            if ext:
                                details = await tmdb.get_movie_details(int(ext.external_id))
                                if details:
                                    original_title = details.get("original_title")
                                    if original_title and original_title != details.get("title"):
                                        lines.append(original_title)
                            lines.append("Фильм")
                            if ext:
                                details = await tmdb.get_movie_details(int(ext.external_id))
                                if details and details.get("runtime"):
                                    lines.append(f"  Длительность: {details['runtime']} мин")
                                credits = await tmdb.get_movie_credits(int(ext.external_id))
                                if credits:
                                    crew = credits.get("crew", [])
                                    director = next((p["name"] for p in crew if p["job"] == "Director"), None)
                                    if director:
                                        lines.append(f"  Режиссёр: {director}")
                                    cast = credits.get("cast", [])[:3]
                                    if cast:
                                        actors = ", ".join(p["name"] for p in cast)
                                        lines.append(f"  В ролях: {actors}")
                            # Get release dates directly from API
                            if ext:
                                release_dates = await tmdb.get_movie_release_dates(int(ext.external_id))
                                thea = _earliest_theatrical_date(release_dates) if release_dates else None
                                digital = _earliest_digital_date(release_dates) if release_dates else None
                                lines.append("")
                                lines.append("Даты:")
                                if thea:
                                    lines.append(f"  - Премьера в кинотеатрах: {thea}")
                                else:
                                    lines.append("  - Премьера в кинотеатрах: не обьявлена")
                                if digital:
                                    lines.append(f"  - Цифровой релиз: {digital}")
                                else:
                                    lines.append("  - Цифровой релиз: не обьявлена")

                        elif m.media_type == "tv":
                            ext = s.query(ExternalId).filter(
                                ExternalId.media_item_id == m.id,
                                ExternalId.source == "tmdb",
                            ).first()
                            if ext:
                                tv_details = await tmdb.get_tv_details(int(ext.external_id))
                                if tv_details:
                                    original_name = tv_details.get("original_name")
                                    if original_name and original_name != tv_details.get("name"):
                                        lines.append(original_name)
                            lines.append("Сериал")
                            if ext:
                                tv_details = await tmdb.get_tv_details(int(ext.external_id))
                                if tv_details:
                                    first_air = tv_details.get("first_air_date")
                                    status = tv_details.get("status")
                                    status_map = {"Returning Series": "Идёт", "Ended": "Завершён", "Canceled": "Отменён", "Planning": "В разработке"}
                                    seasons = await tmdb.get_tv_seasons(int(ext.external_id))
                                    if seasons:
                                        latest_season = None
                                        for s in seasons:
                                            if s.get("season_number") > 0:
                                                if latest_season is None or s.get("season_number") > latest_season.get("season_number"):
                                                    latest_season = s
                                        if latest_season:
                                            current_season = latest_season.get("season_number")
                                            total_seasons = len([s for s in seasons if s.get("season_number") > 0])
                                            lines.append(f"  Статус: {status_map.get(status, status)}")
                                            lines.append(f"  Текущий сезон: {current_season}" + (f" из {total_seasons}" if total_seasons else ""))
                                            episodes = await tmdb.get_tv_season_episodes(int(ext.external_id), current_season)
                                            aired = len([e for e in episodes if e.get("air_date") and e.get("air_date") <= dt.now().strftime("%Y-%m-%d")])
                                            total = len(episodes)
                                            if aired or total:
                                                lines.append(f"  Выпущено: {aired} из {total}")
                                    if first_air:
                                        lines.append(f"  Премьера: {first_air}")
                                    # Next episode
                                    if status == "Returning Series":
                                        next_ep_date = None
                                        if seasons:
                                            latest_season = None
                                            for s in seasons:
                                                if s.get("season_number") > 0:
                                                    if latest_season is None or s.get("season_number") > latest_season.get("season_number"):
                                                        latest_season = s
                                            if latest_season:
                                                current_season = latest_season.get("season_number")
                                                episodes = await tmdb.get_tv_season_episodes(int(ext.external_id), current_season)
                                                for e in episodes:
                                                    air_date = e.get("air_date")
                                                    if air_date and air_date >= dt.now().strftime("%Y-%m-%d"):
                                                        next_ep_date = air_date
                                                        break
                                        if next_ep_date:
                                            next_date = dt.strptime(next_ep_date, "%Y-%m-%d")
                                            days = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
                                            day_name = days[next_date.weekday()]
                                            lines.append(f"  Следующая серия: {next_ep_date} ({day_name})")
                                        else:
                                            lines.append("  Следующий сезон: не анонсирован")

                        elif m.media_type == "anime":
                            ext = s.query(ExternalId).filter(
                                ExternalId.media_item_id == m.id,
                                ExternalId.source == "anilist",
                            ).first()
                            shiki_franchise_ext = s.query(ExternalId).filter(
                                ExternalId.media_item_id == m.id,
                                ExternalId.source == "shikimori_franchise",
                            ).first()
                            shiki_ext = s.query(ExternalId).filter(
                                ExternalId.media_item_id == m.id,
                                ExternalId.source == "shikimori",
                            ).first()
                            if ext:
                                anilist_details = await anilist.get_anime_details(int(ext.external_id))
                                if anilist_details:
                                    english_title = anilist_details.get("title", {}).get("english")
                                    romaji_title = anilist_details.get("title", {}).get("romaji")
                                    if english_title and english_title != romaji_title:
                                        lines.append(english_title)
                            lines.append("Аниме")
                            # Try to build franchise summary
                            summary = None
                            if shiki_franchise_ext:
                                summary = await shikimori.build_franchise_summary(shiki_franchise_ext.external_id)
                            elif shiki_ext:
                                # Fallback: try to get franchise from shiki_id
                                shiki_item = await shikimori.get_by_id(shiki_ext.external_id)
                                if shiki_item:
                                    franchise_key = shiki_item.get("franchise") or f"single:{shiki_ext.external_id}"
                                    summary = await shikimori.build_franchise_summary(franchise_key)
                            if summary:
                                lines.append(f"  сезонов: {summary.total_seasons}")
                                # Get current season AniList details
                                current_anilist = await anilist.get_anime_by_mal(int(summary.current.get("malId")))
                                status_map = {
                                    "ongoing": "Выходит",
                                    "anons": "Анонсирован",
                                    "released": "Завершён",
                                }
                                status_str = status_map.get(summary.current.get("status"), "Неизвестно")
                                if summary.current.get("status") == "ongoing":
                                    status_str += f" сезон {summary.current_index}" + (f" из {summary.total_seasons}" if summary.total_seasons > 1 else "")
                                elif summary.current.get("status") == "anons":
                                    status_str += f" сезон {summary.current_index}"
                                else:
                                    status_str += " (продолжение не анонсировано)"
                                lines.append(f"  Статус: {status_str}")
                                if current_anilist:
                                    total_episodes = current_anilist.get("episodes")
                                    next_ep = current_anilist.get("nextAiringEpisode")
                                    if next_ep:
                                        airing_at = next_ep.get("airingAt")
                                        if airing_at:
                                            next_date = dt.fromtimestamp(airing_at)
                                            days = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
                                            day_name = days[next_date.weekday()]
                                            lines.append(f"  Следующая серия: {next_date.strftime('%Y-%m-%d')} ({day_name})")
                                        current_ep = next_ep.get("episode", 1) - 1
                                        if total_episodes:
                                            lines.append(f"  Серии сезона: {current_ep} из {total_episodes}")
                                        else:
                                            lines.append(f"  Серии сезона: {current_ep} из ?")
                                    elif not next_ep and total_episodes:
                                        lines.append(f"  Серии сезона: {total_episodes} из {total_episodes}")
                                else:
                                    # No AniList data (fresh announcement), use Shikimori
                                    if summary.current.get("status") == "ongoing":
                                        aired = summary.current.get("episodesAired")
                                        total = summary.current.get("episodes")
                                        if aired is not None and total:
                                            lines.append(f"  Серии сезона: {aired} из {total}")

                        elif m.media_type == "game":
                            lines.append("Игра")
                            platforms = media_resolve.get_game_platforms(s, m.id)
                            tracked = media_resolve.get_user_tracked_platforms(s, user.id, m.id)
                            if platforms:
                                lines.append("")
                                lines.append("Платформы:")
                                for gp in platforms:
                                    st = "✅" if gp.platform in tracked else "⬜"
                                    rd = gp.release_date
                                    rd_str = f" ({rd})" if rd else ""
                                    lines.append(f"  {gp.platform.upper()}{rd_str} {st}")

                        await cb.message.answer("\n".join(lines))
                        return
                    except Exception as e:
                        logging.error(f"details handler error: {e}", exc_info=True)
                        try:
                            await cb.message.answer(f"Ошибка: {e}")
                        except Exception:
                            pass
                        return

                if action == "remove":
                    await cb.answer()
                    try:
                        media_item_id = arg
                        m = s.get(MediaItem, media_item_id)
                        if not m:
                            await cb.message.answer("Элемент не найден.")
                            return
                        remove_watch_item(s, user.id, m.id)
                        await cb.message.answer(f"🗑 Удалено: {display_title(m)}")
                        return
                    except Exception as e:
                        logging.error(f"remove handler error: {e}", exc_info=True)
                        try:
                            await cb.message.answer(f"Ошибка при удалении: {e}")
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
                            full_name = display_title(mi) if mi else cb_name
                        else:
                            # First time adding — search for game by truncated name
                            matching = s.query(MediaItem).filter(
                                MediaItem.media_type == "game",
                                MediaItem.canonical_title_en.ilike(f"%{cb_name}%"),
                            ).limit(1).all()
                            if matching:
                                full_name = display_title(matching[0])
                            else:
                                full_name = cb_name
                        year = int(year_str) if year_str and year_str.isdigit() else None
                        platforms = [{"source": source, "platform_id": platform_id, "release_date": "", "store_url": ""}]
                        item, _ = media_resolve.add_game_to_watchlist(s, user.id, full_name, year, platforms)
                        title_display = display_title(item)
                        await cb.message.answer(f"✅ Добавлено: {title_display} [{source.upper()}]")
                    except Exception as e:
                        logging.error(f"ap callback failed: {e}")
                        await cb.message.answer("Ошибка при добавлении.")
                    return

                item = s.get(MediaItem, arg) if arg else None
                if item is None or action not in ("ca_yes", "ca_no", "wt_keep", "wt_stop"):
                    await cb.answer("Неизвестная кнопка")
                    return
                title = display_title(item)
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
                title = display_title(item)
                if not removed:
                    await message.answer(f"Уже не в списке: {title}")
                else:
                    await message.answer(f"🗑 Удалено из списка: {title}")

        @dp.message(Command("watchlist"))
        async def watchlist_handler(message: Message):
            logging.info(f"watchlist_handler: called by user {message.from_user.id}")
            with db() as s:
                if not _is_allowed(message):
                    return
                user = _get_or_create_user(s, message.from_user.id)
                items, total = list_watch_items(s, user.id)
                if not items:
                    await message.answer("Список отслеживания пуст.")
                    return

                groups = {"tv": [], "movie": [], "anime": [], "game": []}
                for w in items:
                    m = s.get(MediaItem, w.media_item_id)
                    logging.info(f"watchlist: item {w.media_item_id} -> media_type={m.media_type if m else 'None'}")
                    if m and m.media_type in groups:
                        groups[m.media_type].append((w, m))
                logging.info(f"watchlist: groups={ {k: len(v) for k, v in groups.items()} }")

                kb_rows = []

                if groups["tv"]:
                    await message.answer("─── 📺 Сериалы ───")
                    for w, m in groups["tv"]:
                        title = display_title(m)
                        year = f" ({m.year})" if m.year else ""
                        kb_rows = [[
                            InlineKeyboardButton(text="📖 Подробнее", callback_data=f"details:{m.id}"),
                            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"remove:{m.id}"),
                        ]]
                        kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
                        await message.answer(f"• {title}{year}", reply_markup=kb)

                if groups["movie"]:
                    await message.answer("─── 🎬 Фильмы ───")
                    for w, m in groups["movie"]:
                        title = display_title(m)
                        year = f" ({m.year})" if m.year else ""
                        kb_rows = [[
                            InlineKeyboardButton(text="📖 Подробнее", callback_data=f"details:{m.id}"),
                            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"remove:{m.id}"),
                        ]]
                        kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
                        await message.answer(f"• {title}{year}", reply_markup=kb)

                if groups["anime"]:
                    await message.answer("─── 🎌 Аниме ───")
                    for w, m in groups["anime"]:
                        title = display_title(m)
                        year = f" ({m.year})" if m.year else ""
                        kb_rows = [[
                            InlineKeyboardButton(text="📖 Подробнее", callback_data=f"details:{m.id}"),
                            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"remove:{m.id}"),
                        ]]
                        kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
                        await message.answer(f"• {title}{year}", reply_markup=kb)

                if groups["game"]:
                    await message.answer("─── 🎮 Игры ───")
                    game_icons = {"steam": "⌨️", "igdb": "🕹️", "psn": "🎮"}
                    for w, m in groups["game"]:
                        title = display_title(m)
                        year = f" ({m.year})" if m.year else ""
                        platforms = media_resolve.get_game_platforms(s, m.id)
                        tracked = media_resolve.get_user_tracked_platforms(s, user.id, m.id)
                        icons = []
                        for gp in platforms:
                            if gp.platform in tracked:
                                icons.append(game_icons.get(gp.platform, "◈"))
                        icon_str = " ".join(icons) if icons else ""
                        prefix = f"{icon_str} " if icon_str else ""
                        kb_rows = [[
                            InlineKeyboardButton(text="📖 Подробнее", callback_data=f"details:{m.id}"),
                            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"remove:{m.id}"),
                        ]]
                        kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
                        await message.answer(f"• {prefix}{title}{year}", reply_markup=kb)

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
                    title = display_title(item)
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
                    title = display_title(m)
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

        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        scheduler = AsyncIOScheduler()
        # The legacy poll scan and its notifications are switched off; the tracker core replaces them.
        # Events whose send failed stay queued, so retry the queue regularly.
        scheduler.add_job(
            tracker.deliver_pending, "interval",
            seconds=DELIVERY_RETRY_SECONDS,
            misfire_grace_time=30, coalesce=True, max_instances=1,
        )
        # Phase 15: daily database backup at 3 AM
        scheduler.add_job(
            _backup_database, "cron", hour=3, minute=0,
            misfire_grace_time=90,
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
