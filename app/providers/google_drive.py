"""Google client of the Google Drive copy: the OAuth sign-in of a desktop client and the Drive API requests that send an archive.

The sign-in is OAuth 2.0 with PKCE (S256) and the scope `drive.file` only (spec 4.2 of stage 7.1, ADR 0012):
- the page: https://accounts.google.com/o/oauth2/v2/auth with `access_type=offline` and `prompt=consent`, so a refresh
  token always comes;
- the code for the tokens: POST https://oauth2.googleapis.com/token, `grant_type=authorization_code`; an access token
  from the refresh token: the same address, `grant_type=refresh_token`;
- the sign-out: POST https://oauth2.googleapis.com/revoke with the refresh token in the form body.
The Drive requests (spec 4.4) see only the files the app made itself (`drive.file`): the folder checked, searched or
made, its listing, the resumable upload in one piece and the delete. Every request has 30 seconds. A failure raises
`GoogleError`; what an answer means is the core's business (`app/tracker/drive_copies.py`). Tokens and codes go in form
bodies or the `Authorization` header, never in an address, so no log line holds them.
"""

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
FILES_URL = "https://www.googleapis.com/drive/v3/files"
UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
SCOPE = "https://www.googleapis.com/auth/drive.file"  # the app sees only the files it made itself
FOLDER_TYPE = "application/vnd.google-apps.folder"
ARCHIVE_TYPE = "application/x-7z-compressed"
TIMEOUT_SECONDS = 30.0
PAGE_SIZE = 1000  # files of one listing: the folder keeps 30 archives
DEFAULT_LIFE_SECONDS = 3600  # an access token's life when Google does not say it


class GoogleError(RuntimeError):
    """Google did not answer, or answered with a failure: `status` is the HTTP status (None without an answer), `error`
    the `error` code of Google's answer (`invalid_grant`…), `reason` the reason of a Drive error
    (`storageQuotaExceeded`, `rateLimitExceeded`…), `cause` the network exception."""

    def __init__(
        self, message: str, status: int | None = None, error: str | None = None, cause: BaseException | None = None,
        reason: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.error = error
        self.reason = reason
        self.cause = cause


@dataclass(frozen=True)
class DriveFile:
    """A file of the folder as Drive lists it; `size` None when Drive gives none."""

    id: str
    name: str
    size: int | None = None


def _quoted(text: str) -> str:
    """A text inside the quotes of a Drive search."""
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _drive_file(body: Any) -> DriveFile:
    """A file record of Drive; one without an id or a name is a failure of Google's answer."""
    if not isinstance(body, dict) or not isinstance(body.get("id"), str) or not isinstance(body.get("name"), str):
        raise GoogleError("Drive answered a file record without an id or a name")
    size = body.get("size")
    try:
        number = int(size) if size is not None else None  # Drive writes the size as a text
    except (TypeError, ValueError):
        number = None
    return DriveFile(body["id"], body["name"], number)


def _address(url: str) -> str:
    """The address without its query, for a message: the query of a search is long and says nothing."""
    return url.split("?", 1)[0]


class GoogleDriveApi:
    """The requests to Google with the owner's own client «Desktop app» (`GOOGLE_DRIVE_CLIENT_ID`, `…_SECRET`)."""

    def __init__(self, client_id: str, client_secret: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.client_id = client_id
        self._client_secret = client_secret
        self._transport = transport  # a fake Google in the tests

    # --- the sign-in -------------------------------------------------------------------------

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

    async def refresh(self, refresh_token: str) -> tuple[str, int]:
        """A new access token for the refresh token and its life in seconds; `invalid_grant` — the access is ended."""
        body = await self._post(TOKEN_URL, {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.client_id,
            "client_secret": self._client_secret,
        })
        token, lasts = body.get("access_token"), body.get("expires_in")
        if not isinstance(token, str) or not token:
            raise GoogleError(f"{TOKEN_URL} answered without an access token (fields: {sorted(body)})")
        return token, lasts if isinstance(lasts, int) and lasts > 0 else DEFAULT_LIFE_SECONDS

    async def revoke(self, token: str) -> None:
        """The token and the access it gives are ended at Google."""
        await self._post(REVOKE_URL, {"token": token})

    async def _post(self, url: str, form: dict[str, str]) -> dict[str, Any]:
        response = await self._send("POST", url, data=form)
        body = self._json(response)
        if not isinstance(body, dict):
            raise GoogleError(f"{url} answered {response.status_code} with no JSON object", status=response.status_code)
        return body

    # --- the Drive requests --------------------------------------------------------------------

    async def folder_alive(self, access: str, folder_id: str) -> bool:
        """Whether the folder of this id is still there and not in the trash; Google's 404 — it is not."""
        try:
            response = await self._send("GET", f"{FILES_URL}/{folder_id}", access, params={"fields": "id,trashed"})
        except GoogleError as exc:
            if exc.status == 404:
                return False
            raise
        body = self._json(response)
        return isinstance(body, dict) and body.get("trashed") is not True

    async def find_folder(self, access: str, name: str) -> str | None:
        """The id of a folder of the app with this name, not in the trash; None — there is none."""
        query = f"name={_quoted(name)} and mimeType={_quoted(FOLDER_TYPE)} and trashed=false"
        files = await self._files(access, query)
        return files[0].id if files else None

    async def create_folder(self, access: str, name: str) -> str:
        """A new folder with this name in the root of My Drive; its id."""
        response = await self._send(
            "POST", FILES_URL, access, params={"fields": "id,name"}, json={"name": name, "mimeType": FOLDER_TYPE}
        )
        return _drive_file(self._json(response)).id

    async def list_folder(self, access: str, folder_id: str) -> list[DriveFile]:
        """The files in the folder, not in the trash."""
        return await self._files(access, f"{_quoted(folder_id)} in parents and trashed=false")

    async def upload(self, access: str, folder_id: str, name: str, content: bytes) -> DriveFile:
        """The file sent into the folder by a resumable upload in one piece: the session, then the bytes to its address."""
        response = await self._send(
            "POST", UPLOAD_URL, access,
            params={"uploadType": "resumable", "fields": "id,name,size"},
            json={"name": name, "parents": [folder_id]},
            headers={"X-Upload-Content-Type": ARCHIVE_TYPE, "X-Upload-Content-Length": str(len(content))},
        )
        address = response.headers.get("location")
        if not address:
            raise GoogleError(f"{UPLOAD_URL} answered {response.status_code} without the upload address")
        sent = await self._send("PUT", address, access, content=content, headers={"Content-Type": ARCHIVE_TYPE})
        return _drive_file(self._json(sent))

    async def delete(self, access: str, file_id: str) -> None:
        """The file deleted for good (not into the trash)."""
        await self._send("DELETE", f"{FILES_URL}/{file_id}", access)

    async def _files(self, access: str, query: str) -> list[DriveFile]:
        response = await self._send(
            "GET", FILES_URL, access,
            params={"q": query, "fields": "files(id,name,size,createdTime)", "pageSize": str(PAGE_SIZE), "spaces": "drive"},
        )
        body = self._json(response)
        files = body.get("files") if isinstance(body, dict) else None
        if not isinstance(files, list):
            raise GoogleError(f"{FILES_URL} answered a listing without files")
        return [_drive_file(item) for item in files]

    # --- one request -----------------------------------------------------------------------------

    async def _send(self, method: str, url: str, access: str | None = None, **request: Any) -> httpx.Response:
        """One request; with `access` it carries the access token. Not a 2xx — `GoogleError` with what the answer says."""
        if access is not None:
            request["headers"] = {**request.get("headers", {}), "Authorization": f"Bearer {access}"}
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, transport=self._transport) as client:
                response = await client.request(method, url, **request)
        except httpx.HTTPError as exc:
            raise GoogleError(f"no answer from {_address(url)}: {type(exc).__name__}", cause=exc) from exc
        if not 200 <= response.status_code < 300:
            error, reason = self._error_of(self._json(response))
            raise GoogleError(
                f"{method} {_address(url)} answered {response.status_code} ({error}, {reason})",
                status=response.status_code, error=error, reason=reason,
            )
        return response

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        try:
            return response.json() if response.content else {}
        except ValueError:
            return None

    @staticmethod
    def _error_of(body: Any) -> tuple[str | None, str | None]:
        """The `error` code and the Drive reason of a failed answer: OAuth writes `{"error": "invalid_grant"}`, Drive
        `{"error": {"status": …, "errors": [{"reason": "storageQuotaExceeded"}]}}`."""
        if not isinstance(body, dict):
            return None, None
        error = body.get("error")
        if isinstance(error, str):
            return error, None
        if not isinstance(error, dict):
            return None, None
        status = error.get("status") if isinstance(error.get("status"), str) else None
        details = error.get("errors")
        first = details[0] if isinstance(details, list) and details and isinstance(details[0], dict) else {}
        reason = first.get("reason") if isinstance(first.get("reason"), str) else None
        return status, reason
