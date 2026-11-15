# Spec 7.2: the app address, the phone, the bot as links, a safer login

Status: accepted

From `description.md` (accepted 2026-11-15) and its «Open questions for the spec». Terms of `CONTEXT.md`; new terms in section 13. What was checked against real answers: `checks.md` next to this file. ADRs it leans on: 0002, 0004, 0007, 0008, 0012, 0013; new: 0014 (section 13).

**Departures from the description**, each with its reason:

1. **The address cannot be `localhost`.** Telegram refuses a link to `localhost` in a button and in a text link, and one refused button stops the whole message (`checks.md`, 1). So the address must be the PC's address in the network, `127.0.0.1` or a name with a dot (1.1).
2. **`/start` and the answers to the old menu buttons carry the link in their text, not as a button** under them. A Telegram message has one keyboard: either the buttons under it or the menu at the bottom of the chat. These messages must bring the new menu (one button) to replace the old one on the phone, so their link goes into the text, as a text link (2.4, 2.5).
3. **The owner's check opens a card from the card after «Да» in «Входящие», not from a test event.** Test events belong to no title, so they have no «📄 Карточка» (as today).
4. **The lock after wrong passwords stays one for the whole app**, not one per client address. Behind Cloudflare Access a stranger never reaches the login page; at home every request comes from the same Docker address. A count per address would give someone with many addresses more tries. The real address goes into the login report, the «Вход» block and the log only (5.2).

## 1. The app address

### 1.1 `APP_URL` in `.env`

New line of `.env`, read by `Settings` (`app/config.py`): `APP_URL` — the address the owner opens the app at from the phone and from Telegram. Empty (the default, and `.env.example`'s) — **no address**: the bot behaves exactly as today.

The value (outer spaces dropped) is an address when **all** of these hold; otherwise it is **malformed**, treated as no address, and the first broken rule is its reason:

| Rule | Reason (Russian, shown in Settings and the log) |
|---|---|
| starts with `http://` or `https://` (any case) | `нужно http:// или https:// в начале` |
| has a host | `нет адреса ПК или имени сайта` |
| the host is an IPv4 address, an IPv6 address in brackets, or a name with at least one dot inside (not first, not last); not `localhost`, not `*.localhost` | `Telegram не открывает такие ссылки — укажите адрес ПК в сети (например, http://192.168.1.124:8080) или имя сайта с точкой` |
| the port, if any, is a number from 1 to 65535 | `порт должен быть числом от 1 до 65535` |
| nothing after the host and port except one `/`: no path, `?`, `#`, `user@` | `после адреса не должно быть ничего лишнего: только http(s)://адрес[:порт]` |

The address is kept in one form: scheme and host in lower case, the port as written, no `/` at the end (`HTTP://Tracker.Example.com/` → `http://tracker.example.com`). Links are made by appending a path: `{address}/titles/42`.

One pure function reads it (`app/config.py`, next to `parse_user_ids`): text in, either the address or the reason out. `main.py` reads it once and hands the result to the bot (2), the web (Settings line, 1.2; allowed hosts, 5.1) — the core does not see it.

At start: a malformed value → warning `APP_URL: <reason> — адрес не используется, кнопки «Карточка» показывают карточку в чате`; a valid one → info `APP_URL: ссылки бота ведут в приложение`. The value itself is not secret but is not logged either (nothing needs it there).

### 1.2 The line in Settings

Block «Бот в Telegram» of Settings: under the state line (`Подключён` or the sentence of the bot not connected, as now) one line about the address, and a hint under it when one applies:

| State | Line |
|---|---|
| address | `Адрес приложения: {address}. Кнопки «Карточка» в сообщениях бота открывают его.` |
| no address | `Адрес приложения не задан (строка APP_URL в .env): кнопки «Карточка» показывают карточку в чате.` |
| malformed | `Адрес приложения в .env (APP_URL) записан с ошибкой: {reason}. Пока кнопки «Карточка» показывают карточку в чате.` |

| Hint (small text), only with an address | When |
|---|---|
| `Адрес — в домашней сети, а приложение открыто только этому ПК: добавьте в .env строку WEB_HOST=0.0.0.0 и запустите .\start-bot.ps1.` | the host is a private IPv4 address (10.x, 172.16–31.x, 192.168.x) and the environment variable `WEB_HOST` is not `0.0.0.0` (`docker compose` passes `.env` into the container, so the process sees it) |
| `Адрес 127.0.0.1 открывается только на этом ПК: на телефоне кнопки не откроются.` | the host is `127.0.0.1` |

## 2. The bot

### 2.1 Two modes

The bot has **link mode** (a valid address) and **chat mode** (no address or a malformed one). Chat mode is today's bot, unchanged in every text and button. Link mode differs only in what 2.2–2.5 say. The mode is fixed at start (`.env` is read once).

One pure helper of the bot, `app/bot/app_links.py`: `AppLinks(address)` gives the addresses `card(title_id)` → `{address}/titles/{id}`, `home()` → `{address}/`, `list()` → `{address}/list`, `settings()` → `{address}/settings`. The bot holds `AppLinks | None`; `None` is chat mode.

### 2.2 «📄 Карточка» is a link

In link mode every button of the action `CARD` (`app/tracker/actions.py`) is sent as a link button to `AppLinks.card(<its title>)`, with the same label: «📄 Карточка» under an event, a Steam message, an announcement of an expansion or a game of the series, and «📄 Карточка: {name}» in a summary. The core keeps deciding which buttons a message has; only the Telegram button changes (`_action_button` in the bot, used by `TelegramSender` and by every card markup). «✅ Посмотрел», «👀 Следить», «🛒 Открыть в Steam», «📺 Просмотренные сезоны», «🗑 Удалить» stay what they are.

### 2.3 A card in the chat

In link mode a title's card sent to the chat (after «Да» of an offer in «Входящие», after «Следить», after «Готово» of the season choice, after the press of an old «Карточка» button) has **one** button: «📄 Открыть в приложении», a link to `AppLinks.card(id)`. The buttons of `card_actions` («Посмотрел», «Просмотренные сезоны», «Удалить») are not sent in link mode: those are done in the app. The question «Какие сезоны вы уже посмотрели?» after adding a series or an anime from «Входящие» stays as it is (spec 7 of stage 6.4).

### 2.4 The menu and `/start`

Link mode menu (the keyboard at the bottom of the chat): one button, «📋 Сводка сейчас». Chat mode: as today («📚 Мои тайтлы», «📋 Сводка сейчас», «🧪 Тестовое событие»). The `/summary` command stays in both.

`/start` in link mode — one message with the new menu; the last words are a text link to `AppLinks.home()`:

> 👋 Бот работает. Чтобы добавить фильм, сериал, аниме или игру, перешлите мне пост о нём или напишите название: я найду и предложу добавить, а что не найду — сохраню во «Входящие» приложения.
>
> Кнопка «Сводка сейчас» присылает накопленные события. Список, карточки, тестовое событие и настройки — в приложении: 🌐 Открыть приложение

(«🌐 Открыть приложение» is the link.) `/start` in chat mode — today's text.

### 2.5 The old menu buttons

In link mode, the text of an old menu button (typed by hand or pressed on the old menu still shown on the phone) gets an answer with the new menu; the last words are a text link:

| Text | Answer | Link |
|---|---|---|
| «📚 Мои тайтлы» | `Список теперь в приложении: 📚 Открыть список` | `AppLinks.list()` |
| «🧪 Тестовое событие» | `Тестовое событие и проверка правил доставки теперь в Настройках приложения: ⚙️ Открыть Настройки` | `AppLinks.settings()` |
| «➕ Добавить» | today's answer, with the new menu | — |

None of them becomes an inbox item (they stay in the list of texts `register_inbox_handlers` does not take, in both modes).

### 2.6 Old buttons in old messages

No special handling (description, decision 6): every callback button sent before keeps doing what it does today in both modes («Карточка» sends the card to the chat — with the button of 2.3 in link mode; «Мои тайтлы» lists, «Удалить несколько», a sample of «Тестовое событие», a moment of the rules check work as before).

### 2.7 Splitting `tracker_handlers.py`

The file (659 lines) is split by what lives together, every handler still on the one router of `register_tracker_handlers` (rule 3 of `docs/coding-standards.md`):

- `app/bot/tracker_handlers.py` — the assembly (`register_tracker_handlers`), the menu by mode, `/start`, «Сводка сейчас», «Добавить» and the old menu texts, the buttons under messages and cards, `TelegramSender`, the markups;
- `app/bot/list_handlers.py` — «Мои тайтлы» and «Удалить несколько»;
- `app/bot/test_event_handlers.py` — the bot's «Тестовое событие» and its rules check;
- `app/bot/app_links.py` — 2.1.

Each new module takes the router and what it needs (the core, `AppLinks`) and registers its handlers on it. The menu texts of chat mode register their handlers only in chat mode; the answers of 2.5 only in link mode; the callback prefixes in both.

## 3. Settings: test event and the delivery check

In the block «Бот в Telegram», under the lines of 1.2, two forms (mockup `mockups/settings-test-event.html`; the texts below are final). Both exist in both modes; in chat mode the bot keeps its own menu too.

### 3.1 «Тестовое событие»

- Heading `Тестовое событие` (an `h3`), hint `Пришлёт в Telegram пример сообщения — посмотреть, как оно выглядит.`
- A list (`select name="sample"`) of the samples of `Tracker.test_samples()` in their order, labels as in the bot; the first is chosen.
- Button «Прислать»: `POST /settings/test-event` (route `settings_test_event`), the sample delivered as the bot's menu does (`Tracker.send_test_event`, at once, whatever the hour).

| Outcome | Answer |
|---|---|
| delivered | `Отправлено — посмотрите в Telegram.` |
| not delivered (no bot, no network, Telegram refused) | `Не удалось отправить: бот не подключён к Telegram или Telegram не ответил. Событие осталось в очереди и придёт позже.` |
| no such sample (an old page) | `Такого примера нет — обновите страницу.` (status 400) |
| an unexpected error | the common «Не получилось» of `pages` with «Обновить» |

### 3.2 «Проверка правил доставки»

- Heading `Проверка правил доставки`, hint `Отправит «Сериал: две серии подряд» так, будто оно появилось в выбранный момент, и покажет, что сделали правила доставки (рабочие дни, тихие часы, сводка).`
- A list (`select name="check"`) of `DELIVERY_CHECKS` (the eight moments of today, their labels).
- Button «Проверить»: `POST /settings/delivery-check` (route `settings_delivery_check`).

| Outcome | Answer |
|---|---|
| delivered at once | `Как будто сейчас {moment}: сообщения пришли сразу, правила их не задерживают.` |
| held and played out | `Как будто сейчас {moment}: в этот момент ничего не пришло, события копились. В Telegram пришла сводка, которая уйдёт {release}.` |
| not delivered | `Не удалось отправить: события остались в очереди и придут позже.` |
| no such moment | `Такого момента нет — обновите страницу.` (status 400) |

`{moment}` and `{release}` read as the bot's check reads them today (`format_when` on the owner's zone). The steps the bot runs today (the moment, the rules, the sample, the outcome) move into one core method, `Tracker.delivery_check(check_id)`, which hands back the outcome; the bot's check (chat mode) and Settings both use it, so the logic lives once. The bot keeps its own texts (it says «Выше — сводка…»); the sentences of the table live with the web.

### 3.3 How the answer comes

Both forms work with and without HTMX:
- HTMX (`hx-post`, `hx-target` the result line under the form, `hx-swap="innerHTML"`): the answer is a fragment that replaces that line only; the page stays where it is.
- No HTMX: `303` back to `/settings` with the answer as the page's notice (`pages.notify`).

## 4. Sign-ins kept on the server (KI-7, KI-8, KI-13)

### 4.1 The file `data/web_login.json`

The web keeps its sign-ins, the last login and the lock after wrong passwords in **one file next to the database, not in it** (ADR 0014):

```json
{
  "version": 1,
  "sessions": {"<sid>": {"since": "2026-11-15T11:32:05Z", "seen": "2026-11-15T12:40:00Z", "device": "Android, Chrome"}},
  "last_login": {"at": "2026-11-15T11:32:05Z", "device": "Android, Chrome", "address": "203.0.113.5"},
  "guard": {"wrong": 2, "locked_until": null}
}
```

- `sid` — 32 hex characters (`secrets.token_hex(16)`), never shown anywhere. `device` — the words of 6.3, never the raw `User-Agent`. `address` — only a public address (5.2), otherwise `null`. Moments in UTC with `Z`.
- Held in memory; every change is written at once to a temporary file in `data/` and moved over the old one (`os.replace`), mode `0600`. The web is its only reader and writer (one process, ADR 0007); file work off the event loop.
- Absent → empty (no sign-ins, no last login, no lock). Not JSON, another `version`, a wrong shape → warning `data/web_login.json испорчен — все входы закрыты, счётчик неверных паролей обнулён`, treated as empty and rewritten at the next change. Cannot be read or written (`OSError`) → warning, kept in memory until the restart.
- A restore (`restore-bot.ps1`) does not touch it; the NAS move carries it with `data/`.

### 4.2 The session cookie

- Name `tracker_session` (as today), signed with the key of `data/web_secret` by `itsdangerous` as today, life 30 days from the last request (every answer sends it anew). It carries a small dict: `sid`, `pw` (the fingerprint of `WEB_PASSWORD`, as today), and the page notice when there is one (`pages.notify` reads and writes `request.session` as today).
- A request is **signed in** when the signature is good and under 30 days old, `pw` matches the fingerprint, and `sid` is in `sessions` with `seen` under 30 days old. Otherwise it is a stranger (the login page, as today).
- `seen` is moved to now when it is over an hour old (at most one write an hour per device); a session whose `seen` is over 30 days old is dropped at the next write.
- Attributes: `HttpOnly`, `SameSite=Lax`, `Path=/`, `Max-Age` 30 days, and `Secure` when the request came over `https` (5.3).
- Starlette's `SessionMiddleware` cannot set `Secure` per request, so the app gets its own small session middleware with the same `request.session` interface and the same signing; its module is `app/web/sessions.py` (with the store of 4.1).
- **After the update every device logs in once**: an old cookie has no `sid`.

### 4.3 Login and «Выйти»

- The right password (`POST /login`): a new `sid` in `sessions` (`since` = `seen` = now, `device` of 6.3), `last_login` replaced, the lock count reset, the cookie set, the login report queued (6.1). At most 20 sessions: beyond that the one with the oldest `seen` is dropped.
- «Выйти» (`POST /logout`): its `sid` leaves `sessions`, the cookie is cleared, `303` to `/login`. A copied cookie of that session no longer works (KI-8).
- A change of `WEB_PASSWORD` ends every session, as today (the fingerprint).

### 4.4 «Выйти на всех устройствах»

`POST /settings/sign-out-everywhere` (route `settings_sign_out_everywhere`): `sessions` emptied (`last_login` and the lock stay), this request's cookie cleared, log info `web: signed out everywhere (<n> sessions)`, `303` to `/login?out=everywhere`. The login page with exactly that parameter shows above the form `Вы вышли на всех устройствах. Войдите снова.`; any other value is ignored. No question before it: nothing is lost but a password typed again.

### 4.5 The block «Вход» in Settings

At the bottom of Settings, after «Копии и выгрузка»:

- Heading `Вход`.
- `Последний вход: {moment}, {device}.` — with `, адрес {address}` before the full stop when `last_login.address` is set; `{moment}` by `moment_in_words` on the owner's zone (`сегодня в 14:32`). No record: `Последний вход: сведений нет.`
- `Вход открыт на {n} устройстве.` when `n` ends in 1 but not in 11 (1, 21, 31…), otherwise `Вход открыт на {n} устройствах.` — `n` the live sessions (this one included).
- Button «Выйти на всех устройствах» (4.4), hint under it: `Выйдет из приложения везде — на ПК, телефоне и в браузере Telegram. Затем на каждом устройстве нужно снова ввести пароль.`

### 4.6 The lock survives a restart (KI-7)

`LoginGuard` keeps its count and the end of a lock in `guard` of 4.1, on the wall clock (UTC), written on every wrong try and every reset. The rules stay: the fifth wrong password in a row locks the login for 15 minutes; while locked even the right password is not looked at and the lock is not extended; the end of a lock starts the count anew; one count for the whole app (departure 4). A clock moved back by the owner can lengthen a lock up to that shift — accepted.

### 4.7 A spoiled key file is made anew (KI-13)

`data/web_secret` shorter than 32 bytes: a new key is written over it (temporary file and `os.replace`, mode `0600`), warning `data/web_secret был испорчен и создан заново: на всех устройствах нужен новый вход`. Writing fails → the key lives in memory, as today.

## 5. Host names and the proxy

### 5.1 Only the app's own names (KI-12)

The outermost layer of the app (inside `HeadAsGet`) compares the request's `Host` (without the port; an IPv6 address in brackets) with the allowed names:
- `localhost`, `127.0.0.1`, `[::1]`;
- the host of a valid `APP_URL`;
- when the environment variable `WEB_HOST` is `0.0.0.0` — any private IPv4 address (10.x, 172.16–31.x, 192.168.x): the phone at home by the PC's address.

The port is not compared (`docker compose` maps it). Any other name, or no `Host`: `400` with the plain text `Неизвестный адрес сайта.` — no page, no session, the security headers on. A refused name goes to the log once per name per run (warning `web: refused host <name>`; at most 100 names remembered). The Docker health check asks `127.0.0.1` and needs no exception. The `Origin` check of today stays and now compares only with an allowed host.

### 5.2 Trusted proxy

New line of `.env`: `TRUSTED_PROXIES` — addresses or networks, comma-separated (`172.18.0.0/16`), from which the proxy headers are believed. Empty (the default): the headers are ignored entirely (uvicorn's `proxy_headers` off), as today in effect. An item that is no address or network: warning at start, the item skipped.

Set: uvicorn gets `proxy_headers=True` and `forwarded_allow_ips=<the list>`; for a connection from those addresses it takes the client address from `X-Forwarded-For` and the scheme from `X-Forwarded-Proto` (`https` behind Cloudflare). `Cf-Connecting-Ip` is not read: `cloudflared` writes `X-Forwarded-For` too, and one mechanism is enough. `requirements.txt` raises the lower bound of uvicorn to the first version whose `forwarded_allow_ips` takes networks (the ticket finds it in uvicorn's changelog; 0.54 has it).

The client address is used only where the owner reads it: `last_login.address`, the login report, the log of a login and a wrong password. It is shown only when it is a **public** address (not private, not loopback, not link-local): at home every request comes from the Docker network, which says nothing.

### 5.3 `Secure` under `https`

The cookie gets `Secure` when the request's scheme is `https` — which happens only behind a trusted proxy. Under `http` (the PC, the phone at home) it goes without, as today: a browser refuses a `Secure` cookie over `http` from a network address.

## 6. The login report

### 6.1 The messages

Two new event types without a title (`title_id` empty, so the Feed never shows them):

| Type | When | Text |
|---|---|---|
| `web_login` | every right password | `🔐 Вход в приложение: {device}, {moment}{, адрес {address}}.`<br>`Если это были не вы — откройте Настройки и нажмите «Выйти на всех устройствах», затем смените WEB_PASSWORD в .env.` |
| `web_login_locked` | the wrong try that begins a lock | `⚠️ Вход в приложение закрыт на 15 минут: 5 неверных паролей подряд. Последняя попытка: {device}, {moment}{, адрес {address}}.`<br>`Если это были не вы — смените WEB_PASSWORD в .env.` |

`{moment}` — `moment_in_words` of now on the owner's zone (`сегодня в 14:32`); `{address}` — only a public one (5.2). No buttons. A locked try or a wrong password before the fifth sends nothing (a lock begins at most every 15 minutes, so at most 96 such messages a day).

### 6.2 Delivery

Like a test event: recorded (dedup key `web_login:<sid>` or `web_login_locked:<end of the lock>`) and sent at once whatever the delivery rules (`force`), only this event. The login answer does not wait for Telegram: the record is made in the request, the send runs as a background task. A failed send leaves the event in the queue; the regular delivery sends it later **by the rules** (a night login reported in the morning; KI-73). One core method takes the facts (type, device, address, moment) and builds the text; the web never writes event texts.

One more sample of «Тестовое событие»: `Вход в приложение`, the text of `web_login` with `Android, Chrome` and the address `203.0.113.5`.

### 6.3 The device in words

A pure function of the web (`app/web/devices.py`): the `User-Agent` (cut to 512 characters) → `{system}, {browser}`.

| System, first match | By |
|---|---|
| iPhone | `iPhone` |
| iPad | `iPad` |
| Android | `Android` |
| ChromeOS | `CrOS` |
| Windows | `Windows` |
| macOS | `Macintosh` or `Mac OS X` |
| Linux | `Linux` |

| Browser, first match | By |
|---|---|
| Яндекс Браузер | `YaBrowser/` |
| Edge | `Edg/`, `EdgA/`, `EdgiOS/` |
| Opera | `OPR/`, `OPT/` |
| Samsung Internet | `SamsungBrowser/` |
| Firefox | `Firefox/`, `FxiOS/` |
| Chrome | `CriOS/`, `Chrome/` |
| Safari | `Safari/` with `Version/` |

Neither known → `неизвестное устройство`; one known → that one alone (`Android`, `Firefox`). No `User-Agent` → `неизвестное устройство`. An iPad on iPadOS 13+ says it is a Mac, so it reads `macOS, Safari` (KI-72).

## 7. Every screen at phone width

Measured, not guessed (`checks.md`, 2): no screen scrolls sideways at 375 or 320 px and every control is at least 44 px high. What hurts is the room the top of the page takes. Fixes:

| # | Where | Fix |
|---|---|---|
| P1 | the menu of every page | under 40rem a grid of three columns: two even rows instead of a ragged wrap; «Выйти» stays at the top right |
| P2 | the filter rows of «Список» and «Архив» | under 40rem each row of links is one line that scrolls sideways inside itself (`overflow-x: auto`, no wrap); the page does not scroll sideways. «Список» at 375 × 812 shows its first title on the first screen (KI-74: the chosen link can be past the edge of its row) |
| P3 | the page box | under 40rem its padding 12 px instead of 20: about 16 px more for text |
| P4 | Settings, «Тихие часы» | «до» and its time stay on one line |
| P5 | the blocks new in this stage (3, 4.5) | built for the phone from the start |

What a fix may change: `style.css` and the markup of templates; no JavaScript, no addresses, no behaviour. Everything sits under the existing breakpoint (`max-width: 40rem`), so the PC looks as today. Done when every screen — Лента, Список (also «Удалить несколько»), Архив, Поиск, Входящие **with items**, the card of each kind, Настройки, Вход, the message pages — has no element past the right edge at 320 and 375 px and no control under 44 px (the measuring script of `checks.md`, 2, run again).

## 8. Installing the app (PWA)

No service worker is needed (`checks.md`, 3): Chrome installs from its menu without one since version 108 on Android and 112 on the PC, Safari on the iPhone never needed one. So none is added and ADR 0004 stands. The manifest and the tags of `base.html` stay unless the check fails.

Checked here on the PC (`localhost` counts as secure): Chrome or Edge at `http://localhost:8080` offers «Установить приложение» in the address bar or the menu, and DevTools → Application → Manifest shows no errors. On the phone it needs `https` — checked by the NAS project once the domain works.

## 9. The document for the NAS project

`docs/outside-access.md` (English; for the agent of the NAS project and for the owner), short:
- `APP_URL=https://tracker.<domain>` and what it changes (the bot's links); `localhost` is refused by Telegram.
- Host names the app answers to (5.1): the host of `APP_URL`; `cloudflared` must pass the original `Host` (do not set `httpHostHeader`, or put that name into `APP_URL`).
- `TRUSTED_PROXIES`: the address or Docker network of the `cloudflared` container; what it trusts (`X-Forwarded-For`, `X-Forwarded-Proto`) and what goes wrong when it is too wide (anyone on that network can claim any address and `https`).
- Cloudflare Access: one application for `tracker.<domain>`, a one-time code to the owner's mail; a **Bypass** policy for `/static/*` (the manifest and icons the browser fetches without cookies; nothing private there: styles, HTMX, icons); no Bypass for anything else, `/health` included.
- Why a tunnel without Access is a bad idea (ADR 0013).
- The Google Drive sign-in works only from a browser on the machine that runs the app (`http://localhost:<port>/settings`, ADR 0012); the token moves with `data/`.
- `data/web_login.json` and `data/web_secret` move with `data/`: sign-ins survive the move (a browser sends the cookie only to the name it got it from, so the new name asks for the password once).
- Installing on the phone: open `https://tracker.<domain>`, sign in through Access and the password, menu → «Установить приложение» (Android) / «На экран „Домой“» (iPhone).

## 10. Data

- No migration. Event types `web_login` and `web_login_locked` go into `events` like any event without a title (they are in the database and in its copies; the JSON export takes them only if it already takes events — no change to the export).
- New files: `data/web_login.json` (4.1). `data/web_secret` is rewritten when spoiled (4.7).
- `.env`: `APP_URL`, `TRUSTED_PROXIES` (both optional, empty by default); `.env.example` gets both with a comment line each; the `.env` table of `PROJECT_CONTEXT.md` gets two rows.

## 11. Edge cases

| Case | Behaviour |
|---|---|
| `APP_URL=http://localhost:8080` | malformed (1.1, the reason about Telegram); chat mode |
| `APP_URL=https://tracker.example.com/app` | malformed (path); chat mode |
| `APP_URL` set to the PC's address, `WEB_HOST` not set | link mode; links lead to an address the phone cannot open; Settings hints (1.2) |
| the PC's address changes (router restart) | old links lead nowhere; the owner fixes `APP_URL` and restarts; ADR 0008 advises fixing the address in the router |
| a card link to a title deleted since | the web's «Тайтла нет» page with «Открыть Список» (as today) |
| a card link opened signed out | the login page; after the password back to the card (`next`, `safe_next` as today) |
| a link opened in Telegram's browser | a browser of its own: on Android its cookies are Chrome's (signed in if Chrome is); on the iPhone a sign-in of its own; both count as devices |
| a summary with «Карточка» of a title deleted before delivery | the link leads to «Тайтла нет» |
| the bot not connected, «Прислать» in Settings | `Не удалось отправить…`; the event waits in the queue |
| two tabs press «Прислать» at once | two samples, each its own event (as two presses in the bot) |
| `data/web_login.json` deleted by hand | every device logs in again, the lock count is zero |
| `data/web_login.json` written by hand with a session | it works only with a cookie signed by the key — no harm |
| more than 20 sign-ins | the least recently used one is dropped |
| «Выйти на всех устройствах» in one tab, another tab open | its next request is a stranger's: HTMX → `HX-Redirect` to `/login`, a page → the login page (as today) |
| a cookie copied before «Выйти» | refused (KI-8 fixed) |
| `Host: evil.example` from a page in the owner's browser (DNS rebinding) | `400`, no lock count touched (KI-12 fixed) |
| a request with `X-Forwarded-For` from an untrusted address | the header ignored; the client is the connection's address |
| `TRUSTED_PROXIES=*` | refused as an item that is no address or network (warning): trusting everyone is never what the owner wants |
| Telegram down at a login | the report waits in the queue and goes out by the rules (KI-73) |
| a lock begins while the previous lock's report still waits | each has its own dedup key; both come |
| no `User-Agent` | `неизвестное устройство` |
| the owner moves the clock back | a lock may last longer by the shift (4.6) |

## 12. Tests

Automated (offline, as all tests):
- **Address (1.1):** each rule of the table with a passing and a failing value; the one form (case, the `/` at the end); IPv6 in brackets; `localhost`, `*.localhost`, a single name refused; the reason texts.
- **Settings line (1.2):** three states and both hints (with `WEB_HOST` set and not).
- **Bot (2):** link mode: «Карточка» of an event, a Steam event, a summary, an announcement is a link to `/titles/<id>` with its label; the card in the chat has only «📄 Открыть в приложении»; the menu has one button; `/start` and the three old texts give the new menu and a text link to the right address; the old callbacks work. Chat mode: every text and button as today (the existing tests pass untouched). The owner filter test (`test_tracker_owner_filter.py`) covers the new modules.
- **Settings forms (3):** each outcome of both tables, with and without HTMX; an unknown id → 400; the delivery check through `Tracker.delivery_check` gives the same outcomes as the bot's (one test for both callers).
- **Sign-ins (4):** login makes a session; «Выйти» ends only it; a copied cookie after «Выйти» is refused; «Выйти на всех устройствах» ends all and keeps `last_login`; `?out=everywhere` shows its sentence, another value nothing; 30 days of `seen`; the hourly write of `seen`; 21st session drops the oldest; the file: absent, spoiled (warning, empty), unwritable (memory); `0600` where the system has it; a cookie without `sid` (the old one) is a stranger; the «Вход» block lines and the plural (1, 2, 5, 11, 21).
- **Lock (4.6):** survives a new app on the same file; ends on time on the wall clock; not extended by a locked try.
- **Key (4.7):** a short file is replaced and a sign-in survives the next start.
- **Hosts (5.1):** each allowed name, with and without a port; a private address only with `WEB_HOST=0.0.0.0`; another name → 400 with the text and no `Set-Cookie`; no `Host` → 400; `/health` by `127.0.0.1` passes; the log line once per name.
- **Proxy (5.2, 5.3):** `TRUSTED_PROXIES` parsing (an address, a network, junk, `*`); the server is built with `proxy_headers` and the list (or off when empty); with a scope of scheme `https` the cookie has `Secure`, with `http` not; a public address is shown, a private one not.
- **Login report (6):** right password → one `web_login` event with the text; the fifth wrong → `web_login_locked`; the sixth (locked) nothing; send failed → the event stays pending; the login answer does not wait for the sender (a sender that hangs); the sample `Вход в приложение` is listed.
- **Device words (6.3):** a real `User-Agent` of each row (Android Chrome, Android Samsung Internet, Android Yandex, iPhone Safari, iPhone Chrome, iPad, Windows Edge, Windows Chrome, Windows Firefox, macOS Safari, Linux Firefox, ChromeOS), empty, unknown.
- **Phone (7):** a test that every template page has the viewport tag; the CSS rules are checked live, not by tests.

Checked live by the owner at the end of the stage (the session prepares everything else):
1. `APP_URL` set to the PC's address (and `WEB_HOST=0.0.0.0`); Settings shows the address line.
2. «Прислать» in Settings → the sample comes to Telegram; «Проверить» → the answer under the button and the messages in Telegram.
3. The bot's menu is only «📋 Сводка сейчас»; «📚 Мои тайтлы» typed by hand → `Список теперь в приложении…` with the link.
4. A name sent to the bot → «Да» → «📄 Открыть в приложении» opens the card on the phone (the login page first, then the card).
5. The login on the phone → the 🔐 message in Telegram.
6. «Выйти на всех устройствах» on the PC → the phone asks for the password again.
7. Every screen on the phone looks right (Лента, Список, Архив, Поиск, Входящие, a card, Настройки).
8. On the PC: Chrome or Edge offers «Установить приложение».
9. `APP_URL` cleared → the bot is as before (three menu buttons, «Карточка» in the chat).

## 13. Docs, terms, ADR, known issues

- **`CONTEXT.md`** (the ticket that brings each term adds it):
  - **Адрес приложения** (app address) — the address the bot's links lead to, `APP_URL` in `.env`; without it the bot keeps the cards in the chat. In code: `app_url` (`Settings`), `AppLinks`; the modes `link mode` / `chat mode`.
  - **Вход** (sign-in) — one browser where the password was typed and not yet ended; «Выйти» ends it, «Выйти на всех устройствах» ends all of them. In code: `sign-in`, the store `app/web/sessions.py`, `sid`. Not the Google Drive sign-in (`drive_sign_in`).
  - **Сообщение о входе** (login report) — the Telegram message about a login or a lock. In code: the events `web_login`, `web_login_locked`.
  - «Тестовое событие» and «Проверка правил доставки»: now a form of Settings too (the bot's menu only in chat mode).
- **ADR 0014** (written with this spec): sign-ins and the lock live in a file in `data/`, outside the database.
- **`KNOWN_ISSUES.md`:** KI-7, KI-8, KI-12, KI-13 → `fixed (test: …)` by the tickets that fix them. New now: KI-72 (an iPad reads as macOS), KI-73 (a login report that failed to send waits for the delivery rules), KI-74 (the chosen filter can be past the edge of its row on the phone).
- **`docs/code-map.md`:** rebuilt by `tools/code_map.py` (new modules `app/bot/app_links.py`, `list_handlers.py`, `test_event_handlers.py`, `app/web/sessions.py`, `devices.py`); its «Not Python» part names `data/web_login.json` and `docs/outside-access.md`.
- **`docs/outside-access.md`:** new (9).
- **`PROJECT_CONTEXT.md`:** the `.env` rows (10); the gotcha «Telegram refuses `localhost` in links».
- **`.env.example`:** `APP_URL`, `TRUSTED_PROXIES`.

## 14. Proposed tickets

| # | Ticket | Spec | Complexity | Blocked by |
|---|---|---|---|---|
| 01 | The app address and the bot as links: `APP_URL`, the Settings line, `AppLinks`, link mode (buttons, chat card, menu, `/start`, old texts), the split of `tracker_handlers.py` | 1, 2 | medium | — |
| 02 | Settings: «Тестовое событие» and «Проверка правил доставки», `Tracker.delivery_check` | 3 | medium | 01 (the same block of Settings) |
| 03 | Sign-ins on the server: `data/web_login.json`, the session middleware, «Выйти», «Выйти на всех устройствах», the block «Вход», KI-7, KI-8, KI-13; ADR 0014 referenced | 4 | complex | — |
| 04 | Host names and the proxy: KI-12, `TRUSTED_PROXIES`, `Secure` | 5 | medium | 01, 03 |
| 05 | The login report: the two events, the device words, the sample | 6 | medium | 03, 04 |
| 06 | The phone pass, the PWA check on the PC, `docs/outside-access.md` | 7, 8, 9 | medium | 02, 03, 05 |

Order: 01 → 02 → 03 → 04 → 05 → 06 (01 and 03 do not touch each other and could swap). With the slicing and the review: 8 sessions.
