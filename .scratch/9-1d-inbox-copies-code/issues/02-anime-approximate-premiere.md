# 02: Anime — the approximate premiere, late airings, hour moves — KI-81, KI-83, KI-84

Status: in review
Complexity: complex (a migration, a new timing through storage, events, cards, Лента and export; changed event detection)
Blocked by: 01

Spec: `../spec.md`, sections 3 (`ReleaseDate.phrase`, `of_day`, `of_period`), 4 (4.1 what Shikimori says, 4.2 the stub, 4.3 what it does to stored data, 4.4 the day announced after it, 4.5 how it reads, 4.6 the owner's titles), 5 (KI-83), 6 (KI-84), section 12 (migration 0018), the anime rows of section 14, the «Approximate» and «Anime» lines of the tests of section 15, the `CONTEXT.md` and `KNOWN_ISSUES.md` lines of section 16. Terms — `CONTEXT.md` («Примерная дата», «Серия»). ADRs to read: 0005, 0015 (polling queue). Standards — rules 2, 7, 9, 11. Fixture: `../../9-1c-feed-web/answers/shikimori-premiere-precision-2026-11-22.json` → `tests/fixtures/shikimori/premiere_precision.json` (read the answer, do not copy its request).

## What to do

Work in this order; each step leaves the suite green.

1. **`ReleaseDate` (3).** Add `phrase`, `of_day(day)`, `of_period(start, timing)` to `release_dates.ReleaseDate` (the table of section 3: «в январе 2027», «в 4 квартале 2027», «во 2 квартале 2027», «в 2028»; «во» only before the number 2).
2. **Shikimori (4.1).** The provider asks `airedOn { date year month day }` wherever it asked `airedOn` (entries, search, lookup by id). `Entry` keeps `aired_on: date | None` and gets `aired: ReleaseDate` (day, month, year; `NOT_ANNOUNCED` without `airedOn`); garbage in `year`/`month`/`day` is read softly (no year → `NOT_ANNOUNCED`; bad day → month; bad month → year).
3. **The stub (4.2).** `EpisodeTiming` gets `MONTH` and `YEAR`; `seasons.Episode` gets `rough: ReleaseDate | None = None` (set only for those two; `air_at=None`). `storage.store_seasons` / `sync_seasons` write `air_at = rough.start` at 00:00 and the timing; `load_seasons` / `load_seasons_of` read the row back into `Episode(number, None, timing, ReleaseDate.of_period(...))`. Every rule that reads moments treats the stub as undated: never out (whatever the clock), no next episode, no move, no «объявлена дата», no `check_interval` effect, never in `feed_released` or «Недавно». `shikimori_chain.part_episodes`: an announced entry with no episode out and no `nextEpisodeAt` — `aired.exact` gives today's `day` stub, a month or year the approximate stub, no `airedOn` no stub; the episodes out of an entry whose `aired` is not exact all get `unknown`.
4. **Stored data (4.3, 4.4).** `series_events._keep_season`: an approximate stub is the source's word, not a gap — it replaces the stored (made-up) day, no message. `assemble` unchanged, loops skip the stub. The first exact day after an approximate one queues «объявлена дата … Премьера: …» with `dedup.moved_key("<season key>[:p<n>]:date_announced", observed_at)` when the previous look had an approximate stub for that season or part; otherwise the plain key.
5. **How it reads (4.5).** `_EpisodeRun.premiere() -> Episode | None` (first dated episode, else the approximate stub, else None); `SeasonAnnouncement.premiere`, `SeasonProgress.next_part_start` and `message_part_ended` read it. `cards.premiere_words(episode, tz)` («с 9 января» / «в январе 2027») for the next part and the message; `announced_line` uses `phrase` («премьера в январе 2027»). `feed_rows.season_pieces`: an approximate piece stands on `rough.end`, `when` = `rough.label`, never in «Скоро», dropped when `rough.end` is before today. JSON export: `"air_at": null, "approximate": "2027-01"` (`ReleaseDate.text`).
6. **Migration 0018 (4.6, 12).** `0018_anime_check_now.py`, data only: `source_snapshots.next_check_at` of the Shikimori snapshot of every anime title = the moment of the migration; downgrade does nothing. Test it on a copy of a base (anime snapshots due, others untouched); the usual copy before the migration happens by itself.
7. **KI-83 (5).** `anime_events.assemble` returns `Assembled(seasons, late)`; `late` = `(season, episode)` of every episode that was not stored or stored without a moment, is out now with an `exact` moment not later than `observed_at`, and is not in an entry the title never had; empty at adding. `series_events.detect_events(..., late=())` hands it to `_newly_out`: an episode of `late` is news, its event carries that moment as `happened_at` (`exact`). Series pass nothing.
8. **KI-84 (6).** `series_messages.message_moved` with `premiere=True` and two equal days: each side with its hour («9 янв 2027, 18:00 → 9 янв 2027, 19:00»); `_moved`: equal days where one side has no hour (`day` or `unknown`) and the other is `exact` is no move, both ways.
9. **Docs.** `CONTEXT.md`: «Примерная дата» also covers the premiere of an anime season or part known by the month or the year; «Серия» (the moment known in three ways, or the approximate premiere stub with no moment); `PROJECT_CONTEXT.md`: migrations up to 0018, the 9.1d line; `tools\code_map.py`; `docs/tests-map.md`; `KNOWN_ISSUES.md`: KI-81, KI-83, KI-84 → `fixed (test: …)` (entry and index); KI-85 stays open as written.

## Done when

- [ ] `phrase` reads every form of section 3 (quarter 2 «во 2 квартале 2027»; not announced «дата не объявлена»).
- [ ] From the saved answer: a day, a month-only and a year-only `airedOn` give the three precisions; garbage falls to what is sure.
- [ ] A month or a year premiere stores as a stub with `air_at` at 00:00 of the first day, reads back with `rough`, and is never out — not on the first day of the period, not after it; no event, no «начался сезон».
- [ ] A stored made-up day is replaced by the stub at the first look, with no message; the exact day that comes later queues «объявлена дата» with the `moved_key` key and an old plain key does not swallow it.
- [ ] The card line («часть 2 — в январе 2027», «Сезон 4 анонсирован, премьера в 2027»), the «закончилась часть» message, the «Позже» piece (`when` «январь 2027», on `rough.end`) and the export (`approximate`) follow the table of 4.5.
- [ ] Migration 0018 makes the Shikimori snapshots of anime due and touches nothing else.
- [ ] The probe case of KI-83 (look 13:00 stores 7; 14:30 says 6; 20:00 says 9 with airings of 8 and 9 at 14:00) gives «вышла серия 8» and «вышла серия 9», `happened_at` 14:00; a new entry's past stays silent; adding sends nothing.
- [ ] KI-84: the hour line, and both no-move cases; different days stay «9 янв 2027 → 16 янв 2027».
- [ ] pyflakes clean; code map rebuilt; no core module over its limit; the full suite green.

## Tests to add

The «Approximate» and «Anime» lists of section 15 in full: `phrase` and `of_period`; Shikimori parsing of `airedOn`; `part_episodes` stubs and the `unknown` of an approximate entry with episodes out; storage round trip of `month`/`year`; never out; `_keep_season`; the exact day after an approximate one with the `moved_key` key; the card lines, `message_part_ended`, the «Позже» piece (and its drop after the period), export `approximate`; an AniList `nextAiringEpisode` beating a stub (the edge row of section 14); migration 0018 on a copy; KI-83 (the probe case, a new entry's past, adding); KI-84.

## Owner check

The session starts the bot and writes the launch result in one line. Within a minute of the start (the migration makes the anime due): in the browser, `http://localhost:8080`, tab «Список» — open the card of «Ванпанчмен»: it says «часть 2 — в январе 2027»; «Реинкарнация безработного…» — «часть 2 — в 2027»; «Монолог фармацевта» — «часть 2 — в апреле 2027» (or «Сезон 3 анонсирован, премьера …» in the form the card has it). Tab «Лента», section «Позже»: «январь 2027», «2027», «апрель 2027». In Telegram no message about any of this arrives. «Не так»: «с 1 января» (the made-up day), a message «начался сезон», an error in `.\logs-bot.ps1`.
