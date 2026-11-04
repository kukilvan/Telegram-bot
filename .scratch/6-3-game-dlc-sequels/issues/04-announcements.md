# 04: Announcements — buttons, summary names, Feed «Следить», bot texts, samples

Status: open
Complexity: medium (one shared list of event types, button and summary naming, a renamed Feed route and the types `Followable` / `FollowOffer`, the bot texts by the kind's source; each part is small, together they touch delivery, Feed, bot and web)
Blocked by: 02, 03

Spec: `../spec.md`, sections 6.4 (buttons), 6.5 (summary), 6.6 («Тестовое событие»), 7.5 (bot «Следить»), 7.6 (Feed), 2.2 (rows `actions.py`, `feed.py`, `feed_rows.py`, `delivery_service.py`, `test_samples.py`, `app/bot/tracker_handlers.py`, `app/web/feed.py`, `feed_body.html`), 0 («In a summary», «Texts», «the wish "a sequel as a pair"»), 8 (rows «Следить» before the weekly check, an announcement waiting for the summary, a waiting message and «Следить» on the card), 9.1 («Bot and Feed»), 9.2 steps 4–5, 10 (documents). From ticket 01 it takes the event types, the texts and the two samples; from 03 `Tracker.follow`. Terms — `CONTEXT.md`; standards — `docs/coding-standards.md` (rules 1, 5, 6, 7, 8, 10, 11). ADR 0002 (the bot is the delivery channel).

Ticket 02 already queues the announcements; before this ticket they carry no buttons. Here they get them.

## What to do

- **`actions.FOLLOW_TYPES`** (6.4): the one list of the event types with «Следить» — the movie `SEQUEL_ANNOUNCED` and `follow_ups.TYPES`; every place that decides «has a follow button» reads it, none compares one type. Under a game announcement: «👀 Следить» (`follow`, arg `game:<igdb id>`) and «📄 Карточка» (the checked game); a movie announcement keeps «👀 Следить» alone.
- **Summary** (6.5, `delivery_service.py`): the button «👀 Следить» is named by the announced game (`sequel_title`), every other button by the event's title: «👀 Следить: Elden Ring: Shadow of the Erdtree», «📄 Карточка: Elden Ring»; «Следить» is never cut. Announcements are lines of the one summary, each with its own button; outside the summary each is a message of its own (decision 5, no folding).
- **Feed** (7.6): `Followable(kind, external_id)` and `FollowOffer(target: Followable, title_id)` replace the bare tuple and `SequelOffer`; `feed_rows.followable_of(data)` replaces `sequel_of` (None for an announcement of the old format); `feed._listed` is keyed by `Followable` and reads the titles already listed for every type of `FOLLOW_TYPES`. «Недавно» shows an announcement as a row with the first line of the message, the other two smaller, and «Следить» or «В списке»; an old-format announcement has no button. `app/web/feed.py` and `feed_body.html`: `POST /feed/follow` (`feed_follow`) replaces `feed_sequels` with `kind` and `external_id`. «Скоро» and «Позже» show a followed expansion as any game. The facade exports `FollowOffer` and `Followable` instead of `SequelOffer`.
- **Bot «Следить»** (7.5, `app/bot/tracker_handlers.py`): the button `game:<id>` goes through the same handler as a movie's — answer, work, tell (rule 8); after it «✅ Добавлено в список» and the card of the added title, for every kind (the text «✅ Продолжение добавлено в список» goes); «Уже в списке» as now. The errors name the source of the button's kind from `KINDS[…].source_name` (an old button with only a number is a movie's: TMDb): «Не нашёл это в IGDB. Попробуйте чуть позже.», «Не удалось получить данные из IGDB. Попробуйте чуть позже.».
- **«Тестовое событие»** (6.6, `test_samples.py`): two text samples after the game samples, `game-expansion` («Игра: анонсировано дополнение») and `game-sequel` («Игра: новая игра серии»), the texts of the spec, no buttons; their ids must not conflict with real keys.
- **Docs:** module docstrings, `tools\code_map.py`; `docs/tests-map.md`; check `CONTEXT.md` against the code — the words «Дополнение», «Продолжение», «Серия игр», «Проверка дополнений и продолжений», «Архив» are used in code and texts exactly as written (`tests/test_code_speaks_glossary.py` stays green); `docs/coding-standards.md` if a rule changed. «Next step» of `PROJECT_CONTEXT.md` changes only with the owner's «ОК» — at that step it becomes the review of 6.3.

## Done when

- [ ] A game announcement has «👀 Следить» (`game:<id>`) and «📄 Карточка»; a movie announcement has «Следить» alone; nothing outside `actions.FOLLOW_TYPES` offers «Следить»; no kind or event type is compared elsewhere.
- [ ] In a summary the buttons are named as in 6.5, «Следить» never cut; announcements are separate lines each with its own button; outside a summary each announcement is its own message.
- [ ] «Недавно» shows game and movie announcements with «Следить» or «В списке»; an old-format announcement has no button; `feed_follow` replaces `feed_sequels`; the Feed holds no bare `(kind, id)` tuple of a sequel.
- [ ] The bot's «Следить» on a game adds it, answers «✅ Добавлено в список» with the card, and «Уже в списке» for a game already listed; the texts of errors name IGDB for a game and TMDb for a movie and for an old button; the early answer of rule 8 comes before the work (`test_tracker_early_answer.py`).
- [ ] An announcement waiting for the summary while the owner follows its game from the card: the message still comes and its «Следить» answers «Уже в списке».
- [ ] «🧪 Тестовое событие» has the two new samples with the exact texts of 6.6.
- [ ] Rules 1, 5, 6, 7, 8, 10, 11; `test_tracker_core_split.py`, `test_code_map.py`, `test_code_speaks_glossary.py` green; `pyflakes app tests` clean; the full test suite green (the three known Windows failures are not new).
- [ ] For the owner (the session starts the bot): step 4 of spec 9.2, and a look at each sample.

## Tests to add

- Spec 9.1 «Bot and Feed»: the buttons of 6.4; the names in a summary (6.5); «Недавно» with «Следить» and «В списке» for game and movie announcements, an old-format announcement without a button; `feed_follow`; the bot «Следить» of a game and its texts (rule 8: `test_tracker_early_answer.py`); the two samples; the existing movie-sequel tests move to the new names with the same assertions.

## Owner check

The session starts the bot itself and writes the launch result in one line. The owner's check (Telegram, the bot's chat; a real announcement cannot be made on purpose — the tests cover it):

1. Press the bot's button «🧪 Тестовое событие». Two new samples come among the others: «Игра: анонсировано дополнение» — «🎮 Анонсировано дополнение: Ведьмак 3: Дикая Охота — Баллады прошлого», the line «Дополнение к игре «Ведьмак 3: Дикая охота»» and «Выход: 2027»; «Игра: новая игра серии» — «🎮 Анонсирована новая игра серии: The Witcher IV», «Продолжение игры «Ведьмак 3: Дикая охота»», «Выход: 2028». Samples have no buttons.
2. Web, `http://localhost:8080` → «Лента» → «Недавно»: nothing of 6.3 is expected there yet (the real announcements will come); the old movie announcements keep their «Следить» or «В списке».

«Не так»: a sample is missing or its text differs; a movie announcement lost its button. What the session verifies itself: the buttons of both announcement types and the names in a summary (tests and a run with a test event), and tells the owner in one line.
