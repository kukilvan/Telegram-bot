"""Minimal aiogram bot entry point. Phase 4: watchlist + notes."""

import asyncio
import logging
from contextlib import contextmanager

from sqlalchemy import select

from aiogram import Bot, Dispatcher
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from app.config import get_settings
from app.database.models import ExternalId, MediaItem, User, UserWatchItem
from app.database.session import ensure_data_dir, get_session_factory
from app.providers.tmdb import TMDbProvider
from app.scheduler.polling import poll_item
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


async def _resolve_media_item(session, tmdb_id: int, provider):
    """Return a MediaItem for a TMDb id, creating it (with external id) if needed.

    Returns None when the id is not found on TMDb.
    """
    ext = session.execute(
        select(ExternalId).where(
            (ExternalId.source == "tmdb") &
            (ExternalId.external_id == str(tmdb_id))
        )
    ).scalar_one_or_none()
    if ext is not None:
        return session.get(MediaItem, ext.media_item_id)

    movie = await provider.get_movie_details(tmdb_id)
    if movie and movie.get("title"):
        item = MediaItem(
            media_type="movie",
            canonical_title_en=movie.get("title"),
            year=int(movie["release_date"][:4]) if movie.get("release_date") else None,
            poster_url=(
                f"https://image.tmdb.org/t/p/original{movie['poster_path']}"
                if movie.get("poster_path") else None
            ),
        )
        session.add(item)
        session.flush()  # generate item.id (UUID default) before FK reference
        ext = ExternalId(
            media_item_id=item.id, source="tmdb", external_id=str(tmdb_id)
        )
        session.add(ext)
        session.commit()
        return item

    tv = await provider.get_tv_details(tmdb_id)
    if tv and tv.get("name"):
        item = MediaItem(
            media_type="tv",
            canonical_title_en=tv.get("name"),
            year=int(tv["first_air_date"][:4]) if tv.get("first_air_date") else None,
            poster_url=(
                f"https://image.tmdb.org/t/p/original{tv['poster_path']}"
                if tv.get("poster_path") else None
            ),
        )
        session.add(item)
        session.flush()  # generate item.id (UUID default) before FK reference
        ext = ExternalId(
            media_item_id=item.id, source="tmdb", external_id=str(tmdb_id)
        )
        session.add(ext)
        session.commit()
        return item

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
                item = await _resolve_media_item(s, tmdb_id, tmdb)
                if item is None:
                    await message.answer("Не нашёл этот TMDb id.")
                    return
                added = add_watch_item(s, user.id, item.id)
                title = item.canonical_title_en or "item"
                if added is None:
                    await message.answer(f"Уже в списке отслеживания: {title}")
                else:
                    # Phase 5: create default enabled rules for relevant events on add.
                    for ev_type in ("DIGITAL_DATE_ANNOUNCED", "RUSSIAN_AUDIO_AVAILABLE"):
                        set_rule(s, user.id, item.id, ev_type, True)
                    await message.answer(f"✅ Добавлено: {title}")

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
                item = await _resolve_media_item(s, tmdb_id, tmdb)
                if item is None:
                    await message.answer("Не нашёл этот TMDb id.")
                    return
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
                        await bot.send_message(
                            chat_id=u.telegram_user_id,
                            text=f"\U0001F514 {ev.event_type} \u2192 {title}",
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
