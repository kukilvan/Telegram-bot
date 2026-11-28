# Spec 6.5: Meta Quest as a platform of games

Status: in review

Built from `description.md` (accepted 2026-11-28) and idea 003; where they differ, this file wins. Terms: `CONTEXT.md` (changes in section 13). ADRs: 0009 (no PlayStation prices — the same reasoning keeps Meta store prices out), 0010 (the bot takes posts and links), 0011 (a followed expansion is a game of its own). A new ADR 0018 (section 13) records that a platform of the tracker can have several IGDB numbers of its own.

Live answers (2026-11-28) lie in `answers/`:
- `platforms.json` — the IGDB platforms named Quest, Oculus or Meta; `platform_counts.json` — how many games each has;
- `external_game_sources.json` — the sources of `external_games` (28 «Oculus» is the Meta store);
- `release_date_statuses.json` — every `status` of a release record (34–36 are new since 6.1);
- `searches.json`, `games.json` — 12 VR games searched and their records with dates and `external_games`;
- `recent_quest_games.json` — the 25 Quest games with the latest first release (from July 2025): how upcoming games are written;
- `by_meta_store_id.json` — a game found by its Meta store number in one request.

The Meta store pages were opened in the browser (meta.com answers `400` to plain HTTP clients); results are in 6.2.

## 0. What changes against the description

Two decisions taken with the owner in this session (2026-11-28), on the real answers:

- **No version text for Quest.** IGDB often gives a new game a date only for Quest 2 (`recent_quest_games.json`: most upcoming games), while in the Meta store it is one app for Quest 2, 3 and 3S. «(версия для Quest 2)» would stand on most cards and say nothing. So the three headsets are the platform's **own** numbers, not older platforms: the earliest date among them is simply the Meta Quest date. «Обратная совместимость» stays as it is (PS5, Xbox Series X|S, Switch 2).
- **SteamVR counts as ПК.** IGDB writes the PC version of a VR game as the platform SteamVR (163), not as PC (6): Beat Saber, Red Matter 2, Thief VR have no 6 (2,758 games have SteamVR without PC, 876 both). The description's "SteamVR games stay PC" assumed IGDB writes them as PC. The owner chose: SteamVR is one more own number of ПК — its date is the ПК date, without any text; the ПК row, release messages and Steam prices work for such games as for any PC game. This touches the games already in the list too (section 5).

Everything else of the description holds. `description.md` gets a pointer to this section.

## 1. The platforms and their IGDB numbers

### 1.1 The table

A platform of the tracker has one or more **own** IGDB numbers and at most one older platform (backward compatibility, unchanged). `PlatformInfo.igdb_id: int` becomes `igdb_ids: tuple[int, ...]`; rule 6 of `docs/coding-standards.md`: the table stays the one place.

| Platform (value) | Settings | Card, messages | Own IGDB numbers | Older |
|---|---|---|---|---|
| `pc` | ПК | ПК | 6 PC (Microsoft Windows), **163 SteamVR** | — |
| `ps5` | PlayStation 5 | PS5 | 167 | PS4 (48) |
| `xbox_series` | Xbox Series X\|S | Xbox Series X\|S | 169 | Xbox One (49) |
| `switch_2` | Nintendo Switch 2 | Switch 2 | 508 | Switch (130) |
| `switch` | Nintendo Switch | Switch | 130 | — |
| **`meta_quest`** | **Meta Quest** | **Meta Quest** | **471 Meta Quest 3, 386 Meta Quest 2, 384 Oculus Quest** | — |

The value `meta_quest` is stored in `game_platforms`, in the setting `my_platforms` and in the JSON export; it never changes. Default «Мои платформы» stay ПК and PS5.

### 1.2 What is not counted

- **162 «Oculus VR»** — a general record of the old Oculus store (Rift, Go, Gear VR era): 223 games have it without any Quest number. Not Meta Quest.
- **385 Oculus Rift, 161 Windows Mixed Reality, 387 Oculus Go** — PC VR of Meta's PC store, a dead headset family, a dead headset. Not ПК (the owner chose SteamVR only), not Meta Quest.
- **390 PlayStation VR2, 165 PlayStation VR** — out of scope (description).
- **Meta Quest 3S** has no IGDB number of its own; its games are the Quest 3 ones.

### 1.3 Release statuses

`release_date_statuses.json` lists three statuses unknown at 6.1: 34 «Advanced Access», 35 «Digital Compatibility Release», 36 «Next-Gen Optimization Patch Release». They stay not taken, as every status but nothing/6, 3 and 5 today. 36 matters: Beat Saber's Quest 3 and Quest 2 records are 36 (a patch for the new headset, not a release); the record of the first Quest (21 May 2019) gives the date.

## 2. The dates of a platform with several own numbers

`games.platform_dates` and everything that reads it (card rows, the Feed, release events, the check interval, follow-ups, the date outside the country):

1. **Per own number** — as `pick` today: the records of that number and type (`full`, `early`), the first region of the store country that has one, two of one region — the earlier start.
2. **Among the own numbers** — the date that ends earliest («the game can surely be played by this day», as for an older platform); equal ends — the narrower one (the later start: «31 декабря 2026» before «2026»); «не объявлена» loses to any date. The result is the platform's own date, with no `via`.
3. **The older platform** — compared with that own date as today (`_better`, `via` «PS4»). No platform has both several own numbers and an older one, but nothing forbids it.
4. **Cancelled** — the platform is cancelled when its own numbers together have records `cancelled` and none of them has `full` or `early` (and the older gives no date, as today). So ПК with 6 cancelled and a SteamVR date is not cancelled.
5. **On the platform** (`has_platform`) — any own number or the older number in `platforms` or in the records.
6. **The date outside the country** (`game_rows.outside_date`) — over every own number and the older one (`igdb_numbers` already returns all of them).
7. **`older_tells`** (Switch 2 ← Switch): the older number is an own number of another told platform — `older.igdb_id in PLATFORMS[other].igdb_ids`.

Examples (country Israel; dates from `games.json`):

| Game | Records | Row |
|---|---|---|
| Batman: Arkham Shadow | 471: 22.10.2024 | «Meta Quest — 22 октября 2024» |
| Asgard's Wrath II | 386 and 471: 15.12.2023 | «Meta Quest — 15 декабря 2023» |
| Beat Saber | 384: 21.05.2019; 386, 471: status 36 (not taken); 163: 21.05.2019 | «ПК — 21 мая 2019», «Meta Quest — 21 мая 2019» |
| Supernatural | 384: 23.04.2020 | «Meta Quest — 23 апреля 2020» |
| Red Matter 2 | 386 and 163: 18.08.2022 | «ПК — 18 августа 2022», «Meta Quest — 18 августа 2022» |
| Postal 2 VR | 386: «июнь 2027» | «Meta Quest — июнь 2027» |

## 3. The line of platforms of a suggestion

Search, «Входящие» offers, the bot's «Это оно?» card. `IGDB_LABELS` maps every own number to its platform's label and every older number to the older label; `platform_line` names each label once, in the order of the table, the older right after its newer:

- Beat Saber (386, 390, 161, 165, 163, 471, 385, 384) → «ПК, Meta Quest»;
- Asgard's Wrath II (386, 471) → «Meta Quest»;
- a game on 6 and 163 → «ПК»; on 167 and 48 → «PS5, PS4» (unchanged);
- a game only on 162 «Oculus VR» → no line, as for any game without the platforms of the tracker.

The mockup's «ПК, PS4, Meta Quest» for Beat Saber was a guess: IGDB lists its PlayStation version as PlayStation VR (165), not PS4.

## 4. What the owner sees

Texts are the existing templates with the new label; nothing else changes in them.

- **Settings → «Мои платформы»:** a sixth checkmark «Meta Quest», last. The hint under the store country stays («Ссылка на PlayStation Store ведёт в магазин этой страны…»): the Meta store link does not depend on the country (6.2).
- **Card (web and bot):** a row «Meta Quest — 22 октября 2024» with «играю здесь», last among the rows; with no date «Meta Quest — дата не объявлена»; cancelled — the existing «Meta Quest — отменена». The bot card's unmarked row «… (не отмечена)» as today.
- **Feed:** «Выход на Meta Quest», «Выход на ПК и Meta Quest» (one piece per day and type, as today).
- **Release messages:** «🎮 <name> вышла на Meta Quest», «… вышла на ПК и Meta Quest», «… вышла в раннем доступе на Meta Quest», late releases with their day; «дата объявлена» and «дата перенесена» on Meta Quest — the existing templates. Delivery rules unchanged.
- **Expansions and series (6.3):** an expansion or a game of the series on Meta Quest counts as «на моих платформах» when Meta Quest is one of them (`follow_ups.on_my_platforms` reads `platform_dates`).
- **Russian (idea 002):** a game the owner plays only on Meta Quest gets «(ПК)» after Steam and ZoG data, by the existing rule.
- **Steam prices:** a VR game whose PC version is SteamVR only now has the ПК row, so with ПК among «Мои платформы» and «играю здесь» on ПК its prices are checked like any game's (the first check is a reference point, without messages). «появилась страница в Steam» does not come for it: the Steam number was known before (the event needs a number new to the snapshot).

## 5. The first poll after the update

The stored snapshot of a game holds only the records of the IGDB numbers the tracker knew when it was taken (`known_platforms`, `read_releases` drop the rest). After the update the first poll of every game would see the SteamVR and Quest records as new and give false «дата объявлена», «дата перенесена» (a SteamVR date earlier than PC's) and late «вышла».

So the snapshot remembers what it could see:
- `GameState.known: tuple[int, ...]` — the IGDB numbers of the tracker when the snapshot was taken (all own and older numbers of the table), stored as `known` in every snapshot from now on;
- a snapshot without the key is from before 6.5: its `known` is `(6, 48, 49, 130, 167, 169, 508)`;
- the events of a poll (`game_events.detect_events`) compare the old snapshot with the new one **restricted to the old snapshot's `known`** (its `platforms` and `releases` of other numbers left out); the stored new snapshot is whole. From the second poll both sides see everything.

So a real PC event of that first poll (on 6) still comes; the SteamVR and Quest dates are only recorded. The platform rows of `game_platforms` are added as today («a platform of mine the game gets later receives the mark by itself»). The same works for any platform added later. The follow-up snapshot needs nothing: a follow-up already listed gives no message whatever its platforms become.

## 6. The Meta store

### 6.1 The number of a game

IGDB `external_games` with `external_game_source = 28` («Oculus»): `uid` is the number of the app in the store (15–17 digits: `2448060205267927`), `url` is `https://www.meta.com/experiences/<uid>` or, for older records, `https://www.oculus.com/experiences/app/<uid>`. The game request already asks `external_games.uid`, `.external_game_source`, `.url`; nothing is added to it. `GameState.meta_store_id: str | None` (stored `meta_store_id`) — the `uid` when it is all digits, else None (as `ps_concept`). In `games.json` 10 of 11 Quest games have it; over IGDB 938 of 1,591 Quest games (59 %), fewer among the upcoming ones.

### 6.2 The address

Checked in the browser on 2026-11-28:
- **page:** `https://www.meta.com/experiences/<id>/` — opens the game (redirects itself to `/experiences/<slug>/<id>/`); an unknown number opens the store's own page «Error | Meta Store» (accepted, no check — description);
- **search:** `https://www.meta.com/experiences/search/?q=<name>` — the store's search results (Asgard's Wrath II found first); `<name>` is the **original name** (`title.original_name or title.name`), encoded with `quote(name, safe='')`: the store is in English, a Russian name finds nothing;
- **country:** neither address has a locale; meta.com picks the language and the currency itself. The store country does not change the link.

`platforms.meta_store_url(meta_store_id, original_name) -> str` builds it, next to `steam_url`.

### 6.3 In the cards

When Meta Quest is one of «Мои платформы» and the game is on Meta Quest (`has_platform`):
- **web card:** the link «Открыть в магазине Meta», after «Открыть в Steam» and «Открыть в PlayStation Store» (the order of the table); opens in a new tab like them; not `checked` (no check at a click);
- **bot card:** the text line «Магазин Meta: https://…», after the lines of Steam and PS Store.

`game_rows.store_links` adds `StoreLink("Открыть в магазине Meta", "Магазин Meta", url)`.

### 6.4 Under the release message

- A release event on Meta Quest («вышла», «вышла в раннем доступе») carries `meta_url` in its payload: the address of 6.2 at the moment of the event (a stored event keeps it). Other events of Meta Quest («дата объявлена», «дата перенесена») and of other platforms do not.
- `actions.event_actions`: an event with `meta_url` has «📄 Карточка», then the link button «🛒 Открыть в магазине Meta» (`Action` named `META`, `url` = `meta_url`).
- **One message of several platforms** (folded events of one game, `game_events.fold_key`): the button is there when any member has `meta_url` — not only the lead, which is the first platform of the table (ПК). The members' cards are one card.
- **In a summary:** the button reads «🛒 Открыть в магазине Meta: <name>», like Steam's; in the limit of the summary's buttons it stands with Steam: «Следить», then «Посмотрел», «Открыть в Steam», «Открыть в магазине Meta», «Карточка».
- **«🧪 Тестовое событие»:** a new sample «Игра: вышла на Meta Quest» — «🎮 Asgard's Wrath II вышла на Meta Quest» with the button to `https://www.meta.com/experiences/2603836099654226/` (no «Карточка»: a sample has no title, as the Steam samples).

## 7. A Meta store link sent to the bot

### 7.1 Which links

`candidates.source_links` gets one more rule: host `meta.com` or `oculus.com` (with or without `www.`, any case), path

`^/(?:[a-z]{2}[-_][a-z]{2}/)?experiences/(?:[^/]+/)?(\d{6,})(?:/|$)`

— source `meta`, kind «игра». Read forms (all seen live or in IGDB):
- `https://www.meta.com/experiences/2448060205267927/`
- `https://www.meta.com/experiences/beat-saber/2448060205267927/`
- `https://www.meta.com/en-gb/experiences/2448060205267927/`
- `https://www.oculus.com/experiences/quest/2603836099654226/`
- `https://www.oculus.com/experiences/app/2108775495884888`
- with a query (`?utm_source=…`) — the path alone is read.

Not read: `meta.com/experiences/search/…`, `meta.com/experiences/` alone, short share links (`meta.com/s/…`), Horizon Worlds — they are ordinary text links.

### 7.2 The lookup

Like a Steam link (6.4): the kind is known, so no «Что это?»; IGDB is asked in one request `where external_games.uid = "<n>" & external_games.external_game_source = 28; limit 10;` with the suggestion fields (`IgdbGameSource.suggest_by_meta`; `by_meta_store_id.json`: Beat Saber). Any type of record counts (an expansion too, ADR 0011). Found — the card «Это оно?» at once. Not found — no name is asked anywhere (no request to the Meta store); the analysis goes on with the text of the post, as after a TMDb or Shikimori link IGDB does not know; nothing — «Входящие», reason «не нашёл». No IGDB keys — reason «игры не подключены», as for a Steam link.

## 8. Data

- **No migration:** platform values are strings in `game_platforms` and in `my_platforms`; the snapshot is JSON.
- **Snapshot keys:** `meta_store_id` (None until the first poll after the update fills it; till then the link is the search) and `known` (section 5). `GameState.from_state` reads a snapshot without them.
- **Export:** the JSON export carries `meta_quest` in `platforms` and in the settings by itself (the values come from the table). The CSV has no platforms.
- **Restore of an old copy:** its snapshots have no `known` — the rule of section 5 covers them.

## 9. External services

Only IGDB, the same requests and limits: the platforms are numbers in the existing fields, `external_games` is already asked. The Meta store link lookup is one more request of the same kind as the Steam one, at the bot's analysis (not in the polling queue). No request to the Meta store.

## 10. Edge cases

| Case | Behaviour |
|---|---|
| A Quest game with no date (`date_format` 7, or no records) | The existing «дата не объявлена» row |
| Dates on 471 and 386 differ | The one that ends earlier (section 2); one release, one message |
| Only a Quest 3 record of status 36 and nothing else | No date: «дата не объявлена» (the game is on Meta Quest by `platforms`) |
| A game on 162 «Oculus VR» only | Not on Meta Quest: no row, no line |
| PC 6 «2026» and SteamVR «12 марта 2026» | «ПК — 12 марта 2026» (ends earlier) |
| PC 6 cancelled, SteamVR dated | ПК has the SteamVR date, not cancelled |
| A game already in the list gains a ПК or Meta Quest row through the update | Rows added with «играю здесь» by the setting; no event on the first poll (section 5); Steam prices start with a reference point |
| The owner ticks Meta Quest in Settings | The existing behaviour: rows read as marked, no messages for dates the snapshot already had |
| The owner unticks Meta Quest | The row, the store link and Quest messages go (existing behaviour) |
| IGDB knows no store number | The search link |
| The store number is dead | Meta's «Error» page; not checked |
| IGDB gives a store number of another game | The wrong page; not handled (rare; a `KNOWN_ISSUES.md` entry when met) |
| A store link with no digits after `experiences/` or a short link | Not a source link (7.1) |
| A store link IGDB does not know, post without other names | «Входящие», «не нашёл» |
| A game both on PS5 and Meta Quest released the same day | One message «вышла на PS5 и Meta Quest» with «Карточка» and the Meta button |

## 11. Tests

Automated (pure tests on saved answers where a source is read; `docs/tests-map.md` names the files):
- **Table:** the new value and labels, `igdb_ids` of ПК and Meta Quest, `check_platforms` accepts `meta_quest`, the order of Settings.
- **Dates (section 2):** an own date from each Quest number; the earliest of two numbers by the end, the narrower on equal ends, «не объявлена» loses; status 36 not taken (Beat Saber record of `games.json`); cancelled with another own number dated; SteamVR alone gives the ПК date; `older_tells` with `igdb_ids`; the date outside the country over several own numbers.
- **The suggestion line:** «ПК, Meta Quest» for Beat Saber's numbers, «Meta Quest» for 471+386, «ПК» for 6+163, «PS5, PS4» unchanged, none for 162.
- **First poll (section 5):** an old snapshot without `known` and a new one with a SteamVR date earlier than PC's and a future Quest date — no events; a PC (6) date that came out the same poll — «вышла» comes; the second poll compares everything; `known` stored.
- **The store (6.1–6.3):** `meta_store_id` from `external_games` (digits only), the page and the search addresses (spaces, `&`, a Cyrillic name encoded), the web and bot links shown only with Meta Quest among mine and the game on it.
- **The button (6.4):** a Quest release carries `meta_url` and the button; an announcement or a PC release does not; a folded PC + Quest release has it although the lead is PC; the summary order; the test sample.
- **The link (7):** every form of 7.1 read with its number, the not-read forms not; the lookup query; found — an offer at once; not found — the text goes on, then «Входящие».
- **Export and settings:** `meta_quest` saved, read and exported.

Owner checks live (section 12).

## 12. Owner check at the end of the stage

The session ticks «Meta Quest» in Settings (the owner can untick it after, if they want) and the owner walks:
1. **Search** (web): «Batman: Arkham Shadow» — line «Meta Quest»; «Beat Saber» — «ПК, Meta Quest».
2. **Add and open the cards** (web):
   - Batman: Arkham Shadow — «Meta Quest — 22 октября 2024», link «Открыть в магазине Meta» opens its page in the store;
   - Supernatural — «Meta Quest — 23 апреля 2020», the link opens the store's search for «Supernatural» (IGDB has no store number for it);
   - Beat Saber — «ПК — 21 мая 2019» and «Meta Quest — 21 мая 2019», links to Steam and the Meta store;
   - Red Matter 2 — «ПК — 18 августа 2022», «Meta Quest — 18 августа 2022».
3. **Bot:** «📚 Мои тайтлы» → Batman: Arkham Shadow — the row and the line «Магазин Meta: https://…».
4. **Bot:** send `https://www.meta.com/experiences/asgards-wrath-2/2603836099654226/` — «Это оно?» with Asgard's Wrath II at once, without «Что это?».
5. **Bot:** «🧪 Тестовое событие» → «Игра: вышла на Meta Quest» — the message and the button «🛒 Открыть в магазине Meta» that opens the store page.
6. Delete the added games after the check if they are not wanted.

## 13. Docs, terms, ADRs, known issues

- **`CONTEXT.md`:** «Платформа» — Meta Quest added; ПК includes SteamVR, Meta Quest is one platform for Quest 3, Quest 2 and the first Quest; a platform may have several IGDB numbers of its own (`igdb_ids`), the earliest date counts, no text. «Обратная совместимость» — one line: the Quest headsets and SteamVR are not older platforms. «Страна магазинов» — the Meta store link is the same in every country. New term **«Магазин Meta»** (Meta store): the store of Quest apps; the game's page by its number from IGDB, else the search by the original name; in code `meta store`, `meta_store_id`, `meta_store_url`, the payload key `meta_url`, the action `META`. The snapshot's `known` named under «Платформа».
- **ADR 0018** «A platform of the tracker can have several IGDB numbers of its own»: why the Quest headsets and SteamVR are own numbers, not older platforms (no version text; the Meta store app is one for every headset; SteamVR is the PC version of a VR game); the rejected options (older platforms with the text; SteamVR out — the owner's choice); consequence: the first-poll rule of section 5 for any number added later.
- **`docs/coding-standards.md`:** nothing new (rule 6 already holds).
- **`docs/project-spec.md`, 6.5:** «Quest 2 and first-Quest versions count» stays; add «SteamVR counts as ПК; no version text» (this session).
- **`description.md`:** a line under «Decisions taken with the owner» pointing to section 0 (this session).
- **`KNOWN_ISSUES.md`:** nothing new.
- **`docs/nas-changes.md`:** nothing (no setting, no `.env` name).

## 14. Proposed tickets

| # | Ticket | Complexity | Sections | Depends on |
|---|---|---|---|---|
| 01 | **The platform**: `igdb_ids`, `meta_quest`, SteamVR in ПК; dates, cancellation, `older_tells`, the suggestion line; the snapshot's `known` and the first-poll rule; Settings, export; `CONTEXT.md`, ADR 0018 | complex (polling and events, every game in the list) | 1–5, 8, 10, 11 (table, dates, line, first poll, export) | — |
| 02 | **The Meta store**: `meta_store_id`, the address, the links of the web and bot cards, `meta_url` and the button (folded, summary), the test sample, the store link in «Входящие» and its IGDB lookup; the term «Магазин Meta» | medium | 6, 7, 8, 10, 11 (store, button, link) | 01 |

Sessions left: slicing, 2 tickets, review — 4.
