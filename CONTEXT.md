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
The number of an episode inside a season, as in the source. The bot does not track watching single episodes, only their release.
_Avoid_: эпизод
In code: `episode`.

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
All titles with a final status. In the archive the owner searches by name, sorts by score and genre and picks recommendations for friends. Tracking of the title itself has stopped, but movies and games are still checked for an announced sequel.
_Avoid_: история, просмотренное (as a section)
In code: `archive`.

**Вернуть в список** (restore):
Cancels a final status: the title leaves the archive and is checked again. The first check after the return is a reference point, without messages: what happened while the title lay in the archive does not come. For a series and anime only from «Бросил»: they get «Просмотрено» by themselves from the marks, to return such a title unmark a season.
In code: `restore`.

**Продолжение** (sequel):
The next movie of the same TMDb collection that came out or was announced after a watched movie. The owner decides whether to follow it («Следить» adds it to the list).
In code: `sequel`.

**Оценка** (score):
The owner's personal score from 1 to 10 with modifiers «+» and «−» (9−, 9, 9+): 28 steps, only «1−» and «10+» do not exist. «+» and «−» weigh a third of a point, so the score is stored as an integer in thirds (9 — 27, 9+ — 28, 10− — 29). Stored only in the app. Given only to a watched title: a movie in the archive, a season with a mark. For a series and anime a score is given per season, and the title's score is its own (set by hand) or the **average over seasons**: the exact average of the visible season scores, shown as the nearest step (exactly in the middle — up).
_Avoid_: рейтинг (that is a foreign score from a source)
In code: `score` (the scale — `scores`: `SCALE`, `label`, `average`, `rounded`; the average over seasons — `by_seasons`).

**Жанр** (genre):
The genre of a title as its source names it (TMDb, Shikimori). In the Archive filter equal genres are merged: case does not matter, «ё» counts as «е» («драма» and «Драма» are one genre «Драма»). Synonyms of different sources («Боевик» and «Экшен») are different genres.
In code: `genre` (merging — `genres`: `key_of`, `merge`).

## Games

**Бандл** (bundle):
A set of a tracked game and at least one other separate game sold together («Hades + Hades II», «The Witcher Trilogy»). In Steam — a purchase option with two games or more, whatever Steam calls it. A message comes about a new bundle of a game; about a discount on a bundle — no.
_Avoid_: набор (in messages), комплект
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
Every 6 hours the tracker asks Steam about the prices of games in «Хочу» that have a Steam page and the checkmark «играю здесь» on PC (and PC among «Мои платформы») — all in one request. The first check after a game became such (added, checkmark set, restored to the list) and after the store country changed is a reference point, without messages.
In code: `price check` (the snapshot of source `steam`; what one check saw of a game — `PriceLook`, what Steam answered — its `answer`). The rule «игра для цен» — which games have their prices checked and by which number — is `steam_number`; without the number (the card shows its block even before the page in Steam) it is `reports_prices`.

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
A game's release date without a day: month, quarter or year («март 2027», «4 квартал 2026», «2027»). Visible in the card and in «Позже» but gives no messages: messages come only about an exact day.
_Avoid_: неточная дата, TBD (that is "date not announced")
In code: `GameDate` without a day.

**Играю здесь** (playing here):
A checkmark at a platform in the game card: a message about the release on this platform will come; the checkmark on PC also decides Steam prices and discounts. At adding it stands on all my platforms where the game exists or is announced; a platform of mine that the game gets later receives it by itself.
In code: `playing` (table `game_platforms`).

## Delivery

**Рабочие дни** (work days):
Days when events accumulate until the summary hour (for the owner Sunday to Thursday). On other days events come at once.
In code: `workdays`.

**Тестовое событие** (test event):
A bot button: the owner picks a sample and gets it the way a real event would come, but bypassing the queue. The last item of the list is the delivery-rules check.
In code: `test sample` — `TestSample`, `register_test_sample`, `Tracker.test_samples()`.

**Проверка правил доставки** (delivery check):
An item of «Тестовое событие»: the owner picks a moment of the week and the bot shows what the delivery rules would do with an event at that moment. The real queue is not touched.
In code: `delivery check` — `DeliveryCheck`, `DELIVERY_CHECKS`, `Tracker.delivery_check_moment`.

**Тихие часы** (quiet hours):
A span of time when the bot sends nothing; what accumulated comes after it ends (for the owner 21:00 to 7:30).
In code: `quiet hours` — `quiet_from` / `quiet_until`.

## Interface

**Лента** (feed):
The main screen of the app: what comes out in the next days and what came out recently, by dates. Blocks: «Скоро» — the next 14 days by day, «Позже» — what comes out after them, «Недавно» — events of 7 days.
_Avoid_: дашборд, календарь
In code: `feed`; blocks — `upcoming` («Скоро»), `later` («Позже»), `recent` («Недавно»).

**Карточка** (card):
A title's page in the app (in the bot — a message) with details, seasons and buttons.
In code: `card`.

**Поиск** (search):
The app screen where the owner looks for a movie, series, anime or game in the sources and adds it to the list.
_Avoid_: добавление (as a section)
In code: `search`.

**Входящие** (inbox):
An app tab with what the owner sent to the bot (a forwarded post or a name) and the bot could not resolve: found nothing, got no answer, a post without text, the source did not answer. An entry leaves the tab when the title is added or the owner removes it. One entry is an **inbox item** («запись Входящих»).
_Avoid_: очередь (that is the delivery queue), черновики
In code: not yet (part 6.4; proposed `inbox`, an entry — `inbox item`).

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
