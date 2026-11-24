# Release tracker — glossary

A personal Telegram bot and web app that follow the owner's movies, series, anime and games, report important events and keep the owner's progress. Anyone can deploy their own instance on their own API keys.

The project's words. Headings are the Russian words of the UI and of the owner's speech; "Avoid" lists Russian words not to use in messages and talk. "In code" gives the fixed English name ("not in code yet" — the concept has no name in code). Code, docs and messages use these words; the session that introduces a term adds it here (rule 5 in `docs/coding-standards.md`). In code `kind` means only the kind of a title (movie, series, anime, game).

## Language

**Владелец** (owner):
The only person who owns the instance, its list and all notifications.
_Avoid_: пользователь, юзер, клиент
In code: `owner`.

**Тайтл** (title):
One entry in the list: a movie, a series, an anime franchise or a game. Seasons and episodes live inside the title and are not separate entries.
_Avoid_: медиа-элемент, MediaItem, произведение, элемент списка
In code: `title`; its name — `name` (`original_name` — the original); its kind — `kind` (`TitleKind`: `movie`, `series`, `anime`, `game`); its status — `status` (`TitleStatus`); status of a delivery-queue entry — `DeliveryStatus` (`pending`, `delivered`).

**Список** (list):
All the owner's titles with state and progress. A title stays in the list after release and after watching.
_Avoid_: вочлист, watchlist, закладки
In code: `list`.

**Сводка** (summary):
A daily message with all events accumulated since the last summary. The owner can ask for it by hand.
_Avoid_: дайджест, рассылка
In code: `summary` (the hour setting — `summary_at`).

## Series and anime

**Сезон** (season):
A numbered unit of a series or anime franchise that the owner can mark as watched. Specials, OVA, recaps and trailers are not seasons. An anime season is recognised by its first Shikimori record; its number is only the display order: when Shikimori inserts, removes or regroups records, the season keeps its mark and episodes and its number shifts.
_Avoid_: season-запись
In code: `season`.

**Часть сезона** (season part):
A portion of episodes of one season released separately after a long break (season 3, part 1 and part 2). A part is the same season, not a new one.
_Avoid_: cour, Part как отдельный сезон
In code: `part`.

**Серия** (episode):
The number of an episode inside a season, as in the source. The bot does not track watching single episodes, only their release. Its moment is known in one of three ways: «точное время» (the source named the moment: the day and the hour on the owner's clock), «только день» (the source knows the day: the date as the source gives it, no hour) or «неизвестно» (no moment from the source: the moment of the check that found it, or the start day of its entry; the day, no hour, and no news after «Вернуть в список»). The first episode of an announced anime season or part whose premiere the source knows only by the month or the year has no moment at all: it holds the «Примерная дата» of the premiere and is never out.
_Avoid_: эпизод
In code: `episode`; where its moment comes from — `EpisodeTiming` (`episodes.timing`); the approximate premiere — `EpisodeTiming.MONTH`/`YEAR` with `Episode.rough`.

## Statuses and archive

**Хочу** (want):
The title is added but the owner has not started watching or playing it.
In code: `want`.

**В процессе** (in progress):
The owner is now watching a series or anime or playing a game. For a running series or anime the status is set by itself: some of the released seasons are marked. For a game the owner sets it with the button «Начал играть».
_Avoid_: смотрю, играю (as separate statuses)
In code: `in_progress`; the button «Начал играть» — `start` (`mark_started`).

**Жду** (waiting):
Everything released is watched, the next season or sequel is expected, release tracking is on.
In code: `waiting`.

**Досмотреть** (to finish):
A series or anime is closed, the owner started it (at least one season is marked) but has not watched everything; release tracking is off. A closed and not started series stays «Хочу» and is checked once a week so that a comeback is not missed.
In code: `to_finish`.

**Просмотрено**, **Пройдено**, **Бросил** (watched, completed, dropped):
Final statuses. «Просмотрено» — for a movie, series and anime; «Пройдено» — for a game; «Бросил» — for any kind. The final "done" status is set by a button: «Посмотрел» for a movie, «Прошёл» for a game; for a series and anime «Просмотрено» is set by itself from the season marks.
In code: `watched` («Просмотрено»), `completed` («Пройдено»), `dropped` («Бросил»); the "done" status of a kind — `KINDS[…].finished`. The buttons «Посмотрел» and «Прошёл» are one action `watched` (`mark_watched`; the name already lives in bot buttons), the button's label — `KINDS[…].finish_press`.

**Архив** (archive):
All titles with a final status. In the archive the owner searches by name, sorts by score and genre and picks recommendations for friends. Tracking of the title itself has stopped, but a movie in «Просмотрено» is still checked for an announced sequel, and a game in «Пройдено» for its expansions and the new games of its series.
_Avoid_: история, просмотренное (as a section)
In code: `archive`.

**Вернуть в список** (restore):
Cancels a final status: the title leaves the archive and is checked again. The first check after the return is a reference point, without messages: what happened while the title lay in the archive does not come. For a series and anime only from «Бросил»: they get «Просмотрено» by themselves from the marks, to return such a title unmark a season.
In code: `restore`.

**Продолжение** (sequel):
For a movie: the next movie of the same TMDb collection that came out or was announced after a watched movie. For a game: a game of the same series of games that comes out on «Мои платформы» and did not come out before this game — a new part, a spin-off, a remake or a remaster («новая игра серии»). The owner decides whether to follow it («Следить» adds it to the list as «Хочу»).
In code: `sequel` (the game event — `game_sequel_announced`). «Следить» under an announcement of a sequel or an expansion: what it adds — `Followable`, the offer in the Feed — `FollowOffer`, the event types that have it — `FOLLOW_TYPES`; the stored key of the announced title stays `sequel_id` for an expansion too.

**Оценка** (score):
The owner's personal score from 1 to 10 with modifiers «+» and «−» (9−, 9, 9+): 28 steps, only «1−» and «10+» do not exist. «+» and «−» weigh a third of a point, so the score is stored as an integer in thirds (9 — 27, 9+ — 28, 10− — 29). Stored only in the app. Given only to a watched title: a movie in the archive, a season with a mark. For a series and anime a score is given per season, and the title's score is its own (set by hand) or the **average over seasons**: the exact average of the visible season scores, shown as the nearest step (exactly in the middle — up).
_Avoid_: рейтинг (that is a foreign score from a source)
In code: `score` (the scale — `scores`: `SCALE`, `label`, `average`, `rounded`; the average over seasons — `by_seasons`).

**Жанр** (genre):
The genre of a title as its source names it (TMDb, Shikimori). In the Archive filter equal genres are merged: case does not matter, «ё» counts as «е» («драма» and «Драма» are one genre «Драма»). Synonyms of different sources are merged by an own table in the Archive filter («Боевик» of TMDb and «Экшен» of Shikimori are «Боевик»), a composite TMDb genre counts under each part («НФ и Фэнтези» is «Фантастика» and «Фэнтези»); the card and the Search keep the source's names.
In code: `genre` (merging — `genres`: `key_of`, `merge`, the table `SYNONYMS`).

## Games

**Бандл** (bundle):
A set of a tracked game and at least one other separate game sold together («Hades + Hades II», «The Witcher Trilogy»). In Steam — a purchase option with two games or more, whatever Steam calls it. A message comes about a new bundle of a game; about a discount on a bundle — no. The price is of the whole set: Steam is asked without the owner's account, so what the owner already has is not taken off (KI-43); the card row and the message say «, цена набора целиком».
_Avoid_: набор (in messages, except the fixed words «цена набора целиком»), комплект
In code: `bundle`.

**Издание** (edition):
A version of the same game that adds its own extras (Complete, Collector's etc.). Not a bundle. It is not added as a separate title: IGDB marks an edition as a "version" of another game (`version_parent`) and it does not reach Search suggestions. In Steam an edition is a purchase option with one game, even when Steam calls it a bundle («Cyberpunk 2077: Полное издание»); it becomes the price of the game only if it is cheaper than the game itself.
_Avoid_: бандл (for editions)
In code: `edition` (the edition's name when the game's price is its price).

**Цена** (price):
The price of a game in Steam in the currency of the store country: the cheapest purchase option that holds one game (the game itself or its edition; not a bundle and not a subscription). The currency sign and its place come from how Steam writes the price. Only Steam has prices (PlayStation does not, ADR 0009).
In code: `price` (a purchase option — `purchase option`, an amount — `Money`). The owner reads it in the block «Steam» of the web card and in the line «Цена в Steam: …» of the bot card (both only for a game in «Хочу» that prices are told about: `reports_prices`), and as the mark «−30 %» of the row of the list while a discount goes (`mark`; a discount whose end has come is over for the owner before the next check): `steam view`, `price_rows`.

**Скидка** (discount):
A temporary reduction of a game's price in Steam: percent, price before and after and the end day. A message comes when a discount starts or gets deeper in the same sale; the same discount does not come twice, the next sale comes again. A 100 % discount is «раздают бесплатно». A discount that Steam itself does not show as a discount (the EU lowest-price-in-30-days law) is not counted by the tracker either.
_Avoid_: акция, распродажа (about one game's discount)
In code: `discount`.

**История цен** (price history):
Records of a game's price in Steam: a new record only when the price or the discount changed. It accumulates while the game's prices are checked. From it comes «самая низкая с добавления»: only records of the same country, currency and Steam number.
In code: `price history` (table `price_history`, a record — `PriceRecord`; «самая низкая с добавления» — `lowest`).

**Страница в Steam** (Steam page):
A game's page in the Steam store; its number (`steam_id`) comes from IGDB. When IGDB first learns the number of a game whose prices would be checked, the message «появилась страница в Steam» comes — once per game.
In code: `steam page`. The number is `steam_id`; where the core keeps what Steam was asked about — the price look and the price history — it is `appid`, the name Steam answers by (a key of stored snapshots and a column, so it stays, rule 5).

**Проверка цен** (price check):
Every 6 hours the tracker asks Steam about the prices of games in «Хочу» that have a Steam page and the checkmark «играю здесь» on PC (and PC among «Мои платформы») — all in one request. The first check after a game became such (added, checkmark set, restored to the list) and after the store country changed is a reference point, without messages. A press that makes a game no longer such («Начал играть», «Прошёл», «Бросил», the checkmark taken off, PC taken out of «Мои платформы») ends its price check at once: its snapshot and its undelivered Steam messages go in the press itself. The events of one check are queued together, so two discounts come as one message.
In code: `price check` (the snapshot of source `steam`; what one check saw of a game — `PriceLook`, what Steam answered — its `answer`). The rule «игра для цен» — which games have their prices checked and by which number — is `steam_number`; without the number (the card shows its block even before the page in Steam) it is `reports_prices`.

**Дополнение** (expansion):
A big expansion of a game: a new story or a region (Blood and Wine, Shadow of the Erdtree) — what IGDB records as an expansion. Small DLC (a quest, gear, a soundtrack) is not one. A standalone expansion plays without its game (Miles Morales, The Lost Legacy). «Следить» makes an expansion a game of its own in the list (ADR 0011): its card says «Дополнение к игре «…»», its row in the List and the Archive has the word «дополнение» after the name. An expansion that needs its game has no expansions and sequels of its own; a standalone one has.
_Avoid_: DLC (that is the small stuff), аддон
In code: `expansion` (`GameState.expansion`: `expansion` or `standalone`; the game it belongs to — `parent`; the event — `game_expansion_announced`; the word after the name of a row — `tag`: `Poller.list_tags`, `TitleSummary.tag`; not `mark`, which is the discount of Steam).

**Серия игр** (game series):
The games IGDB puts together under one name («The Witcher», «Hades»). In messages and on the card always with «игр» or «игра»: «новая игра серии», «серия «The Witcher»» — a bare «серия» is an episode.
_Avoid_: франшиза (IGDB has franchises too, with editions and crossovers in them; they are not used)
In code: `collection` (the word of IGDB; `series` is the kind of a TV series).

**Проверка дополнений и продолжений** (follow-up check):
Once a week the tracker asks IGDB about the expansions of a game and the games of its series: for a game in «Хочу», «В процессе» and «Пройдено», not in «Бросил» and not for an expansion that needs its game. The first check of a game (after adding, after «Вернуть в список» from «Бросил») only records what exists, without messages; from «Пройдено» back to «Хочу» the check goes on as it was. «Бросил» ends the check at once, so «Вернуть в список» right after it still starts anew. Each new expansion or new game of the series comes as a message of its own with «Следить»; one announced game comes once, however many games of the series are in the list (one taken out by «Бросил» before it went out can still come from another game of the series). A change of «Мои платформы» or of the store country gives no messages.
In code: `follow-up check` (`follow_ups`; the snapshot of source `igdb_follow_ups`; which games are checked — `for_follow_ups`; an expansion or a game of the series the snapshot lists — `FollowUp`, never `Candidate`, which is the «Кандидат» of «Входящие»).

**Платформа** (platform):
Where a game comes out: PC, PlayStation 5, Xbox Series X|S, Nintendo Switch 2 or Nintendo Switch. PC is one platform wherever the game is sold (Steam is only a link in the card). A game has its own release date and its own checkmark «играю здесь» on each platform.
_Avoid_: консоль, система
In code: `platform` (`Platform`, table `PLATFORMS`).

**Обратная совместимость** (backward compatibility):
A new console runs the games of the old one: PS5 — PS4 games, Xbox Series X|S — Xbox One, Switch 2 — Switch. If the old version comes out earlier, its date counts as the date of the new platform («PS5 — 27 марта 2015 (версия для PS4)»). "Earlier" is by the end of the period: «2026» ends on 31 December, so the exact day of PS5 «10 ноября 2026» is earlier than the year of the PS4 version; with equal ends the own date is taken. PS4 and Xbox One cannot be chosen in «Мои платформы»; Switch can be chosen on its own.
In code: the older platform — `older`; the date taken from it — `via`.

**Ранний доступ** (early access):
A release of a game before the full one: it can be played but is not finished (Hades II — from 6 May 2024, in full — 25 September 2025). One message about it — «вышла в раннем доступе»; later «вышла» comes separately.
_Avoid_: альфа, бета, предзаказ (not early access)
In code: `early access` (date kind — `early`; full release — `full`).

**Примерная дата** (approximate date):
A game's release date without a day: month, quarter or year («март 2027», «4 квартал 2026», «2027»); also the premiere of an anime season or part known by the month or the year («в январе 2027» in the card, «январь 2027» in «Позже»), and the date of an offer of «Входящие» («выйдет в 4 квартале 2027»). Visible in the card and in «Позже» but gives no messages: messages come only about an exact day.
_Avoid_: неточная дата, TBD (that is "date not announced")
In code: `ReleaseDate` without a day (`release_dates`; `label` alone, `phrase` inside a sentence); for an anime premiere `EpisodeTiming.MONTH`/`YEAR` and `Episode.rough`.

**Дата вне страны** (date outside the country):
A release date of a game in a region that is not the store country's (Japan, Australia…). It is not a release for the owner: no message, no piece of the Feed, no effect on the check interval. The card shows it in a line of its own after the platforms («в Японии — 12 марта 2027») when it ends earlier than the platform's own date.
In code: `outside date` (`game_rows.outside_date`, `CardPart.outside_date`).

**Поздний выход** (late release):
A game that came out earlier than yesterday and is told only now («🎮 Hades II вышла на ПК 5 октября»). It is told when its day is not earlier than 30 days before the tracker began following the game (adding or «Вернуть в список», the later one); an older day is IGDB correcting old data, not news.
In code: `late` (payload of «вышла» and «вышла в раннем доступе»), `since` of `game_events.detect_events`.

**Играю здесь** (playing here):
A checkmark at a platform in the game card: a message about the release on this platform will come; the checkmark on PC also decides Steam prices and discounts. At adding it stands on all my platforms where the game exists or is announced; a platform of mine that the game gets later receives it by itself.
In code: `playing` (table `game_platforms`).

**Русский язык** (Russian support):
Whether a game can be played in Russian: «текст» (Russian interface or subtitles), «озвучка» (full Russian voice), both, «нет», or «нет данных» when no source has said anything yet (never shown as «нет»). Official Russian comes from Steam, for a game with no Steam page from IGDB; fan Russian (народный перевод) from ZoG. The card shows both apart in the line «Русский: …», the fan part only for what the official lacks (fan voice beside official text, never fan text beside official text); «(ПК)» when the data is about the PC version only and the owner plays the game elsewhere too. Idea 002, stage 9.1b.
_Avoid_: локализация (in messages), русификатор, фанатский перевод
In code: `russian` (what one source says — `Support` with `text` and `voice`, «нет данных» is None; the line — `russian.line`; what IGDB says in the own snapshot — `GameState.russian`; the card — `RussianView`; the events — `game_russian_official`, `game_russian_fan`, the one list `russian_events.TYPES`).

**Народный перевод** (fan translation):
Russian made by fans for a game, from the game's page on ZoG (zoneofgames.ru): its «Русификатор» entries for PC or with no platform named — «текст», «звук» or both; «Українізатор» and patches for Switch or other platforms do not count. Always about the PC version. The card shows it only for what the official Russian lacks («текст — официально; озвучка — народная»), with the link «Страница перевода» to the page. «Страница на ZoG» is the game's page there: found by the name or pasted by the owner; «Не та игра» says the found page is another game.
_Avoid_: русификатор (in the app's texts), фанатский перевод, патч
In code: `fan` (`russian.FanLook` — the state of the snapshot `zog`; `FOUND`, `OWNER`, `NOT_FOUND`, `REJECTED`), the page `zog page` (`sources/zog_pages`: `addresses`, `matches`, `read_page`, `page_of`), `set_zog_page`, `reject_zog_page` (ticket 9.1b.06).

**Проверка русского языка** (Russian check):
Every 6 hours the tracker asks Steam which languages the games in «Хочу» and «В процессе» have (on any platforms), all in one request, in the US store (a game not sold in a country lists no languages there); a game with no Steam page takes what IGDB said with its dates. Once a week it reads the game's page on ZoG for the fan translation, two games a minute: a page not known yet is found by the game's original name (at most four addresses, taken only when ZoG's name and year match the game); a ZoG failure is not reported, only tried again in 6 hours; a page whose layout cannot be read keeps what it said before. The first check of a game, the check after a Steam page appeared or changed, the first read of a ZoG page and the first check after «Вернуть в список» only record what exists, without messages; later each Russian part that appears (text, voice) comes as a message («🎮 В «Stray» появился русский текст», «🎮 Для «Baldur’s Gate 3» вышла народная русская озвучка» — a fan part only when the official lacks it), Russian that disappears gives none, and a source that says nothing keeps what it said before. «Прошёл» and «Бросил» stop the check and take its undelivered messages out; the card keeps the last line.
In code: `Russian check` (`pollers/game_russian` — the official part; `pollers/game_zog` — the ZoG part; the snapshots of sources `russian_official` and `zog`, what one check saw — `russian.Look`, `russian.FanLook`; which games are checked — `for_russian`; the events — `game_russian_official`, `game_russian_fan`).

## Delivery

**Рабочие дни** (work days):
Days when events accumulate until the summary hour (for the owner Sunday to Thursday). On other days events come at once.
In code: `workdays`.

**Тестовое событие** (test event):
A form of Settings (the bot's menu button only in chat mode): the owner picks a sample and gets it the way a real event would come, at once, whatever the hour. In the bot the last item of the list is the delivery-rules check.
In code: `test sample` — `TestSample`, `register_test_sample`, `Tracker.test_samples()`; the form `app/web/settings_test_event.py`.

**Проверка правил доставки** (delivery check):
A form of Settings and an item of the bot's «Тестовое событие»: the owner picks a moment of the week and sees what the delivery rules would do with an event at that moment (delivered at once, held and played out as a summary, not delivered). The real queue is not touched.
In code: `delivery check` — `DeliveryCheck`, `DELIVERY_CHECKS`, `Tracker.delivery_check` (the one place of the logic; the bot and Settings only word its `DeliveryCheckResult`), `Tracker.delivery_check_moment`.

**Тихие часы** (quiet hours):
A span of time when the bot sends nothing; what accumulated comes after it ends (for the owner 21:00 to 7:30).
In code: `quiet hours` — `quiet_from` / `quiet_until`.

## Copies

**Копия базы** (backup):
A file of `data/backups` that holds the whole database at one moment, made with SQLite's online backup. Four, by what made it (its origin, not a «kind»: that word is a title's): the daily copy (the hourly job makes it when the newest daily one is over a day old; 14 newest and one a month for 12 months are kept), the manual copy (the button «Сделать копию сейчас»; 10 newest kept), the copy before an update (before a migration; never deleted) and the copy before a restore (never deleted). The time in its name is UTC with a `Z` (`tracker_db_20261123_132100Z.db`); a name made before 9.1d has no `Z` and is the clock of the container that wrote it. Every copy is shown in the zone chosen in Settings.
_Avoid_: бэкап (in messages to the owner), дамп
In code: `backup` — `app/utils/backup.py` (`Copy`, `Copy.origin`, `copies`), the core's `Backups`, `Tracker.backup_block`, `make_backup_now`, `backup_database`; the event `backup_failed`.

**Копия в Google Drive** (drive copy):
An encrypted archive of a copy of the database in the owner's own Google Drive, in the folder «Трекер — копии» (7z with AES-256, the password `BACKUP_PASSWORD`; 30 kept). Off by default: on when `.env` has the owner's Google client and the password (`DriveSettings.setup`), then connected once by «Подключить Google Drive» in Settings on this PC; the connection is the file `data/google_drive_token.json`, outside the database.
_Avoid_: бэкап в облаке, облачная копия
In code: `drive copy` — module `google_drive` (`GoogleDrive`, `DriveSettings`, `DriveFiles`), its sending `drive_copies` (`DriveCopies`: after each daily and manual copy and after the sign-in), the state of the sending `drive_state` (`DriveState`, the file `data/google_drive_state.json`), its texts `drive_rows` and `backup_events` (the reason keys `connection`, `sign_in`, `full`, `down`, `no_copy`, `unknown`), the archive `app/utils/archive.py`, the Google client `app/providers/google_drive.py`; `Tracker.drive_sign_in`, `drive_signed_in`, `drive_sign_out`.

**Пароль копий** (backup password):
The password the archives of the Google Drive copy are encrypted with: `BACKUP_PASSWORD` in `.env`, at least 12 characters. Kept by the owner outside this PC too: without it the copies in Google Drive cannot be opened; a new password holds only for new copies.
_Avoid_: ключ шифрования
In code: `backup_password` (`Settings`), `DriveSettings.password`.

**Восстановление** (restore):
The database replaced as a whole by a copy — one of `data/backups`, a downloaded archive of the Google Drive copy or a `.db` taken out of it — by `restore-bot.ps1` with the bot stopped; the base it replaces is kept first as the copy before a restore. It touches nothing but `tracker.db`. Not «Вернуть в список» of a title (in code `restore_title`).
_Avoid_: откат, импорт
In code: `restore` — `app/utils/restore.py` (`list_copies`, `check`, `apply`), run by `restore-bot.ps1` in a one-off container (`app.container_start app.utils.restore`).

**Выгрузка** (export):
The data of the owner as a file to download from Settings: the CSV list (one line per title, for Excel) and the JSON of everything (titles with seasons, episodes, platforms, prices, the settings and «Входящие»). Download only: there is no import, the data comes back from a copy of the database.
_Avoid_: импорт, дамп
In code: `export` — `Tracker.export_list`, `export_all`, the core's `Exports` (`exports`), `export_all` (the JSON document), `export_rows` (the formats, pure); the addresses `/settings/export.csv`, `/settings/export.json`.

## Interface

**Адрес приложения** (app address):
The address the links of the bot lead to: `APP_URL` in `.env`, the PC's address in the home network with the port or a name with a dot (not `localhost`: Telegram refuses such links); a Cyrillic name is taken as written (`https://трекер.рф`), the bot's links and the browser use its `xn--…` form, Settings shows it as written. With it the bot is in link mode: «Карточка» under a message is a link, a card in the chat has «Открыть в приложении», the menu is «Сводка сейчас» alone. Without it (or with a malformed one) the bot is in chat mode and keeps the cards in the chat, as before. The mode is fixed at start.
_Avoid_: URL бота, ссылка на веб
In code: `app_url` (`Settings`, read through `app_url_reading` → `AppUrl` with `address`, `host` and `shown`, `parse_app_url`), `AppLinks` (`app/bot/app_links.py`), `link mode` / `chat mode`.

**Вход** (sign-in):
One browser where the password was typed and that has not been ended: the PC, the phone, the browser of Telegram each count as a device. «Выйти» ends this one; «Выйти на всех устройствах» in Settings ends all of them; 30 days without a request end one by itself. The server keeps them, the last login and the count of wrong passwords in `data/web_login.json` (ADR 0014), with a mark of the password and the key of `data/web_secret`: a change of either ends all sign-ins at start, so the block «Вход» of Settings, which shows the last login and how many are open, counts only those that still work.
_Avoid_: сессия (in the owner's texts), авторизация
In code: `sign-in` — the store `SignIns` and the cookie middleware `SessionCookies` of `app/web/sessions.py`, the id `sid` in the cookie and the file, the `mark` of the file (`auth.login_mark`); the block `app/web/settings_sign_in.py`. Not the Google Drive sign-in (`drive_sign_in`).

**Сообщение о входе** (login report):
The Telegram message about a sign-in or a lock: «🔐 Вход в приложение: Android, Chrome, сегодня в 14:32, адрес …» for every right password, «⚠️ Вход в приложение закрыт на 15 минут: 5 неверных паролей подряд…» for the wrong try that begins a lock. Both are sent at once, whatever the delivery rules, and never wait for Telegram; one that failed to send goes at the next delivery pass, whatever the rules (quiet hours, a working morning), as a message of its own and never in a summary, and never expires (KI-73). The address is named only when it is a public one. It has a sample in «Тестовое событие» («Вход в приложение»). The device is in words (`Android, Chrome`), never the raw `User-Agent`.
_Avoid_: уведомление о входе, алерт
In code: the events `web_login` and `web_login_locked` (`WEB_LOGIN`, `WEB_LOGIN_LOCKED`; no title, so the Feed never shows them), the texts `app/tracker/login_events.py`, the record `Tracker.record_login_report` (`login_reports`), the web side `LoginReporter` (`app/web/login_report.py`), the device words `app/web/devices.py`.

**Лента** (feed):
The main screen of the app: what comes out in the next days and what came out recently, by dates. Blocks: «Скоро» — the next 14 days by day, «Позже» — what comes out after them, «Недавно» — events of 7 days. «Недавно» also shows what came out in those days before adding or while the title was in the archive (rows from the schedule: a grey line «вышла до добавления в список» / «…, пока тайтл был в архиве», no hour, no buttons), unless an event already tells it.
_Avoid_: дашборд, календарь
In code: `feed`; blocks — `upcoming` («Скоро»), `later` («Позже»), `recent` («Недавно»); rows from the schedule — `feed_released`.

**Карточка** (card):
A title's page in the app (in the bot — a message) with details, seasons and buttons.
In code: `card`.

**Поиск** (search):
The app screen where the owner looks for a movie, series, anime or game in the sources and adds it to the list. Opened by «Найти» of an inbox item, it says «Из «Входящих»: добавленный тайтл уберёт эту запись.»: adding a title deletes that item (the `inbox` parameter of the address).
_Avoid_: добавление (as a section)
In code: `search`.

**Входящие** (inbox):
An app tab with what the owner sent to the bot (a forwarded post, a name, an album, a forward with its comment) and the bot could not resolve: found nothing, got no answer, a post without text, the source did not answer. An entry leaves the tab when the title is added or the owner removes it. One entry is an **inbox item** («запись Входящих»).
_Avoid_: очередь (that is the delivery queue), черновики
In code: `inbox`; an entry — `inbox item` (table `inbox_items`, `InboxRecord`; what the core hands out — `InboxEntry`; the message it is made of — `IncomingMessage`; what the bot says next about it — `InboxReply`). Its states (`InboxState`): `waiting` «ждёт ответа» (the question «Что это?» or an offer waits in the chat; at most one) and `inbox` (in the tab). The answer to its pause — the question or the first offer card — is marked (`answered_at`): a waiting item a restart left without it gets the question after the start too, in the owner's chat. Its reasons (`InboxReason`): `not_found` «не нашёл», `no_answer` «без ответа», `no_text` «нет текста», `source_failed` «источник не ответил», `not_connected` «игры не подключены». A resolved, not saved or removed item is deleted.

**Кандидат** (candidate):
A name the rules pick from what the owner sent to the bot (a name message, a Latin run, a quote, a bold piece, a capitalised Russian name in the middle of a sentence…), with a weight; the most likely ones are searched in the source of the kind. A name that is a company of IGDB (at least 20 games) is dropped before the search.
_Avoid_: вариант
In code: `candidate` (`Candidate` of `candidates`); the companies — `companies` (`IgdbGameSource.companies`, `sources/igdb_companies`).

**Предложение** (offer):
A record of a source the bot shows for an inbox item as a card «Это оно?» (or «Возможно, вы имели в виду:» after a typo) with «Да» / «Нет»; «Да» adds it to the list. Its date is as precise as the source knows it: «выйдет 12 февраля 2027», «выйдет в 4 квартале 2027», «выйдет в 2028», the year once out. Not a search suggestion of the web or of a source.
_Avoid_: подсказка, результат поиска
In code: `offer` (`Offer` of `offers`, the card — `OfferCard`); a search suggestion is `Suggestion`. Not the «Следить» of an announcement (`FollowOffer`, `offers_follow_ups` — «Продолжение»): there `offer` is part of a longer name, never alone.

**Настройки** (settings):
The app screen with the owner's rules (time zone, work days, summary hour, quiet hours, season-part threshold — the break in weeks after which a series season is split into parts; my platforms; store country); stored in the database. Not the `.env` file — that is the launch settings (`Settings` in `app/config.py`).
_Avoid_: конфиг
In code: `settings`.

**Мои платформы** (my platforms):
Checkmarks of platforms in Settings (default PC and PlayStation 5; at least one). The game card shows only them; release events, the Feed and prices count only them — and the checkmarks «играю здесь» of the game itself.
_Avoid_: все платформы
In code: `my platforms` (setting `my_platforms`).

**Страна магазинов** (store country):
The country of the owner's Steam and PlayStation accounts (default Israel). It picks the region of a game's release dates, the store in the PlayStation Store link and the Steam prices (their currency).
In code: `store country` (setting `store_country`, table `STORE_COUNTRIES`).
