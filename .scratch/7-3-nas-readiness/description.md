# Stage 7.3: NAS readiness and the move guide

Status: accepted

Terms come from `CONTEXT.md`. The stage is the last part of stage 7 (`docs/project-spec.md`). ADRs it leans on: 0001 (one instance), 0005 (SQLite with WAL), 0006 (Docker on the PC until the NAS), 0007 (one process), 0012 (Drive copies with the owner's client, the sign-in returns to `localhost`), 0013 (outside access by the owner's domain; the move is the NAS project's), 0015 (the health check ends a hung app). `docs/outside-access.md` (stage 7.2) already says what the app needs behind a domain; this stage does not repeat it, the guide points to it.

## Goal

The owner moves the app to a UGREEN DXP2800 (Intel N100, NVMe SSD, 3 TB HDD) in a separate Claude Code project, the one that sets up the NAS for two apps (ADR 0013). This project does not move anything and does not touch the NAS (the owner's wish, 2026-11-24). It makes the app ready to run there without PowerShell, and writes one guide for the agent of the NAS project: what to move, where, in what order, every problem that can come up with its solution, and what to report back. The NAS project's report then lets the sessions of this project go on with the app on the NAS.

## What the owner will see at the end

- **A guide `docs/nas-move.md`**, for the agent of the NAS project (English, like `docs/outside-access.md`; that agent speaks Russian to the owner). The owner gives it to the NAS project; nothing else needs explaining there. It holds:
  - what the app is in one paragraph and where its code lives (this repository, `kukilvan/Telegram-bot`; stage 8 will change the address);
  - **what moves**: `data` whole (the database with its `-wal` and `-shm`, `backups`, `logs`, `web_secret`, `web_login.json`, the Google Drive files), `.env`, the code with `docker-compose.yml`; what stays on the PC;
  - **where**: the database on a local SSD volume, never on a network share; the copies may go to a folder on the HDD;
  - **in what order**: stop the bot on the PC, copy, change `.env` for the NAS, build and start, the checks; **one instance only** — the bot on the PC is never started again; the way back to the PC if the NAS start fails;
  - **start, stop, logs and restore by `docker compose`**, no PowerShell; what `.\start-bot.ps1` checks on the PC as a checklist done by hand;
  - **the changes of `.env`** for the NAS (`APP_URL`, `WEB_HOST`, `WEB_PORT`, `TRUSTED_PROXIES`, `PUID`/`PGID`, `BOT_TIMEZONE`), pointing to `docs/outside-access.md` for the domain part;
  - **the checks after the move**: health, the log, a message in Telegram, the web by the home address and by the domain, a copy made, the Google Drive copy;
  - **every known problem with its solution** (the list is below, the spec completes it);
  - **«Report back»**: what the NAS project returns to this project when the move is done (decision 2).
- **The restore on the NAS by three commands** (KI-70, decision 5): stop the bot, run the restore (it asks the number of the copy and «да» in the terminal itself), start the bot. The owner can try the same three commands in PowerShell on the PC. `.\restore-bot.ps1` keeps working on the PC, also with an older Docker Compose.
- **The copies on another disk**: one small file next to `docker-compose.yml`, only on the NAS, puts `data/backups` on the HDD; on the PC nothing changes (decision 4).
- **KI-15**: the container started not as `root` (a `user:` line) no longer asks for `PUID` and `PGID`.

## Problems the guide covers

Each with a solution; the spec checks those that can be checked on the PC and completes the list.

1. **Two instances.** The PC and the NAS with the same bot token take each other's Telegram updates, and the two databases drift apart. The guide's order stops the PC first and copies only after; the PC bot is never started again (decision 3).
2. **The database on a network share.** SQLite in WAL mode spoils on SMB or NFS: the database lives on a local volume of the NAS; nothing on the PC opens it over the network. `tracker.db`, `-wal` and `-shm` are copied together and only while the bot is stopped.
3. **The owner of `data`.** The app writes as `PUID`/`PGID` (1000 by default); on UGOS the folder's owner can differ: how to find the numbers. KI-15 for a `user:` line.
4. **An older Docker on the NAS.** `--quiet-build` of the restore (KI-70) and `--start-interval` of the `HEALTHCHECK` (Docker Engine 25+) may be unknown; `init: true` is needed by ADR 0015 — a Docker GUI of UGOS that drops it would break the health check's end of a hung app.
5. **`.env` written on Windows.** The `$` sign stays forbidden (`docker compose` substitutes it); what a byte-order mark or Windows line endings do to it.
6. **A busy port.** The other app of the NAS may take 8080: `WEB_PORT`.
7. **The tunnel reaching the app.** `cloudflared` on the same Docker network or by the NAS address; the `Host` header and `TRUSTED_PROXIES` (`docs/outside-access.md`, points 2 and 3).
8. **The Google Drive sign-in returns to `localhost`** (ADR 0012), and the NAS has no browser. Connect on the PC before the move (the connection moves with `data`); to connect again on the NAS later — an SSH tunnel from the PC.
9. **The HDD never sleeps.** The hourly job looks at the copies; with the copies on the HDD that may wake the disk every hour.
10. **Old copy names without `Z`** are read in the zone of the process: the same `BOT_TIMEZONE` on the NAS keeps them right.
11. **Getting the code**: a clone of this repository (if it is private — a read-only key or token) or a copy from the PC; the image is built on the NAS (the same `amd64`), which needs the internet for `pip`.
12. **The NAS restarts or updates**: `restart: unless-stopped` brings the app back once Docker of UGOS starts by itself.

## In scope · out of scope

- In scope: the guide `docs/nas-move.md`; the restore without PowerShell (an asking mode of `app.utils.restore` run by `docker compose`); KI-70; KI-15; the copies on another folder or disk by a NAS-only compose file; the image built and run by an older Docker where the fix is small; checks of all of it on the PC.
- Out of scope: the move itself, the domain, the tunnel, Cloudflare Access, setting up the NAS and its SSH (the NAS project, ADR 0013); a guard in the code against two instances (decision 3); shell scripts for the NAS; an image built elsewhere and pulled (a registry, CI); changing how the app works on the PC beyond KI-70.

## Pulled-in known issues and wishes

- **KI-15** (`app/container_start.py`): `PUID`/`PGID` read only when the container starts as `root`; the refusal to write names the real user of the process.
- **KI-70** (`restore-bot.ps1`): the image built by its own `docker compose build`, the restore run without `--build --quiet-build`.
- The other open entries (KI-78–89) belong to 9.2. The wishes of review 9.1d are for 9.2 and 8; none fits here.

## Decisions taken with the owner

1. **This project prepares, the NAS project moves** (2026-11-24). Nothing here runs on the NAS, the checks of this stage run on the PC; the guide names every problem it can foresee with a solution, so the NAS project needs no answer from here during the move.
2. **The guide asks for a report back** (2026-11-24). At the end of the move the NAS project writes for this project, without secret values: the NAS (model, UGOS version, disks and volumes), Docker Engine and Compose versions, what else runs there and on which ports; for this app — the folders of the code, of `data` and of the copies, the compose files used, `PUID`/`PGID`, the container and its Docker network, the `cloudflared` side (`TRUSTED_PROXIES`, the domain in `APP_URL`), `WEB_HOST`/`WEB_PORT`, the time zone; how the code gets there and is updated; the exact commands to start, stop, read the log and restore; how to reach the NAS from the PC by SSH (host, user, key file — the command, never the key); whether Google Drive is connected; the results of every check; the problems met and what was done; what was left on the PC. The owner brings the report here.
3. **Two instances: only the rule in the guide** (2026-11-24, the owner's choice; no code guard). The guide puts it in the order of the move and in the checks; after the move `CLAUDE.md` and `docs/workflow.md` no longer start the bot on the PC (decision 6).
4. **The copies may live on the HDD.** The database stays on the SSD in `data`; `data/backups` is mounted from the HDD by a compose file only the NAS has (a dead SSD then leaves the copies, besides Google Drive). The PC keeps one folder.
5. **The restore on the NAS is three `docker compose` commands**, the middle one asks for the copy and «да» itself, so no script and no PowerShell are needed; it refuses to replace the base while the bot runs.
6. **After the move the sessions of this project check on the NAS** (2026-11-24): the session sends its branch to the NAS by SSH and restarts the bot there; the owner checks as now; the PC runs tests only. This is written into `docs/workflow.md`, `CLAUDE.md` and `PROJECT_CONTEXT.md` by one session **«Приём переезда» (stage 7.4)** after the NAS project's report, before 9.2: it reads the report, records the NAS in «Environment», changes «Run» and «Session on the owner's PC», and checks the SSH access, the health and the log on the NAS.

## Open questions for the spec

- Whether `--start-interval` stays in the `Dockerfile` (and the guide says Docker 25+) or goes (the first health answer then waits up to 30 s); what Docker Engine and Compose versions the app needs at least.
- How the asking restore knows the bot is running (it runs in a one-off container beside the stopped or running one) — or the guide's order is the only guard.
- The NAS-only compose file: `docker-compose.override.yml` (read by `docker compose` by itself, kept out of git) or a named file passed by `-f`; whether the hourly job can see the newest copy without listing the HDD folder (problem 9).
- Whether every write between `data` and `data/backups` works when they are two disks (the restore already copies into `data` before its rename; the copies and the copy before an update — to check).
- What `.env` with a byte-order mark or Windows line endings does under `docker compose` (problem 5).
- The repository private or public, and so how the NAS project gets the code.
- How the session of decision 6 sends a branch to the NAS: `git` on the NAS, or an archive from the PC by SSH — settled by stage 7.4 from the report.

Sessions (est.): spec 1, slicing 1, about 3 tickets (restore and KI-70, KI-15 and the other disk and Docker versions, the guide), review 1; then «Приём переезда» (7.4) 1.
