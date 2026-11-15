# Stage 7.2: the app address, the phone, the bot as a link to the web, a safer login

Status: in review

Terms come from `CONTEXT.md`. The decisions taken for 7.2 in `.scratch/7-1-backups-export/description.md` are the starting point; **this description changes two of them** (decision 2 there — Tailscale, and the NAS move as stage 7.3 of this project), see «Decisions taken with the owner» and ADR 0013. Mockups: `mockups/bot-links.html`, `mockups/settings-test-event.html`. ADRs it leans on: 0002 (the web is the main interface, the bot delivers), 0004 (no own JavaScript), 0006 and 0008 (Docker on the PC until the NAS, the web open to the home network on request), 0010 (the bot takes posts and names), 0012 (the Google Drive sign-in returns to `localhost`), 0013 (new: outside access by the owner's domain).

## Goal

The bot says *what* happened; the owner then wants to *open* it: mark a season, give a score, look at the card. Today a bot message leads only to a card in the chat, and the list lives behind «📚 Мои тайтлы» in the bot as well as in the web — two places for one thing. After this stage the bot is a delivery channel with links: a button under a message opens that title's card in the web app, on the PC or the phone. The web works well at phone width on every screen. And the login is ready for the day the app opens to the internet (the owner's domain, with the NAS): a stolen cookie can be revoked, the lockout survives a restart, foreign host names are refused, and every login is reported to Telegram.

Outside access itself — the domain, Cloudflare Tunnel, Cloudflare Access — is **not** set up here: the owner moves this app and another one to the NAS in a separate Claude Code project, which sets up one tunnel for both (ADR 0013). This stage makes the app ready to stand behind it and writes down what it needs.

## What the owner will see at the end

**The address of the app** — a new line in `.env` (name decided by the spec, e.g. `APP_URL`). Until the NAS it can be the PC's address in the home network (`http://192.168.1.124:8080`, with `WEB_HOST=0.0.0.0`, ADR 0008); after the NAS project — `https://tracker.<owner's domain>`. Empty (the default, and the template's default) — the bot stays exactly as it is today.

**Bot, with the address set** (mockup `bot-links.html`):
- Under events and Steam messages «📄 Карточка» is a link button: it opens the card of that title in the web (in Telegram's browser or the phone's). «✅ Посмотрел», «Следить», «🛒 Открыть в Steam» stay as they are.
- The card after «Да» in «Входящие» gets «📄 Открыть в приложении».
- The menu at the bottom is only «📋 Сводка сейчас»; «📚 Мои тайтлы» and «🧪 Тестовое событие» are gone. `/start` says where the list, the cards and the test event now are, with «🌐 Открыть приложение».
- A press of «📚 Мои тайтлы» typed by hand (or an old menu still on the phone) answers «Список теперь в приложении» with «🌐 Открыть список».
- Old buttons in old messages get no special handling: the owner clears the chat history if they get in the way (owner, 2026-11-15).

**Web Settings** (mockup `settings-test-event.html`):
- Block «Бот в Telegram» gains a line about the address: set (the address) or not set (the cards stay in the chat).
- «Тестовое событие»: a choice of samples and «Прислать» — the message comes to Telegram, as the bot menu sends it today.
- «Проверка правил доставки»: a moment to choose and «Проверить» — the sample goes through the delivery rules as if it appeared then, and the page says what the rules did.
- A new block «Вход»: the last login (when, which device) and «Выйти на всех устройствах» — every session ends, on the PC, the phone and in Telegram's browser.

**Telegram, on every login to the web** (with or without the address): «🔐 Вход в приложение: Android, Chrome, сегодня в 14:32» and what to do if it was not the owner.

**The phone.** Every screen — Feed, List, Archive, Search, card, Settings, «Входящие», login — is walked at phone width and fixed where it breaks (owner, 2026-11-15). The phone opens the app at home over Wi-Fi by the PC's address. Installing it as an app (PWA) needs `https`, so on the phone it is checked by the NAS project; here the installability is checked on the PC (`localhost` counts as secure).

**A safer login** (each was deferred «until the web is open outside the home»):
- KI-7: the count of wrong passwords and the lockout survive a restart (kept in `data/`).
- KI-8: «Выйти» really ends that session on the server; «Выйти на всех устройствах» ends all of them; a copied cookie stops working.
- KI-12: the app answers only to its own host names (`localhost`, `127.0.0.1`, the host of the address, the home-network address when open to it); a foreign name — refused.
- KI-13: a spoiled session key file is made anew, not kept spoiled.
- Ready for a proxy in front: behind Cloudflare the real client address and `https` come in headers; the lockout, the login report and the cookie (`Secure` under `https`) use them — only from a trusted proxy.

**A short document for the NAS project** — what the app needs to be opened by a domain: the address variable, the host names, the headers it trusts, what Cloudflare Access must let through (the manifest and icons, if installing the app needs it), why a tunnel without Access is a bad idea, and that the Google Drive sign-in works only from a browser on the same machine (ADR 0012). The full move guide is stage 7.3.

**Owner's check at the end of the stage:** set the address to the PC's home address; a test event from Settings comes to Telegram; «📄 Карточка» under it opens the card on the phone; log in on the phone and get the 🔐 message; «Выйти на всех устройствах» on the PC and see the phone asked for the password again; the bot menu has only «Сводка сейчас»; clear the address — the bot is as before.

## In scope · out of scope

**In 7.2:** the address variable, link buttons in the bot and the menu without «Мои тайтлы» and «Тестовое событие», `/start` text, test event and delivery-rules check in Settings, the «Вход» block, the login report, KI-7, 8, 12, 13, trusted proxy headers, the phone pass over every screen, PWA installability on the PC, the document for the NAS project, ADR 0013, the `.env` line in `PROJECT_CONTEXT.md`.

**Out:**
- The domain, Cloudflare Tunnel and Cloudflare Access — the NAS project (ADR 0013). Tailscale — dropped.
- Installing on the phone and opening from outside the home — checked by the NAS project once the domain works.
- The NAS move and its guide — stage 7.3, after stages 9 and 8.
- Special handling of old buttons in old messages — the owner clears the chat.
- Sign-in to the web by Telegram (a Mini App): it needs JavaScript (ADR 0004) and a domain; the password stays.
- A second factor for the login: Cloudflare Access in front plays that part.

## Pulled-in `KNOWN_ISSUES.md` entries and review wishes

- **KI-7, KI-8, KI-12, KI-13** — fixed in this stage (above).
- **KI-15** (the container start checks `PUID`/`PGID` even when not root) and **KI-70** (`restore-bot.ps1` needs a recent Docker Compose) — stage 7.3, the NAS readiness.
- **Review 6.4 wish:** split `bot/tracker_handlers.py` (659 lines) when it grows — this stage removes «Мои тайтлы», the selection «Удалить несколько» and the test-event menu from the link mode but keeps them for the mode without an address; the spec decides whether the cards, the statuses and the menu go apart.
- **Review 7.1 wishes** (copies) — no fit; stay for stage 9 or 8.

## Decisions taken with the owner

1. **Outside access by the owner's domain (~$10 a year), Cloudflare Tunnel and Cloudflare Access (a code to the owner's mail before any request reaches the app), set up by the separate NAS project** (owner, 2026-11-15). Reason: the app opens from any device and browser without Tailscale on the phone, Telegram links just open, and one domain and tunnel serve both of the owner's apps on the NAS. Tailscale (decision 2 of 7.1's description) is dropped. Cloudflare Access is what keeps strangers away: without it the login page would be open to the whole internet and anyone could keep the owner locked out. Recorded as ADR 0013; it makes the choice ADR 0006 left open «when the NAS appears», so 0006 and 0008 stand (outside access still comes with the NAS).
2. **The NAS move is done by that separate project; this project only prepares it** (owner, 2026-11-15): stage 7.3 becomes «NAS readiness and the move guide» — the app proven to run in its container on a UGREEN DXP2800 (Intel N100, the same `amd64` image; the database on the NVMe SSD, never on a network share; copies may go to the HDD), start, stop and restore by `docker compose` without PowerShell, KI-15, KI-70, and a guide of what to move, where and in what order. It needs no NAS and comes **after stages 9 and 8** (owner): order 7.2 → 9 → 8 → 7.3.
3. **Bot buttons become links once the address is set; without it nothing changes** (7.1's decision 6, kept). «📚 Мои тайтлы» goes, «📋 Сводка сейчас» stays, «🧪 Тестовое событие» and the delivery-rules check move to Settings.
4. **«Выйти на всех устройствах»** in Settings and **a Telegram message on every login** (owner's wishes, 2026-11-15) — once the app is on the internet, a strange login is seen at once and cut off with one button.
5. **Every screen at phone width** in this stage, not only the install (owner, 2026-11-15).
6. **Old buttons in old messages — no special handling**; the owner clears the chat (owner, 2026-11-15).

## Open questions for the spec

- The name and rules of the address variable (`APP_URL`?): `http` allowed (the home address) or `https` only; a path after the host; what Settings and the start log say for a malformed one; does setting it to the home address need `WEB_HOST=0.0.0.0` checked.
- Revocation (KI-8): a session generation number in `data/` (one counter — «Выйти на всех устройствах» bumps it) plus a list of ended session ids, or server-side sessions; how long the list lives (30 days, the cookie's life); where the lockout count lives (KI-7: `data/login_guard.json` or the database) and how a restore treats both.
- The login report: on every password login, or only on a device not seen before; what «device» is (parsed `User-Agent`: system and browser in Russian words); the client address in it or not; does a locked-out attempt get reported (and how often, so a brute force does not flood Telegram).
- Trusted proxy: which headers (`X-Forwarded-For`, `X-Forwarded-Proto`, `Cf-Connecting-Ip`), trusted from whom (the Docker network of the tunnel container? a setting?); uvicorn's `--proxy-headers` and `forwarded_allow_ips`; the `Secure` cookie only under `https`.
- Allowed hosts (KI-12): built from the address, `localhost`, `127.0.0.1` and — with `WEB_HOST=0.0.0.0` — any private-network address, or an explicit list; what the refusal looks like; `/health` exempt for the Docker healthcheck.
- PWA: is a service worker needed for installing on Android Chrome and iOS Safari today; if it is, it contradicts ADR 0004 — say so, do not add it silently. Does Cloudflare Access break loading the manifest (a bypass rule for `/static/`?).
- The link target: `/titles/<id>` for every kind; a title deleted since the message — the web's «Этого тайтла нет в списке»; the login page after the password returns to the card (a `next` parameter, only paths of the app).
- Settings test event: the list of samples is the bot's (`SAMPLES`); the rules check moments; HTMX answers in place; what happens with the bot not connected.
- The phone pass: which screens break today at 375 px (measured, not guessed), and what a «fix» is allowed to change (CSS only?).
- The two modes of the bot (with and without the address) and the split of `tracker_handlers.py`.
- The ticket split: likely 4–5 — the address and the bot links; Settings test event and the rules check; the login hardening (KI-7, 8, 12, 13, «Выйти на всех устройствах», proxy headers); the login report; the phone pass with the PWA check and the document for the NAS project.
