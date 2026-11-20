# 05: Numbers never reused (migration 0015) and posters on the current Shikimori address

Status: accepted
Complexity: medium (one small migration, one place that creates titles, one pure function with three callers)
Blocked by: —

Spec: `../spec.md`, sections 5 (KI-24), 3.3 (KI-21), the rows «A title created by a test directly in the session» and «`SHIKIMORI_BASE_URL` not `https`» of section 7, tests of 3.3 and 5 in section 8, the `PROJECT_CONTEXT.md` Gotchas and `docs/backups.md` lines of section 9. Terms — `CONTEXT.md`; standards — rules 1, 3, 7, 10, 11; migrations — note the style of 0014 and the warning of 0009. Known issues: KI-24, KI-21.

## What to do

- **Numbers never reused (5).** Migration **0015**: table `issued_ids` (`name` text primary key, `last_id` integer not null) with one row `('titles', <max(titles.id) or 0>)`; model `IssuedId` in `models.py`. `Titles._store_title`, in its write session: `id = max(issued last_id, max(titles.id)) + 1`, set on the new `Title`, and `last_id` updated in the same commit; a missing row (a hand edit) is made again from `max(titles.id)`. No `AUTOINCREMENT` and no rebuild of `titles` (eight tables cascade from it). `docs/backups.md` — one line: a restore of an old copy brings its own `last_id`, so numbers given after that copy may come again; the restore is the owner's deliberate step. `PROJECT_CONTEXT.md` Gotchas — `issued_ids` keeps the last number of a title; "migrations up to 0015" in State (budget 20,000 bytes).
- **Posters on the current address (3.3).** `poster_url(stored, size, shikimori_site)`: a stored `https://` address whose host is `shikimori.<zone>` or a subdomain of it (the label before the last one is `shikimori`) gets the `shikimori.<zone>` part of the host replaced by the host of `shikimori_site`, the scheme and port from `shikimori_site`, the path and query kept. `shikimori_site` is the site of `SHIKIMORI_BASE_URL` as `image_sources` reads it (`https` only); no valid site — the address stays as stored; TMDb and IGDB addresses never change. Callers: the web (the template global `poster_url` gets the site from `create_web_app`), the bot's card (`tracker_handlers.py`) and the inbox card (`inbox_handlers.py`), both given the site by `build_dispatcher`; `app/main.py` passes `settings.shikimori_base_url`. Stored addresses stay as they are.
- **Docs:** module docstrings, `tools\code_map.py`, `docs/tests-map.md`; `KNOWN_ISSUES.md` — KI-24, KI-21 `fixed (test: …)`.

## Done when

- [ ] Delete the last title, add another: a new number, not the deleted one; migration 0015 seeds `max(id)` (also on an empty table: 0); a missing `issued_ids` row is made again; a title created directly in the session by a test does not break `max + 1`.
- [ ] The examples of 3.3 hold with site `https://shikimori.io` (`shikimori.one/uploads/…` → `shikimori.io/uploads/…`; `desu.shikimori.one` → `desu.shikimori.io`; `shikimori.io` unchanged); TMDb and IGDB addresses unchanged; no valid site (empty, `http`) — unchanged.
- [ ] The web, the bot's card and the inbox card all show the fixed address (one test per caller).
- [ ] Migration 0015 runs on a copy of the owner's real database shape (children rows present) and keeps every row.
- [ ] KI-24 and KI-21 are `fixed (test: …)`; pyflakes clean; the code map rebuilt; the full suite green (the three known Windows failures are not new).

## Tests to add

- `issued_ids`: the delete-and-add case; the seed at migration (with titles, without); the row made again; the interplay with `max(titles.id)`.
- `poster_url`: the three examples, a subdomain, a port in the site, TMDb and IGDB, no valid site, a stored `http://` address.
- The three callers show the fixed address.
- The migration test of the project's style: upgrade from 0014 with data.

## Owner check

The session starts the bot itself and writes the launch result in one line. Browser, `http://localhost:8080`, signed in:

1. Open «Мои тайтлы» / «Список»: all titles are there and the same as before; posters of anime that were broken now show (if you had any gray frames instead of anime posters, they should be pictures now).
2. Open an anime card: the poster is a picture.

«Не так»: titles missing, an error page, an anime poster still a gray frame (tell which title).
