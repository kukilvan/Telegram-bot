"""The line of Settings about the app address (`APP_URL`) and the hint under it (spec 1.2 of stage 7.2); pure.

Three lines by what `app.config.parse_app_url` said: an address, none, or a malformed one with its reason. A hint comes
only with an address: a private home-network address while the web is open to this PC alone, and `127.0.0.1`, which a
phone cannot open.
"""

from typing import NamedTuple

from app.config import AppUrl
from app.web.hosts import is_private_ipv4

OPEN_TO_NETWORK = "0.0.0.0"  # the value of WEB_HOST that opens the web to the home network


class AddressNote(NamedTuple):
    line: str
    hint: str  # empty: no hint


def address_note(app_url: AppUrl, web_host: str) -> AddressNote:
    """The line and the hint for the state of `APP_URL`; `web_host` is the value of the environment variable WEB_HOST."""
    if app_url.address is None:
        if app_url.reason is None:
            return AddressNote(
                "Адрес приложения не задан (строка APP_URL в .env): кнопки «Карточка» показывают карточку в чате.", ""
            )
        return AddressNote(
            f"Адрес приложения в .env (APP_URL) записан с ошибкой: {app_url.reason}. "
            "Пока кнопки «Карточка» показывают карточку в чате.",
            "",
        )
    line = f"Адрес приложения: {app_url.address}. Кнопки «Карточка» в сообщениях бота открывают его."
    if app_url.host == "127.0.0.1":
        hint = "Адрес 127.0.0.1 открывается только на этом ПК: на телефоне кнопки не откроются."
    elif is_private_ipv4(app_url.host or "") and web_host.strip() != OPEN_TO_NETWORK:
        hint = (
            "Адрес — в домашней сети, а приложение открыто только этому ПК: "
            "добавьте в .env строку WEB_HOST=0.0.0.0 и запустите .\\start-bot.ps1."
        )
    else:
        hint = ""
    return AddressNote(line, hint)
