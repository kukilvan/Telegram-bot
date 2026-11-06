# Spec 6.4: «Входящие» — add a title from Telegram by a post or a name

Status: accepted

Built from `description.md` (accepted 2026-11-05) and idea 001; where they differ, this file wins. Terms: `CONTEXT.md` (new ones in section 12). ADRs: 0002 (the web is the main interface), 0007 (one process), 0010 (the bot takes posts and names; what is not resolved goes to «Входящие»). Section 3 narrows ADR 0010's «бот спрашивает тип» to posts without a link of a source — decided with the owner in the description, no new ADR.

Live answers of the services (2026-11-05) lie in `answers/`:
- `search-expected.json` — searches of the expected names of the 18 samples and of the noise names (TMDb, Shikimori, IGDB);
- `search-typos-links.json` — names with typos, IMDb → TMDb `/find`, Steam app → IGDB `external_games`;
- `links.json` — IGDB `/games` by a Steam number in one request, Steam `appdetails`, a Shikimori entry by id;
- `offers-prototype.json` — every answer the prototype of sections 4–5 got on the 18 samples and 10 names;
- `poster-preview.json` — the poster addresses checked (all `200 image/jpeg`); the three test messages are in section 8;
- `candidates_prototype.py`, `offers_prototype.py` — the throwaway prototype the rules were checked with (the ticket writes the real modules; the rules are this file, not the prototype).

## 1. Taking in a message (bot)

### 1.1 What is taken in

Every message from the owner is an **inbox item** («запись Входящих») except:
- a command (text starting with `/`);
- the texts of the menu buttons: «📚 Мои тайтлы», «📋 Сводка сейчас», «🧪 Тестовое событие»;
- the text «➕ Добавить» (the old keyboard stays on the phone until a new one comes): the answer is «Кнопки «Добавить» больше нет: просто перешлите мне пост или напишите название.» with the new keyboard (2.4);
- an edited message (`edited_message` is not handled).

What the item keeps of a message:
- **text** — `text` or `caption`; the text of the joined messages (1.2) goes in arrival order, separated by an empty line; cut to 10,000 characters;
- **bold** — the pieces of the text under the entities `bold` (each 1–8 words; longer ones are dropped);
- **links** — the addresses of the entities `url` and `text_link` (a hidden link such as «Підписатись» is a link here, never a name);
- **media** — when the message has no text: `photo` «картинка», `video` «видео», `animation` «гифка», `document` «файл», `sticker` «стикер», `voice` / `video_note` «голосовое», anything else «сообщение» (the web shows «(картинка без подписи)» and the like);
- **post link** — only for a forward from a public channel: `forward_origin` of type `channel` whose chat has a `username` → `https://t.me/<username>/<message_id>`. A private channel, a group, a user, a hidden user: no link;
- **forwarded** — whether the message is a forward (`forward_origin` is set);
- **received** — the moment of arrival (naive UTC).

The item is written to the database before the bot answers anything (KI-9: a restart in the middle loses no post).

### 1.2 One item for an album and for a forward with a comment

A message joins the newest item instead of starting one when it arrives at most **2 seconds** after the last message of that item and:
- both have the same `media_group_id` (an album: Telegram sends one message per picture, the caption usually on the first), or
- the newest item is one message, not a forward, and this message is a forward (a forward with a comment: Telegram sends the comment first, the post a moment later).

Anything else starts a new item. The joined text: the comment first, then the post. The post link, bold and links of every joined message are kept.

### 1.3 What comes next

Two seconds after the last message of an item (a message joined meanwhile restarts the pause; the pause lives in the bot's memory):
1. the item has a link of a source (section 3) → the analysis by the links, no question;
2. the item has no text and no link of a source → it goes to «Входящие» with the reason «нет текста»: «В сообщении нет текста — сохранил во «Входящие».»;
3. otherwise the question «Что это?» (2.1).

A new item (not a joined message) moves every other item that waits for an answer to «Входящие» with the reason «без ответа». If any moved, the first message the bot sends about the new item starts with the line «Предыдущий пост без ответа ушёл во «Входящие».» and an empty line. «Five posts in a row without answers» thus leaves four in «Входящие» and the last waiting.

## 2. Bot texts and buttons

### 2.1 «Что это?»

```text
Что это?
```
Buttons, two rows: «Фильм» «Сериал» / «Аниме» «Игра»; a third row «🗑 Не сохранять». Labels are `KINDS[kind].label`; «Игра» is there even without the keys of IGDB.

Callback data (at most 64 bytes): `inb:<item id>:k:<kind>`, `inb:<item id>:x`.

### 2.2 Presses

Rule 8 of the coding standards: a dead button (no such item) answers with a popup; a live one answers «Ищу…» at once, then works, then reports by messages.

| Press | Result |
|---|---|
| a kind | the kind is stored; the analysis (sections 4–5) with that kind; a second press of another kind on the same question starts it again |
| «🗑 Не сохранять» | the item is deleted; popup «Не сохраняю.»; the buttons of the question are taken off |
| any button of a deleted item (resolved, not saved, removed in the web) | popup «Эта запись уже разобрана.» |
| `inb:` data the bot cannot read | popup «Эта кнопка больше не работает.» |

After a kind press the buttons of the question are taken off.

### 2.3 Results of the analysis

| Case | Message | Item |
|---|---|---|
| an offer (section 6) | its card «Это оно?» / «Возможно, вы имели в виду:» | waits |
| the offer is in the list | «Уже в списке» and the card of the title (2.5), no «Да» / «Нет» | resolved (deleted) |
| nothing found | «Не нашёл — сохранил во «Входящие». Разберите в веб-приложении.» | «Входящие», «не нашёл» |
| the source failed | «Не удалось связаться с <source> — сохранил во «Входящие».» (`KINDS[kind].source_name`) | «Входящие», «источник не ответил» |
| a game without the keys of IGDB | «Игры не подключены: нет ключей IGDB в .env — сохранил во «Входящие».» | «Входящие», «игры не подключены» |

### 2.4 Menu and greeting

Keyboard: row 1 «📚 Мои тайтлы», row 2 «📋 Сводка сейчас», row 3 «🧪 Тестовое событие».

`/start`:
```text
👋 Бот работает. Чтобы добавить фильм, сериал, аниме или игру, перешлите мне пост о нём или напишите название: я найду и предложу добавить, а что не найду — сохраню во «Входящие» веб-приложения.

Кнопки меню внизу: «Мои тайтлы» — ваш список, «Сводка сейчас» присылает накопленные события, «Тестовое событие» показывает, как выглядят сообщения, и проверяет правила доставки.
```

«📚 Мои тайтлы» with an empty list: «Список пуст. Перешлите мне пост о фильме, сериале, аниме или игре или напишите название.»

Removed: «➕ Добавить», its kind menu (`tadd:`), the name request (`KindInfo.ask_name` goes), the list of suggestions (`tpick:`) and `awaiting_name`. An old `tadd:` / `tpick:` button answers «Эта кнопка больше не работает.».

### 2.5 Cards

Every card the bot sends (after «Да», «Уже в списке», «Карточка» under an event, «📚 Мои тайтлы», «Готово» of the seasons, «Следить») carries the poster above the text (section 8). The card text and buttons are as today.

## 3. Links of sources

The links of an item (its text and its `url` / `text_link` entities), in order of appearance, without repeats; the first **3** that are links of a source:

| Link | Kind | Lookup |
|---|---|---|
| `store.steampowered.com/app/<digits>` | game | IGDB `/games` with the search fields and `where external_games.uid = "<n>" & external_games.external_game_source = 1` — one request (`links.json`: 1245620 → Elden Ring, 2622380 → Elden Ring Nightreign) |
| `themoviedb.org/movie/<digits>` (any language prefix, a `-slug` after the number) | movie | TMDb `/movie/<id>` |
| `themoviedb.org/tv/<digits>` | series | TMDb `/tv/<id>` |
| `shikimori.<any>/animes/<optional letter><digits>` | anime | Shikimori by id (the entry; adding takes its chain) |
| `imdb.com/title/tt<digits>` | movie or series | TMDb `/find/<tt…>?external_source=imdb_id`: the first of `movie_results`, else of `tv_results` (`search-typos-links.json`) |
| `jut.su/<slug>/…`, `jutsu.ru/<slug>/…` | — | not an offer: the slug with `-` as spaces is a name candidate of weight 50 (`kikansha-no-mahou` → «kikansha no mahou») |

Host match ignores `www.`, `http`/`https` and the case. Each found record is an offer (section 6) with the heading «Это оно?». The item's kind is the kind of the first link that gave an offer; the item skips «Что это?».

- A Steam number IGDB does not know (`4000000` → `[]`): Steam `appdetails` gives its name (`links.json`: `ELDEN RING NIGHTREIGN`), which becomes a name candidate of weight 100 for the kind game. Steam failing too: the link gives nothing.
- After the offers of the links, the text of the item adds offers of its name candidates with the same kind (sections 4–5) up to 3 in all.
- No link gave an offer (a source failed, unknown ids): the item goes on as one without links — «Что это?» (or «нет текста»).
- A game link without the keys of IGDB: as «игры не подключены» (2.3).

## 4. Name candidates (pure, no network)

A **candidate** («кандидат») is a name the rules pick from the text of an item; the rules do not depend on the kind. Checked on the 18 samples: every expected first name comes first (table in 4.6).

### 4.1 Cleaning, line by line

- invisible characters are removed (U+200B–U+200F, U+2060, U+FEFF, U+3164 «ㅤ», U+115F, U+1160, U+00AD);
- a line with «Підписатись», «Подписаться», «Подпишись» or «Subscribe» (any case) is dropped — the signature of a channel;
- URLs (`http(s)://…`, `t.me/…`, `jut.su/…`, `jutsu.ru/…`) and `@handles` are cut out of the line;
- a line left as one word ending with `:` («Main:», «Ru:») is dropped;
- a line of a press score is dropped: it has `N/10` (`9/10`, `8.5/10`) or a word «бал», «балл», «балів», «бали», «баллов», «points».

### 4.2 Kinds of candidates and their weights

| Source of the candidate | Weight |
|---|---|
| the whole text of a **name message** — one line of at most 8 words, not a forward, nothing joined | 100 |
| a Steam name from 3 | 100 |
| the head of an episode line: the line starts with `<name>: <N> серия` (or «серія», «эпизод») — the `<name>` | 50 |
| a jut.su slug (3) | 50 |
| a bold piece | +8 (added to whatever else the same name gets) |
| a **Latin run** (4.3) | 6, +4 on the first line, +4 right after a kind word (4.4), −5 right after a marker (4.4), −1 when it is one word, not on the first line and not all capitals |
| a **quote** — the text inside «», "", “”, „“ (1–80 characters) | 3, +1 when it starts the first line, 0.5 right after a marker |
| a Cyrillic name right after a kind word: the words up to the first `. , ! ? : ; — – (` (at most 6), the first with a capital letter | 5 |
| nothing found at all: the first line up to the first `. ! ? — –`, at most 8 words | 1 |

A name met again adds +2 per extra time. Ranking: weight from the highest; equal weights — by the first appearance in the text.

### 4.3 Latin run

A run of Latin words and numbers: a word is `[A-Za-z0-9][A-Za-z0-9'’.&+]*` with `-` inside («Dead-End»); words are joined by spaces, by `: ` («Death Stranding: Isolations») and by ` - ` / ` – `. A run inside a quote belongs to the quote. Dropped runs:
- digits and punctuation only («2027», «1.6.0»);
- starting with a platform or store: Xbox, Nintendo, PlayStation, `PS<digit>`, Switch, Steam, Quest (followed by a word);
- one word of at most 3 characters not on the first line («UG», «One», «NPC»);
- on the stop list (4.5).

### 4.4 Kind words and markers

Compared on the end of the text before the candidate (case ignored).

- **Kind words** (the next name is likely the title): игра/игры/игру/игре, гра/гри/гру, сериал/сериала/сериале/сериалу, серіал/серіалу/серіалі, аниме, аніме, фильм/фильма/фильме/фильму, фільм/фільму/фільмі, мультфильм…, экранизация/экранизации/экранизацию, екранізація/екранізації/екранізацію, ремастер, ремейк, дорама/дорамы/дораму, экшн, экшен, лайфсим, симулятор, приключение/приключения.
- **Markers** (the next name is a comparison, a studio, a store): смесь…, как в, как у, вроде, наподобие, аналог…, в духе, похож…, наследник…, наступник…, преемник…, известн… по (серии), відом… за, вытеснив, помимо, кроме, после, на основе, по мотивам, от, від, from, студи…/студі…, компани…/компані…, издател…/видав…, разработчик…/розробник…, выходцами из, из, магазин…, фестивал….

### 4.5 Stop list and merging

Never candidates (compared by the name key, 4.7): Steam, PC, ПК, PS4, PS5, PlayStation, Xbox, Xbox One, Xbox Series, Xbox Series X|S, Nintendo, Nintendo Switch, Nintendo Switch 2, Switch, Switch 2, Quest, Meta, Meta Horizon, Netflix, HBO, Apple TV+, Disney+, Amazon Prime Video, YouTube, Twitch, Telegram, IGN, Metacritic, Opencritic, VR, AR, XR, NPC, AI, DLC, RU, EU, US, UA, Hard, Easy, Normal, MAPPA, A24, Sony, Microsoft, Epic Games Store, GOG, itch.io. Also dropped: a name of fewer than 2 characters, of digits only, of more than 8 words.

A candidate whose words stand inside a longer candidate merges into it: its appearances count for the longer one («SQL» into «Ghost in the SQL Data»).

The **years of the item**: every `19[5-9]x` / `20xx` in the text («2027»), used by the order (5.3).

### 4.6 Expected on the samples

| # | Kind | First candidate | Next (weight) |
|---|---|---|---|
| 1 | Игра | Ghost in the SQL Data | — |
| 2 | Сериал | Dead-End Job | «Игры в кальмара» (3), «Разделения» (0.5) |
| 3 | Игра | Petit Planet | «Animal Crossing от HoYoverse» (4), «Геншине» (0.5) |
| 4 | Аниме | Death Stranding: Isolations | E&H production (1) |
| 5 | Игра | Phantom Blade Zero | Black Myth: Wukong (6), Elden Ring (6) |
| 6 | Аниме | Блич | — |
| 7 | Игра | EXODUS | Mass Effect (5) |
| 8 | Игра | Silent Hill: Townfall | — |
| 9 | Игра | Alien: Isolation 2 | — |
| 10 | Игра | The Wolf Among Us Remastered | — (the score lines are dropped) |
| 11 | Игра | Fishy (24) | Scary Baboon (6), Enver (2), Meta Horizon (1), Animal Company (1) |
| 12 | Игра | Fabula Rasa (18) | Pixel Ripped, XR Experience, Best of Tech, Miami Filmgate Interactive (6) |
| 13 | Аниме | Магия вернувшегося должна быть особенной | — |
| 14 | Аниме | Реинкарнация безработного | — |
| 15 | Игра | Phantom Blade Zero | — |
| 16 | Игра | Tomb Raider: Legacy of Atlantis | — |
| 17 | Фильм | ELDEN RING | — (A24 on the stop list) |
| 18 | Игра | Control: Resonant | — |

Samples 13 and 14 also have the jut.su slugs («kikansha no mahou», «mushoku tensei», weight 50).

### 4.7 The name key

How names are compared: `text.key` (case, «ё» as «е») and then every run of characters that are not letters or digits is one space, outer spaces off. «Control: Resonant» and «Control Resonant» are one key. One place (rule 7: one rule — one place).

## 5. Offers: candidates in the source

An **offer** («предложение») is a record of the source shown to the owner as a card with «Да» / «Нет». Searches go through the search of the kind (`Titles.search`: the search the owner waits for, ahead of the paced requests; it marks the records already in the list).

### 5.1 Which candidates are searched

The candidates in rank order whose weight is at least half of the first one's, at most **3**. So: Fishy (24) is searched alone; Fabula Rasa (18) alone; Phantom Blade Zero (10) with Black Myth: Wukong and Elden Ring (6); EXODUS (10) with Mass Effect (5); Dead-End Job (14) alone.

### 5.2 Which records of a candidate

The match of a record and a candidate, by the name key (4.7), over every name of the record — the name, the original name, the Russian name of Shikimori, the alternative names of IGDB:
- **exact** — a name's key equals the candidate's key;
- **prefix** — a name's key starts with the candidate's key and a space («Реинкарнация безработного» → «Реинкарнация безработного: История о приключениях в другом мире»; «kikansha no mahou» → «Kikansha no Mahou wa Tokubetsu desu»).

A candidate gives its exact records, then its prefix records, each group in the order of 5.3; **at most 2** records per candidate. The first candidate only: when none of its records match, the source's first record is taken as a **weak** offer — the source found it by a name it does not return (TMDb answers «Dead-End Job» with «Работа с призрачными перспективами» / 꿀알바). The offers of the item: the records of the candidates in rank order, without repeats, **at most 3**.

### 5.3 Order: new first

Inside a group:
1. the record's year is one of the years of the item (4.5) — «EXODUS … Реліз 7 квітня 2027» takes Exodus 2027, not Exodus 2025;
2. new with a date: the date is not earlier than the same day two years ago on the owner's clock (2026-11-05 → from 2024-11-05) or in the future;
3. without a date (IGDB leaves the date empty for announced games: Alien: Isolation 2) — counted as new, after the dated new ones;
4. the rest;
then the order of the source.

The date of a record: TMDb `release_date` / `first_air_date`, Shikimori `airedOn.date` of the entry shown, IGDB `first_release_date`. `Suggestion` gets the field `released: date | None` (the date the search answer gives, read softly, rule 9).

An anime is a franchise: Shikimori's suggestion is one per franchise (its earliest season), so «Блич» is one offer — «Блич» (2004) — and adding it takes the whole chain with «Тысячелетняя кровавая война». The note of sample 6 about «its latest part» is met by the franchise itself.

### 5.4 A typo in a name message

Only for a name message (4.2) of at least 2 words whose search gave no exact or prefix record:
1. search the name without one word, dropping the words from the last to the first, at most 3 such searches, until one gives a **close** record: a name of the record with at least as many words as the candidate (n), whose first n words have a key with `difflib.SequenceMatcher` ratio at least **0.85** to the candidate's key;
2. the **corrected name** is those first n words of that name (trailing punctuation off); it is searched as a candidate: its exact and prefix records (at most 2), or, when it gives none, the close record itself;
3. these offers carry the heading «Возможно, вы имели в виду:»; the weak offer of the original search (5.2), if any, comes after them with «Это оно?».

A one-word name is not corrected. Checked live (`offers-prototype.json`):

| Sent | Kind | Offer «Возможно, вы имели в виду:» | Searches |
|---|---|---|---|
| Реинкарнация безработнго | Аниме | Реинкарнация безработного: История о приключениях в другом мире | 3 |
| Phantom Blad Zero | Игра | Phantom Blade Zero | 4 |
| Ведьмак 3 Дикая охта | Игра | The Witcher 3: Wild Hunt (via «Ведьмак 3: Дикая охота») | 3 |
| Cyberpnk 2077 | Игра | Cyberpunk 2077, Cyberpunk 2077: Turf Wars | 4 |
| Игра в кальмра | Сериал | Игра в кальмара, Игра в кальмара: вызов | 3 |
| Eldn Ring | Фильм | Elden Ring (2028) | 4 |
| Dead-End Job | Сериал | none: «Это оно?» Работа с призрачными перспективами (weak) | 3 |

None of the sources corrects typos itself (`search-typos-links.json`: «Phantom Blade Zer0», «Dead-End Jb», «Eldn Ring» → nothing). A typo in the English name of a series TMDb answers in another language is not corrected (KI, section 13).

### 5.5 Requests per item

At most 3 link lookups (+1 Steam `appdetails` each), 3 candidate searches, and 4 more for a typo: at most 10, usually 1–3 (the 18 samples: 1–3, measured). All searches go at once, ahead of the paced polling (TMDb counts them in its window: the polling waits a little longer; IGDB the same, about 4 a second at most). A source failing on any search of an item ends the analysis with «источник не ответил» unless offers were already found — then they are shown and the failure goes to the log.

### 5.6 Expected first offers of the samples (live)

| # | First offer | Further offers |
|---|---|---|
| 1 | Ghost in the SQL Data (IGDB 414822) | — |
| 2 | Работа с призрачными перспективами (TMDb tv 289517, weak) | — |
| 3 | Petit Planet (370095) | — |
| 4 | Выход смерти: Изоляция / Death Stranding: Isolations (Shikimori 62931) | — |
| 5 | Phantom Blade Zero (250618) | Black Myth: Wukong (136879), Elden Ring (119133) |
| 6 | Блич (269) | — |
| 7 | Exodus 2027 (279621) | Exodus 2025 (379592), Mass Effect (73) |
| 8 | Silent Hill: Townfall (222342) | — |
| 9 | Alien: Isolation 2 (319082, no date) | — |
| 10 | The Wolf Among Us Remastered (404716) | — |
| 11 | Fishy 2026 (422039) | Fishy 2004 (102522) |
| 12 | none — IGDB has no Fabula Rasa: «Не нашёл — сохранил во «Входящие».» | — |
| 13 | Магия вернувшегося должна быть особенной (54852) | — |
| 14 | Реинкарнация безработного: История о приключениях в другом мире (39535) | — |
| 15 | Phantom Blade Zero (250618) — «Уже в списке» when added before | — |
| 16 | Tomb Raider: Legacy of Atlantis (381235, a remake) | — |
| 17 | Elden Ring (TMDb movie 1485839, 2028) | — |
| 18 | Control Resonant (225582) | — |

## 6. The offer card, «Да», «Нет»

### 6.1 The card

```text
Это оно?

🎮 The Wolf Among Us Remastered
2026 · ПК, PS5, Xbox Series X|S
```
- heading: «Это оно?» or «Возможно, вы имели в виду:» (5.4);
- line 1: `KINDS[kind].icon` and the name of the record;
- line 2: the original name when its key differs from the name's («Выход смерти: Изоляция» → «Death Stranding: Isolations»);
- line 3: the date — out: the year («2026»); in the future with a day: «выйдет 12 февраля 2027»; no date: «дата не объявлена»; then ` · ` and the details of the record when it has them (the platforms of a game);
- the poster of the record above the text (section 8);
- buttons in one row: «✅ Да» `inb:<item id>:y:<n>`, «❌ Нет» `inb:<item id>:n:<n>`, where `n` is the number of the offer in the item (0–2).

An offer that is in the list already (the search marked it): «Уже в списке» and the card of the title, the item resolved (2.3).

### 6.2 «Да»

Early answer «Добавляю…», then `add_title(kind, external id of offer n)` — adding as on the web: «Хочу», a game gets «играю здесь» on «Мои платформы» it has.
- success, new: the buttons of the offer go; «✅ Добавлено в список» and the card; for a series and an anime the question about the watched seasons (as today); the item resolved;
- success, already there: «Уже в списке» and the card; resolved;
- the source failed: «Не удалось получить данные из <source>. Нажмите «Да» ещё раз чуть позже.»; the buttons stay; the item stays where it is;
- the source has no such record (`TitleNotFound`): as «Нет» on this offer;
- no keys of IGDB: «Игры не подключены: нет ключей IGDB в .env.»; the item stays.

Games are added from the bot now; their statuses still change only on the web: `KindInfo.web_only` keeps its meaning «moved between statuses only on the web» (its comment loses «added»), the game card in the bot keeps «Удалить» alone.

### 6.3 «Нет»

Popup-free early answer, the buttons of the offer go, then:
- offer `n+1` exists → its card (or «Уже в списке» as in 6.1);
- the last offer → «Не нашёл — сохранил во «Входящие». Разберите в веб-приложении.»; a waiting item goes to «Входящие» with «не нашёл»; an item already there stays with «не нашёл».

«Да» / «Нет» on an offer number the item does not have: «Эта кнопка больше не работает.».

## 7. Waiting and «Входящие»

### 7.1 States of an item

| State | Meaning |
|---|---|
| `waiting` | «ждёт ответа»: the question or an offer card waits; at most one item is `waiting` once its pause (1.3) is over |
| `inbox` | in «Входящие» with a reason |

Resolved («Да», «Уже в списке»), «🗑 Не сохранять», «Убрать» in the web and adding from «Найти» **delete** the item: nothing of it is kept. Its old buttons then answer «Эта запись уже разобрана.»; ids never come back (`AUTOINCREMENT`), so an old button never acts on another item (lesson of KI-24).

Reasons: `not_found` «не нашёл», `no_answer` «без ответа», `no_text` «нет текста», `source_failed` «источник не ответил», `not_connected` «игры не подключены».

### 7.2 Moves to «Входящие»

- a new item (1.3) — the others `waiting` → `no_answer`;
- **12 hours** after `received` with no answer → `no_answer`, silently: `Tracker.expire_inbox()` in a scheduler job of its own every `TRACKER_BEAT_SECONDS` (60 s; `add_jobs`), so a bug there does not stop polling or delivery; the 12 hours count from arrival, across restarts;
- the analysis ends without an offer (2.3), «Нет» on the last offer, no text.

### 7.3 Buttons of an item in «Входящие»

Keep working: a kind press runs the analysis (the item stays `inbox`; its kind and reason are updated; a found offer is sent as a card; it does not become `waiting` and does not move the waiting one); «Да» resolves it; «Нет» on the last offer leaves it with «не нашёл»; «Не сохранять» deletes it.

### 7.4 Concurrency

The analysis takes seconds; a new post may move the item to «Входящие» meanwhile: the offers are still sent and work as in 7.3. Every change of an item is one write session (rule 9): «move the waiting ones and write the new one» together; «read the state, change it» together.

## 8. Posters in bot cards

The card stays a text message (up to 4,096 characters) with its buttons; the poster comes as the link preview of the poster address, not in the text:
`link_preview_options = LinkPreviewOptions(url=<poster address>, show_above_text=True, prefer_large_media=True)`.

- The address: the stored value (`poster_path`) as the web card makes it, size `CARD_SIZE` (TMDb `w342`, IGDB `t_cover_big_2x`, Shikimori as stored). The pure `poster_url` and the sizes move from `app/web/posters.py` to the core as `app/tracker/posters.py` and `core` re-exports them; `app/web/posters.py` keeps `image_sources` and imports from `core` (rule 10 stays: the web imports only `core` and the pure modules listed).
- No poster: `link_preview_options=LinkPreviewOptions(is_disabled=True)` — the text card of today.
- Telegram fetches the picture itself; when it cannot, the message comes without a preview — the send does not fail.

Checked live 2026-11-05: three messages from the bot to the owner's chat with the posters of TMDb (`image.tmdb.org`, w342), IGDB (`images.igdb.com`, `t_cover_big_2x`) and Shikimori (`shikimori.io/uploads/poster/…`); the TMDb one 1,400+ characters of text, each with a link button. The owner saw all three with the poster above the text and the button below (2026-11-06).

Cards are: the title card (`send_card` in the bot: after adding, «Уже в списке», «Карточка», «📚 Мои тайтлы», «Готово», «Следить») and the offer card (6.1). Event messages and the summary stay without posters.

## 9. Web: the tab «Входящие»

### 9.1 Menu

`SECTIONS` gets «Входящие» (`/inbox`, code `inbox`) between «Поиск» and «Настройки». Its label is «Входящие (N)» when there are N > 0 items in `inbox` (the `waiting` one is not counted: it is in the chat), «Входящие» otherwise. The number is read by `Tracker.inbox_count()` on every page; a failure of the read leaves the label without a number and a log line.

### 9.2 The page `/inbox`

Heading «Входящие». Items in `inbox`, newest `received` first. Each:
- a head line: the date on the owner's clock — «Сегодня, 14:20», «Вчера, 22:41», «3 ноября, 09:12» (another year: «3 ноября 2025, 09:12»); the kind with its icon («🎮 Игра») or «тип не выбран»; the reason;
- the text: up to the first 4 lines and 300 characters, cut at a word with «…»; a longer text has «показать всё» (`<details>`, no script); an item without text — «(картинка без подписи)», «(видео без подписи)»… by its media;
- buttons: «Найти» (not for an item without text and without a kind), «Убрать»; the link «Открыть пост ↗» (new tab, `rel="noopener"`) when it has a post link.

Empty: «Здесь пусто: всё, что вы присылали боту, разобрано.»

### 9.3 «Найти»

A link to `/search?kind=<kind>&q=<query>&inbox=<item id>` — no kind: without `kind` (the remembered one). The **query** of an item is stored when it is taken in (the rules of section 4 do not need the kind): the first candidate; none — the first 60 characters of the text cut at a word; for an item of links — the name of its first offer. The Search page with `inbox` of an existing item shows under the field «Из «Входящих»: добавленный тайтл уберёт эту запись.»; the suggestions and the add form carry `inbox`; after `add_title` succeeds (new or already in the list) the item is deleted (`Tracker.resolve_inbox(id)`; an item gone already is no error). An unknown or garbage `inbox` is ignored.

### 9.4 «Убрать»

`POST /inbox/<id>/remove`: deletes the item without a question; with HTMX the row goes (the menu number is updated out of band), without HTMX — back to `/inbox`. A removed item answers the same (nothing to do). Behind the sign-in like every page.

## 10. Data

Migration `0014_inbox.py`, table `inbox_items` (`sqlite_autoincrement=True`):

| Column | Type | Meaning |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | never reused |
| `state` | VARCHAR(16), index | `waiting` / `inbox` |
| `reason` | VARCHAR(24) NULL | 7.1 |
| `kind` | VARCHAR(16) NULL | the chosen or linked kind |
| `text` | TEXT NOT NULL default '' | 1.1 |
| `media` | VARCHAR(16) NULL | 1.1 |
| `bold` | JSON NOT NULL default [] | strings |
| `links` | JSON NOT NULL default [] | addresses |
| `post_url` | TEXT NULL | 1.1 |
| `forwarded` | BOOLEAN NOT NULL | 1.1 |
| `media_group_id` | VARCHAR(64) NULL | 1.2 |
| `query` | TEXT NOT NULL default '' | 9.3 |
| `offers` | JSON NOT NULL default [] | each: `kind`, `external_id`, `name`, `original_name`, `released` (ISO or null), `details`, `poster`, `heading` |
| `received_at` | DATETIME NOT NULL | naive UTC |
| `last_message_at` | DATETIME NOT NULL | 1.2 |
| `moved_at` | DATETIME NULL | when it went to «Входящие» |

The offers are stored when the analysis ends, so «Нет» and «Да» need no new search (whether an offer is in the list is checked again when it is shown).

## 11. Code

| Where | What |
|---|---|
| `app/tracker/candidates.py` (pure) | 3 (reading the links), 4: candidates, weights, years, the name key, the query of an item |
| `app/tracker/offers.py` | 5: the searches of an item through the sources (link lookups, candidates, match, order, typo), the offer card text (6.1) |
| `app/tracker/inbox.py` | 1, 7, 10: take in and join, states, moves, 12 hours, list, count, delete; calls `offers` |
| `app/tracker/posters.py` (pure) | 8: `poster_url`, sizes |
| `app/tracker/core.py` | facade methods: `take_in`, `answer_kind`, `answer_offer` (yes / no), `forget_inbox_item`, `resolve_inbox`, `inbox_items`, `inbox_count`, `expire_inbox`; results in `results.py` |
| sources | `suggest_by_id` for TMDb movie and series, Shikimori, IGDB; IGDB `suggest_by_steam`; TMDb provider `find_imdb`; `Suggestion.released` |
| `app/bot/inbox_handlers.py` | the taking-in handler (registered last on the owner router), the pause of 1.3, `inb:` presses, the cards with posters through one sending function shared with `tracker_handlers` |
| `app/bot/tracker_handlers.py` | «Добавить» removed; menu, `/start`, empty list text; cards with posters |
| `app/web/inbox.py`, `templates/inbox.html` | 9.2, 9.4; `search.py` — the `inbox` parameter (9.3); `menu.py` / `pages.py` — the number |
| `app/bot/main.py` | the job of `expire_inbox` |

Each module ≤ 400 lines (rule 7); the bot handlers of «Входящие» stay out of `tracker_handlers.py` (wish of the 6.3 review).

## 12. Edge cases

| Case | Expected |
|---|---|
| a message from anyone else | not taken in (the allowlist, rule 3) |
| two posts forwarded in one go (not an album, no comment) | two items; the first goes to «Входящие» «без ответа» when the second arrives |
| an album of 5 photos with one caption | one item, the caption is its text |
| a forward with a comment | one item, the comment first |
| a name typed, then a second name 1 s later | two items (the second is not a forward) |
| a restart within the 2-second pause | the item waits without a question; it goes to «Входящие» by the next post or 12 hours (KI, 13) |
| a restart while an item waits | its buttons work after the start; the 12 hours count from arrival |
| the same post sent twice | a second item; its offer is «Уже в списке» if it was added, else a new analysis |
| a post of only a link of a source | no question, the card at once; «Найти» query — the offer name |
| a link of a source plus a name | the link offers first, then the candidates, at most 3 |
| a text of only a link that is no source (t.me, youtube) | «Что это?»; the candidates are empty → the fallback (4.2) is empty too → «не нашёл» |
| a very long post (4,096) | taken in; 10,000 characters kept; the web shows 4 lines with «показать всё» |
| a sticker, voice, video without caption | «нет текста» at once |
| «Да» on an offer whose title was added meanwhile on the web | «Уже в списке», resolved |
| an item removed in the web, its «Да» pressed | «Эта запись уже разобрана.» |
| two items «waiting» found at start (an older version, a crash) | the next new item moves all of them; `expire_inbox` handles the old ones |
| the owner's clock zone changes | the web dates follow; 12 hours are UTC |
| a game post with «Игра» and no IGDB keys | «Игры не подключены…», «Входящие» |
| a movie made from a game (sample 17) | the kind decides the source: «Фильм» → TMDb movie |
| an old `tadd:` / `tpick:` button | «Эта кнопка больше не работает.» |
| «Нет» pressed twice on the same card (double tap) | the second sees the next offer already shown and shows the one after it, or — after the last — «Входящие» once; acceptable |

## 13. Known limitations → `KNOWN_ISSUES.md`

The ticket that brings each adds the entry:
- a typo in a name is not corrected when the source answers in another language than the name (TMDb series with a non-Russian original: «Dead-End Jb») — ticket 04;
- a Cyrillic name in the middle of a post without quotes, kind word or bold is not a candidate (only the fallback of the first line) — ticket 02;
- a restart within the 2-second pause leaves the item without «Что это?» until the next post or 12 hours — ticket 01;
- the stop list is a fixed list: a studio or store not on it and not after a marker can come first in a post without a Latin title — ticket 02.

## 14. Tests

Automated (offline, fake sources fed with the saved answers of `answers/`):
- **Candidates** (`candidates`): each of the 18 samples gives the first candidate of 4.6 and the «not first» names after it; the weights and drops of 4.1–4.5 one by one (score lines, signature, invisible characters, platforms, stop list, merging, kind words, markers, quotes, bold, Cyrillic after a kind word, fallback); the name key; the years; the links of section 3 (every form, `www.`, slugs, letters before the Shikimori id; no duplicates; at most 3).
- **Offers** (`offers`): the 18 samples give the first offers of 5.6 from the saved answers; the order (year of the item, new with a date, no date, old) on made-up records; at most 2 per candidate and 3 in all; the weak offer only for the first candidate; the half-weight rule; the typos of 5.4 (headings, the count of searches); a failure before and after the first offer; the budget of 5.5; the card text of 6.1 (original name, three date forms, details).
- **Inbox** (`inbox`, a database in memory): take in and join (album, comment + forward, 2 seconds, not joined after); the states and every move of 7.2; 12 hours at the edge (11:59 stays, 12:00 moves); delete on resolve, not saved, removed; ids not reused after deleting the last; the query; the item survives a new core on the same file (a restart).
- **Bot** (fake Telegram): taking in vs commands, menu texts, «➕ Добавить»; the pause and the «Предыдущий…» line; «Что это?» buttons and data; every row of 2.2 and 2.3; «Да» (series: seasons question; game: added with «играю здесь»; failure keeps the buttons), «Нет» to the end; the early answer before the source (`tests/test_tracker_early_answer.py`, rule 8); buttons after «Входящие» and after delete; the keyboard without «Добавить»; `/start` text; every card with `link_preview_options` above the text and `is_disabled` without a poster; tests of «➕ Добавить» are removed or rewritten.
- **Web**: the menu with and without the number; the page (empty, items with each reason, cut text, no text, post link); «Найти» address; Search with `inbox` (the line; adding deletes the item; garbage ignored); «Убрать» with and without HTMX; sign-in required; rule 10 imports.
- `tests/test_tracker_core_split.py`, `tests/test_code_map.py` stay green (new modules ≤ 400 lines, docstrings).

The owner checks live (stage end, from the description): forward 3–4 sample posts (a game, a series, an anime, a movie) and answer the kind — a card with a poster, «Да» adds; a name with a typo — «Возможно, вы имели в виду:»; «Нет» on a post with several games — the next one, to the end — «сохранил во «Входящие»»; two posts without an answer — the first in «Входящие» on the web; «Найти» → Search filled, adding removes the item; «Убрать»; «Карточка» under an event — with the poster; a post with a Steam link — the card at once; «🗑 Не сохранять».

## 15. Docs

- `CONTEXT.md`: «Входящие» — In code: `inbox`, an entry — `inbox item` (table `inbox_items`), the states `waiting` / `inbox`, the reasons; new **Кандидат** (candidate: a name the rules pick from what the owner sent; In code `candidate`) and **Предложение** (offer: a record of the source shown as «Это оно?» with «Да» / «Нет»; In code `offer`; not a search suggestion, `Suggestion`); «Поиск» — the line «Из «Входящих»».
- `docs/coding-standards.md` rule 7: rows `candidates`, `offers`, `inbox`, `posters`; pure list gets `candidates`, `posters`.
- `docs/code-map.md`: built; templates line gets `inbox.html`.
- `docs/tests-map.md`: the new test modules.
- `KINDS`: `ask_name` goes; `web_only` comment.
- `PROJECT_CONTEXT.md`: State (no «➕ Добавить»; games added from the bot), Next step.
- No new ADR (section 3 narrows ADR 0010 as the description decided; the poster as a preview is easy to reverse).

## 16. Proposed tickets

| # | Ticket | Spec | Complexity | Blocked by |
|---|---|---|---|---|
| 01 | «Входящие» in the database and taking in: migration 0014, `inbox` (take in, join, states, moves, 12 hours, delete), the bot handler, the pause, «Что это?», «Не сохранять», «Предыдущий…», «нет текста», «➕ Добавить» removed, menu, `/start`. Until 04 a kind press stores the kind and moves the item to «Входящие» with «не нашёл» and the text «Тип запомнил — сохранил во «Входящие».» | 1, 2 (no 2.3), 7, 10, 11, 12 | complex | — |
| 02 | Candidates: the pure module, links of sources, the 18 samples | 3 (parsing only), 4 | medium | — |
| 03 | Posters in all bot cards | 8 | simple | — |
| 04 | Offers and cards: searches, match, order, typos, link lookups (`suggest_by_id`, `suggest_by_steam`, `find_imdb`, `Suggestion.released`), the card, «Да» / «Нет», «Уже в списке», games through the bot, failures; the interim text of 01 goes | 2.3, 3, 5, 6, 7.3–7.4 | complex | 01, 02, 03 |
| 05 | The web tab: menu number, page, «Найти» with `inbox`, «Убрать», adding from Search deletes the item; the query of an item | 9 | medium | 01 |

02 and 03 can go in parallel with 01; 05 after 01. Sessions: slicing, 5 tickets, review — 7 more (8 with this one).
