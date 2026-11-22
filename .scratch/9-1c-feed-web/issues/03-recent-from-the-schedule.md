# 03: «Недавно» from the schedule — KI-29

Status: in review
Complexity: complex (a new read in three pollers, pure row-building with a matching against the event log, the template, the number of reads held)
Blocked by: 01

Spec: `../spec.md`, section 2 (2.1 which rows, 2.2 how a row reads — the whole table, folding, the day, no hour, no buttons, the order, the empty sentence; 2.3 reads), section 1.2 (the day of a moment), the «Недавно» line of the tests of section 14, the lines of section 13 about the 7-day window, titles in the archive, games, a deleted title added again, renumbering and a series dated today, the `CONTEXT.md` line **Лента** of section 15. Terms — `CONTEXT.md` («Лента», «Недавно», «Архив», «Вернуть в список»). ADRs to read: 0005. Standards — rules 5, 7, 9, 10, 11. Known issue: KI-29 (`fixed`). Mockup: `../mockups/feed.html` (the section «Недавно» with the grey line).

## What to do

- **The pure part, `feed_rows` (2.1, 2.2).** `released_rows` takes what a poller handed it and the events of the window, and gives the rows: the pieces of «Скоро» (`season_pieces` with the parts of the card), the reason (**before adding** — `air_at ≤ titles.added_at`; **in the archive** — `titles.restored_at` is set and `air_at ≤ restored_at`; the first reason wins), the folding (the episodes of one part of one season of a title on one day with the same reason make one row; another day, another row), the matching against the log, and the texts of the table of 2.2 word for word: «Сезон 2, серия 3», «Сезон 2, серии 3–5», «Сезон 3 — премьера», «Сезон 3 — премьера, серии 1–2», «Сезон 3, часть 2 — премьера», «Премьера в кино», «Цифровой релиз», «Премьера в кино и цифровой релиз», with the grey lines «вышла / вышли / вышел до добавления в список» and «вышла / вышли / вышел, пока тайтл был в архиве». If this pushes `feed_rows` past 400 lines (it has 292), the rows go to a new module `feed_released`.
- **Which episodes and films (2.1).** An episode of a series or an anime: dated, timing `exact` or `day`, `air_at ≤ now`, its day (1.2) within today − 6 … today, before the baseline; an `unknown` episode never makes a row. A film: the theatrical or the digital date the card shows, within the same 7 days and not after today, and `day_start(date) ≤ added_at` or `≤ restored_at`. Only titles not in the archive now; series, anime and movies; never games, never the films of an anime franchise.
- **Not in the log (2.1).** An episode is in the log when an event of the title of type `series_season_started`, `series_episode_out` or `series_season_ended` with `payload.season` and `payload.episode` equal to its own was detected since today − 7; a film date is in the log when a `movie_released` (theatrical) or `movie_digital` (digital) event of the title was detected since then. A title archived then returned within 7 days keeps its event row and gets no row from the schedule.
- **The reads (2.3).** `Poller.feed_released(session, shown, basis, since)` — games and the default: none; `SeasonalPoller` from the stored seasons; `MoviePoller` from its own states. `FeedReader` reads the events of the window once more for the matching (types and ids only), so the number of reads does not depend on the number of titles; `added_at` and `restored_at` come with the titles already read. The page compares neither kinds nor statuses.
- **The row (2.2).** `{icon} {name} — {what}` and the grey line in the place of `details`; `RecentRow.at` is None, `watched` False, `follow` None; the row leads to the card. The day it stands on is the day of the schedule (1.2), not the day it was found. Order in a day: the event rows first (the latest first, as now), then the rows from the schedule by name (`text.key`), then title id, then season and first episode. The sentence «За неделю ничего не случилось» shows only when there are neither events nor rows from the schedule. Nothing is queued and no message goes.
- **Docs.** Docstrings, `tools\code_map.py`, `docs/tests-map.md`; `CONTEXT.md` — **Лента** («Недавно» also shows what came out before adding or while in the archive: rows from the schedule, no buttons); `KNOWN_ISSUES.md` — KI-29 `fixed (test: …)` with the index row.

## Done when

- [ ] Every row of the table of 2.2 reads word for word, for both reasons; the example «📺 Одни из нас — Сезон 2, серия 3» / «вышла до добавления в список» is a test.
- [ ] The window edges hold: today − 6 in, today − 7 out; an episode after now out; an `unknown` episode out; a title in the archive out; a game out; a film of an anime franchise out.
- [ ] An episode with an event shows once, as the event row; a title returned from the archive shows what came out while it was there with «пока тайтл был в архиве», and what came out before the first adding with «до добавления в список».
- [ ] The rows of one part on one day fold into one; the order in a day is as in 2.2; the empty sentence shows only when both are empty.
- [ ] `test_the_feed_reads_as_much_for_one_title_of_each_sort_as_for_fifty` keeps passing with the rows from the schedule in it.
- [ ] pyflakes clean; code map rebuilt; no core module over 400 lines (the facade 500, and `core.py` gets no new method: section 10); the full suite green (the known Windows failures are not new).

## Tests to add

- Each row of 2.2, one, several, premiere, part 2, film, digital, both; before adding and in the archive.
- Folding by part and day; different days stay apart.
- The matching against the log: an episode with an event shows once; a film date with `movie_released` / `movie_digital`; a title deleted and added again (a new id: its old events are not its own).
- The window edges, `unknown`, the archive, games, the order, the empty sentence.
- The reads do not grow with the number of titles (the existing count test, extended).

## Owner check

The session starts the bot and writes the launch result in one line. In the browser, tab «Лента», section «Недавно»:

1. Add through «Найти» a series that is on right now (one with an episode that came out in the last days). Open «Лента»: under «Недавно» a row «📺 <название> — Сезон N, серия M» with a grey line «вышла до добавления в список» appears, with no hour and no buttons; pressing the row opens the card.
2. Check that nothing arrived in Telegram for it (the rows are only on the page).

«Не так»: no row for a series with a fresh episode; the row says an hour; the same episode shows twice; the sentence «За неделю ничего не случилось» stays while rows exist.
