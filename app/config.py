"""Application configuration loaded from environment variables."""

from dotenv import load_dotenv
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Central settings. All secrets come from env vars, never hardcoded."""

    # Telegram
    telegram_bot_token: str
    allowed_telegram_user_ids_raw: str = ""  # comma-separated ints, e.g. "123456789,987654321"

    # TMDb
    tmdb_api_key: str

    # IGDB
    igdb_client_id: str

    # KinoPub (OAuth device flow)
    kinopub_client_id: str | None = None
    kinopub_client_secret: str | None = None
    kinopub_access_token: str | None = None

    # PlayStation Store region
    ps_store_region: str = "US"

    @property
    def allowed_telegram_user_ids(self) -> list[int]:
        if not self.allowed_telegram_user_ids_raw:
            return []
        return [int(x.strip()) for x in self.allowed_telegram_user_ids_raw.split(",")]


def get_settings() -> Settings:
    load_dotenv()  # loads .env into os.environ before Settings reads it
    return Settings()
