"""Minimal aiogram bot entry point. Phase 4: watchlist + notes."""

import asyncio
import logging
from contextlib import contextmanager
from datetime import date

from sqlalchemy import delete, select

from aiogram import Bot, Dispatcher
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.domain.events import pre_add_check
from app.config import get_settings
from app.database.models import (
    ExternalId,
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
from app.database.session import ensure_data_dir, get_session_factory
from app.providers.tmdb import TMDbProvider
from app.scheduler.polling import _fetch_tmdb_state, poll_item, _store_state
from app.services.notes import create_or_update_note, list_notes
from app.services.notifications import get_enabled_rules, set_rule
from app.services.watchlist import (
    add_watch_item,
    get_media_item_by_external_id,
    list_watch_items,
    remove_watch_item,
)


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


async def _lookup_tmdb_details(provider, tmdb_id: int):
    """Probe BOTH TMDb endpoints for one numeric id.

    TMDb shares a single id space across movies and TV shows, so the same
    number can legitimately resolve to both /movie/{id} and /tv/{id}.
    Returns (movie_details or None, tv_details or None).
    """
    movie = await provider.get_movie_details(tmdb_id)
    tv = await provider.get_tv_details(tmdb_id)
    return (
        movie if movie and movie.get("title") else None,
        tv if tv and tv.get("name") else None,
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


async def _resolve_media_for_add(session, tmdb_id: int, provider):
    """Resolve a TMDb id for the /add flow.

    Returns one of:
      ("item", MediaItem)           — unambiguous (existing row or single hit)
      ("pick", movie_details, tv_d) — both endpoints live: user must choose
      ("none", None)                — nothing found on TMDb
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

    movie, tv = await _lookup_tmdb_details(provider, tmdb_id)
    hits: dict[str, dict] = {}
    if movie:
        hits["movie"] = movie
    if tv:
        hits["tv"] = tv
    if not hits:
        return ("none", None)

    matching = [m for m in ext_items if m.media_type in hits]
    if len(matching) == 1:
        # Existing item (created earlier via /add or pick button) matches a hit.
        return ("item", matching[0])
    if "movie" in hits and "tv" in hits:
        logging.info(f"TMDb id {tmdb_id} collides across movie+TV; sending pick prompt")
        return ("pick", movie, tv)
    media_type, details = next(iter(hits.items()))
    # Single live endpoint: create the item, self-healing stale wrong-type rows.
    logging.info(f"TMDb id {tmdb_id}: single '{media_type}' hit; creating item")
    return ("item", _ensure_media_item(session, tmdb_id, details, media_type))


async def _perform_add_flow(s, tmdb, item: MediaItem, user_id: int, sender):
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
    decision = pre_add_check(state, item.media_type, date.today().isoformat())
    status_line = _format_status_line(decision)

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
    """Default enabled notification rules created on /add (Phases 5/7)."""
    if media_type == "tv":  # anime shares the TMDb flow in later phases
        return ("NEW_SEASON_ANNOUNCED", "ALL_EPISODES_OUT")
    return ("DIGITAL_DATE_ANNOUNCED", "RUSSIAN_AUDIO_AVAILABLE")


def _format_status_line(decision) -> str | None:
    """One-line human summary of the current release state (for /add messages)."""
    if decision.code == "released":
        return f"Дата цифрового релиза уже известна: {decision.date} — уже вышел"
    if decision.code == "upcoming":
        return f"Цифровой релиз ожидается: {decision.date}"
    if decision.code == "season_complete":
        return f"Все серии сезона {decision.season} уже вышли ({decision.aired}/{decision.total})"
    if decision.code == "airing":
        if not decision.aired:
            return f"Сезон {decision.season} анонсирован, серий ещё не вышло"
        extra = f", {decision.aired}/{decision.total} серий вышли" if decision.total else ""
        return f"Идёт сезон {decision.season}{extra}"
    return None


async def main() -> None:
    settings = get_settings()
    logging.info("Starting bot...")

    dp = Dispatcher()
    tmdb = TMDbProvider()
    ensure_data_dir()
    session_factory = get_session_factory()  # sessionmaker; call it to create a Session

    @contextmanager
    def db():
        s = session_factory()
        try:
            yield s
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

            movie_results = await tmdb.search_movie(query)
            tv_results = await tmdb.search_tv(query)

            if not movie_results and not tv_results:
                await message.answer("Ничего не найдено.")
                return

            lines = []
            for r in movie_results[:5]:
                name = r.get("title", "Unknown")
                year = (r.get("first_air_date") or "")[:4] if r.get("first_air_date") else ""
                lines.append(f"🎬 {name} ({year}) [id={r['id']}]")

            for r in tv_results[:5]:
                name = r.get("name", "Unknown")
                year = (r.get("first_air_date") or "")[:4] if r.get("first_air_date") else ""
                lines.append(f"📺 {name} ({year}) [id={r['id']}]")

            await message.answer("\n".join(lines) or "Ничего не найдено.")

        @dp.message(Command("add"))
        async def add_handler(message: Message):
            parts = message.text.split(maxsplit=1)
            if len(parts) < 2:
                await message.answer("Использование: /add <tmdb_id>")
                return
            try:
                tmdb_id = int(parts[1])
            except ValueError:
                await message.answer("Нужно число TMDb id, например: /add 841")
                return
            with db() as s:
                if not _is_allowed(message):
                    return
                user = _get_or_create_user(s, message.from_user.id)
                result = await _resolve_media_for_add(s, tmdb_id, tmdb)
                kind = result[0]
                if kind == "none":
                    await message.answer("Не нашёл этот TMDb id.")
                    return
                if kind == "pick":
                    movie_d, tv_d = result[1], result[2]
                    kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text=f"🎬 {movie_d.get('title', 'фильм')}", callback_data=f"pick_movie:{tmdb_id}")],
                        [InlineKeyboardButton(text=f"📺 {tv_d.get('name', 'сериал')}", callback_data=f"pick_tv:{tmdb_id}")],
                    ])
                    await message.answer(
                        "Этот TMDb id совпадает с двумя произведениями. Какой добавить?",
                        reply_markup=kb,
                    )
                    return
                item = result[1]
                await _perform_add_flow(s, tmdb, item, user.id, message)

        @dp.callback_query()
        async def confirm_handler(cb: CallbackQuery):
            """Inline-button actions from the /add confirmation flow."""
            data = cb.data or ""
            action, _, arg = data.partition(":")
            with db() as s:
                if not _is_allowed(cb):
                    return
                user = _get_or_create_user(s, cb.from_user.id)

                if action in ("pick_movie", "pick_tv"):
                    try:
                        tmdb_id = int(arg)
                    except ValueError:
                        await cb.answer("Неизвестная кнопка")
                        return
                    media_type = "movie" if action == "pick_movie" else "tv"
                    details = (
                        await tmdb.get_movie_details(tmdb_id)
                        if media_type == "movie"
                        else await tmdb.get_tv_details(tmdb_id)
                    )
                    valid = bool(
                        details and (details.get("title") or details.get("name"))
                    )
                    if not valid:
                        await cb.answer()
                        await cb.message.answer(f"TMDb не вернул данные для id {tmdb_id}.")
                        return
                    item = _ensure_media_item(s, tmdb_id, details, media_type)
                    logging.info(f"pick_{media_type} {tmdb_id}: resolved to item {item.id}")
                    await cb.answer()
                    await _perform_add_flow(s, tmdb, item, user.id, cb.message)
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
                    # Store the fetched state as baseline: already-known past dates /
                    # aired seasons must NOT retroactively trigger notifications.
                    _store_state(s, item.id, "tmdb", state)
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
                if kind == "pick":
                    await message.answer(
                        "Этот TMDb id совпадает с фильмом и сериалом. "
                        "Сначала добавьте его через /add, выбрав нужное произведение."
                    )
                    return
                item = result[1]
                create_or_update_note(s, user.id, item.id, note_text)
                title = item.canonical_title_en or "item"
                await message.answer(f"📝 Заметка для {title}: {note_text}")

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

        async def _run_polling_cycle():
            """One adaptive polling cycle for all watch items (Phase 5)."""
            with db() as s:
                rows = s.execute(select(UserWatchItem)).scalars().all()
                for w in rows:
                    item = s.get(MediaItem, w.media_item_id)
                    if item is None:
                        continue
                    events = await poll_item(s, tmdb, item, user_id=w.user_id)
                    for ev in events:
                        u = s.execute(select(User).where(User.id == w.user_id)).scalar_one_or_none()
                        if u is None:
                            continue
                        title = item.canonical_title_en or "item"
                        date = ev.payload.get("date")
                        season = ev.payload.get("season")
                        if date:
                            text = f"\U0001F514 {ev.event_type} \u2192 {title} ({date})"
                        elif season is not None:
                            text = f"\U0001F4FA {ev.event_type} \u2192 {title}, сезон {season}"
                        else:
                            text = f"\U0001F514 {ev.event_type} \u2192 {title}"
                        await bot.send_message(
                            chat_id=u.telegram_user_id,
                            text=text,
                        )

        # Phase 5: run one polling cycle at startup + schedule adaptive re-polls.
        await _run_polling_cycle()

        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        scheduler = AsyncIOScheduler()
        scheduler.add_job(_run_polling_cycle, "interval", seconds=600)  # every 10 min
        scheduler.start()

        # Long polling (for VPS deployment without webhook setup)
        await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
