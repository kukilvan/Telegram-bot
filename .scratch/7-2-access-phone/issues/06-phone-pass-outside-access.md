# 06: The phone pass, the PWA check on the PC, `docs/outside-access.md`

Status: accepted
Complexity: medium (CSS and template fixes across every screen, a measuring run, one document; no behaviour change)
Blocked by: 02, 03, 05 (the new blocks of Settings and the login page are measured with the rest)

Spec: `../spec.md`, sections 7 (all), 8 (all), 9 (all), 12 (the phone test), 13 (`docs/outside-access.md`, `docs/code-map.md`'s «Not Python» part; KI-74). The measuring script and the numbers it gave: `../checks.md`, 2 (run it again, do not rewrite it); the PWA facts: `../checks.md`, 3. Mockups of the stage: `../mockups/`. ADRs 0004 (no service worker stands), 0008, 0013. Terms — `CONTEXT.md`; standards — rules 7, 11. What a fix may change: `style.css` and the markup of templates; no JavaScript, no addresses, no behaviour; everything under the existing breakpoint `max-width: 40rem`, so the PC looks as today.

## What to do

- **The phone fixes** (7, P1–P5):
  - P1: the menu of every page under 40rem is a grid of three columns, two even rows instead of a ragged wrap; «Выйти» stays at the top right;
  - P2: the filter rows of «Список» and «Архив» under 40rem are one line each, scrolling sideways inside themselves (`overflow-x: auto`, no wrap), the page itself does not scroll sideways; «Список» at 375 × 812 shows its first title on the first screen; the chosen link past the edge of its row is KI-74 (already in `KNOWN_ISSUES.md`): fix it only if a CSS-only way exists, and then mark KI-74 `fixed (test: …)` or say why no test; otherwise it stays open;
  - P3: the page box padding is 12 px instead of 20 under 40rem;
  - P4: Settings, «Тихие часы» — «до» and its time stay on one line;
  - P5: the blocks new in this stage (the forms of ticket 02, the block «Вход» of 03, the login page's new sentence) look right at 320 and 375 px; fix what does not.
- **The measuring run:** the script of `checks.md`, 2, at 320 and 375 px, on every screen — Лента, Список (also «Удалить несколько»), Архив, Поиск, Входящие **with items**, the card of each kind, Настройки, Вход, the message pages: no element past the right edge and no control under 44 px. Put the numbers of the run (before / after, short) into `checks.md` under a new heading. A test that every template page has the viewport tag (the CSS is checked live, not by tests).
- **The PWA check on the PC** (8): Chrome or Edge at `http://localhost:8080` offers «Установить приложение» and DevTools → Application → Manifest shows no errors (browser pane or by reading the manifest and the tags if the pane cannot show the install offer — say which in the owner's message). No service worker is added; the manifest and the tags of `base.html` change only if the check fails (then say why, and whether ADR 0004 still stands).
- **`docs/outside-access.md`** (9, English, short, for the agent of the NAS project and for the owner): the eight points of the spec — `APP_URL` and why `localhost` is refused; the host names the app answers to and that `cloudflared` must pass the original `Host`; `TRUSTED_PROXIES` and what too wide a list allows; Cloudflare Access with the **Bypass** for `/static/*` only (`/health` included in nothing); why a tunnel without Access is a bad idea (ADR 0013); the Google Drive sign-in works only from a browser on the machine that runs the app; `data/web_login.json` and `data/web_secret` move with `data/`; installing on the phone.
- **Docs:** `docs/code-map.md`'s «Not Python» part names `data/web_login.json` and `docs/outside-access.md` (check what `tools\code_map.py` keeps by itself and what the part holds by hand); `docs/tests-map.md`; `PROJECT_CONTEXT.md` — a pointer to `docs/outside-access.md` if it fits the budget.

## Done when

- [x] At 320 and 375 px no screen of the list above scrolls sideways and no control is under 44 px (the run is in `checks.md`, new heading).
- [x] The menu is a grid of three columns under 40rem; the filter rows of «Список» and «Архив» scroll inside themselves; «Список» at 375 × 812 shows its first title on the first screen; at 40rem and wider the screens look as before.
- [x] The Chrome or Edge install offer and the manifest check are done and recorded; no service worker was added.
- [x] `docs/outside-access.md` has the eight points and says nothing the spec does not.
- [x] KI-74 is either fixed and marked so, or still open and unchanged.
- [x] The viewport-tag test passes; `.venv\Scripts\python.exe -m pyflakes app tests` clean; the full suite green (the three known Windows failures are not new).

## Tests to add

- Every template page has the viewport tag (the one test of the spec). Nothing else is automated here: CSS and the document are checked by the run and by the owner.

## Owner check

The session starts the bot itself and writes the launch result in one line, and the measuring numbers in a few lines. The owner's check on the phone (Wi-Fi, the address of `APP_URL`, signed in):

1. Лента, Список, Архив, Поиск, Входящие, a title's card, Настройки: scroll each down and across. Nothing wider than the screen, no text cut at the right edge.
2. Список: the menu at the top is two even rows; the first title is visible without scrolling.
3. Настройки: «Тихие часы» — «до» and the time on one line; the forms «Тестовое событие» and «Проверка правил доставки», the block «Вход» fit.
4. PC, Chrome or Edge, `http://localhost:8080`: in the address bar or the menu «Установить приложение» is offered.

«Не так»: any screen that moves sideways, buttons too small to hit with a thumb, the PC layout changed.
