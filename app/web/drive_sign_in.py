"""The sign-in and the sign-out of the Google Drive copy from Settings: «Подключить Google Drive», Google's return and «Отключить Google Drive».

`GET /settings/google-drive/connect` sends the owner to Google's page (or back to Settings with a notice), Google sends
them back to `GET /settings/google-drive/callback` (or, with the switch `DRIVE_REDIRECT` on `ROOT`, to the Feed's
address, which hands the answer here), and `POST /settings/google-drive/disconnect` ends the connection. Every rule is
the core's (`Tracker.drive_sign_in`, `drive_signed_in`, `drive_sign_out`); the pages are behind the sign-in like every
other. Rules: section 4.2 of the spec of stage 7.1.
"""

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

from app.tracker.core import DRIVE_CALLBACK_PATH
from app.web import pages

GOOGLE_ANSWER = frozenset({"code", "error"})  # with `state`, the query Google sends the owner back with

router = APIRouter()


def _to_settings(request: Request, notice: str) -> Response:
    if notice:
        pages.notify(request, notice)
    return RedirectResponse(str(request.app.url_path_for("settings")), status_code=303)


def is_google_answer(request: Request) -> bool:
    """Whether the request is Google sending the owner back (the Feed's address asks it under the switch `ROOT`)."""
    query = request.query_params
    return "state" in query and not GOOGLE_ANSWER.isdisjoint(query.keys())


async def finish(request: Request) -> Response:
    """Google's answer goes to the core; Settings shows its notice."""
    notice = await pages.tracker_of(request).drive_signed_in(dict(request.query_params))
    return _to_settings(request, notice)


@router.get("/settings/google-drive/connect", name="settings_drive_connect")
@pages.guarded_with_refresh("settings")
async def connect(request: Request) -> Response:
    """«Подключить Google Drive»: the page opened at its `Host` decides whether the sign-in may begin here."""
    step = await pages.tracker_of(request).drive_sign_in(request.headers.get("host", ""))
    if step.address:
        return RedirectResponse(step.address, status_code=303)
    return _to_settings(request, step.notice)


@router.get(DRIVE_CALLBACK_PATH, name="settings_drive_callback")
@pages.guarded_with_refresh("settings")
async def callback(request: Request) -> Response:
    return await finish(request)


@router.post("/settings/google-drive/disconnect", name="settings_drive_disconnect")
@pages.guarded_with_refresh("settings")
async def disconnect(request: Request) -> Response:
    """«Отключить Google Drive»."""
    return _to_settings(request, await pages.tracker_of(request).drive_sign_out())
