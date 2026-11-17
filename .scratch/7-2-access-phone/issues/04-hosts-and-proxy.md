# 04: Host names and the proxy — allowed hosts (KI-12), `TRUSTED_PROXIES`, `Secure` under `https`

Status: in review
Complexity: medium (a layer in front of the app, uvicorn options, one cookie attribute; no database, no new screen)
Blocked by: 01 (the host of `APP_URL` is allowed), 03 (the session middleware that sets the cookie, and `last_login.address`)

Spec: `../spec.md`, sections 5 (all), 10 (`.env`, `.env.example`), 11 (rows on `Host`, `X-Forwarded-For`, `TRUSTED_PROXIES=*`), 12 (tests of hosts and proxy), 13 (KI-12 to `fixed`, `.env` rows of `PROJECT_CONTEXT.md`, `.env.example`). The document for the NAS project (9) is ticket 06's. Terms — `CONTEXT.md`; standards — rules 3, 7, 10, 11; ADRs 0007, 0008, 0013. `KNOWN_ISSUES.md`: KI-12 by its `## KI-12` heading.

## What to do

- **Only the app's own names** (5.1): the outermost layer of the app (inside `HeadAsGet`) compares the request's `Host` (no port; an IPv6 address in brackets) with the allowed names: `localhost`, `127.0.0.1`, `[::1]`; the host of a valid `APP_URL`; and, when the environment variable `WEB_HOST` is `0.0.0.0`, any private IPv4 address (10.x, 172.16–31.x, 192.168.x). The port is not compared. Any other name, or no `Host`: `400` with the plain text `Неизвестный адрес сайта.`, no page, no session, no `Set-Cookie`, the security headers on, no touch of the lock count. A refused name is logged once per name per run (warning `web: refused host <name>`, at most 100 names remembered). The Docker health check asks `127.0.0.1` and needs no exception. The `Origin` check of today stays and compares only with an allowed host.
- **`TRUSTED_PROXIES`** (5.2): a new optional line of `.env` (addresses or networks, comma-separated). Empty — the proxy headers are ignored (uvicorn's `proxy_headers` off). An item that is no address or network (`*` included) → warning at start, the item skipped. Set → uvicorn gets `proxy_headers=True` and `forwarded_allow_ips=<the list>`; for a connection from those addresses the client address comes from `X-Forwarded-For` and the scheme from `X-Forwarded-Proto`; `Cf-Connecting-Ip` is not read. `requirements.txt` raises the lower bound of uvicorn to the first version whose `forwarded_allow_ips` takes networks (find it in uvicorn's changelog; the spec says 0.54 has it) — check that `docker compose` builds with it.
- **The client address** (5.2, third paragraph): a helper that gives the address only when it is **public** (not private, loopback or link-local), otherwise `None`; the login of ticket 03 stores it into `last_login.address` and logs it with the login and the wrong password. The block «Вход» already shows it when set.
- **`Secure`** (5.3): the cookie of the session middleware gets `Secure` when the request's scheme is `https` (which happens only behind a trusted proxy); under `http` it goes without.
- **Docs and files:** `.env.example` gets `TRUSTED_PROXIES` with a comment line; `PROJECT_CONTEXT.md` — its `.env` row; `KNOWN_ISSUES.md` — KI-12 → `fixed (test: …)`; module docstrings and `tools\code_map.py`; `docs/tests-map.md`.

## Done when

- [ ] Each allowed name passes with and without a port; a private address passes only with `WEB_HOST=0.0.0.0`; another name and a missing `Host` give 400 with the sentence, no `Set-Cookie`; the health check by `127.0.0.1` passes; the log line appears once per name.
- [ ] `TRUSTED_PROXIES` parses an address and a network, skips junk and `*` with a warning; empty turns the proxy headers off; set, the server is built with `proxy_headers` and the list.
- [ ] A request from a trusted address with `X-Forwarded-Proto: https` gets a `Secure` cookie; plain `http` does not; `X-Forwarded-For` from an untrusted address is ignored.
- [ ] A public client address reaches `last_login.address`; a private one does not.
- [ ] The app still answers on `localhost:8080` and, with `WEB_HOST=0.0.0.0`, on the PC's network address; KI-12 is marked fixed.
- [ ] No module of the core over 400 lines; `.venv\Scripts\python.exe -m pyflakes app tests` clean; the full suite green (the three known Windows failures are not new).

## Tests to add

- Hosts: each allowed name with and without a port; private address with and without `WEB_HOST=0.0.0.0`; `evil.example` → 400 with the text and no cookie; no `Host` → 400; `/health` by `127.0.0.1`; the once-per-name log.
- Proxy: parsing (an address, a network, junk, `*`); the server built with `proxy_headers` and the list, or off when empty; `Secure` with a scope of scheme `https`, none with `http`; a public address shown, a private one not.

## Owner check

The session starts the bot itself and writes the launch result in one line. Needs `WEB_HOST=0.0.0.0` and `APP_URL` from ticket 01 in `.env` (already there if 01 was checked).

1. PC browser, `http://localhost:8080` and `http://127.0.0.1:8080`: both open as before.
2. PC browser, `http://<the PC's network address>:8080` (the same address as in `APP_URL`): the login page opens. Phone on the same Wi-Fi, same address: the login page opens.
3. PowerShell: `curl.exe -i -H "Host: evil.example" http://127.0.0.1:8080/` → the first line `400` and the text «Неизвестный адрес сайта.».
4. The proxy and `https` part cannot be checked on the PC: it waits for the NAS project (the tests cover it).

«Не так»: the app does not open at the network address while `WEB_HOST=0.0.0.0` and `APP_URL` are set, an error page at `localhost`, the bot not starting.
