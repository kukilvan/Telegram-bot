# Checks behind spec 7.2

Done 2026-11-15 in the session «Спека 7.2». What was asked and what came back; the spec sections that lean on each.

## 1. Which addresses Telegram takes in a link (spec 1.1, 2)

`sendMessage` of the owner's bot to the owner's chat, with the owner's leave; every accepted message deleted at once (`deleteMessage` answered `ok`). Script: a one-off in the session's scratch folder, printing only Telegram's verdicts.

| Address | Inline button (`url`) | Text link (`text_link` entity) |
|---|---|---|
| `http://192.168.1.124:8080/titles/1` | accepted | accepted |
| `http://127.0.0.1:8080/titles/1` | accepted | accepted |
| `https://tracker.example.com/titles/1` | accepted | — (not asked) |
| `http://localhost:8080/titles/1` | **refused**: `400 Bad Request: inline keyboard button URL 'http://localhost:8080/titles/1' is invalid: Wrong HTTP URL` | **refused**: `400 Bad Request: entity URL '…' is invalid: Wrong HTTP URL` |

One refused button refuses the whole message: a message with four buttons, one of them `localhost`, was not sent at all. So an address Telegram does not take would stop **every** message with a card button — the queue keeps them and tries again forever. Hence the address rules of spec 1.1 refuse `localhost` and single names without a dot before the bot ever uses them. Single names (`http://desktop-pc:8080`) were not asked; they are refused by the same rule to be safe.

## 2. Every screen at phone width (spec 7)

A scratch web server (`create_web_app` on a copy of `data/tracker.db` made with SQLite's online backup, a throwaway password, port 8091, no bot and no polling) opened in the desktop app's browser pane at 375 × 812 and 320 × 640. On every page a script looked for elements past the right edge and for controls lower than 40 px.

| Screen | 375 px | 320 px | Seen |
|---|---|---|---|
| Лента | no overflow | no overflow | the menu takes two rows («Настройки» alone on the second) |
| Список, also «Удалить несколько» | no overflow | no overflow | the search and the filter rows (kind, status, order: 7 rows of 44 px) fill the whole first screen; the first title is below it |
| Архив | no overflow | no overflow | the same, with the genres: 9 rows of filters before the first title |
| Поиск | no overflow | no overflow | fine |
| Входящие (empty) | no overflow | — | fine |
| Карточка: movie, series, anime with a 63-letter name, game | no overflow | no overflow | fine; the poster 160 px wide in the middle |
| Настройки | no overflow | no overflow | «Тихие часы»: «с [21:00] до» on one line and «[07:30]» alone on the next |
| Вход | no overflow | no overflow | fine |

Every control is at least 44 px high: the checkboxes and radio buttons are 20–24 px, but each sits in a label 44 px high, which takes the touch. Text width inside a page box: 375 − 2 × 16 (page) − 2 × 21 (box border and padding) ≈ 300 px.

Not measured: «Входящие» with items (the copy had none) — the ticket of spec 7 fills a few in its own copy.

## 3. Installing the app (PWA) without a service worker (spec 8)

- Chrome dropped the service worker with a `fetch` handler from its install criteria for installing from the browser menu: version 108 on Android, 112 on desktop. The automatic install banner may still want one; the menu item «Установить приложение» / «Добавить на главный экран» does not. Source: «Revisiting Chrome's installability criteria», developer.chrome.com/blog/update-install-criteria; blink-dev «Remove the service worker requirement for WebAPKs».
- iOS Safari «На экран „Домой“» never needed one; it reads `apple-touch-icon` and the `apple-mobile-web-app-*` tags, which `base.html` has.
- So no service worker is added and ADR 0004 (no own JavaScript) stands.
- Behind Cloudflare Access the browser fetches the manifest **without cookies** unless the `<link rel="manifest">` has `crossorigin="use-credentials"`; without the Access cookie the request is turned to Access's sign-in page and the manifest is lost. The usual fix is an Access «Bypass» policy for the manifest and icons (reports on Hudu, SilverBullet and Chatwoot; one report says `use-credentials` broke other PWA features). Spec 9 asks the NAS project for a Bypass on `/static/` (nothing private there).
