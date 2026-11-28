# 01: The platform Meta Quest — several IGDB numbers of one platform, SteamVR as ПК, the first poll after the update

Status: accepted
Complexity: complex (the platform table, dates, polling and release events of every game in the list)
Blocked by: —

Spec: `../spec.md`, section 0 (what changed against the description), sections 1–5 (the table, the dates, the line of a suggestion, what the owner sees, the first poll), section 8 (data; of the snapshot keys only `known`), the rows of section 10 from «A Quest game with no date» to «The owner unticks Meta Quest» and «A game both on PS5 and Meta Quest» (without the store link and the button: ticket 02), the **Table**, **Dates**, **The suggestion line**, **First poll** and **Export and settings** lines of section 11, and the `CONTEXT.md` «Платформа», «Обратная совместимость» and ADR 0018 lines of section 13. Terms — `CONTEXT.md` («Платформа», «Обратная совместимость», «Мои платформы», «Страна магазинов»). ADRs to read: 0009, 0011. Standards — `docs/coding-standards.md`, rule 6 (the table stays the one place) and the rules on modules and tests. Live answers — `../answers/games.json`, `release_date_statuses.json`.

## What to do

1. **The table (1.1–1.3).** `app/tracker/platforms.py`: `PlatformInfo.igdb_id: int` becomes `igdb_ids: tuple[int, ...]`; ПК gets 6 and 163 (SteamVR); the new platform `meta_quest` («Meta Quest» in Settings, cards and messages; own numbers 471, 386, 384; no older platform), last in the table. Default «Мои платформы» stay ПК and PS5. Every reader of the old field moves to the new one. 162, 385, 161, 387, 390, 165 are not taken; release statuses 34–36 stay not taken.
2. **The dates (section 2, points 1–7).** Per own number as today, then the earliest end among the own numbers (equal ends — the narrower; «не объявлена» loses), no `via`; then the older platform as today; cancelled only when no own number has a `full` or `early` record; `has_platform`, the date outside the country and `older_tells` over every number.
3. **The line of a suggestion (section 3).** `IGDB_LABELS` maps every number to its label; `platform_line` names each label once, in the order of the table.
4. **What the owner sees (section 4).** Settings, the web and bot cards, the Feed, release messages, expansions and series, the «(ПК)» mark and Steam prices work with the new table; no new text templates. A list of platforms written by hand anywhere else is brought to the table.
5. **The first poll (section 5).** `GameState.known` — all own and older numbers of the table at the moment of the snapshot, stored as `known`; a stored snapshot without the key has `(6, 48, 49, 130, 167, 169, 508)`; `game_events.detect_events` compares the old snapshot with the new one restricted to the old `known`; the stored new snapshot is whole.
6. **Data (section 8).** No migration. The JSON export and the setting `my_platforms` carry `meta_quest`; a snapshot of a restored old copy reads by the rule of point 5.
7. **Docs.** `CONTEXT.md`: «Платформа» (Meta Quest; ПК includes SteamVR; own numbers `igdb_ids`, the earliest date, no version text; the snapshot's `known`), «Обратная совместимость» (the Quest headsets and SteamVR are not older platforms). New `docs/adr/0018-…`: a platform of the tracker can have several IGDB numbers of its own (section 13: why, the rejected options, the consequence for any number added later). Docstrings of changed modules; `tools\code_map.py`; `docs/tests-map.md`.

## Done when

- [ ] The examples of section 2 give exactly their rows (country Israel, records of `games.json`), Beat Saber's status-36 records not taken.
- [ ] The line of a suggestion: «ПК, Meta Quest» for Beat Saber, «Meta Quest» for 471 and 386, «ПК» for 6 and 163, «PS5, PS4» unchanged, no line for 162 alone.
- [ ] ПК with 6 cancelled and a SteamVR date shows the date; PC «2026» with SteamVR «12 марта 2026» shows «12 марта 2026».
- [ ] A snapshot without `known` and a new one with an earlier SteamVR date and a future Quest date give no events; a PC (6) release of the same poll still gives «вышла»; the next poll compares everything.
- [ ] A game on PS5 and Meta Quest released the same day gives one message «вышла на PS5 и Meta Quest».
- [ ] On the owner's PC after the start, the polls of games that happen during the check add no «дата объявлена», «дата перенесена» or «вышла» caused by a SteamVR or Quest date; no red text in the log.
- [ ] No migration is added; pyflakes clean; the code map rebuilt; the full suite green (the known Windows failures do not count).

## Tests to add

By the lines **Table**, **Dates**, **The suggestion line**, **First poll** and **Export and settings** of spec section 11: the new value, labels, `igdb_ids`, `check_platforms`, the order of Settings; an own date from each Quest number, the earlier of two, the narrower on equal ends, «не объявлена» loses, status 36, cancelled with another number dated, SteamVR alone, `older_tells`, the date outside the country; the line of a suggestion; the first poll (old snapshot, PC release in the same poll, second poll, `known` stored); `meta_quest` saved, read and exported.

## Owner check

The session starts the bot (one line with the result), opens `http://localhost:8080` → «Настройки», ticks «Meta Quest» in «Мои платформы» and saves (the owner may untick it after the check).

1. «Настройки»: «Meta Quest» is the sixth checkmark, the last, ticked.
2. «Поиск»: «Batman: Arkham Shadow» — the line under the name says «Meta Quest»; «Beat Saber» — «ПК, Meta Quest».
3. Add the games and open their cards:
   - Batman: Arkham Shadow — «Meta Quest — 22 октября 2024» with «играю здесь»;
   - Supernatural — «Meta Quest — 23 апреля 2020»;
   - Beat Saber — «ПК — 21 мая 2019» and «Meta Quest — 21 мая 2019», the link «Открыть в Steam»;
   - Red Matter 2 — «ПК — 18 августа 2022» and «Meta Quest — 18 августа 2022».
4. Bot: «📚 Мои тайтлы» → Batman: Arkham Shadow — the same row.

Keep the added games: ticket 02 checks the store links on them.

«Не так»: no checkmark or no row; a text «(версия для Quest 2)»; a message «дата объявлена», «дата перенесена» or «вышла» about a game that was already in the list, with no news behind it; a red text in `.\logs-bot.ps1`. The link «Открыть в магазине Meta» is not there yet — it comes with ticket 02.
