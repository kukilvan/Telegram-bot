# Moving the app to the NAS

For the agent of the NAS project (it speaks Russian to the owner; this file is English). The owner hands it over as it is. The move is yours; this repository only made the app ready for it (stage 7.3) and does nothing on the NAS. Domain, Cloudflare Tunnel and Cloudflare Access: `docs/outside-access.md` (read it too, it is short). Copies, Google Drive, restore: `docs/backups.md`.

Placeholders: `<app folder>` — the clone with `.env` and `data`, on a local SSD volume; `<copies folder>` — a folder on the HDD (optional); `<NAS>` — its address; `<port>` — `WEB_PORT`. Every `docker compose` command runs inside `<app folder>`. Never print a value of `.env`, a token or a password: not in the chat, not in the report.

## 1. What the app is

A personal tracker of movies, series, anime and games for one owner: the Telegram bot and the web app are **one Python process** in one Docker container (service `tracker`), the database is SQLite in WAL mode, the file `data/tracker.db`. One bot token means **one instance**: two running apps with the same token take each other's Telegram updates and their databases drift apart. Code: `https://github.com/kukilvan/Telegram-bot`, branch `master` (public, so a plain `git clone` over `https` needs no key; a later stage moves the code to a new repository and the owner will say so). Do not edit files of the clone: local settings live only in `.env` and `docker-compose.override.yml` (both out of git), so `git pull` always works.

## 2. What moves and what stays

Moves: the whole `data` folder (`tracker.db` with `tracker.db-wal` and `tracker.db-shm` if present, `backups`, `logs`, `web_secret`, `web_login.json`, `google_drive_token.json`, `google_drive_state.json`, the rest as it is) and `.env`. The code comes from git, not from the PC.

Stays on the PC: `.venv`, the Docker image, and the PC's own `data` and `.env`, untouched — they are the way back (step 9 of section 5), and this project's tests still run on the PC.

## 3. Where

`data` lies on a **local volume of the NAS (the SSD)**: never on an SMB or NFS share, never opened from the PC over the network (SQLite in WAL mode is spoiled by network file systems, ADR 0005). Copying the files over the network while the bot is stopped is fine; *opening* the database there is not. The copies (`data/backups`) may go to `<copies folder>` on the HDD (section 5, step 6); the database stays on the SSD.

## 4. Before the move, on the PC

1. Google Drive copy: if the owner wants it, connect it in Settings on the PC first (the sign-in returns to `localhost`, ADR 0012; the connection moves with `data`). `BACKUP_PASSWORD` and the two `GOOGLE_DRIVE_*` lines are in `.env` and move with it.
2. Settings → «Сделать копию сейчас».
3. On the NAS: `docker version` (Engine 23 or newer), `docker compose version` (v2, the `docker compose` command, not `docker-compose`), free space (about 1 GB for the image), the port free (`ss -ltn`, default 8080). If the NAS user is not in the `docker` group, every `docker` command here takes `sudo`.

## 5. The order of the move

1. On the NAS: `git clone https://github.com/kukilvan/Telegram-bot.git <app folder>`.
2. **Stop the bot on the PC.** PowerShell in `E:\LocalAI\Bionic\Telegram-bot`: `.\stop-bot.ps1`; `docker compose ps` shows nothing. From now on the PC bot is **never started again** (problem 1).
3. Copy `data` and `.env` from the PC to `<app folder>`. In PowerShell on the PC: `cd E:\LocalAI\Bionic\Telegram-bot`, then `scp -r data .env <user>@<NAS>:<app folder>/` (or put the same files there through the NAS's share). `tracker.db`, `-wal` and `-shm` go together, and only while the bot is stopped (step 2). With the copies on the HDD: `mv <app folder>/data/backups/* <copies folder>/` (the folder `data/backups` stays, empty).
4. `.env` for the NAS, in `<app folder>`: no byte-order mark and no `\r` — `sed -i '1s/^\xEF\xBB\xBF//; s/\r$//' .env`; no `$` in a value (`docker compose` substitutes it) — `grep -nv '^[[:space:]]*#' .env | grep '\$' | cut -d= -f1` must print nothing (it shows only the line number and the name); `chmod 600 .env`; then the values of section 6.
5. The owner of `data`: `stat -c '%u %g' data` prints two numbers; put them in `.env` as `PUID=` and `PGID=` (problem 3).
6. Copies on the HDD only: `cp docker-compose.override.example.yml docker-compose.override.yml` and write `<copies folder>` before `:/app/data/backups` (the file says where).
7. `docker compose up -d --build`. Wait until `docker inspect --format '{{.State.Health.Status}}' $(docker compose ps -q tracker)` prints `healthy` (up to 2 minutes; problem 4 for an older Docker).
8. The checks of section 8.
9. **The way back**, if the NAS does not work and cannot be fixed now: `docker compose down` on the NAS; if the NAS bot ever ran, copy its `data` back to the PC first (it is newer than the PC's); then `.\start-bot.ps1` on the PC. Never both at once.

## 6. `.env` for the NAS

All names are in `.env.example` with comments. What changes:

| Name | Value |
|---|---|
| `APP_URL` | `https://tracker.<domain>` once the tunnel works; until then empty or `http://<NAS LAN address>:<port>`. Not `localhost` (Telegram refuses it) |
| `WEB_HOST` | `127.0.0.1` (default) when `cloudflared` reaches the app over a Docker network; `0.0.0.0` for the home network or for a `cloudflared` that reaches the NAS address (then plain `http` is open to the whole LAN) |
| `WEB_PORT` | another free port if 8080 is taken (problem 6) |
| `TRUSTED_PROXIES` | the `cloudflared` address or its Docker network, `docs/outside-access.md` point 3 |
| `PUID`, `PGID` | the owner of `data` (step 5) |
| `BOT_TIMEZONE` | the same as on the PC (problem 10) |

`APP_URL` and the rest are read once at start: `docker compose up -d` again after a change.

## 7. Start, stop, log, restore, update

In `<app folder>`:

- start or rebuild: `docker compose up -d --build`; stop: `docker compose stop`;
- log: `docker compose logs --tail 50 tracker`, and the file `data/logs/bot.log`;
- update: `git pull`, then `docker compose up -d --build`; migrations run by themselves, a copy of the database is made first;
- **restore**, three commands (the middle one lists the copies of `data/backups`, asks the number and «да» itself, and refuses while the bot runs):

```
docker compose stop
docker compose run --rm tracker python -m app.container_start app.utils.restore
docker compose up -d
```

A downloaded Google Drive archive or a `.db`: put it into `data/restore/` (the container sees only `data`), give its path to the middle command (`.7z` needs `BACKUP_PASSWORD` in `.env`), and delete the file afterwards:

```
docker compose run --rm tracker python -m app.container_start app.utils.restore data/restore/<file>
```

Answers may be piped (`printf '1\nда\n' | docker compose run --rm -T tracker …`). Details and texts: `docs/backups.md`, «Without PowerShell (the NAS)». If the middle command says «Бот работает…» after a pause of several seconds while `docker compose ps` shows no running `tracker`, the NAS's name service did not answer (no internet or router, KI-92): restore once the network is back.

What `.\start-bot.ps1` checks on the PC, to do by hand: `.env` exists and has no `$`; nothing else runs this bot; the build passed; health is `healthy`; the log has no `токен бота неверного вида` (the web works even then, the bot does not).

## 8. The checks after the move

| Check | Right | Wrong |
|---|---|---|
| `curl -s http://localhost:<port>/health` on the NAS | `{"status":"ok"}` | `503` with `fail` and the failed parts, or no answer |
| `docker compose logs --tail 50 tracker`, 15 seconds, then a minute | no `Traceback`; within a minute `Job "Tracker.poll_due …" executed successfully` | red text, `polling title … failed` before the job line |
| Telegram (the owner): `/start`, then «📋 Сводка сейчас» | both answer | silence: the bot is not connected (token, or a second instance) |
| The web by the home address (`WEB_HOST=0.0.0.0`) and by `https://tracker.<domain>` | login with `WEB_PASSWORD`; the list holds the titles of the PC | `Неизвестный адрес сайта.` (problem 7); a login that never takes |
| Settings → «Сделать копию сейчас», then `ls -l <copies folder>` (or `data/backups`) | a new `tracker_db_…_manual.db` | no file; a message in Telegram about a failed copy |
| Google Drive (if connected) | Settings shows the copy sent | «Google Drive не принял вход…» (problem 8) |
| **The restore rehearsed**: the three commands, Enter at the number | `Отменено. Ничего не изменено.`; the bot comes back with `docker compose up -d` | `Бот работает, а базу можно заменить…` — the first command was skipped |
| After a restart of the NAS: the app is back by itself; `df <copies folder>` shows the HDD | health `healthy`, the HDD's device | the container stays down (problem 12); the system disk (problem 13) |

## 9. Problems and solutions

Symptom → cause → what to do.

1. **Telegram updates go missing, or the list differs between the PC and the NAS** → two instances with one token → stop the PC bot (`.\stop-bot.ps1`), never start it again. If both ran, the newer database wins: copy it and keep the other as the way back.
2. **The database is corrupt or «database is locked»** → `data` is on a network share, or the three files were not copied together → move `data` to the SSD; copy `tracker.db`, `-wal`, `-shm` together with the bot stopped; restore the PC's copy from `data/backups` if needed (section 7).
3. **Log: `Нет прав на запись в папку /app/data (её владелец N:M, приложение работает как …). На NAS задайте в .env PUID и PGID…`** → the volume refuses `chown`, or `PUID`/`PGID` differ from the folder's owner → set them to `stat -c '%u %g' data`. With a `user:` line in a compose file the text names that line; remove the line or own the folder. `PUID` 0 prints a root warning: allowed, not wanted.
4. **`--start-interval` unknown, build or health odd** → older Docker. The `Dockerfile` has the `# syntax=docker/dockerfile:1` line, so Engine 23+ builds; Engine below 25 ignores the interval and the first `healthy` comes after 30 s (nothing to do); below 23 use `DOCKER_BUILDKIT=1 docker compose up -d --build`. `init: true` of `docker-compose.yml` is needed (ADR 0015: the health check ends a hung app).
5. **`$` or a byte-order mark or `\r` in `.env`** → values read wrong, or every `docker compose` command fails → step 4 of section 5. Newer Compose forgives a mark and `\r`; older may not.
6. **`port is already allocated` or `address already in use`** → the other app takes 8080 → `WEB_PORT=<free port>` in `.env`, `docker compose up -d` again.
7. **The domain answers `Неизвестный адрес сайта.` or the real client address is missing** → `cloudflared` changed the `Host`, or `TRUSTED_PROXIES` lacks its address → `docs/outside-access.md`, points 2 and 3.
8. **Google Drive sign-in on the NAS** (the NAS has no browser; the return goes to `localhost`) → connect on the PC before the move. Later, from the PC: `ssh -L 8080:127.0.0.1:<port> <user>@<NAS>`, then `http://localhost:8080` in the PC's browser, login, Settings → «Подключить Google Drive». Drop the tunnel afterwards.
9. **The HDD never sleeps** → the hourly job lists `data/backups`, which may wake a sleeping disk (KI-90) → report whether the tracker wakes it (UGOS shows the disk's sleep). If it does: delete `docker-compose.override.yml` and `docker compose up -d` (the copies go back to the SSD).
10. **Times of old copies are an hour or more off** → names without `Z` (older than stage 9.1d) are read in the zone of the process → the same `BOT_TIMEZONE` as on the PC.
11. **No code or no image** → public repo: `git clone` by `https`; or copy the folder from the PC. The image is built on the NAS (`amd64`), which needs the internet for `pip`, the base image and the Dockerfile frontend.
12. **After a restart of the NAS the app is down** → `restart: unless-stopped` brings it back only if Docker itself starts by itself and the container was not stopped by hand → enable Docker's autostart in UGOS; `docker compose up -d`.
13. **The HDD was not mounted when the container started** → Docker created the folder on the system disk and the copies land there (KI-91) → after a restart check `df <copies folder>`; when the HDD is back, `docker compose stop`, move what landed on the system disk into the HDD folder, `docker compose up -d`.
14. **A Docker GUI of UGOS imports or edits the project and drops `init: true` or `stop_grace_period`** → run the app by `docker compose` over SSH; if the GUI's project feature is used, it points to this `docker-compose.yml` unchanged.
15. **`docker compose` says «no configuration file provided»** → the command ran outside `<app folder>` → `cd <app folder>` first. The container's name comes from the folder's name (the PC's is `telegram-bot-tracker-1`); nothing depends on it.
16. **`cloudflared` lives in another compose project** → join its network in `docker-compose.override.yml` (`networks:` with `external: true`) and put that network in `TRUSTED_PROXIES`.
17. **Wrong time: Telegram or the Google sign-in refuse, copy names look off** → the NAS clock → NTP on in UGOS. The app's zone is `BOT_TIMEZONE`, not the NAS's.
18. **`git pull` refuses** → local edits in the clone → `git status` must be clean; settings only in `.env` and the override file.

## 10. Report back

Copy this template to `nas-report.md`, fill every heading, bring the file to the owner (stage 7.4 reads it). **No secret values anywhere**: no token, password, key or key file contents; for SSH only the command.

```markdown
# Report on the move

## The NAS
Model, UGOS version, disks and volumes (SSD, HDD), what else runs there and on which ports:

## Docker
Engine version, Compose version:

## Folders
<app folder>, data, <copies folder> (or: on the SSD):

## Compose files used
docker-compose.yml, docker-compose.override.yml (or: none):

## PUID and PGID
The numbers, and whose they are:

## Container and network
Container name, Docker network:

## cloudflared and the domain
Where it runs, TRUSTED_PROXIES, the domain in APP_URL:

## WEB_HOST and WEB_PORT

## Time zone
BOT_TIMEZONE and the NAS clock (NTP):

## Getting and updating the code
How the code gets there and how it is updated:

## Commands
Start, stop, read the log, restore (exact):

## SSH from the PC
The command (user, host, port, key file name; never the key):

## Google Drive
Connected or not:

## Checks of section 8
health:
log (the poll_due line):
Telegram /start and «Сводка сейчас»:
web by the home address and by the domain:
a manual copy in the copies folder:
Google Drive copy:
restore rehearsed:
restart of the NAS (app back by itself, df of the copies folder):

## The HDD's sleep
Does the tracker wake it (KI-90)?

## Problems met
What happened and what was done (numbers of section 9):

## Left on the PC
What stays there, and that the PC bot is stopped for good:
```
