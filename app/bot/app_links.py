"""The addresses of the app the bot's links lead to, made from the app address (`APP_URL`); the bot holds them in link mode.

`AppLinks(address)` takes the address in its one form (`app.config.parse_app_url`: no `/` at the end) and appends the
paths of the pages. A bot without `AppLinks` (`None`) is in chat mode: it keeps the cards in the chat.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AppLinks:
    address: str

    def card(self, title_id: int) -> str:
        return f"{self.address}/titles/{title_id}"

    def home(self) -> str:
        return f"{self.address}/"

    def list(self) -> str:
        return f"{self.address}/list"

    def settings(self) -> str:
        return f"{self.address}/settings"
