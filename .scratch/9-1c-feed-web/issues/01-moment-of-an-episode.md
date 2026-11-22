# 01: The moment of an episode — KI-28, KI-32, KI-77, KI-48

Status: accepted
Complexity: complex (a migration, one new field through four adapters, one display rule in three places, a changed event moment)
Blocked by: —

Spec: `../spec.md`, sections 1.1–1.4 (the timing, who sets what, how a moment reads, KI-77, the examples; 1.5 is ticket 02), section 9 (KI-48 only), section 11 (migration 0017 and its fit), the Timing, Migration, Display and KI-77 lines and the KI-48 line of the tests of section 14, the lines of section 13 about 00:00 UTC, a premiere by the day, an anime AniList does not know and a zone west of UTC, the `CONTEXT.md` line **Серия** of section 15. Terms — `CONTEXT.md` («Серия», «Лента», «Карточка»). ADRs to read: 0005 (migrations). Standards — rules 2, 5, 6, 7, 9, 11. Known issues: KI-28, 32, 77 (`fixed`), KI-48 (`won't fix`). Fixture: `../answers/shikimori-jjk-s4-and-genres-2026-11-22.json` → copy to `tests/fixtures/shikimori/` (the announced part 2 of KI-48).

## What to do

Work in this order; each step leaves the suite green.

1. **The type and the migration (1.1, 11).** `seasons.EpisodeTiming` (`exact` · `day` · `unknown`, an enum per rule 6) and `Episode.timing` (default `exact`: a test or a sample that builds `Episode(n, at)` keeps its meaning). Migration `0017` adds `episodes.timing` (text, not null) and fills the old rows by the table of section 11 — a series `day`; an anime with no `air_at` `unknown`; a moment with seconds or microseconds `unknown`; at 00:00:00 UTC the lowest number of the season with that moment `day`, the other episodes of the season with the same moment `unknown`; any other moment `exact`. The downgrade drops the column. The model, `storage.store_seasons`, `sync_seasons`, `load_seasons`, `load_seasons_of` write and read it wherever they handle `air_at`. The export of 7.1 stays without `timing`.
2. **The adapters (1.1, «Who sets what»).** TMDb (`sources/tmdb_series.py`): every dated episode `day`. Shikimori (`sources/shikimori_anime.part_episodes`): the episode of `nextEpisodeAt` `exact`; the premiere stub of an announced entry (`airedOn`) `day`; of the episodes out, the first is `day` when `airedOn` is known, the others `unknown`; an entry with `releasedOn` alone gives `unknown` to all. AniList (`anime_events._scheduled`): the episode with `airingAt` `exact`; the next one known by number only takes Shikimori's moment with its timing; an episode out takes Shikimori's moment when that one is out (with its timing), else the moment of this look (`unknown`) — the airing of the last days (1.5) is added by ticket 02 in the first place of this order, so leave one clear place for it. `anime_events.assemble` with something stored: an episode out now that was not stored keeps the fresh moment when it is `exact`, otherwise gets the moment of this look as `unknown`; the first recorded moment of an episode already out stays with its timing; an episode of a new entry that was out by the previous look keeps its own moment and timing. `series_events.ShowState.keeping_known` takes the stored episode whole (moment and timing).
3. **The rule of the hour (1.2).** One rule in one place, `cards`, next to `local_moment`: the hour only for an `exact` moment of a kind with `local_times`; the day of an `exact` or `unknown` moment on the owner's clock, of a `day` moment as stored. `seasons` hands out episodes: `_EpisodeRun.next_episode(now)` and `first_episode()` (`next_air_at`, `first_air_at` stay for callers that need the moment alone); `SeasonProgress.next_air_at`, `next_part_at` and `SeasonAnnouncement.first_air_at` carry an `Episode` (or fields that do). Replace the «midnight UTC means the day only» guesses by the rule in: `feed_rows.day_of` and `season_pieces` (Лента, «Скоро»), `cards.progress_line` (the next episode; «часть 2 — с …»; «Сезон 4 анонсирован, премьера …») and the bot messages `series_events._next_line`, `message_announced`, `message_moved`. `series_events._only_the_hour_learned` reads the timing (a `day` moment followed by an `exact` one of the same day is no move). **`series_events._moment_key` keeps its midnight rule** — it makes the dedup keys of events already stored. Series: nothing the owner sees changes (their existing tests pass untouched).
4. **KI-77 (1.3).** `series_events._aired_at` gives `happened_at` = the moment when the timing is `exact` or `day`, None for `unknown`; `Flavor.moments` goes. So the first check after «Вернуть в список» reports an anime episode whose moment is later than the return, and stays silent for an episode found with no schedule; a `day` moment on the day of the return is earlier than the return and stays silent.
5. **KI-48 (9).** A test pins the card of an announced season without data from the saved answers (the saved franchise `tests/fixtures/shikimori/jujutsu_kaisen.json` with the part as answered now): «Сезон 4 анонсирован, дата не объявлена». No code change; the entry → `won't fix (test: …)`.
6. **Docs.** Docstrings of every touched module and `.venv\Scripts\python.exe tools\code_map.py`; `docs/tests-map.md`; `CONTEXT.md` — **Серия** (a sentence on the moment: «точное время», «только день», «неизвестно»; `In code: EpisodeTiming (episodes.timing)`); `KNOWN_ISSUES.md` — KI-28, 32, 77 `fixed (test: …)`, KI-48 `won't fix (test: …)`, with the index rows. The Gotcha «Moments of aired anime episodes are unknown» of `PROJECT_CONTEXT.md` is changed by ticket 02, not here.

If the session cannot hold steps 1–6, do not cut the ticket by the middle: finish step 3 (display) on the data of steps 1–2 and move 4–6 to a short ticket `01b`, written in this folder (with its own «Done when»), and say so in the message to the owner.

## Done when

- [ ] Migration 0017 on a base with every row of the table of section 11 (a season of shared 00:00 moments like «Ван-Пис», a lone 00:00, a whole minute, a moment with microseconds, a series, `NULL`) fills each as the table says; downgrade drops the column; a copy goes to `data/backups/` first.
- [ ] The adapters set the timing as 1.1 says; `assemble` and `keeping_known` keep a stored moment with its timing; a fresh `exact` moment is kept, anything else gets the moment of the look as `unknown`.
- [ ] The Feed, both cards and the bot messages read a moment by the one rule: an AniList episode at 00:00 UTC shows its hour on the owner's clock (KI-28); an episode found by a check shows «Сегодня» with no hour (KI-32); a premiere known by the day shows no hour and, west of UTC, the source's date, not the day before.
- [ ] The first check after a return reports an anime episode with an `exact` moment after the return and keeps silent for `unknown`; `_only_the_hour_learned` and `_moment_key` give the old results on old data.
- [ ] The card of the announced season without data (KI-48) reads «Сезон 4 анонсирован, дата не объявлена».
- [ ] `KNOWN_ISSUES.md` has the five statuses and index rows; pyflakes clean; code map rebuilt; no core module over 400 lines (the facade 500); the full suite green (the known Windows failures are not new), and the existing series tests pass untouched.

## Tests to add

- **Timing**: TMDb `day`; Shikimori `exact` / `day` / `unknown` on the saved franchises (`one_piece.json`, `kusuriya.json`, `jujutsu_kaisen.json`); `_scheduled` with and without an airing; `assemble` keeps a stored moment and its timing, takes the fresh `exact` moment, else `unknown`; `keeping_known` keeps both.
- **The migration** as in «Done when», upgrade and downgrade.
- **Display**: `day_of` by timing (00:00 `exact` shows the hour — KI-28; `unknown` shows none — KI-32); `progress_line`, the part line, `announced_line`, `_next_line`, `message_announced`, `message_moved` for `exact` / `day` / `unknown`, one zone east and one west of UTC; the examples of 1.4 as cases.
- **KI-77**: the return then the check, `exact` after the return reported, `unknown` silent, `day` on the day of the return silent; `_only_the_hour_learned` and `_moment_key` on old data.
- **KI-48** as step 5.

## Owner check

The session starts the bot and writes the launch result in one line; the migration copy goes to `data/backups/` by itself. Then, in the browser at `http://localhost:8080`, tab «Лента»:

1. Open «Скоро» and look at an anime that is running (for example «Монолог фармацевта»): its next episode shows a day and an hour; an anime whose premiere is only a day (an announced season) shows the day with no hour.
2. Open the card of the same anime: the line «следующая — …» shows the hour only where the Feed does.

«Не так»: an announced season shows an hour such as «в 03:00»; an anime that came out today shows an hour that is the minute of a check; the page shows an error. The part about «Вернуть в список» is checked by the tests (the owner has no title to return at the right minute).
