"""The web app (ADR 0004): a thin shell over the tracker core, served by uvicorn in the bot's process (ADR 0007)."""

from app.web.app import create_web_app
from app.web.auth import MIN_PASSWORD_LENGTH
from app.web.server import web_server

__all__ = ["MIN_PASSWORD_LENGTH", "create_web_app", "web_server"]
