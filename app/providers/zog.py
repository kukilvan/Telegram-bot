"""ZoG client: one game page of zoneofgames.ru as text.

Public pages, no key, no API (ADR 0016). Only the page of one game is asked — `GET
https://www.zoneofgames.ru/games/<page>/` — at most four to find a page, two games a polling pass, each game once a
week (spec 5.6 of stage 9.1b); the pace is the caller's. The `User-Agent` names the program and its pace, never the
owner. Redirects are not followed: any answer but 200 is a failure (`ZogError`), and so is a timeout or no connection.
A page ZoG does not have still answers 200 (its title is «Ошибка»): what a page means is the business of
`app/tracker/sources/zog_pages.py`. The body is decoded from `windows-1251`, the encoding of the site.
"""

import logging
import re

import httpx

logger = logging.getLogger(__name__)

PAGE_URL = "https://www.zoneofgames.ru/games/{page}/"
USER_AGENT = "release-tracker (personal game tracker; one page per game a week)"
TIMEOUT_SECONDS = 10.0
ENCODING = "windows-1251"
_PAGE = re.compile(r"[a-z0-9_]+")


class ZogError(RuntimeError):
    """ZoG could not give the page: `status` — the HTTP status of an answer that is not 200, `cause` — the network
    exception (a timeout, no connection)."""

    def __init__(self, message: str, status: int | None = None, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.cause = cause


class ZogProvider:
    """ZoG client; `transport` — a test's fake transport (None: the network)."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS, follow_redirects=False, headers={"User-Agent": USER_AGENT}, transport=transport
        )
        self.call_count = 0

    async def page(self, page: str) -> str:
        """The text of the game page `page` (`[a-z0-9_]+`, else ValueError). An answer that is not 200 or a network
        failure raises `ZogError`."""
        if not _PAGE.fullmatch(page):
            raise ValueError(f"not a ZoG page address: {page!r}")
        self.call_count += 1
        try:
            response = await self._client.get(PAGE_URL.format(page=page))
        except httpx.HTTPError as error:
            logger.info("ZoG page %s failed: %s", page, type(error).__name__)
            raise ZogError(f"ZoG page {page}: {type(error).__name__}", cause=error) from error
        if response.status_code != 200:
            raise ZogError(f"ZoG page {page}: HTTP {response.status_code}", status=response.status_code)
        return response.content.decode(ENCODING, errors="replace")

    async def close(self) -> None:
        await self._client.aclose()
