# 02: Settings — «Тестовое событие» and «Проверка правил доставки», `Tracker.delivery_check`

Status: open
Complexity: medium (two forms with HTMX and a fallback, one core method moved out of the bot; no database change)
Blocked by: 01 (the same block of Settings, «Бот в Telegram»)

Spec: `../spec.md`, sections 3 (all), 11 (rows on «Прислать» with the bot not connected and two tabs), 12 (the tests of Settings forms), 13 (`CONTEXT.md` note on the two names). Mockup: `../mockups/settings-test-event.html` (the texts of the spec are final, the mockup is the layout). Terms — `CONTEXT.md`; standards — rules 1, 3, 7, 10, 11. Phone width: the forms are built for it from the start (spec 7, P5).

## What to do

- **`Tracker.delivery_check(check_id)`** (3.2, last paragraph): the steps the bot's check runs today (the moment, the delivery rules, the sample, the outcome) move into this one core method, which hands back the outcome (delivered at once · held and played out with the release moment · not delivered · no such moment). The bot's check (chat mode, `test_event_handlers.py`) calls it and keeps its own texts («Выше — сводка…»); the sentences of the 3.2 table live with the web. Behaviour of the bot's check does not change; its tests pass untouched.
- **«Тестовое событие» form** (3.1): heading, hint, the list of `Tracker.test_samples()` in their order with the first chosen, button «Прислать»; `POST /settings/test-event` (route `settings_test_event`) delivers the sample through `Tracker.send_test_event`, at once, whatever the hour. The four outcomes and their sentences as in the table (delivered; not delivered with the event staying in the queue; no such sample → 400; an unexpected error → the common «Не получилось» of `pages` with «Обновить»).
- **«Проверка правил доставки» form** (3.2): heading, hint, the list of `DELIVERY_CHECKS` (the eight moments and their labels), button «Проверить»; `POST /settings/delivery-check` (route `settings_delivery_check`) through `Tracker.delivery_check`; the four outcomes with `{moment}` and `{release}` read as the bot reads them (`format_when` on the owner's zone).
- **How the answer comes** (3.3): with HTMX (`hx-post`, `hx-target` the result line under the form, `hx-swap="innerHTML"`) the answer is a fragment replacing that line, the page stays where it is; without HTMX `303` back to `/settings` with the answer as the page's notice (`pages.notify`). Both forms exist in both modes (the bot keeps its own menu in chat mode).
- **Layout:** under the lines of 1.2 in the block «Бот в Telegram», the two forms one under another, each with its own result line; nothing wider than the screen at 320 px, controls at least 44 px high.
- **Docs:** `CONTEXT.md` — «Тестовое событие» and «Проверка правил доставки» now also a form of Settings; module docstrings and `tools\code_map.py`; `docs/tests-map.md`.

## Done when

- [ ] Both forms are in Settings in both modes; the lists carry the samples of the bot and the eight moments in their order.
- [ ] Every outcome of both tables shows its sentence, with HTMX as a fragment under the form and without it as the notice after `303`; an unknown sample or moment gives 400 with its sentence.
- [ ] `Tracker.delivery_check` is the only place of the check's logic; the bot's check and the web give the same outcomes for the same moment (one test for both callers).
- [ ] The bot's «Тестовое событие» and its rules check work as before (existing tests untouched).
- [ ] No module of the core over 400 lines; the web goes through the facade only; `.venv\Scripts\python.exe -m pyflakes app tests` clean; the full suite green (the three known Windows failures are not new).

## Tests to add

- Settings forms: each outcome of both tables, with and without HTMX; an unknown id → 400; the not-connected bot (a sender that fails) leaves the event in the queue; two presses → two events.
- `Tracker.delivery_check`: every outcome of the eight moments; the same outcomes through the bot's check and through the web route.

## Owner check

The session starts the bot itself and writes the launch result in one line. Browser, `http://localhost:8080/settings`, signed in; the block «Бот в Telegram».

1. Under the address line a heading «Тестовое событие» and a list. Choose any sample, press «Прислать» → under the button «Отправлено — посмотрите в Telegram.» and the page does not jump; in Telegram the sample is there.
2. A heading «Проверка правил доставки» and a list of moments. Choose a night one, press «Проверить» → «Как будто сейчас …: в этот момент ничего не пришло, события копились. В Telegram пришла сводка, которая уйдёт …» and the messages in Telegram. Choose a working-day afternoon → «…сообщения пришли сразу, правила их не задерживают.»
3. On the phone (or the browser window narrowed to 375 px) both forms fit, no sideways scroll.

«Не так»: a button that reloads the whole page without a sentence under it, a sample that does not reach Telegram while the sentence says «Отправлено», an error page.
