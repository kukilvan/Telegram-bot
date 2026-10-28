"""The menu of the app and the one list of the addresses that need no sign-in. The sections that are not built yet are
stubs here; a section that becomes a page gets its own module and its phrase goes."""

from typing import NamedTuple

from fastapi import APIRouter, Request, Response

from app.web import pages


class Section(NamedTuple):
    address: str
    code: str  # the name in code (from CONTEXT.md); it names the route
    label: str
    phrase: str | None  # the one phrase of the stub until the section is built; None: the section has a page of its own


class OpenAddress(NamedTuple):
    name: str  # a name ending in "/" is a folder: everything under it
    always: bool  # open even when no password is set (the service ones: Docker and the styles are needed always);
    # `/login` and `/logout` are not — without a password they say «sign-in is not configured»


SECTIONS = (
    Section("/", "feed", "Лента", "Скоро будет: что выходит в ближайшие дни и что вышло недавно (часть 5.3)"),
    Section("/list", "list", "Список", None),
    Section(
        "/archive", "archive", "Архив",
        "Скоро будет: поиск и сортировка по оценке (часть 5.3). "
        "Пока просмотренное и брошенное — в Списке, фильтр «Просмотрено» или «Бросил»",
    ),
    Section("/search", "search", "Поиск", None),
    Section("/settings", "settings", "Настройки", "Скоро будет: часовой пояс, рабочие дни, час сводки, тихие часы (часть 5.4)"),
)
# The one list of the addresses that need no sign-in; a page added later is closed without a word here
OPEN_ADDRESSES = (
    OpenAddress("/health", True),
    OpenAddress("/static/", True),
    OpenAddress("/login", False),
    OpenAddress("/logout", False),
)

router = APIRouter()


def _add_stub(section: Section) -> None:
    @router.get(section.address, name=section.code)
    async def stub(request: Request) -> Response:
        return await pages.page(request, "section.html", current=section.address, heading=section.label, phrase=section.phrase)


for section in SECTIONS:
    if section.phrase is not None:
        _add_stub(section)
