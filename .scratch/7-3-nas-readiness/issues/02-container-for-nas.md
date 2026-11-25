# 02: The container ready for the NAS — a start not as `root`, the `# syntax` line, the copies on another disk — KI-15

Status: accepted
Complexity: simple (one function branch, one Dockerfile line, one example file, one ignore line; one live check)
Blocked by: —

Spec: `../spec.md`, section 1 (facts 4 and 5), section 3 (3.1 KI-15, 3.2 an older Docker, 3.3 the copies on another disk), the rows of section 5 about `user:`, the HDD and Engine < 25, the `container_start` and `docker files` lines of the tests of section 6, and the `CONTEXT.md` «Копия базы», `docs/backups.md` (the table of copies) and `KNOWN_ISSUES.md` (KI-15, KI-90, KI-91) lines of section 7. Terms — `CONTEXT.md` («Копия базы»). ADRs to read: 0005, 0007, 0015. Standards — `docs/coding-standards.md`, the rules on modules and tests.

## What to do

1. **KI-15 (3.1).** `app/container_start.py`, `start`: as `root` — as now; not as `root` — `PUID` and `PGID` are not read (garbage there is no error), the identity is `os.getuid()`, `os.getgid()`, no warning, no hand-over of rights. The refusal to write names the real user: not as `root` the new text of 3.1; as `root` the text stays. Module docstring updated.
2. **The `# syntax` line (3.2).** `Dockerfile` gets the first line `# syntax=docker/dockerfile:1`. `HEALTHCHECK` stays as it is.
3. **The override example (3.3).** New file `docker-compose.override.example.yml` with the text of 3.3; `.gitignore` gets `docker-compose.override.yml`; `docker-compose.yml` is not changed. `container_start` hands the rights over on the folder mounted in `data/backups` too if it walks `data` already (check; if it does not follow a mount, make it so), its write check stays on `data` and `data/logs`.
4. **Live check (spec section 6, the PC).** The session puts a `docker-compose.override.yml` on the PC that mounts a folder on drive C over `/app/data/backups`, starts the bot: a manual and the daily copy land in that folder, the asking restore (ticket 01) lists them, the Google Drive copy is sent if connected; checks that nothing renames across the two disks (the spec's fact 4: a copy, its rotation and a restore with a second folder); then removes the override and the folder and starts the bot as before. The result goes into the ticket's closing note in one line.
5. **Docs and issues.** `docs/backups.md`: the table of copies says the folder may be on another disk (`docker-compose.override.yml`, the example file). `CONTEXT.md` «Копия базы»: `data/backups` may be another disk. `tools\code_map.py` (the non-Python list takes `docker-compose.override.example.yml` if the tool lists such files); `docs/tests-map.md`; `KNOWN_ISSUES.md`: KI-15 → `fixed (test: …)` (entry and index). KI-90 and KI-91 are already recorded by the spec session: check they are in the index, add what is missing.

## Done when

- [ ] Not as `root`, `PUID=abc` does not stop the start, the identity comes from `getuid` and `getgid`, no warning; as `root` nothing changes.
- [ ] An unwritable `data` with a `user:` line gives the new refusal with the real `uid:gid`, exit 1; as `root` the old text.
- [ ] The `Dockerfile` starts with `# syntax=docker/dockerfile:1` and the image builds on the PC (`.\start-bot.ps1` ends with «Готово»).
- [ ] With the override on drive C a manual copy and the daily copy land there, the Settings list shows them, rotation and restore work; with the override removed the bot runs as before and `git status` shows no `docker-compose.override.yml`.
- [ ] `docker-compose.yml` is unchanged; `docker-compose.override.example.yml` mounts only `/app/data/backups`.
- [ ] pyflakes clean; the code map rebuilt; the full suite green (the known Windows failures do not count).

## Tests to add

`tests/test_container_start.py`: not root — `PUID=abc` ignored, identity from `getuid` and `getgid`, no warning, the refusal names the user with the new text; root — unchanged. `tests/test_docker_files.py`: the `Dockerfile` starts with the `# syntax` line; `docker-compose.override.example.yml` mounts only `/app/data/backups`; `.gitignore` has `docker-compose.override.yml`; `docker-compose.yml` still mounts only `./data`.

## Owner check

The session has run the live check above and writes the result in one line, then the launch result of the normal bot in one line. The owner opens `http://localhost:8080`, tab «Настройки», presses «Сделать копию сейчас» — a new copy appears in the list. «Не так»: the bot does not start, a red text in `.\logs-bot.ps1`, the copy does not appear. What only the NAS can show (an older Docker, the HDD, UGOS) is checked by the NAS project and comes back in its report.
