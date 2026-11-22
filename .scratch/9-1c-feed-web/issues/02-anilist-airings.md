# 02: AniList airings of the last 8 days

Status: open
Complexity: medium (one request root, one field, two callers; the moments of episodes already out)
Blocked by: 01

Spec: `../spec.md`, section 1.5 (the request, the strict reading, `PartSchedule.aired`), the third list item of «AniList» in 1.1 (who takes the airings), section 12 (the AniList row), the «AniList airings» line of the tests of section 14, the lines of section 13 about «AniList's `recent` has more than 50 airings» and «AniList numbers an entry on through the season», the `PROJECT_CONTEXT.md` Gotcha of section 15. Terms — `CONTEXT.md` («Серия»). ADRs to read: 0015 (the polling queue). Standards — rules 2, 7, 9, 11. Fixtures: `../answers/anilist-recent-2026-11-22.json` → `tests/fixtures/anilist/schedules_recent.json`; `../answers/anilist-recent-request.json` is the request the live check sent — read it, do not copy it.

## What to do

- **The request (1.5).** `AniListProvider.get_schedules` (packs of 50 ids) gets the second root `recent: Page(perPage: 50) { airingSchedules(mediaId_in: $ids, airingAt_greater: $since, airingAt_lesser: $until, sort: TIME_DESC) { mediaId episode airingAt } }` in the same request, with `$since` = now − 8 days and `$until` = now, unix seconds (the clock comes from the caller as everywhere else: rule 2). No `pageInfo`. No new request, so the rate of the client stays.
- **The reading.** `sources/anilist_schedule` reads the airings strictly: an airing without an `int` `mediaId`, a positive `int` `episode` or an `int` `airingAt` is skipped; an airing of an id that was not asked is skipped; numbers beyond the part's announced count are dropped (as `_usable` does for the rest). `PartSchedule` gets `aired: Mapping[int, datetime]` — the entry's own episode number to its naive UTC moment. An answer without `recent`, or a broken one, gives every part `aired = {}` and the schedules are used as now; `_usable` dropping a schedule drops its airings with it.
- **The callers (1.1).** `anime_events._scheduled`: an episode out takes, in this order, its airing (`exact`), Shikimori's moment when that one is out (with its timing), else the moment of this look (`unknown`) — ticket 01 left the place. `assemble` gives an episode found now its airing moment as the fresh `exact` moment. So the episodes out at adding and at the first check after a return get their own moments when they aired in the last 8 days, and an episode a check finds out gets the moment it aired instead of the moment of the check.
- **Docs.** Docstrings and `tools\code_map.py`; `PROJECT_CONTEXT.md` — change the Gotcha «Moments of aired anime episodes are unknown»: they are known for 8 days for the entries AniList knows (the moment of the check stays for the rest); `docs/tests-map.md`.

## Done when

- [ ] One request carries both roots; the variables hold now − 8 days and now in unix seconds.
- [ ] On the saved answer episode 8 of 195516 reads as `1795183200` = 2026-11-20 14:00 UTC; a broken node, an unasked id and a number beyond the count are skipped; no `recent` gives `aired = {}`.
- [ ] A title added with an episode out 3 days ago stores that episode with its airing moment and `exact`; an episode a check finds a minute after it aired is stored at the airing moment, not the check's; with no airing the moment of the look and `unknown`, as after ticket 01.
- [ ] The Gotcha is rewritten; pyflakes clean; code map rebuilt; no core module over 400 lines; the full suite green (the known Windows failures are not new).

## Tests to add

- Parsing the saved answer; a broken node skipped; no `recent` → `{}`; an unknown id skipped; beyond the count dropped; the request text carries `$since` and `$until` with the right values for a fixed clock.
- `_scheduled` and `assemble` with an airing (adding, a later check, the first check after a return), without one, and with Shikimori's moment as the second choice.
- More than 50 airings in a pack: the oldest missing episode takes the moment of the check (`unknown`).

## Owner check

The session starts the bot and writes the launch result in one line. This part is mostly invisible; the tests carry it. One look in the browser, tab «Лента», section «Сегодня» or «Недавно»: an anime episode that came out in the last days stands on the day it really aired (not on the day the bot found it) and, if the source gave the minute, shows its hour. «Монолог фармацевта», серия 8, вышла 20 ноября в 14:00 UTC — on a card of that title (if it is in the list) the episode is dated 20 ноября.

«Не так»: the episode stands on the day of the last check; an error in the log (`.\logs-bot.ps1`, red text) about AniList.
