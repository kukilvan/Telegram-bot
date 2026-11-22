"""Application configuration loaded from environment variables."""

import ipaddress
import logging
import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import idna
from dotenv import load_dotenv
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings

from app.utils.secrets_mask import remember_secrets

DEFAULT_WEB_PORT = 8080


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


_NOT_NAMED = "нужно http:// или https:// в начале"
_NO_HOST = "нет адреса ПК или имени сайта"
_TELEGRAM_REFUSES = (
    "Telegram не открывает такие ссылки — укажите адрес ПК в сети (например, http://192.168.1.124:8080) "
    "или имя сайта с точкой"
)
_IDNA_REFUSES = "имя сайта записано с ошибкой — проверьте буквы и точки"
_BAD_PORT = "порт должен быть числом от 1 до 65535"
_EXTRA = "после адреса не должно быть ничего лишнего: только http(s)://адрес[:порт]"
_HOST_NAME = re.compile(r"[a-z0-9-]+(\.[a-z0-9-]+)+")  # at least one dot, inside the name


@dataclass(frozen=True)
class AppUrl:
    """What `APP_URL` says: `address` in its one form, or no address with the `reason` it is malformed (None for an
    empty line). `host` is the host of a valid address (lower case, ASCII, an IPv6 one without brackets): a name with
    Cyrillic letters is in its IDNA form (`xn--…`) in both, which is what the bot's links, Telegram and the `Host` of a
    browser use. `shown` is the address as written (lower case), for the person; an ASCII address is its own `shown`."""

    address: str | None = None
    reason: str | None = None
    host: str | None = None
    shown: str | None = None


class _NameRefused(ValueError):
    """The name has letters and IDNA does not take it."""


def _host_reads(host: str) -> tuple[str, str] | None:
    """The host in the form Telegram opens (lower case, ASCII) and as written (lower case), or None: an IPv4 address, an
    IPv6 one in brackets, a name with a dot inside, never `localhost` or `*.localhost`. A name with a character outside
    ASCII is turned into its ASCII form by IDNA (UTS 46); one IDNA refuses is a `_NameRefused`."""
    if host.startswith("["):
        inner = host[1:-1] if host.endswith("]") else ""
        try:
            ipaddress.IPv6Address(inner)
        except ValueError:
            return None
        return host.lower(), host.lower()
    shown = host.lower()
    if not host.isascii():
        try:
            host = idna.encode(host, uts46=True).decode("ascii")
        except idna.IDNAError:
            raise _NameRefused from None
    host = host.lower()
    try:
        ipaddress.IPv4Address(host)
        return host, shown
    except ValueError:
        pass
    if host == "localhost" or host.endswith(".localhost"):
        return None
    return (host, shown) if _HOST_NAME.fullmatch(host) else None


def parse_app_url(raw: str) -> AppUrl:
    """The address of the app from `APP_URL`: text in, the address in its one form (scheme and host in lower case, the
    port as written, no `/` at the end) or the first broken rule's reason out. An empty text is no address and no reason."""
    text = raw.strip()
    if not text:
        return AppUrl()
    lowered = text.lower()
    scheme = next((s for s in ("http://", "https://") if lowered.startswith(s)), None)
    if scheme is None:
        return AppUrl(reason=_NOT_NAMED)
    rest = text[len(scheme):]
    end = next((i for i, c in enumerate(rest) if c in "/?#"), len(rest))
    authority, tail = rest[:end], rest[end:]
    host_part = authority.rpartition("@")[2]
    if host_part.startswith("["):  # an IPv6 address: its colons are no port
        close = host_part.find("]")
        host, port = (host_part[:close + 1], host_part[close + 1:]) if close >= 0 else (host_part, "")
    else:
        host, _, port = host_part.partition(":")
        port = f":{port}" if ":" in host_part else ""
    if not host:
        return AppUrl(reason=_NO_HOST)
    try:
        known = _host_reads(host)
    except _NameRefused:
        return AppUrl(reason=_IDNA_REFUSES)
    if known is None:
        return AppUrl(reason=_TELEGRAM_REFUSES)
    if port and not port.startswith(":"):  # something stuck to the closing bracket: «[::1]x»
        return AppUrl(reason=_EXTRA)
    if port:
        number = port[1:]
        if not (number.isascii() and number.isdigit() and 0 < int(number) < 65536):
            return AppUrl(reason=_BAD_PORT)
    if authority != host_part or tail not in ("", "/"):
        return AppUrl(reason=_EXTRA)
    ascii_host, shown = known
    scheme = scheme.lower()
    return AppUrl(f"{scheme}{ascii_host}{port}", None, ascii_host.strip("[]"), f"{scheme}{shown}{port}")


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

    # Password of the web app; without it (or shorter than 8 characters) the login is closed, the bot works as usual
    web_password: str = ""

    # Time zone of the owner's rules when the owner has set none; read through `time_zone_of`
    bot_timezone: str = "UTC"

    # The port of the web on the PC (docker compose maps it); read through `web_port_number`
    web_port: str = ""

    # The address the owner opens the app at from the phone and from Telegram; empty — no address, the bot keeps the cards
    # in the chat. Read through `app_url_reading` (the rules and the reasons: `parse_app_url`)
    app_url: str = ""

    # Addresses and networks whose proxy headers are believed, comma-separated; empty — the headers are ignored. Read
    # through `app.web.proxy.parse_trusted_proxies`
    trusted_proxies: str = ""

    # The Google Drive copy (spec 4.1 of stage 7.1): the password of the archives and the owner's Google client
    # «Desktop app». None is required; whether the copy is on is decided in one place, `DriveSettings.setup`
    backup_password: str = ""
    google_drive_client_id: str = ""
    google_drive_client_secret: str = ""

    @field_validator("web_password", "backup_password", "google_drive_client_id", "google_drive_client_secret", "app_url", "trusted_proxies")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @property
    def web_port_number(self) -> int:
        """WEB_PORT as a number; 8080 (docker compose's default too) when it is blank or not a port."""
        value = self.web_port.strip()
        return int(value) if value.isdigit() and 0 < int(value) < 65536 else DEFAULT_WEB_PORT

    @property
    def app_url_reading(self) -> AppUrl:
        """APP_URL as `parse_app_url` reads it."""
        return parse_app_url(self.app_url)

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
    remember_secrets()  # the log is set up before .env is read: its tokens must join the masked values now
    return Settings()
