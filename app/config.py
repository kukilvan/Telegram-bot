"""Application configuration loaded from environment variables."""

import logging
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


def parse_user_ids(raw: str) -> list[int]:
    """Parse "123, 456" into [123, 456]; blank items are skipped, junk raises ValueError."""
    ids = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError:
            raise ValueError("ALLOWED_TELEGRAM_USER_IDS must be comma-separated integers") from None
    return ids


class Settings(BaseSettings):
    """Central settings. All secrets come from env vars, never hardcoded."""

    # Telegram
    telegram_bot_token: str
    # comma-separated ints, e.g. "123456789,987654321"; the env name is ALLOWED_TELEGRAM_USER_IDS
    allowed_telegram_user_ids_raw: str = Field(
        "",
        validation_alias=AliasChoices("ALLOWED_TELEGRAM_USER_IDS", "ALLOWED_TELEGRAM_USER_IDS_RAW"),
    )
    owner_chat_id: str = ""  # Telegram chat ID for the owner's messages; read through `owner_chat`

    # TMDb and its request pacing (AniList and IGDB have their own, fixed in their clients)
    tmdb_api_key: str
    tmdb_min_call_interval: float = 1.5        # seconds between consecutive TMDb calls
    tmdb_max_calls_per_minute: int = 30        # rolling per-minute cap on requests
    tmdb_429_backoff_base_seconds: float = 5.0  # initial wait on HTTP 429 (doubles per retry)
    tmdb_429_max_retries: int = 3              # retries after the first 429

    # IGDB
    igdb_client_id: str = ""
    igdb_client_secret: str = ""

    # Shikimori
    shikimori_base_url: str = "https://shikimori.io"
    shikimori_user_agent: str = "Telegram-Bot"

    # Time zone of the owner's rules when the owner has set none; read through `time_zone_of`
    bot_timezone: str = "UTC"

    @property
    def allowed_telegram_user_ids(self) -> list[int]:
        return parse_user_ids(self.allowed_telegram_user_ids_raw)

    @property
    def owner_chat_id_number(self) -> int | None:
        """OWNER_CHAT_ID as a number; None when it is blank or not a number."""
        try:
            return int(self.owner_chat_id)
        except ValueError:
            return None

    @property
    def owner_chat(self) -> int | None:
        """The one chat for everything meant for the owner: OWNER_CHAT_ID if it is a number, otherwise the first
        allowed user (a private chat id equals the user id); None when there is neither."""
        number = self.owner_chat_id_number
        if number is not None:
            return number
        allowed = self.allowed_telegram_user_ids
        return allowed[0] if allowed else None


def time_zone_of(settings: Settings) -> ZoneInfo:
    """The time zone from BOT_TIMEZONE; when it is not set, UTC and a warning in the log."""
    if "bot_timezone" not in settings.model_fields_set or not settings.bot_timezone.strip():
        logging.warning("BOT_TIMEZONE: часовой пояс не задан, используется UTC")
    return ZoneInfo(settings.bot_timezone.strip() or "UTC")


def get_settings() -> Settings:
    load_dotenv()  # loads .env into os.environ before Settings reads it
    return Settings()
