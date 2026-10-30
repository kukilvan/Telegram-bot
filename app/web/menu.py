"""The menu of the app and the one list of the addresses that need no sign-in. Every section is a page of its own module."""

from typing import NamedTuple


class Section(NamedTuple):
    address: str
    code: str  # the name in code (from CONTEXT.md); it names the route
    label: str


class OpenAddress(NamedTuple):
    name: str  # a name ending in "/" is a folder: everything under it
    always: bool  # open even when no password is set (the service ones: Docker and the styles are needed always);
    # `/login` and `/logout` are not — without a password they say «sign-in is not configured»


SECTIONS = (
    Section("/", "feed", "Лента"),
    Section("/list", "list", "Список"),
    Section("/archive", "archive", "Архив"),
    Section("/search", "search", "Поиск"),
    Section("/settings", "settings", "Настройки"),
)
# The one list of the addresses that need no sign-in; a page added later is closed without a word here
OPEN_ADDRESSES = (
    OpenAddress("/health", True),
    OpenAddress("/static/", True),
    OpenAddress("/login", False),
    OpenAddress("/logout", False),
)
