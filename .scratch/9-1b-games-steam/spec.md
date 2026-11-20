# Spec 9.1b: games and Steam prices — the known issues and Russian in games

Status: in review

Built from `description.md` (accepted 2026-11-21) and idea 002. Terms come from `CONTEXT.md`. ADRs it leans on: 0004 (no own JavaScript), 0007 (one process), 0009 (no PlayStation prices; its reason against reading store pages is answered for ZoG in the new ADR 0016, section 11), 0011 (a followed expansion is a game of its own: its decision stands, its last consequence — KI-52 — stops being true), 0015 (`checks.still_checked`). No migration: everything new lives in JSON snapshots (section 6).

Live answers of 2026-11-21 are saved in `answers/` (section 7); the tickets copy what their tests need into `tests/fixtures/`. The live checks of the description (Steam languages of Cyberpunk 2077 and Stray, ZoG addresses) were not repeated, only saved.

## 1. Game dates and links

### 1.1 KI-35 — a date outside the store country's regions is not a release

- `games.pick` takes only the records of the regions of the country (`STORE_COUNTRIES[country].regions`, in their order); the fallback «the earliest of the others» goes. A platform with records only outside those regions has no date of that type: its card line reads «PS5 — дата не объявлена», no «вышла», no «дата объявлена», no piece in the Feed, no effect on `check_interval`. The follow-up dates (`follow_ups.follow_up_date`) read through the same `pick`, so they change the same way.
- **The outside line** (pure, `game_rows`): over the platforms of «Мои платформы» the game is on and that are not cancelled, the full-release records (own IGDB platform and its older one) of regions outside the country's table, announced dates only; the earliest by start. It is shown when it ends earlier than that platform's own date for the country (or the platform has none announced). Text: `«в <region> — <date label>»`, e.g. «в Японии — 12 марта 2027», «в Японии — март 2027». Region words (table in `platforms`, rule 6): 3 «в Австралии», 4 «в Новой Зеландии», 5 «в Японии», 6 «в Китае», 7 «в Азии», 9 «в Корее», 10 «в Бразилии», 0 (no region) «в другой стране». Regions 1, 2, 8 are in every country's table, so they never appear.
- Web card: a row after the platform rows, without a checkbox, then the hint «Дата только в Японии — не выход для вашей страны: сообщения «вышла» по ней не будет.» (`Дата только <region> — …`). Bot card: the same line after the platform lines. `CardPart.outside_date: str` (empty — none).

### 1.2 KI-36 — a late release still comes

- The 30-day rule (`game_events.FRESH` against today) is replaced: «вышла» and «вышла в раннем доступе» on a platform come when the new date is an exact day not later than today, the previous snapshot did not have it out (as now), and the day is **not earlier than 30 days before the tracker began following the game** — the later of `Title.added_at` and `Title.restored_at`, as a UTC date. `GamePoller.apply` reads it in the read session it opens already and passes it to `detect_events` (`since: date`). The set of messages only grows: today's rule is the case «began following = today».
- An old correction stays silent: a game added in 2026 whose «2015» becomes «19 мая 2015»; a game added with no date that gets an old day.
- **Late form.** A release whose day is earlier than yesterday names the day: «🎮 Hades II вышла на ПК 5 октября», «🎮 Hades II вышла в раннем доступе на ПК 5 октября»; another year — «5 октября 2025». On time (today, yesterday) — the text as now. The payload gets `late` (the day as stored text, or absent); `game_events.fold_key` of these two types adds `late`, so only releases of the same day fold («вышла на ПК и PS5 5 октября»).
- No mark per platform and no migration (the direction of the description said «a mark»; the day following began says the same without a new column: «вышла» can come only once anyway — its key `game:<id>:<platform>:released`).

### 1.3 KI-38 — a record without precision

`GameDate.from_igdb`: when `date_format` is missing or not one of 0–7, the record is a year — `y`, else the year of `date` (UTC); 7 stays «not announced». Never a month or a day: in the saved answers (1 267 records) a year record carries `m: 12` and a quarter record the quarter's last month, so `m` cannot tell a month from them (the direction said `y`, `m`). The KI example `{"date": 1795046400, "y": 2026}` reads «2026»; an approximate date gives no messages.

### 1.4 KI-37 — the PlayStation Store link

- Live (2026-11-21): `HEAD https://store.playstation.com/<locale>/concept/<n>` answers `200` for a concept the store has (Hades II `10018449`, Bloodborne `200520`, GTA VI `10000730` in `en-il`; `en-tr` too), and `302` with `Location: /<locale>/error?conceptId=<n>&…` for one it does not have (`99999999`). The page itself is 400–700 KB; `HEAD` is enough (0.2–1 s).
- The web card's «Открыть в PlayStation Store», when the game has a concept, leads to the app's own address `GET /titles/<id>/playstation` (route `card_playstation`, behind the login). It asks `Tracker.playstation_link(title_id)`: the core reads the concept, the original name and the country (no network), then one `HEAD` without following redirects (5 s): `200` → the concept page; `302` to an address with `/error` → the search by the original name (as for a game without a concept); a failure or any other answer → the concept page (as today). The answer is kept in memory a day per (locale, concept). The route answers `302` to that address; a title gone, not a game or without the link → the card.
- Without a concept the link is the search, as now (no request). The bot's card keeps the concept address in its text line («PS Store: …»): the core does not know the app address there, and in link mode the card opens the web card. KI-37 closes «fixed for the web card; the bot's text link keeps the concept».

## 2. The price check

### 2.1 KI-43 — the bundle price (won't fix)

The price stays the full price of the set (only a Steam sign-in knows what the owner has). Texts gain «, цена набора целиком»:
- web card, block «Steam», a bundle row: ««Hades + Hades II» (2 игры) — ₪250, цена набора целиком»;
- the message: «🎮 Hades II продаётся в бандле «Hades + Hades II» (2 игры) — ₪250, цена набора целиком» (and its sample «Игра: бандл в Steam»).

The entry closes `won't fix (test: …)`. The first ticket that closes a `won't fix` entry adds the status to the rules at the top of `KNOWN_ISSUES.md` (decision 4 of the 9.1 description): «`won't fix (test: …)` — the app cannot fix it; the entry says why and what the owner decided; the test pins the behaviour».

### 2.2 KI-44 — a live preorder

Live (`answers/getitems_preorder_il_live.json`, three games, Israel): a preorder is `is_coming_soon: true` with one-game purchase options, as assumed. The parser reads it unchanged: Warhammer 40,000: Dawn of War IV — preorder with a discount (₪238 → ₪214,20, −10 %, until 3 December), DRAGON QUEST MONSTERS: The Withered World — preorder ₪209, Rayman Legends Retold — preorder ₪159. A test on this fixture checks the look and the card lines («Предзаказ со скидкой −10 %: ₪238 → ₪214,20, до 3 декабря», «Предзаказ: ₪209»). KI-44 closes `fixed (test: …)`; no parser change.

### 2.3 KI-46 — short discounts (won't fix)

Checks stay every 6 hours, messages go by the delivery rules (decision 3 of 9.1). A test pins it: `PRICE_INTERVAL` is 6 hours; a discount found on a work day at 22:00 that ends at 08:00 the next day is old by the 15:00 summary and is not sent; one that ends after 15:00 is sent in the summary. Closes `won't fix (test: …)`.

### 2.4 KI-50 — a spoiled price snapshot

The reconciliation reads each price snapshot on its own: one whose state `PriceLook.from_state` cannot read is left out of the plan (not reset, not asked) — unless the game is no longer for prices, then it is dropped as any. Such a game counts as a failure of its check («неизвестная ошибка») each time its snapshot is due: the `ValueError` joins the failures of the pass and the snapshot waits 30 minutes, so the owner gets «could not check» once a day by the usual window. The log line «title N: its price snapshot cannot be read» comes once a day per game (`failures.DailyLog`, section 8). The other games are checked as usual. (The direction said only «skipped with a log line»; the report follows KI-55, so the owner learns that something is wrong.)

### 2.5 KI-51 and the wish of review 9.1a — one write session for the events of one check

`GamePrices.check` works in three phases: (1) all packs are asked; for every game answered, the events are detected in a read session (as `_store` does now); (2) **one write session** queues the events of every game of the check: a game no longer checked (`checks.still_checked(session, due)`, section 3) or a fact already known (the keys of the batch are read first: the write session holds the database) is skipped without a rollback; a new discount takes the undelivered discount of its game out of the queue only when it is queued itself; one commit; (3) each look is stored in a write session of its own (a failed store finds the same facts again next time, their keys drop them). The delivery job reads all the events of a check or none, so two discounts of one check fold into «🎮 Скидки в Steam:».

The queueing of a batch is `EventQueue.enqueue_all` (one place, also used by the Russian official check, section 5.5); `EventQueue.enqueue` stays for one event.

## 3. A press ends the checks at once; a withdrawn event frees its key

### 3.1 KI-47 and KI-53 — the press

The checks at the end of a pass made their snapshots and dropped them only in the reconciliation of the next pass, so a message could go out (KI-47) or a reference point be lost (KI-53) in that minute. Now a press that can stop a check of a game does the reconciliation's «drop» itself, in its own write session:

- `Poller.after_marks(session, title_ids)` — base: nothing; `GamePoller`: for the given games (None — all games of the kind): the price snapshots of games no longer «игра для цен» (`steam_number`) go, with their undelivered Steam events (`price_events.TYPES`); the follow-up snapshots of games no longer «игра для проверки» (`for_follow_ups`) go; the undelivered Russian events (section 5.8) of games no longer in «Хочу» or «В процессе» are withdrawn (their snapshots stay: the card keeps the line, section 5.9). The same rules as the reconciliation (one place each), only applied now.
- Called in the write session of: «Прошёл» (`_set_watched`), «Начал играть», the mark «играю здесь», «Бросил», and the save of Settings (the hook is given to `SettingsStore` by the core; for every kind, `title_ids` None) — «Мои платформы» without PC ends every price check at once.
- New snapshots are made only by the reconciliation at the start of a pass (under `poll_lock`), never by a press. So during a check a snapshot can only disappear, never be replaced by a fresh one the check would overwrite.
- KI-53: «Бросил» drops the follow-up snapshot at once; «Вернуть в список» gets an empty one at the next pass, and its first check is the silent reference point.
- The docstrings of `pollers/game_prices.py` and `pollers/game_follow_ups.py` («No button touches the … snapshots») change: the rule still lives in one place, a press only applies it.

### 3.2 `still_checked` for the checks at the end of a pass

- Prices and follow-ups: «the snapshot exists» is now enough (the press drops it at once). The follow-up check queues through `EventQueue.enqueue(…, due=game)` (the wish of review 9.1a) instead of its own `_title_checked`; `_decide` keeps `_title_checked` for reading what the rules need.
- `DueTitle` gets `statuses: tuple[TitleStatus, ...] | None = None`: when set, `still_checked` also requires the title's status to be one of them. The Russian checks set it to «Хочу», «В процессе» (their snapshots stay after the game leaves them).

### 3.3 KI-54 — a withdrawn event frees its key

`EventQueue.withdraw` deletes the undelivered queue entries **and their events** (explicitly both, not by cascade). A fact taken out by «Бросил», by the end of a price check or by a deeper discount can then come again — from another game of the series (KI-54), never from the same game: «Вернуть в список» makes every check of the game start with a silent reference point, and a deeper discount moves the stored look past the older one. A withdrawn event also leaves «Недавно» (it never went out). The docstring «The events stay: their dedup keys keep the same facts from coming again» changes.

## 4. The follow-up check

### 4.1 KI-52 — the game's own type and parent

`FOLLOW_UPS_QUERY` also asks `parent_game.name` (it asks `game_type` already); `parse_follow_ups` reads the game's own expansion kind and parent with the helpers of `sources/igdb_games` (`expansion_type`, `_parent` made public as `parent_of`) into `FollowUpsSnapshot.own_expansion` / `own_parent` (not stored in the follow-up state). In the store write session, when the game's own check does not run (status not in `POLLED_STATUSES` or tracking off — a game in «Пройдено»), and the own snapshot's `expansion` / `parent` differ, they are written into the own snapshot (`GameState` with them replaced; a spoiled own state is left alone — section 4.2 reports it). A standalone expansion completed before 6.3 then gets «Дополнение к игре «…»» and the List mark after its next weekly check. A game that turns out to need its game (type 2) is dropped from the check by the next reconciliation, as any.

### 4.2 KI-55 — an unreadable own snapshot

- Reconciliation: a game whose own snapshot cannot be read (`games.expansion_of` raises) is treated by its status alone: in «Хочу», «В процессе», «Пройдено» it counts as a game for the check (its snapshot is made if missing, never dropped). The log line comes once a day per game (`failures.DailyLog`).
- The check: the own snapshot is read before IGDB is asked; unreadable — the failure at once, no request; the game waits 30 minutes and joins the «could not check» messages (once a day by the window). So a game that had a follow-up snapshot and one that never had are treated alike.

## 5. Russian in games (idea 002)

### 5.1 What a source says

- **Support** — what one source says about Russian when it says something: `text` (interface or subtitles) and `voice` (full voice), each yes or no. «No data» — the source has not said anything (absent, not a Support with both no).
- **Official** — from Steam when Steam has data for the game's Steam number, else from IGDB (decision of the idea: Steam wins). Steam data is about the PC version (PC-only); IGDB data is about the game (no platform).
- **Fan** — from the game's page on ZoG: the «Русификатор» entries for PC or with no platform named (section 5.6). Always PC-only.
- A source that once had data and later says nothing keeps the previous value (as a lost date, `games.carry_over`): «no data» never overwrites known data of the same source; a failure is never shown as «нет».

### 5.2 The line «Русский: …»

Let O be the official Support (or no data), F the fan Support of the current page (or no data: no page, not read yet, unreadable, rejected). The fan part shown fills only what the official lacks (decision 1): fan text is shown when F.text and not O.text; fan voice when F.voice and not O.voice.

| Official segment (O has text or voice) | Fan segment (shown fan) |
|---|---|
| «текст и озвучка — официально» · «текст — официально» · «озвучка — официально» | «текст и озвучка — народные» · «текст — народный» · «озвучка — народная» |

- Body = the segments joined by «; »: «текст — официально; озвучка — народная».
- No segment: «нет» — O is no and F is no (a page read without Russian entries); «официально нет» — O is no and F is no data; «нет данных» — every other case (O no data).
- «(ПК)» goes once at the end of the line when the owner has «играю здесь» in this game on a platform other than PC (`GameScope.told` minus PC is not empty) and the body rests on PC-only data: the official segment or «официально нет» / «нет» from Steam, or a fan segment. Never after «нет данных». With «играю здесь» on PC only — no mark.
- Examples (the mockup's games, by today's live data): Cyberpunk 2077 — «Русский: текст и озвучка — официально»; Baldur's Gate 3 — «Русский: текст — официально; озвучка — народная»; Hades II — «Русский: текст — официально; озвучка — народная»; Stray — «Русский: текст — официально» (ZoG has only «Українізатор»); Lorelei and the Laser Eyes — «Русский: текст — народный»; Bloodborne (no Steam page, IGDB) — «Русский: текст — официально»; a game whose official source says no and whose ZoG page is not found — «Русский: официально нет»; any of them with PS5 marked too and Steam data — «… (ПК)».

The line lives in a pure module (`russian`, section 6); the bot card and the web block take it ready.

### 5.3 The web card — block «Русский язык»

After «Платформы», before «Steam». Shown for a game in «Хочу» or «В процессе»; for a game in another status only when it has data (the last line), without the form.

1. The line: «**Русский:** текст — официально; озвучка — народная».
2. Hints under it (small text), each when it applies, in this order:
   - sources: «Steam — проверено сегодня в 09:00 · ZoG — проверено 18 ноября» (official source «Steam» or «IGDB» with the moment of its last check, `format_past_moment`; «ZoG — …» when a page was read); nothing checked yet — «Ещё не проверяли — строка появится через минуту-другую»;
   - the mark: «(ПК) — данные о версии для ПК, а вы играете ещё и на другой платформе»;
   - the page: not found — «Страница на ZoG не найдена — вставьте ссылку, если перевод есть»; rejected — «Страница на ZoG не указана — вставьте ссылку, если перевод есть»; unreadable — «Страницу на ZoG не удалось прочитать — народный перевод пока неизвестен»;
   - «нет данных» after a check: with a Steam page — «Языки ещё не объявлены. Проверяю: Steam — каждые 6 часов, ZoG — раз в неделю»; without — «Языки ещё не объявлены. Проверяю: IGDB — вместе с датами игры, ZoG — раз в неделю»;
   - another status — «Игра не в «Хочу» и не «В процессе» — русский язык больше не проверяется».
3. The link «Страница перевода» (ZoG) — the game's ZoG page, when a fan segment is shown.
4. The form (only in «Хочу», «В процессе»): label «Страница на ZoG», a URL field (value: the page address `https://www.zoneofgames.ru/games/<page>/`, or empty; placeholder «https://www.zoneofgames.ru/games/…/»), «Сохранить», and «Не та игра» when a page is set. An error stands under the field (section 5.7), the typed text stays in it. POST `/titles/<id>/zog` (field `link`, route `card_zog`) and POST `/titles/<id>/zog/reject` (`card_zog_reject`) answer as the other presses of the card (`_press`: the fresh card fragment; a title gone — the fragment of «title gone»).

The texts of the mockup states 4 and 5 move from the line to the hints (the page state is not Russian support); the rest is as the mockups.

### 5.4 The bot card

- The line «Русский: …» after «Цена в Steam: …» (or after the platform lines), before the store links; the same body as the web.
- Under the card, before «🗑 Удалить»: the link button «🌐 Страница перевода» when a fan segment is shown (`card_actions`).

### 5.5 The official check

At the end of each pass, after the prices and the follow-ups (`GamePoller.end_of_pass`), `pollers/game_russian`:

- **Which games.** «Игра для русского» (`for_russian`, one place): status «Хочу» or «В процессе», any platforms. The reconciliation makes an empty snapshot `russian_official` (due now) for such a game without one; it never drops one (the card keeps the line; deleting a title deletes them). Due: the snapshots of games for Russian whose time has come, `next_check_at` empty first.
- **Steam.** Games whose own state has a Steam number: `GetItems` in packs of 100 with `"data_request": {"include_supported_languages": true}` only, **country `US`** whatever the store country (a game not sold in a country answers `success: 15` with no languages — in `RU` even Cyberpunk 2077 and The Witcher 3, `answers/getitems_languages_ru.json`). Russian is `elanguage` 8: text = `supported` or `subtitles`, voice = `full_audio`; a non-empty list without 8 — Support(no, no); a missing or empty list, or `success` 15 — no data. A list that is not records with yes/no flags — the answer about that game is unreadable (a failure of the game, as prices). A failure of the request — every game of the pack fails (30 minutes, «could not check» with the source «Steam»: `failures.source_name` maps `russian_official` to «Steam»).
- **IGDB.** The own query (`GAME_QUERY`) also asks `language_supports.language,language_supports.language_support_type`; the own snapshot (`GameState.russian`) keeps Russian (language 22): text = support type 2 (subtitles) or 3 (interface), voice = type 1 (audio); a non-empty list without 22 — Support(no, no); none — no data. No extra request: it comes with adding and every own poll. A snapshot from before 9.1b has no key — «not asked yet».
- **The look.** Steam data when it has some, else IGDB data, else none: `{"source": "steam", "appid": "1091500", "text": true, "voice": true}`, `{"source": "igdb", "text": true, "voice": false}`, `{"source": null}` (checked, no data). While Steam has none and IGDB is «not asked yet», nothing is stored (the snapshot stays `{}`): the first look with data must be a reference point, not news.
- **Reference point** (stored, no events): the snapshot is empty; the source or the Steam number changed (a Steam page appeared or went); the first check after «Вернуть в список» (`observed_at` earlier than `restored_at`).
- **Events.** Otherwise each of text and voice that is yes now and was not yes before (no data counts as no) — one event with the parts that appeared (section 5.8): an announced game whose languages Steam lists for the first time with Russian is told «появился русский текст»; Russian that disappears is silent.
- Events of all games of the check queue in one write session (`EventQueue.enqueue_all`, `DueTitle.statuses` = «Хочу», «В процессе»), then each look is stored; next check in 6 hours, after a failure in 30 minutes. A game whose own state cannot be read is skipped with a log line once a day (its own poll reports it).

### 5.6 The ZoG check

Next, `pollers/game_zog`, for the same games (`for_russian`), snapshot `zog`:

- **Cadence.** At most 2 games a pass (`ZOG_PER_PASS`), never-checked first, then the earliest; a pause of 1 s between requests; after a check — 7 days; after a failure — 6 hours, a log line, **no message to the owner** (ZoG is a small community site; the card shows when it was read). A rejected page is never asked (its next check is set 7 days on, nothing requested).
- **The client** (`app/providers/zog.py`): `GET https://www.zoneofgames.ru/games/<page>/`, `User-Agent: release-tracker (personal game tracker; one page per game a week)` — no owner details; 10 s; no redirects followed (any answer but 200 is a failure); the body decoded from `windows-1251`.
- **Reading a page** (pure, `sources/zog_pages.py`):
  - `<title>` «Ошибка» — no such page (ZoG answers 200 for it). «<name> | Игровой архив на Zone of Games» — a game page, `name` the text before « | », HTML entities opened. Any other title — the layout is unreadable.
  - The year: the first `/games/year/<YYYY>.html` after «В официальной продаже с»; missing — none.
  - The entries: after «Переводы:» up to the next `</table>`, the links `/games/<page>/files/<n>.html`. No «Переводы:» — no translations, Support(no, no) (Astro Bot). «Переводы:» with no such link — unreadable.
  - An entry counts when its text starts with «Русификатор (»: the words inside the first brackets — «текст» gives text, «звук» gives voice («текст и звук» both; «текстуры», «видео» and the like nothing); a «для <X>-версии» after the brackets with X other than «ПК» (Switch, Mac, Linux, PS4…) — not counted; «для ПК-версии», no platform, or «для Phantom Liberty» — counted. «Українізатор», «Беларусізатар» and other languages — not counted.
  - Fan Support = (any counted text, any counted voice).
  - Saved pages and what they give: `baldurs_gate_3` text + voice (PC text «исправление официального», voice by neural voice), `hades_2` voice, `lorelei_and_the_laser_eyes` text (its Switch entry not counted), `split_fiction` text + voice («текст и звук»), `lies_of_p` voice («текстуры» not counted), `disco_elysium` voice, `cyberpunk_2077` voice («для Phantom Liberty»), `prey` text + voice (no platform; its year 2006), `stray` none (only «Українізатор»), `astro_bot` none (no «Переводы:»), `the_witcher_3_wild_hunt` — «Ошибка».
- **Finding a page** (no page stored, or the stored one answered «Ошибка»): addresses from the original name (decision 3), in order, each once, at most 4: (1) the name; (2) the name with its numbers switched — a Roman word II–X to Arabic, or, when it has none, an Arabic word 2–10 to Roman; (3) the name before the first «:» or « - » / « – »; (4) the switch of (3). The address of a name: accents dropped (NFKD), lower case, «'», «’» and «.» removed, every other run of non-`[a-z0-9]` → «_», trimmed. «Baldur's Gate III» → `baldurs_gate_iii` (none) → `baldurs_gate_3`; «Hades II» → `hades_ii` → `hades_2`; «The Witcher 3: Wild Hunt» → 4 addresses, none found.
- **A found page is taken** only when its name matches the game and its year fits: the match key (accents dropped, lower case, «ё» → «е», Roman words II–X → Arabic, everything but letters and digits dropped, spaces squeezed) of ZoG's name equals the key of the original name, the Russian name or either before its «:»; and the page's year, when both have one, is not earlier than the year before the game's (`Title.year`): «S.T.A.L.K.E.R. 2: Heart of Chornobyl*» matches «S.T.A.L.K.E.R. 2: Heart of Chornobyl»; the `prey` page (2006) is refused for Prey (2017). Nothing taken — «not found», checked again in 7 days.
- **The state**: `{}` (not checked); `{"page": "baldurs_gate_3", "by": "found" | "owner", "text": true, "voice": true}`; `{"page": "…", "by": …, "unreadable": true, …previous text/voice kept}`; `{"page": null, "by": "none"}` (not found); `{"page": null, "by": "rejected"}`. An unreadable layout keeps the last Support of the same page (the line shows it, the hint says it could not be read; a page never read gives no data) and logs once a day.
- **Events** — the fan Support of the same page compared with the previous: each of text and voice that is yes now and was not, **and that the official lacks now** (decision 1, the official read in the same session from the `russian_official` snapshot). Reference point: the first read of a page (found anew or set by the owner), the first check after «Вернуть в список». One write session queues them (`still_checked` with `statuses`), then the state is stored.

### 5.7 «Страница на ZoG» — the owner's page

- `Tracker.set_zog_page(title_id, link)`; the link is read by `zog_pages.page_of(link)` (pure): `http(s)://(www.)zoneofgames.ru/games/<page>/…` — the first segment after `/games/` (`[a-z0-9_]+`, case ignored), anything after it (a file of the game) ignored, query and fragment ignored. Then the page is asked once (a press that goes to the network; the web awaits it, 10 s).
- Answers (the error under the field, nothing saved):
  - empty — «Вставьте ссылку на страницу игры на ZoG»;
  - not such an address — «Это не страница игры на ZoG. Нужна ссылка вида https://www.zoneofgames.ru/games/…/»;
  - «Ошибка» — «На ZoG нет такой страницы — проверьте ссылку»;
  - ZoG did not answer — «ZoG не ответил — попробуйте позже»;
  - a game not in «Хочу» or «В процессе» (a card open from before) — the card comes back without the form.
- Saved: `{"page": …, "by": "owner", …}` with the Support read now (no name or year check: the owner's choice wins), next check in 7 days, a reference point (no message); the undelivered fan events of the game are withdrawn (they were about another page). The same link twice — the same state.
- «Не та игра» (`Tracker.reject_zog_page`): `{"page": null, "by": "rejected"}`, the undelivered fan events withdrawn; no finding by itself until the owner saves a link; twice — the same.

### 5.8 Messages

Only for a game in «Хочу» or «В процессе», by the delivery rules; each its own message (no folding), a line each in a summary and in «Недавно».

| Type | Parts | Text |
|---|---|---|
| `game_russian_official` | text | «🎮 В «Stray» появился русский текст» |
| | voice | «🎮 В «Hollow Knight: Silksong» появилась русская озвучка» |
| | text, voice | «🎮 В «Hades II» появились русский текст и озвучка» |
| `game_russian_fan` | text | «🎮 Для «Lorelei and the Laser Eyes» вышел народный русский перевод текста» |
| | voice | «🎮 Для «Baldur’s Gate 3» вышла народная русская озвучка» |
| | text, voice | «🎮 Для «Split Fiction» вышли народный русский перевод текста и озвучка» |

- « (ПК)» at the end by the rule of 5.2 (official from Steam or fan, the owner plays elsewhere too).
- Buttons: official — «📄 Карточка» and «🛒 Открыть в Steam» when the payload has `steam_id`; fan — «📄 Карточка» and «🌐 Страница перевода» (the ZoG page). `actions.event_actions` reads `russian_events.TYPES`, the one list.
- Keys: `moved_key("game:<id>:russian:official:<parts>", previous_look)` and `moved_key("game:<id>:russian:fan:<page>:<parts>", previous_look)` (`parts`: `text`, `voice`, `text_voice`): found again after a failed store — dropped; a real later appearance — told.
- Payloads: `{"text", "name", "parts", "source", "steam_id", "pc"}` / `{"text", "name", "parts", "zog_page", "pc"}`.
- «Тестовое событие»: «Игра: появился русский язык» — «🎮 В «Hollow Knight: Silksong» появилась русская озвучка» with «🛒 Открыть в Steam» (1030300); «Игра: народный перевод» — «🎮 Для «Baldur’s Gate 3» вышла народная русская озвучка» with «🌐 Страница перевода» (`baldurs_gate_3`). Samples are events of the real types, so their buttons work.

### 5.9 Leaving and coming back

- «Прошёл», «Бросил»: the checks stop (the due queries read the status), the undelivered Russian events go (section 3.1), the snapshots stay: the card keeps the last line without the form.
- «Вернуть в список»: the checks go on; the first check of each part after it is the reference point.
- Right after adding (decision 2): IGDB's Russian comes with the snapshot of adding; the reconciliation of the next pass (within a minute) makes both snapshots due now, so Steam and ZoG are asked at the end of that pass — a never-checked game goes first. Adding itself asks nothing more and cannot fail because of Steam languages or ZoG. Until then the line reads by what IGDB gave, and the hint says «Ещё не проверяли — строка появится через минуту-другую». (The description said «the Steam request made at adding»; the next pass gives the same within a minute and keeps adding as it is.)

## 6. Data

No migration. New and changed state:

| Where | What |
|---|---|
| `source_snapshots`, source `russian_official` | the official look (5.5); `observed_at` its last check |
| `source_snapshots`, source `zog` | the ZoG state (5.6) |
| own snapshot (source `igdb`), `GameState.russian` | `"russian": {"text": bool, "voice": bool}` or `null` (IGDB has no languages); no key — not asked yet; read strictly |
| events | `game_russian_official`, `game_russian_fan`; release payloads get `late` |

New modules (rule 7, each under 400 lines): `russian` (pure: Support, the looks and their strict reading, the line, what appeared, «(ПК)»), `russian_events` (pure: texts, keys, payloads, samples, `TYPES`), `pollers/game_russian` (the official check and the card's view), `pollers/game_zog` (the ZoG check and the owner's page), `sources/steam_languages` (GetItems records → Support), `sources/zog_pages` (addresses, match key, page parse, link check), `app/providers/zog.py` (the client). `SteamProvider.store_items` gets a languages request (a flag or a second method); `failures.DailyLog` — a log line per key at most once a day, in memory (a restart may repeat one).

`CardPart` gets `outside_date: str` and `russian: RussianView | None` (the line, the hints, the ZoG link, the field value, whether «Не та игра» and the form are shown, the error). The export (7.1) does not carry the Russian state: it is read again from the sources.

## 7. External services

| Service | Request | Limits, failures | Checked live 2026-11-21 (`answers/`) |
|---|---|---|---|
| Steam `GetItems` | languages: `include_supported_languages`, country `US`, packs of 100, every 6 h | a failure — the pack fails, 30 min, «could not check» (Steam) | `getitems_languages_us.json` (10 apps: Russian flags; Lorelei none; 999999999 — 15), `getitems_languages_ru.json` (15 without languages), `getitems_coming_soon_il.json` (upcoming games list languages) |
| Steam `GetItems` | prices (unchanged) | — | `getitems_preorder_il_live.json` (KI-44) |
| IGDB `/games` | `language_supports.language,language_supports.language_support_type` added to the own query; `parent_game.name` to the follow-up query | as every IGDB request | `igdb_language_supports.json`: Russian is language 22 (`ru-RU`), types 1 Audio, 2 Subtitles, 3 Interface; Cyberpunk 2077 1/2/3, Bloodborne 2/3, GTA VI 2/3, Yomawari none of 4 |
| ZoG | one game page, ≤ 4 to find one, ≤ 2 games a pass, weekly | a failure — 6 h, log only | `zog/*.html` (section 5.6), `zog/robots.txt` (game pages allowed) |
| PlayStation Store | `HEAD /<locale>/concept/<n>` at a click on the web link, kept a day | a failure — the concept link | section 1.4 (the pages are too big to keep) |

## 8. Edge cases

- Steam answers for some games of a pack and not others (`UnreadAnswer`): only those fail.
- The same Steam number on two games (two IGDB records): asked once, serves both (as prices).
- Steam lists languages, then a check without them: the previous look stays (no «нет»), no event.
- A game gets a Steam page: the first official look from Steam is the reference point; the line switches from IGDB to Steam data silently.
- Official text appears after a fan text was shown and told: the official message comes; the fan text is hidden from then on.
- Official voice disappears while ZoG has fan voice: the line shows the fan voice, no message.
- ZoG lists several games of one name: the address variants find one page; the year rule refuses an older namesake; the owner pastes the right one or presses «Не та игра».
- The stored found page starts answering «Ошибка» (renamed on ZoG): finding again; nothing found — «не найдена» (the fan part becomes no data, no message).
- An owner's page starts answering «Ошибка»: the same as a found one (finding again).
- ZoG down for days: the line keeps the last fan part; the hint shows the last read day; no messages.
- ZoG changes its layout: «unreadable» — the last values stay, the hint says so, a log line a day.
- «Не та игра» then a link of the same page: saved as the owner's page (reference point).
- A press on «Сохранить» of a game deleted meanwhile — «title gone»; one that left «Хочу»/«В процессе» — the card without the form.
- Two passes cannot run at once (`poll_lock`); a press during a check: the check's queueing asks `still_checked` in its write session (section 3).
- A release in Japan only that later gets a European day: «вышла» by the European day, as any.
- A late release (KI-36) whose day folds with an on-time one of another platform: they do not fold (different `late`), two lines.
- A discount withdrawn by a deeper one: the older event is deleted; if the store of the look then fails, the next check finds only the deeper one again (its key drops it).
- The first pass after the update: every game gets empty Russian snapshots — Steam languages for all of them in one or two requests, ZoG two games a minute; all reference points, no messages.
- A game in «В процессе» with no Steam page and IGDB «not asked yet» (snapshot from before the update): «нет данных» until its next own poll; then the official check records the reference point.

## 9. Tests

Automated (offline, on the saved answers and fakes):
- Dates: `pick` without outside regions; the outside line (shown, not shown when the own date ends earlier, region words, the older platform); `from_igdb` without or with an unknown `date_format` → the year; the since-rule (late release told, old correction silent, after «Вернуть в список»); the late form and its folding.
- PS link: `200` → concept, `302 …/error` → search, a failure → concept, the day cache, the route (login, title gone, not a game).
- Prices: the bundle texts; the live preorder fixture; KI-46 pin; a spoiled snapshot (others checked, one failure, one log line a day, dropped when no longer for prices); the events of one check in one write session (a delivery started between two games sees none or all; two discounts fold).
- The press: «Начал играть», «Прошёл», the PC mark, «Мои платформы» without PC — the price snapshot and its undelivered events go in the press's session; a check answering after the press queues nothing; «Бросил» + «Вернуть в список» → the next follow-up check is the reference point (KI-53); a withdrawn announcement comes from another game of the series (KI-54); `withdraw` deletes events.
- Follow-ups: own type and parent written for «Пройдено» only; an unreadable own snapshot — no IGDB request, one failure, the snapshot made, one log line a day.
- Russian: Steam languages parse (US fixture; 15; empty; malformed); IGDB `language_supports` parse; the line for every row of 5.2 with and without «(ПК)»; the official check (reference points: empty, source change, number change, after return; «not asked yet» stores nothing; no-data keeps the previous; events of appeared parts only; one write session); the ZoG page parse on every saved page; addresses and variants; the match key and the year rule; finding order and the 4-request limit; cadence (2 a pass, never-checked first, rejected never asked); fan events with the decision-1 filter; failures not reported; the owner's link (every answer of 5.7, twice); «Не та игра» twice; the web block in every state; the bot line and the button; messages, keys, buttons, samples; `still_checked` with `statuses`; the press withdraws Russian events and keeps the snapshots.

Owner checks (live, by ticket):
- Web cards of Cyberpunk 2077, Stray, Baldur's Gate 3, an announced game: the line and the hints as in 5.2–5.3; the bot card of the same game with the same line and «🌐 Страница перевода» when the fan part is shown.
- «Страница на ZoG»: paste a wrong address — the error; a right one — saved; «Не та игра» — the hint «не указана».
- «Тестовое событие»: «Игра: появился русский язык», «Игра: народный перевод», «Игра: бандл в Steam» (with «цена набора целиком»).
- «Открыть в PlayStation Store» of a game on PS5 opens its page in the store of the country.

What only tests can show (no live case on demand): a Japan-only date, a late release, a record without precision, a missing concept, a press in the minute of a delivery, a spoiled snapshot, a real Russian patch.

## 10. Docs, terms, ADR, known issues

- `CONTEXT.md`: «Русский язык» — In code: `russian` (`Support`; the official check `russian_official`, `for_russian`; the line `russian.line`; the events `game_russian_official`, `game_russian_fan`, `russian_events.TYPES`); «Народный перевод» — In code: `fan`, the page `zog` («Страница на ZoG»: `zog page`, `set_zog_page`, `reject_zog_page`); new entry «Проверка русского языка» (Russian check): the official part every 6 hours (Steam in the US store, else IGDB with the game's dates), ZoG once a week, «Хочу» and «В процессе», the first check and the first after «Вернуть в список» silent; «Бандл»: «the price is of the whole set»; «Ранний доступ» / «Примерная дата» unchanged; «Проверка цен»: a press ends it at once.
- `docs/coding-standards.md`, rule 7 table: rows for the new modules (section 6) and the changed rows of `pollers/game_prices`, `pollers/game_follow_ups`, `queue` (`enqueue_all`, `withdraw` deletes), `checks` (`statuses`).
- `docs/code-map.md` — by `tools/code_map.py`; `docs/tests-map.md` — new test modules.
- `PROJECT_CONTEXT.md`, «External services»: ZoG (new row), Steam (languages in `US`), IGDB (`language_supports`), PlayStation Store (the `HEAD` check of a concept).
- **ADR 0016** «Fan translations are read from ZoG game pages» (written by the ZoG ticket): no API, Google search only; the page address by the name, the name and year match, the owner's link; against ADR 0009's reason (a page breaks without warning): here a broken layout shows «unreadable» and keeps the last value, a log line a day, no message invented, no money at stake; rejected — GamesVoice and others (not one catalog), ZoG search (JavaScript), asking the owner for every game.
- ADR 0011 stays; its last consequence (KI-52) stops being true — said in `docs/history.md`, no new ADR (the decision did not change).
- `KNOWN_ISSUES.md`: the 14 entries get their statuses (35, 36, 37 (web), 38, 44, 47, 50, 51, 52, 53, 54, 55 `fixed (test: …)`; 43, 46 `won't fix (test: …)`), the `won't fix` rule at the top; new entries the review defers go to 9.1c.

## 11. Proposed tickets

| # | Ticket | Sections | Complexity | Blocked by |
|---|---|---|---|---|
| 01 | Game dates and the PlayStation link: KI-35 (regions, the outside line in both cards), KI-36 (since-rule, late form), KI-38, KI-37 (the route, `HEAD`, the day cache) | 1 | medium | — |
| 02 | The price check: KI-43, KI-44, KI-46, KI-50 (`DailyLog`), KI-51 (`enqueue_all`); the press hook `after_marks` with its price part and the Settings hook (KI-47); the `won't fix` rule | 2, 3.1 (prices), 3.2 | complex | — |
| 03 | The follow-up check and withdrawn events: the follow-up part of `after_marks` (KI-53), `withdraw` deletes events (KI-54), queueing through `still_checked` (wish of 9.1a), KI-52, KI-55 | 3.1 (follow-ups), 3.2, 3.3, 4 | complex | 02 |
| 04 | Russian — the official part: `GameState.russian` from IGDB, the official check with Steam languages, `russian` and `russian_events` (official), the line in both cards (official segment, «нет», «официально нет», «нет данных», «(ПК)»), the block's hints, the messages and the sample, `DueTitle.statuses`, the Russian part of `after_marks` | 3.2, 5.1, 5.2, 5.3 (without the form), 5.4, 5.5, 5.8 (official), 5.9 | complex | 01, 03 |
| 05 | Russian — ZoG: the client, the page parse, finding a page, the ZoG check, the fan segment, «Страница перевода» (web link, bot button), the fan messages and the sample, ADR 0016 | 5.2, 5.3 (hints, link), 5.4, 5.6, 5.8 (fan) | complex | 04 |
| 06 | Russian — «Страница на ZoG»: the form, `set_zog_page`, «Не та игра», the errors | 5.3 (form), 5.7 | medium | 05 |

Order: 01 and 02 may go in either order (different modules); 03 after 02 (the same check files and the hook); 04 after 01 (`games.py`) and 03 (`withdraw`, the hook); then 05, 06. Sessions after this one: slicing 1, tickets 6, review 1 — 8 (the estimate of the description holds).
