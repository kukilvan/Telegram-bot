# Outside access

The move of the app to the NAS itself (what to copy, in what order, the checks, the problems): `docs/nas-move.md`.

For the agent of the NAS project and for the owner. What the app needs to stand behind a domain, a Cloudflare Tunnel and Cloudflare Access (ADR 0013). The tunnel, the domain and Access are set up by the NAS project, not here; this project only made the app ready. Until the move the app stays on the PC (ADR 0006, 0008).

Eight points, each one needed.

## 1. `APP_URL`

Set `APP_URL=https://tracker.<domain>` in `.env`. The bot then sends links to the app instead of cards in the chat (its «Карточка» buttons, «📄 Открыть в приложении», the text link after `/start`); empty — the bot works as before. Only `http(s)://host[:port]` is taken, with nothing after it (no path, query or `user@`). A Cyrillic domain may be written as it is (`https://трекер.рф`): the app turns it into its `xn--…` form for the bot's links and shows it as written in Settings (KI-76); a name with a mistake in the letters or the dots is refused with the reason in Settings.

Telegram refuses `localhost` (and a single name without a dot) in a link, and one refused button stops the whole message. So such an address is not taken: Settings and the log say why, and the bot stays in chat mode. The value is read once at start; restart after changing it.

## 2. Host names the app answers to

The app answers only to its own names; any other gets `400` and the text `Неизвестный адрес сайта.`:
- `localhost`, `127.0.0.1`, `[::1]`;
- the host of `APP_URL`;
- with `WEB_HOST=0.0.0.0` — any private IPv4 address (`10.x`, `172.16–31.x`, `192.168.x`).

The port is not compared. So `cloudflared` must pass the **original `Host`** of the request (`tracker.<domain>`): do not set `httpHostHeader` in its ingress rule to anything else — or, if it must, put that name into `APP_URL` as well.

## 3. `TRUSTED_PROXIES`

The list of addresses or networks (`172.18.0.0/16`, comma-separated) whose `X-Forwarded-For` and `X-Forwarded-Proto` the app believes: the address of the `cloudflared` container, or the Docker network it sits on. Believed headers give the real client address (shown in the login report and in Settings, only when it is a public address) and the scheme `https`, which turns on the `Secure` flag of the cookie. Empty (the default) — the headers are ignored.

Do not make it wider than needed. Whoever can reach the app from a trusted address can claim any client address and `https` in these headers. An item that is no address or network (`*` too) is skipped with a warning at start.

## 4. Cloudflare Access

One Access application for `tracker.<domain>`: a one-time code sent to the owner's mail. Add one **Bypass** policy for the path `/static/*` and for nothing else: the browser fetches the manifest and the icons without cookies, and without Bypass Access turns that request into its own sign-in page, so the app cannot be installed. There is nothing private under `/static/` (styles, HTMX, icons). `/health` is not bypassed: nothing outside needs it, Docker asks it from inside.

## 5. Not a tunnel without Access

A tunnel alone would put the login page in front of the whole internet. Then the password and the lock (5 wrong tries, 15 minutes) are the only guard, and anyone can keep the owner locked out by guessing. With Access nobody reaches even the login page without the code (ADR 0013).

## 6. The Google Drive sign-in

It returns to `http://localhost:<port>/settings/google-drive/callback` (ADR 0012), so it works only from a browser **on the machine that runs the app**. The token it gets lives in `data/google_drive_token.json` and moves with `data/`.

## 7. Files that move with `data/`

`data/web_login.json` (the sign-ins, the last login and the lock) and `data/web_secret` (the key that signs the cookie) belong to `data/`: copy the whole folder and the sign-ins survive the move. A browser sends a cookie only to the name it got it from, so at the new name every device asks for the password once.

## 8. Installing on the phone

Open `https://tracker.<domain>`, pass Access, type the password, then the browser menu → «Установить приложение» (Android, Chrome) or «На экран „Домой“» (iPhone, Safari). It needs `https`, so it is checked only when the domain works. No service worker is needed (ADR 0004 stands): the manifest and the icons are enough.
