# 05: Copies and `.env` — UTC names, the zone of Settings, Drive pages and duplicates, the restore note, the six names — KI-66, KI-67, KI-68, KI-69, KI-49

Status: accepted
Complexity: medium (names, one zone rule, two Drive fixes, a test on `.env.example`; no migration)
Blocked by: 01

Spec: `../spec.md`, section 10 (10.1 KI-66, 10.2 KI-67, 10.3 KI-68, 10.4 KI-69), section 11 (KI-49), section 13 (the Google Drive `files.list` row), the copy rows of section 14, the «Copies» line of the tests of section 15, the `CONTEXT.md`, `PROJECT_CONTEXT.md`, `docs/backups.md` and `KNOWN_ISSUES.md` lines of section 16. Terms — `CONTEXT.md` («Копия базы»). ADRs to read: 0005, 0012 (Drive copies through its API; this ticket stays within the same calls). Standards — rules 2, 7, 9, 11. No fixtures from `answers/`.

## What to do

Work in this order; each step leaves the suite green.

1. **KI-66, writing (10.1).** Every writer takes `datetime.now(timezone.utc)` (naive) and writes `Z` after the time: `tracker_db_20261123_132100Z.db`, `…Z_manual.db`, `…Z_before-0018.db`, `…Z_before-restore.db`, the archive `tracker_db_20261123_132100Z.7z`. Writers: `create_backup`, `create_manual_backup`, `backup_if_due`, `_backup_before_migration` (`create_session_factory`'s `now`), the restore's copy before a restore.
2. **KI-66, reading.** `COPY_NAME`, `ARCHIVE_NAME`, `NAME_TIME` accept an optional `Z` (`backup.copies`, `drive_copies.own_archives`, `restore.phrase_of`). `Copy.moment` is naive UTC: a `Z` name as written; a name without `Z` in the zone of the process (parameter `old_zone`, None — the process's zone, for tests) turned into UTC (`fold=0` at the hour the clocks go back). Rotation, the daily due check and «already in Drive» compare in UTC; old and new names mix in one order.
3. **KI-66, showing.** `backup_rows.copies_block`, the notice after «Сделать копию сейчас» and the reason «copy not made» (`backups`) turn the moment into the zone of Settings before `moment_in_words`, as the Google Drive line already does. The restore (`app.utils.restore`: `list`, `check`, `apply`) reads the zone of Settings from the base being replaced (`settings` row `time_zone`, read-only; missing, unreadable or not a zone — the process's zone), shows every copy in it, and `now` is that zone's wall clock. The `moment_words` docstring about KI-66 goes.
4. **KI-67 (10.2).** `google_drive._files` follows `nextPageToken` (`fields=nextPageToken,files(id,name,size,createdTime)`, `pageToken`) until none, at most 50 pages, then a warning and works with what it has; `list_folder` and `find_folder` both go through it.
5. **KI-68 (10.3).** `DriveCopies._upload`: once the archive is in the folder (sent now, or found with its name and size), every other file of that name is deleted for good (`delete`), each failure a warning; the count of kept archives does not include what was deleted.
6. **KI-69 (10.4).** `restore.OLDER` = «Копия от более старой версии: при запуске база обновится сама.»; the line «Нынешняя база сохранена: data\backups\…» after «да» stays.
7. **KI-49 (11), the code side.** `.env.example` lists every variable the code reads (the `Settings` fields by their names, plus `WEB_PORT`, `WEB_HOST`, `PUID`, `PGID` of `docker compose` and `app/container_start.py`) and gets `SHIKIMORI_BASE_URL` and `SHIKIMORI_USER_AGENT`, commented out with their defaults and one line each. A test reads `Settings.model_fields` and the names `docker-compose.yml` and `container_start` read, and fails when `.env.example` misses one or names one nobody reads.
8. **KI-49, the owner's `.env` (11) — the session does it on the owner's PC.** A small script (not kept in the repo; run from the scratchpad) matches the name before `=` and removes the lines of `KINOPUB_ACCESS_TOKEN`, `PS_STORE_REGION`, `SHIKIMORI_CLIENT_ID`, `SHIKIMORI_CLIENT_SECRET`, `psn_api_key`, `rawg_api_key`; it prints only the names it removed and the count, never a value; comments and the other lines stay byte for byte (read and write as bytes; keep the line endings); no copy of `.env` is made. Then `.\start-bot.ps1` checks the file as usual. The `.env` is not in git, so this step leaves no commit.
9. **Docs.** `docs/backups.md`: the names of the table say the time is UTC («время в UTC»), old names the clock of the PC; `CONTEXT.md` «Копия базы»: UTC with `Z`, names before 9.1d the container's clock, shown in the zone of Settings; `PROJECT_CONTEXT.md` Gotcha: copy names in UTC with `Z`; `tools\code_map.py`; `docs/tests-map.md`; `KNOWN_ISSUES.md`: KI-49, KI-66, KI-67, KI-68, KI-69 → `fixed (test: …)` (entry and index).

## Done when

- [ ] A new copy of every kind has a `Z` name; the Drive archive too; old and new names mix in one rotation, in one correct order.
- [ ] An old name is read in `old_zone` and turned to UTC; at the repeated hour of the clock change the earlier moment is taken.
- [ ] The Settings block, the notice after «Сделать копию сейчас», the «copy not made» reason and the restore list show the zone of Settings (a base with `time_zone` set, and one without — then the process's zone).
- [ ] A fake Drive with two pages (1001 files) is listed whole by `list_folder` and `find_folder`; 50 pages stop with a warning.
- [ ] Two files of the archive's name, one of the right size: it counts as sent, the other is deleted; a failed delete is a warning and does not fail the sending.
- [ ] The restore of an older copy says the new `OLDER` text.
- [ ] The `.env.example` test passes and fails when a name is missing or alien.
- [ ] The six names are gone from the owner's `.env`, and the session reports their names and the count (no value); `.\start-bot.ps1` ends with «Готово».
- [ ] pyflakes clean; code map rebuilt; no module over its limit; the full suite green.

## Tests to add

The «Copies» list of section 15: names with `Z` for each writer; old names in a given `old_zone` (and the clock-change hour); mixed rotation; the Settings block, notice and restore list in the zone of Settings (with and without `time_zone`); `phrase_of`; Drive pages (a fake with `nextPageToken`) and the 50-page stop; the same-name delete and its failure; the `OLDER` text; the `.env.example` test; the script that edits `.env` is tried on a made-up file (a test file with fake names and values) before it touches the real one.

## Owner check

The session starts the bot and writes the launch result in one line, and says which six names left `.env` (names and a count only). In the browser, `http://localhost:8080`, tab «Настройки»: the time of each copy is the time of the zone chosen in Settings, and the Google Drive line agrees with it. Press «Сделать копию сейчас»: the notice gives the time of your clock. In `data\backups` there is a new file with `Z` in its name (the session shows the folder listing). «Не так»: a copy time that differs from your clock by hours, an error in `.\logs-bot.ps1`, the bot does not start after the `.env` change.
