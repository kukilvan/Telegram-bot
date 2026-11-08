"""Google client of the Google Drive copy: the address of the sign-in page and the requests of the OAuth sign-in of a desktop client.

The sign-in is OAuth 2.0 with PKCE (S256) and the scope `drive.file` only (spec 4.2 of stage 7.1, ADR 0012):
- the page: https://accounts.google.com/o/oauth2/v2/auth with `access_type=offline` and `prompt=consent`, so a refresh
  token always comes;
- the code for the tokens: POST https://oauth2.googleapis.com/token, `grant_type=authorization_code`;
- the sign-out: POST https://oauth2.googleapis.com/revoke with the refresh token in the form body.
Every request has 30 seconds. A failure raises `GoogleError`; what an answer means is the core's business
(`app/tracker/google_drive.py`). Tokens and codes go in form bodies, never in an address, so no log line holds them.
"""

from typing import Any
from urllib.parse import urlencode

import httpx

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
SCOPE = "https://www.googleapis.com/auth/drive.file"  # the app sees only the files it made itself
TIMEOUT_SECONDS = 30.0


class GoogleError(RuntimeError):
    """Google did not answer, or answered with a failure: `status` is the HTTP status (None without an answer), `error`
    the `error` field of Google's answer (`invalid_grant`…), `cause` the network exception."""

    def __init__(
        self, message: str, status: int | None = None, error: str | None = None, cause: BaseException | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.error = error
        self.cause = cause


class GoogleDriveApi:
    """The requests to Google with the owner's own client «Desktop app» (`GOOGLE_DRIVE_CLIENT_ID`, `…_SECRET`)."""

    def __init__(self, client_id: str, client_secret: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.client_id = client_id
        self._client_secret = client_secret
        self._transport = transport  # a fake Google in the tests

    def sign_in_address(self, redirect_uri: str, state: str, challenge: str) -> str:
        """The address of Google's sign-in page that returns to `redirect_uri` with `state` and a code for `challenge`."""
        return AUTH_URL + "?" + urlencode({
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        })

    async def exchange_code(self, code: str, redirect_uri: str, verifier: str) -> dict[str, Any]:
        """The answer of Google to the code of a sign-in: a JSON object (`refresh_token`, `access_token`, …)."""
        return await self._post(TOKEN_URL, {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": self.client_id,
            "client_secret": self._client_secret,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        })

    async def revoke(self, token: str) -> None:
        """The token and the access it gives are ended at Google."""
        await self._post(REVOKE_URL, {"token": token})

    async def _post(self, url: str, form: dict[str, str]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, transport=self._transport) as client:
                response = await client.post(url, data=form)
        except httpx.HTTPError as exc:
            raise GoogleError(f"no answer from {url}: {type(exc).__name__}", cause=exc) from exc
        try:
            body = response.json() if response.content else {}
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise GoogleError(f"{url} answered {response.status_code} with no JSON object", status=response.status_code)
        if response.status_code != 200:
            error = body.get("error")
            error = error if isinstance(error, str) else None
            raise GoogleError(f"{url} answered {response.status_code} ({error})", status=response.status_code, error=error)
        return body
