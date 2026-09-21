"""Application configuration loaded from environment variables."""

from dotenv import load_dotenv
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Central settings. All secrets come from env vars, never hardcoded."""

    # Telegram
    telegram_bot_token: str
    allowed_telegram_user_ids_raw: str = ""  # comma-separated ints, e.g. "123456789,987654321"
    owner_chat_id: str = ""  # Telegram chat ID for error notifications

    # TMDb
    tmdb_api_key: str

    # TMDb adaptive polling tuning (Phase 7.5)
    tmdb_min_call_interval: float = 1.5        # seconds between consecutive TMDb calls
    tmdb_max_calls_per_minute: int = 30       # rolling per-minute cap on requests
    tmdb_429_backoff_base_seconds: float = 5.0  # initial wait on HTTP 429 (doubles per retry)
    tmdb_429_max_retries: int = 3             # retries after the first 429
    poll_scan_interval_seconds: int = 120     # how often the scheduler scans for due items

    # IGDB
    igdb_client_id: str = ""
    igdb_client_secret: str = ""

    # KinoPub (OAuth device flow)
    kinopub_client_id: str | None = None
    kinopub_client_secret: str | None = None
    kinopub_access_token: str | None = None

    # RAWG API (for PSN game search)
    rawg_api_key: str = ""

    # PlayStation Store region
    ps_store_region: str = "il"

    # Steam Store region
    steam_country_code: str = "IL"

    @property
    def allowed_telegram_user_ids(self) -> list[int]:
        if not self.allowed_telegram_user_ids_raw:
            return []
        return [int(x.strip()) for x in self.allowed_telegram_user_ids_raw.split(",")]


def get_settings() -> Settings:
    load_dotenv()  # loads .env into os.environ before Settings reads it
    return Settings()
