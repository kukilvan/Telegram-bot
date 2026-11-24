# 04: Offers and the bot — the date of an offer, English names, links again, «Что это?» after a restart — KI-64, KI-61, KI-62, KI-57

Status: accepted
Complexity: complex (a migration, four sources, the analysis of an item, the start of the bot; two independent halves)
Blocked by: 02, 03

Spec: `../spec.md`, section 8 (8.1 KI-64, 8.2 KI-61, 8.3 KI-62, 8.4 the requests per item), section 9 (KI-57), section 12 (migration 0019), section 13 (the IGDB `/games` search, the TMDb search and failures rows), the offer rows of section 14, the «Offers and bot» line of the tests of section 15, the `CONTEXT.md`, `PROJECT_CONTEXT.md` and `KNOWN_ISSUES.md` lines of section 16. Terms — `CONTEXT.md` («Входящие», «Примерная дата»). ADRs to read: 0007 (one process: the bot asks at start), 0010, 0015. Standards — rules 2, 7, 9, 11. Fixtures: `../answers/igdb-search-date-format-2026-11-23.json` → `tests/fixtures/igdb/search_date_format.json`; `../answers/tmdb-alternative-titles-2026-11-23.json` → `tests/fixtures/tmdb/dead_end_job.json` (the `alternative_titles` part is for reading only). Spec 6.4 of the earlier stage (5.3 the order of offers, 5.4 the typo) — only where this ticket changes it.

## What to do

Two halves that do not touch each other; do A, then B. Each step leaves the suite green.

**A. The offers (section 8).**

1. **KI-64 (8.1).** `Suggestion.released` and `Offer.released` become `ReleaseDate` (default `NOT_ANNOUNCED`); `inbox_items.offers` stores `ReleaseDate.text` («2027-Q4», «2028», «2027-02-12»); reading is strict (`parse`), an old stored day text reads as a day. TMDb (movies, series, `/find`): `ReleaseDate.of_day`. Shikimori: `Entry.aired` (ticket 02). IGDB: the search also asks `release_dates.date,release_dates.date_format,release_dates.y,release_dates.m`; the record whose `date` equals `first_release_date` gives `ReleaseDate.from_igdb`, the least precise record wins (year over quarter over month over day), no matching record — the year of `first_release_date` alone. `offer_cards.released_line(released, today)`: an exact day after today «выйдет 12 февраля 2027»; an approximate date whose `end >= today` «выйдет » + `phrase` («выйдет в 2028», «выйдет во 2 квартале 2027», «выйдет в январе 2027»); anything else the year; not announced «дата не объявлена». The order of offers (5.3 of 6.4) reads `released.year` and `released.start`.
2. **KI-61 (8.2).** The typo correction (a name message of 2+ words with no match, search without one word): when that search in the source's language gives no close name and the source can search in English, search the shortened name once more with `language=en-US` (`suggest(query, english=True)`; the provider's `search_movie` / `search_tv` get `language`); a close English name is the correction. The corrected name is then searched in the source's language and the offer is the record of the **same id** from that search (Russian name); not there — the English record. Shikimori and IGDB are not asked twice. A failure of the English search follows the typo path (after an offer — the log; before — «источник не ответил»).
3. **KI-62 (8.3).** `answer_kind`: before the name candidates, the links of the item **of the chosen kind** (`SourceLink.kind == kind`; an IMDb link for a movie or a series) are looked up again as `by_links` does — records first, a Steam number IGDB does not know gives Steam's name as a candidate, a failing link goes to the log and gives nothing. A link of another kind is not looked up.
4. The request budget of 8.4 holds (10 at the end of the pause, 17 at a kind press); the English search only on the typo path of a name message.

**B. «Что это?» after a restart (section 9).**

5. **Migration 0019** `0019_inbox_answered_at.py`: `inbox_items.answered_at DATETIME NULL` by `ALTER TABLE … ADD COLUMN`, filled with `last_message_at`; downgrade drops it the same way as 0016. The model gets the field.
6. **Setting it.** Every write of `InboxAnswers` that leaves the item `waiting` after its pause sets `answered_at`: the question (the `pause_over` path that answers `ASK` gets a small write that sets it when the item still waits) and the offer card (`_show`). An item that leaves `waiting` needs none.
7. **`Tracker.inbox_unanswered() -> list[int]`** (`Inbox.unanswered`): items `waiting`, `answered_at` empty, `received_at` within the last 12 hours, oldest first. The facade grows by this one method; `core.py` stays ≤ 470 lines.
8. **The start of the bot.** Once polling starts (the dispatcher's start, before the first update), the bot asks `inbox_unanswered()` and gives each item its pause answer: `inbox_pause_over(id)` and the messages of `say`, to the owner's chat (`OWNER_CHAT_ID`, as events), without the line «Предыдущий…». `say` gets a target that is the owner's chat instead of the message it answered (the question, the card with its poster, the texts). A failure goes to the log.
9. **Docs.** `CONTEXT.md`: «Входящие» — the question comes after a restart too (`answered_at`); the offer date («выйдет в 4 квартале 2027»); `PROJECT_CONTEXT.md`: migrations up to 0019, the TMDb row (the English search of a typo); `tools\code_map.py`; `docs/tests-map.md`; `KNOWN_ISSUES.md`: KI-57, KI-61, KI-62, KI-64 → `fixed (test: …)` (entry and index); in KI-57 the window of section 9 («Not asked twice…») is written down.

## Done when

- [ ] On the saved IGDB answer: The Witcher IV (`date_format` 2) → «выйдет в 2028»; Intergalactic and Marvel 1943 → «выйдет в 2027»; Fishy Bar (4, quarter 2) → «выйдет во 2 квартале 2027»; Hollow Knight: Silksong (0) → «2025»; several records of one date — the least precise wins; none matching — the year.
- [ ] TMDb and Shikimori offers show their precision; an offer stored before this stage reads as a day.
- [ ] «Dead-End Jb» + «Сериал» on the saved answers gives «Возможно, вы имели в виду:» «Работа с призрачными перспективами» (id 289517, the same-id rule); with the same id missing from the Russian search the English record is the offer.
- [ ] A Steam link that failed at the pause gives its card after the press of «Игра»; a link of another kind is not looked up; the counts of 8.4 hold.
- [ ] Migration 0019 on a copy of a base: the column is there, existing rows have `last_message_at` in it, downgrade removes it.
- [ ] The question and the offer card set `answered_at`; `inbox_unanswered` returns only a waiting, unanswered item younger than 12 hours (13 hours — not; answered — not).
- [ ] The start sends the question to the owner's chat once; a restart afterwards sends nothing for the same item.
- [ ] pyflakes clean; code map rebuilt; no module over its limit; `core.py` ≤ 470 lines; the full suite green.

## Tests to add

The «Offers and bot» list of section 15 in full: `released_line` on every form of 8.1 (day after today, approximate not ended, approximate ended, past day, not announced); IGDB precision from the saved search; Shikimori precision; old stored offers; KI-61 the typo path on the saved answers, the same-id rule, a failed English search; KI-62 both cases; the budget counts; migration 0019; `answered_at` by the question and by the card; `inbox_unanswered`; the start sends the question once (a fake dispatcher start and a fake bot).

## Owner check

The session starts the bot and writes the launch result in one line. In Telegram, to the bot (wait about 3 seconds for the question «Что это?»):

1. Send «The Witcher IV», press «Игра». The offer says «выйдет в 2028».
2. Send «Dead-End Jb», press «Сериал». The card «Возможно, вы имели в виду:» offers «Работа с призрачными перспективами».

The restart after the question and the failed link are checked by the tests; the session says so. «Не так»: «выйдет 31 декабря 2028» or another made-up day; no card for «Dead-End Jb»; red text in `.\logs-bot.ps1`. The test items are answered «Нет» or removed in the web tab «Входящие» with «Убрать» (the session says so).
