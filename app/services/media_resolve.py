"""Unified game resolver — Phase 22.

Searches games across Steam/IGDB/PSN, groups by title+year,
and manages MediaItem + GamePlatform records.

Fully isolated from the existing add_handler — old /add flow unchanged.
"""

import asyncio
import json
import logging
import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.database.models import GamePlatform, MediaAlias, MediaItem, UserWatchItem

logger = logging.getLogger(__name__)


async def search_games(query: str, limit: int = 10) -> list[dict]:
    """Search games across all platforms. Returns unified results grouped by title+year.

    Returns:
        List of dicts:
        {
            "title": "Game Name",
            "year": 2026,
            "platforms": [
                {"source": "steam", "id": "2514330", "release_date": "2026-09-21", "name": "The Rabbit Haul"},
                {"source": "igdb", "id": "265277", "release_date": "2026-09-21", "name": "The Rabbit Haul"},
            ]
        }
    """
    from app.providers.igdb import IGDBProvider
    from app.providers.psn import PSNProvider
    from app.providers.steam import SteamProvider

    steam = SteamProvider()
    igdb = IGDBProvider()
    psn = PSNProvider()

    try:
        results = await asyncio.gather(
            steam.search_games(query, limit=limit),
            igdb.search_games(query, limit=limit),
            psn.search_games(query, limit=limit),
        )
    finally:
        await steam.close()
        await igdb.aclose()
        await psn.close()

    steam_results, igdb_results, psn_results = results

    # Normalize all results to a common format
    all_items = []

    for item in steam_results:
        all_items.append({
            "title": item.get("name", ""),
            "year": _extract_year_from_date(item.get("release_date", "")),
            "platform": "steam",
            "platform_id": str(item.get("appid", "")),
            "release_date": item.get("release_date", {}).get("date", "") if isinstance(item.get("release_date"), dict) else item.get("release_date", ""),
            "name": item.get("name", ""),
            "store_url": f"https://store.steampowered.com/app/{item.get('appid', '')}/",
        })

    for item in igdb_results:
        all_items.append({
            "title": item.get("name", ""),
            "year": _extract_year_from_date(item.get("first_release_date")),
            "platform": "igdb",
            "platform_id": str(item.get("id", "")),
            "release_date": _extract_year_from_date(item.get("first_release_date")),
            "name": item.get("name", ""),
            "store_url": "",
        })

    for item in psn_results:
        all_items.append({
            "title": item.get("name", ""),
            "year": None,
            "platform": "psn",
            "platform_id": item.get("id", ""),
            "release_date": "",
            "name": item.get("name", ""),
            "store_url": item.get("url", ""),
        })

    # Group by (title, year)
    groups: dict[tuple[str, Optional[int]], dict] = {}
    for item in all_items:
        key = (item["title"], item["year"])
        if key not in groups:
            groups[key] = {
                "title": item["title"],
                "year": item["year"],
                "platforms": [],
            }
        groups[key]["platforms"].append({
            "source": item["platform"],
            "id": item["platform_id"],
            "release_date": item["release_date"],
            "name": item["name"],
            "store_url": item["store_url"],
        })

    return list(groups.values())


def _extract_year_from_date(date_value) -> Optional[int]:
    """Extract year from various date formats."""
    if not date_value:
        return None
    if isinstance(date_value, int):
        return date_value
    s = str(date_value).strip()
    if not s:
        return None
    # ISO date: "2026-09-21"
    if "-" in s:
        return int(s.split("-")[0])
    # Already a 4-digit year
    if s.isdigit() and len(s) == 4:
        return int(s)
    return None


def resolve_existing_game(session: Session, title: str, year: Optional[int] = None) -> Optional[MediaItem]:
    """Find an existing MediaItem by title (and optionally year).

    Case-insensitive match on canonical_title_en.
    """
    q = session.query(MediaItem).filter(
        MediaItem.canonical_title_en.ilike(title)
    )
    if year:
        q = q.filter(MediaItem.year == year)
    return q.first()


def get_game_platforms(session: Session, media_item_id: str) -> list[GamePlatform]:
    """Get all GamePlatform records for a MediaItem."""
    return session.query(GamePlatform).filter(
        GamePlatform.media_item_id == media_item_id
    ).order_by(GamePlatform.platform).all()


def get_user_tracked_platforms(session: Session, user_id: int, media_item_id: str) -> list[str]:
    """Get the list of tracked platforms for a user's watchlist entry."""
    watch_item = session.query(UserWatchItem).filter(
        UserWatchItem.user_id == user_id,
        UserWatchItem.media_item_id == media_item_id,
    ).first()
    if not watch_item or not watch_item.tracked_platforms:
        return []
    try:
        return json.loads(watch_item.tracked_platforms)
    except (json.JSONDecodeError, TypeError):
        return []


def add_game_to_watchlist(
    session: Session,
    user_id: int,
    title: str,
    year: Optional[int],
    platforms: list[dict],
) -> tuple[MediaItem, list[GamePlatform]]:
    """Create or update a MediaItem and its GamePlatform records.

    Args:
        session: DB session
        user_id: Telegram user ID
        title: Game title
        year: Release year (optional)
        platforms: List of platform dicts with 'source', 'platform_id', 'release_date', 'store_url'

    Returns:
        (MediaItem, [GamePlatform])
    """
    # Check if MediaItem already exists
    existing = resolve_existing_game(session, title, year)

    if existing:
        logger.info(f"Found existing MediaItem {existing.id} for '{title}' ({year})")
    else:
        existing = MediaItem(
            id=str(uuid.uuid4()),
            media_type="game",
            canonical_title_en=title,
            year=year,
        )
        session.add(existing)
        session.flush()
        logger.info(f"Created new MediaItem {existing.id} for '{title}' ({year})")

    # Add GamePlatform records
    game_platforms = []
    for p in platforms:
        gp = GamePlatform(
            media_item_id=existing.id,
            platform=p["source"],
            platform_id=p["platform_id"],
            release_date=p.get("release_date") or None,
            store_url=p.get("store_url") or None,
        )
        session.add(gp)
        game_platforms.append(gp)

    # Add to watchlist if not already there
    existing_watch = session.query(UserWatchItem).filter(
        UserWatchItem.user_id == user_id,
        UserWatchItem.media_item_id == existing.id,
    ).first()

    if not existing_watch:
        tracked = [p["source"] for p in platforms]
        existing_watch = UserWatchItem(
            user_id=user_id,
            media_item_id=existing.id,
            tracked_platforms=json.dumps(tracked),
        )
        session.add(existing_watch)
        logger.info(f"Added '{title}' to user {user_id}'s watchlist")
    else:
        # Update tracked_platforms
        existing_platforms = get_user_tracked_platforms(session, user_id, existing.id)
        for p in platforms:
            if p["source"] not in existing_platforms:
                existing_platforms.append(p["source"])
                gp = GamePlatform(
                    media_item_id=existing.id,
                    platform=p["source"],
                    platform_id=p["platform_id"],
                    release_date=p.get("release_date") or None,
                    store_url=p.get("store_url") or None,
                )
                session.add(gp)
        existing_watch.tracked_platforms = json.dumps(existing_platforms)

    return existing, game_platforms
