"""The block «Вход» at the bottom of Settings and its button «Выйти на всех устройствах» (spec 4.4–4.5 of stage 7.2).

The block says when and from which device the last login was (on the owner's clock, `moment_in_words`) and on how many
devices the sign-in is open; the button posts to `/settings/sign-out-everywhere`, which ends every sign-in of
`data/web_login.json` (the last login and the lock stay), clears this cookie and sends the browser to
`/login?out=everywhere`, where the login page says so. No question before it: nothing is lost but a password typed again."""

import logging
from datetime import timezone
from typing import NamedTuple

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

from app.tracker.cards import plural
from app.tracker.moment_words import moment_in_words
from app.web import pages
from app.web.sessions import LastLogin

router = APIRouter()

OUT_EVERYWHERE = "everywhere"  # the value of `out` on the login page after the button
SIGNED_OUT_EVERYWHERE = "Вы вышли на всех устройствах. Войдите снова."
NO_LAST_LOGIN = "Последний вход: сведений нет."
HINT = (
    "Выйдет из приложения везде — на ПК, телефоне и в браузере Telegram. "
    "Затем на каждом устройстве нужно снова ввести пароль."
)


class SignInBlock(NamedTuple):
    last_login: str
    devices: str
    hint: str
    address: str  # of the button


def last_login_line(last: LastLogin | None, words: str) -> str:
    """`words` is the moment of `last` on the owner's clock («сегодня в 14:32»)."""
    if last is None:
        return NO_LAST_LOGIN
    address = f", адрес {last.address}" if last.address else ""
    return f"Последний вход: {words}, {last.device}{address}."


def devices_line(count: int) -> str:
    """«устройстве» for 1, 21, 31… but not 11, 111…; «устройствах» otherwise."""
    return f"Вход открыт на {count} {plural(count, 'устройстве', 'устройствах', 'устройствах')}."


async def sign_in_block(request: Request) -> SignInBlock:
    web = pages.context_of(request)
    last = web.sign_ins.last_login
    words = ""
    if last is not None:
        now = web.now().astimezone(timezone.utc).replace(tzinfo=None)
        try:
            rules = await pages.tracker_of(request).delivery_rules()  # the owner's zone
            words = moment_in_words(rules.local(last.moment), rules.local(now))
        except Exception as exc:  # the block does not take the page down: the moment on the UTC clock
            logging.warning("web: the owner's zone for the block «Вход» cannot be read: %r", exc)
            words = moment_in_words(last.moment, now)
    return SignInBlock(
        last_login_line(last, words), devices_line(web.sign_ins.count), HINT,
        str(request.app.url_path_for("settings_sign_out_everywhere")),
    )


@router.post("/settings/sign-out-everywhere", name="settings_sign_out_everywhere")
@pages.guarded_with_refresh("settings")
async def settings_sign_out_everywhere(request: Request) -> Response:
    """«Выйти на всех устройствах»: every sign-in ends, this one too."""
    ended = await pages.context_of(request).sign_ins.end_all()
    logging.info("web: signed out everywhere (%s sessions)", ended)
    request.session.clear()
    return RedirectResponse(f"/login?out={OUT_EVERYWHERE}", status_code=303)
