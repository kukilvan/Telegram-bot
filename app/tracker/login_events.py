"""The login report (pure): the types of its two events, their texts and the sample of «Тестовое событие».

`web_login` is a right password, `web_login_locked` the wrong try that begins a lock (spec 6.1 of stage 7.2). Neither has
a title, so the Feed never shows them. The web gives the facts (the device in words, the public address or None, the
key of the fact) and never writes a text; `LoginReports` records the event with the text made here.
"""

WEB_LOGIN = "web_login"
WEB_LOGIN_LOCKED = "web_login_locked"
TYPES = (WEB_LOGIN, WEB_LOGIN_LOCKED)

SAMPLE_DEVICE = "Android, Chrome"
SAMPLE_ADDRESS = "203.0.113.5"  # an address of the range kept for examples
SAMPLE_MOMENT = "сегодня в 14:32"


def dedup_key(event_type: str, unique: str) -> str:
    """One report of each fact: a login by its `sid`, a lock by the end of the lock."""
    return f"{event_type}:{unique}"


def _address_words(address: str | None) -> str:
    return f", адрес {address}" if address else ""


def login_text(device: str, moment: str, address: str | None) -> str:
    return (
        f"🔐 Вход в приложение: {device}, {moment}{_address_words(address)}.\n"
        "Если это были не вы — откройте Настройки и нажмите «Выйти на всех устройствах», затем смените WEB_PASSWORD в .env."
    )


def locked_text(device: str, moment: str, address: str | None) -> str:
    return (
        "⚠️ Вход в приложение закрыт на 15 минут: 5 неверных паролей подряд. "
        f"Последняя попытка: {device}, {moment}{_address_words(address)}.\n"
        "Если это были не вы — смените WEB_PASSWORD в .env."
    )


def text_of(event_type: str, device: str, moment: str, address: str | None) -> str:
    """The text of a report; a type that is no report is a `ValueError`."""
    if event_type == WEB_LOGIN:
        return login_text(device, moment, address)
    if event_type == WEB_LOGIN_LOCKED:
        return locked_text(device, moment, address)
    raise ValueError(event_type)


# (id, menu label, message text) of the sample of «Тестовое событие»
TEST_SAMPLES: list[tuple[str, str, str]] = [
    ("web-login", "Вход в приложение", login_text(SAMPLE_DEVICE, SAMPLE_MOMENT, SAMPLE_ADDRESS)),
]
