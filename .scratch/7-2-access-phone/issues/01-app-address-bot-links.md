# 01: The app address and the bot as links — `APP_URL`, the Settings line, link mode, the split of `tracker_handlers.py`

Status: in review
Complexity: medium (a pure parser, a mode of the bot, a split of a 659-line module; no external service, no database)
Blocked by: —

Spec: `../spec.md`, sections 1 (all), 2 (all), 10 (`.env`, `.env.example`), 11 (rows on `APP_URL`, the card links and the old menu), 13 (`CONTEXT.md` terms «Адрес приложения», the modes; the gotcha of `PROJECT_CONTEXT.md`). Terms — `CONTEXT.md`; standards — `docs/coding-standards.md` (rule 3 on the one router, rule 7 on texts, rule 10 on the web reaching the core only through the facade, rule 11 on module docstrings); ADRs 0002, 0007, 0008. Checks on real Telegram answers behind the spec: `../checks.md`, 1.

## What to do

- **`APP_URL`** (1.1): a new optional line of `.env`, read by `Settings` (`app/config.py`). One pure function next to `parse_user_ids`: text in, the address in its one form or the first broken rule's reason out (the five rules and the Russian reasons of the table, in that order; scheme and host lower case, the port as written, no `/` at the end). `main.py` reads it once and hands the result to the bot and to the web (Settings line); the core does not see it. At start: the warning for a malformed value and the info line for a valid one, texts as in 1.1; the value itself is not logged.
- **The Settings line** (1.2): in the block «Бот в Telegram», under the state line, the line of the three states and the two hints (private IPv4 address while `WEB_HOST` is not `0.0.0.0`; `127.0.0.1`). The texts of the spec are final. The web gets the address and the reason from `main.py`, not from the environment on its own.
- **`AppLinks`** (2.1, `app/bot/app_links.py`): `card(title_id)`, `home()`, `list()`, `settings()`; the bot holds `AppLinks | None`, `None` is chat mode. Fixed at start.
- **Link mode** (2.2–2.5), chat mode unchanged in every text and button:
  - every `CARD` button of the core's actions is a link button to the card with the same label (`_action_button` in the bot, used by `TelegramSender` and by every card markup); the other actions stay as they are;
  - a title's card sent to the chat has the one button «📄 Открыть в приложении» and not the buttons of `card_actions`; the question about watched seasons after adding from «Входящие» stays (2.3);
  - the menu is one button «📋 Сводка сейчас»; `/start` has the text of 2.4 with the text link «🌐 Открыть приложение»; the old texts «📚 Мои тайтлы» and «🧪 Тестовое событие» get the answers of 2.5 with their links; «➕ Добавить» keeps today's answer with the new menu; none of them becomes an inbox item in either mode;
  - the old callback buttons keep working in both modes (2.6).
- **The split** (2.7): `tracker_handlers.py` keeps the assembly, the menu by mode, `/start`, «Сводка сейчас», «Добавить» and the old texts, the buttons under messages and cards, `TelegramSender`, the markups; `list_handlers.py` takes «Мои тайтлы» and «Удалить несколько»; `test_event_handlers.py` takes the bot's «Тестовое событие» and its rules check. Everything stays on the one router of `register_tracker_handlers`; the menu texts of chat mode register only in chat mode, the answers of 2.5 only in link mode, the callback prefixes in both. Do the split first, with the existing tests passing untouched, then add the mode.
- **Docs and files:** `.env.example` gets `APP_URL` with a comment line (`TRUSTED_PROXIES` is ticket 04's); `PROJECT_CONTEXT.md` — the `.env` row of `APP_URL` and the gotcha «Telegram refuses `localhost` in links»; `CONTEXT.md` — the term «Адрес приложения» (in code `app_url`, `AppLinks`, `link mode` / `chat mode`; the test event and the delivery check as a form of Settings are ticket 02's); module docstrings (first sentence = the code-map line) and `.venv\Scripts\python.exe tools\code_map.py`; `docs/tests-map.md`.

## Done when

- [ ] Every rule of 1.1's table fails on its own bad value with its reason and no other; valid values come out in the one form; `localhost`, `*.localhost` and a name without a dot are refused.
- [ ] Settings shows each of the three lines and each hint from a prepared environment; a malformed value never breaks the page.
- [ ] With an address, every `CARD` button of an event, a Steam message, an announcement and a summary is a link to `/titles/<id>` with its own label; the chat card has only «📄 Открыть в приложении»; the menu has one button; `/start` and the two old texts answer as in 2.4–2.5 with the right link.
- [ ] Without an address or with a malformed one, every text and button is as before the ticket; the existing bot tests pass untouched.
- [ ] `tracker_handlers.py` is split as in 2.7, no handler is lost; the owner-filter test covers the new modules.
- [ ] No module of the core over 400 lines; the web goes through the facade only; `.venv\Scripts\python.exe -m pyflakes app tests` clean; the full suite green (the three known Windows failures are not new).

## Tests to add

- Address (1.1): each rule with a passing and a failing value; the one form (case, the `/` at the end); IPv6 in brackets; `localhost`, `*.localhost`, a single name; the reason texts.
- Settings line (1.2): three states, both hints (with `WEB_HOST` set to `0.0.0.0` and not).
- Bot, link mode: «Карточка» of an event, of a Steam event, of a summary and of an announcement is a link with its label; the chat card has only «📄 Открыть в приложении»; the menu; `/start` and the old texts with their links; «➕ Добавить»; the old callbacks work. Chat mode: the existing tests untouched. `test_tracker_owner_filter.py` for the new modules.

## Owner check

The session starts the bot itself and writes the launch result in one line. The session also edits `.env` only if the owner has put `APP_URL` there; without it the owner's check starts from step 1.

1. PowerShell: `ipconfig`, find the line «IPv4-адрес» of your network (like `192.168.1.124`). Open `E:\LocalAI\Bionic\Telegram-bot\.env` in Notepad and add two lines: `APP_URL=http://<that address>:8080` and `WEB_HOST=0.0.0.0`. Save. Then `.\start-bot.ps1` (it restarts the bot).
2. Browser, `http://localhost:8080/settings`: under «Бот в Telegram» the line «Адрес приложения: http://…. Кнопки «Карточка» в сообщениях бота открывают его.» and no hint.
3. Telegram, the bot: the menu at the bottom is one button «📋 Сводка сейчас» (if the old three buttons are still there, send `/start`). `/start` answers with the new text and a link «🌐 Открыть приложение» at its end. Type «📚 Мои тайтлы» by hand → «Список теперь в приложении: 📚 Открыть список».
4. Send the bot a film name → «Да» on the offer → the card comes with one button «📄 Открыть в приложении». Press it on the PC: the app's card opens (the login page first, then the card).
5. In `.env` put a `#` before `APP_URL`, `.\start-bot.ps1` → Settings says «Адрес приложения не задан…», the bot menu is the three old buttons after `/start`, «Карточка» sends the card to the chat.

«Не так»: Telegram answers «Bad Request: wrong HTTP URL» to a card, a menu that stays old after `/start`, a line in Settings that does not match `.env`, an error page.
