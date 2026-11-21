"""PlayStation Store client: one `HEAD` request that says whether a page of the store is there.

Public pages, no key. Only the address of a concept is asked and only at a click on the link of the card (spec 1.4 of
stage 9.1b); no price or text is read (ADR 0009): the store answers `200` for a concept it has and a redirect to
`/<locale>/error?conceptId=…` for one it does not have. The redirect is not followed — it is the answer.
"""

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 5.0


class PlayStationError(RuntimeError):
    """The store could not be asked: a timeout or no connection."""


@dataclass(frozen=True)
class PageAnswer:
    """What the store answered to `HEAD`: the status and the `Location` of a redirect (empty: none)."""

    status: int
    location: str = ""


class PlayStationProvider:
    """PlayStation Store client."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=False)

    async def head(self, url: str) -> PageAnswer:
        """The answer of the store to `HEAD url`, redirects not followed. A network failure raises `PlayStationError`;
        any status is an answer."""
        try:
            response = await self._client.head(url)
        except httpx.HTTPError as error:
            logger.info("PlayStation Store HEAD failed: %s", type(error).__name__)
            raise PlayStationError(type(error).__name__) from error
        return PageAnswer(response.status_code, response.headers.get("location", ""))

    async def close(self) -> None:
        await self._client.aclose()
