"""The two forms of Settings under «Бот в Telegram»: «Тестовое событие» and «Проверка правил доставки» (spec 3 of stage 7.2).

`POST /settings/test-event` sends the chosen sample at once, whatever the hour; `POST /settings/delivery-check` sends
«Сериал: две серии подряд» as if a chosen moment of the week were now and says what the delivery rules did (the logic is
`Tracker.delivery_check`; the sentences are here). With HTMX the answer is a fragment for the line under the form and
the page stays where it is; without it the answer is the notice of the page after a `303`. An unknown sample or moment
(an old page) is a `400` with its sentence on a page of its own, and for HTMX the same sentence as a fragment with a
`200`: HTMX 2 does not show a `4xx`. Both forms exist in both modes of the bot."""

from typing import NamedTuple

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

from app.tracker.core import DELIVERY_CHECKS, CheckOutcome
from app.web import pages

router = APIRouter()

SAMPLE_SENT = "Отправлено — посмотрите в Telegram."
SAMPLE_NOT_SENT = (
    "Не удалось отправить: бот не подключён к Telegram или Telegram не ответил. Событие осталось в очереди и придёт позже."
)
NO_SUCH_SAMPLE = "Такого примера нет — обновите страницу."
CHECK_AT_ONCE = "Как будто сейчас {moment}: сообщения пришли сразу, правила их не задерживают."
CHECK_HELD = (
    "Как будто сейчас {moment}: в этот момент ничего не пришло, события копились. "
    "В Telegram пришла сводка, которая уйдёт {release}."
)
CHECK_NOT_SENT = "Не удалось отправить: события остались в очереди и придут позже."
NO_SUCH_CHECK = "Такого момента нет — обновите страницу."


class ListLine(NamedTuple):
    value: str
    label: str


class Answer(NamedTuple):
    text: str
    ok: bool  # false: something to put right or wait for (the sentence is shown as a warning)
    status: int = 200


def sample_lines(request: Request) -> list[ListLine]:
    """The list of «Тестовое событие»: the samples of the core in their order."""
    return [ListLine(sample.id, sample.label) for sample in pages.tracker_of(request).test_samples()]


def check_lines(request: Request) -> list[ListLine]:
    """The list of «Проверка правил доставки»: the moments of the core in their order."""
    return [ListLine(check.id, check.label) for check in DELIVERY_CHECKS]


async def _reply(request: Request, answer: Answer) -> Response:
    """The answer to a press: a fragment for HTMX, the notice of the page after a `303` otherwise; a sentence with a
    status above 200 is a page of its own with a link back (there is nothing to put in a notice)."""
    if pages.is_htmx(request):
        return pages.fragment(request, "settings_answer.html", text=answer.text, ok=answer.ok)
    address = str(request.app.url_path_for("settings"))
    if answer.status != 200:
        return await pages.message_page(
            request, "Не получилось", answer.text, answer.status, link=(address, "Открыть Настройки")
        )
    pages.notify(request, answer.text)
    return RedirectResponse(address, status_code=303)


@router.post("/settings/test-event", name="settings_test_event")
@pages.guarded_with_refresh("settings")
async def settings_test_event(request: Request) -> Response:
    """«Прислать»: the sample goes out at once, whatever the hour."""
    sample_id = str((await request.form()).get("sample", ""))
    try:
        result = await pages.tracker_of(request).send_test_event(sample_id)
    except KeyError:
        return await _reply(request, Answer(NO_SUCH_SAMPLE, False, 400))
    return await _reply(request, Answer(SAMPLE_SENT, True) if result.delivered else Answer(SAMPLE_NOT_SENT, False))


@router.post("/settings/delivery-check", name="settings_delivery_check")
@pages.guarded_with_refresh("settings")
async def settings_delivery_check(request: Request) -> Response:
    """«Проверить»: what the delivery rules do with an event at the chosen moment of the week."""
    check_id = str((await request.form()).get("check", ""))
    try:
        result = await pages.tracker_of(request).delivery_check(check_id)
    except KeyError:
        return await _reply(request, Answer(NO_SUCH_CHECK, False, 400))
    if result.outcome is CheckOutcome.AT_ONCE:
        answer = Answer(CHECK_AT_ONCE.format(moment=result.moment), True)
    elif result.outcome is CheckOutcome.HELD:
        answer = Answer(CHECK_HELD.format(moment=result.moment, release=result.release), True)
    else:
        answer = Answer(CHECK_NOT_SENT, False)
    return await _reply(request, answer)
