# Spec 7.3: NAS readiness and the move guide

Status: accepted

From `description.md` (accepted 2026-11-24). Terms of `CONTEXT.md`. ADRs: 0001, 0005, 0006, 0007, 0012, 0013, 0015. Nothing here runs on the NAS: every check of this stage runs on the PC (decision 1).

## 1. Facts checked on the PC (2026-11-24)

| # | Question of the description | What was run | Answer |
|---|---|---|---|
| 1 | How the restore in a one-off container knows the bot runs | `docker compose run --rm --no-deps -T tracker python -c …` with the bot running, then after `.\stop-bot.ps1` | Running: the name `tracker` resolves to the bot's container only (`172.18.0.2`; the one-off is `172.18.0.3` and has no such alias), a TCP connection to `tracker:8080` succeeds; `GET /health` by that name answers `400` (the host check, KI-12). Stopped: `socket.gaierror [Errno -2] Name or service not known`. |
| 2 | `.env` with a byte-order mark and Windows line endings | `docker compose config` (Compose v5.4.0) on a file with a BOM, `\r\n` and a trailing space | All values read right: the BOM and `\r` are dropped, the trailing space too. The owner's `.env` has no BOM and Windows line endings. Older Compose versions are not known to be as kind: the guide asks for UTF-8 without a BOM and `\n` and gives the command that makes it so. |
| 3 | Repository private or public | `gh repo view` | `kukilvan/Telegram-bot` is **public**: the NAS clones it by `https`, no key or token. |
| 4 | Writes between `data` and `data/backups` on two disks | read the code | Every write into `data/backups` makes a new file with SQLite's online backup (`db.copy_database`: the daily, manual, before-update and before-restore copies) or deletes one (rotation); the Google Drive archive is made and deleted in `data/backups/upload/`, on the same disk as the copies. Every `os.replace` stays inside one folder (`tracker.db.restoring` → `tracker.db` in `data`; the Drive token, `web_login.json`, the sessions in `data`; the health count in `/tmp`). An archive is opened in the container's `/tmp`. **Nothing renames across the two disks.** Ticket 02 checks it live with a second folder. |
| 5 | Versions | `docker version`, `docker compose version` | PC: Docker Engine 29.7.2 (API 1.55), Compose v5.4.0. `data` is 39 MB (copies 18 MB, logs 15 MB). |

## 2. The restore without PowerShell (decision 5, KI-70)

### 2.1 Three commands

In the app folder (where `docker-compose.yml` is), on the NAS by SSH or in PowerShell on the PC:

```
docker compose stop
docker compose run --rm tracker python -m app.container_start app.utils.restore
docker compose up -d
```

The middle command is the **asking restore**: `app.utils.restore` with no arguments. With one argument that is not a command (`list`, `check`, `apply`) it is the path of a file to restore, seen from the container: `docker compose run --rm tracker python -m app.container_start app.utils.restore data/restore/<file>`. The commands `list`, `check <path>`, `apply <path>` of `restore-bot.ps1` stay as they are. The image is the one already built (no `--build`): the version that ran the bot checks the copy against its own migrations.

The command line is one constant of `app/utils/restore.py` (`RESTORE_COMMAND`), used by its texts; `docs/backups.md` and `docs/nas-move.md` quote it, and a test checks that they quote it exactly.

### 2.2 The asking restore, step by step

1. **Is the bot running?** (2.4). Running or unknown → the refusal text, exit 1, nothing read or asked.
2. **No path given:** the list of the copies of `data/backups`, as `list` makes it, without the `@` lines (header, then `  1) сегодня в 07:58 — сделана вручную`, …). No copies → `NO_COPIES_ASKING`, exit 0. The folder unreadable → `UNREADABLE`, exit 1.
3. The prompt `Номер копии (Enter — отмена): `. Empty → `Отменено. Ничего не изменено.`, exit 0. Not a number of the list → `Нет копии с номером <answer>.` and the prompt again. The end of input → as empty.
4. **The copy checked** (`check`): its lines (`Копия … в порядке, тайтлов в ней: N.`, and `Копия от более старой версии…` when it is older). A refusal (damaged, not a tracker, newer, no password, wrong password) → its text, exit 1.
5. The question `Вернуть базу к копии <phrase>? Всё, что изменилось позже, пропадёт. Нынешняя база сохранится отдельно. (да/нет): `. Anything but `да` (case and spaces ignored) or the end of input → `Отменено. Ничего не изменено.`, exit 0.
6. **Is the bot running?** again, just before the change (the owner may have started it meanwhile). Running → the refusal text, exit 1.
7. `apply`: its lines (`Нынешняя база сохранена: data/backups/<name>`, `База восстановлена из копии <phrase>.`), then `Готово. Запустите бота: docker compose up -d`, exit 0. A failure → its line (`Не удалось … База не тронута.`), then `Запустите бота на прежней базе: docker compose up -d`, exit 1.

`Ctrl+C` at a prompt → `Отменено. Ничего не изменено.`, exit 1. During `apply` it is what it is today: the copy before a restore is made first, a broken `.restoring` is removed, the base is replaced only by the last `os.replace`.

The answers are read from standard input line by line, so the restore works both at a terminal and with the answers piped (`-T`, for an agent): `printf '1\nда\n' | docker compose run --rm -T tracker python -m app.container_start app.utils.restore`. Input that is not UTF-8 is read with replacement characters (no crash; the answer then is not `да`).

### 2.3 Texts

| Constant | Text |
|---|---|
| `HEADER` (changed: `/`) | `Копии базы в data/backups (новые сверху):` |
| `UNREADABLE` (changed) | `Папку data/backups не прочитать ({reason}). Ничего не изменено.` |
| `SAVED` (changed) | `Нынешняя база сохранена: data/backups/{name}` |
| `NO_COPIES` (script, stays) | `В data\backups нет копий базы. Восстановить можно из скачанной копии: .\restore-bot.ps1 "путь к файлу"` |
| `NO_COPIES_ASKING` | `В data/backups нет копий базы. Восстановить можно из скачанной копии: положите файл .7z или .db в папку data/restore и запустите: {RESTORE_COMMAND} data/restore/<имя файла>` |
| `NUMBER_PROMPT` | `Номер копии (Enter — отмена): ` |
| `NO_SUCH_COPY` | `Нет копии с номером {answer}.` |
| `CANCELLED` | `Отменено. Ничего не изменено.` |
| `QUESTION` | `Вернуть базу к копии {phrase}? Всё, что изменилось позже, пропадёт. Нынешняя база сохранится отдельно. (да/нет): ` |
| `BOT_RUNNING` | `Бот работает, а базу можно заменить только у остановленного. Остановите его: docker compose stop — и запустите восстановление снова. Ничего не изменено.` |
| `START_NOW` | `Готово. Запустите бота: docker compose up -d` |
| `START_OLD` | `Запустите бота на прежней базе: docker compose up -d` |

`HEADER`, `UNREADABLE` and `SAVED` are shown by `restore-bot.ps1` too: the slash works in PowerShell paths as well; `docs/backups.md` quotes the new form. `USAGE` adds the asking mode: `Команды: без аргументов — спросить копию; <путь> — восстановить файл; list, check <путь>, apply <путь>.`

### 2.4 Is the bot running

`bot_running()` in `app/utils/restore.py`: `socket.getaddrinfo("tracker", 8080)`.
- `gaierror` with `EAI_NONAME` (or `EAI_NODATA` where defined) → **stopped**: a stopped or removed container leaves the network's names.
- The name resolves → **running**, whatever the port says: a container that starts (migrations, before the web listens) is running too.
- Any other error → **unknown**, treated as running (the refusal text).

`tracker` is the service name of `docker-compose.yml` (constant `SERVICE_NAME`, a test checks it against the file). The check runs in the asking restore (steps 1 and 6) and in `apply` of the script (so `restore-bot.ps1` is guarded too: it stops the bot before `apply`). Outside Docker (the tests, the PC's Python) the name never resolves, so the tests give the function as a parameter. The guard is for the same Docker host only; two machines are the guide's rule (decision 3).

### 2.5 `restore-bot.ps1` (KI-70)

- Before the list (or the given file) it builds the image once: `Write-Host "Готовлю образ бота…"`, `docker compose build --quiet` (output kept like `Invoke-Restore` keeps it). A failure → Docker's lines and `Образ бота не собрать — ошибка выше. Ничего не изменено.`, exit 1.
- `Invoke-Restore` runs `docker compose run --rm --no-deps --interactive=false -T tracker python -m app.container_start app.utils.restore @Arguments` — no `--build`, no `--quiet-build`.
- Nothing else changes: texts, questions, stop and start, the `data\restore` folder.

## 3. The container ready for the NAS

### 3.1 KI-15: a container started not as `root`

`app/container_start.py`, `start`:
- As `root` (today's `docker-compose.yml`): as now — `PUID`/`PGID` read (1000 by default), the warning when one is 0, the rights handed over, the user changed.
- Not as `root` (a `user:` line): `PUID` and `PGID` are not read (garbage there is no error); the identity is the process's own (`os.getuid()`, `os.getgid()`); no warning, no hand-over.
- The refusal to write names the real user. Not as `root`: `Нет прав на запись в папку {path} (её владелец {who}, приложение работает как {uid}:{gid} — так задано строкой user: в docker-compose). Сделайте этого пользователя владельцем папки или уберите строку user:`. As `root` the text stays.

### 3.2 An older Docker

- The `Dockerfile` gets the first line `# syntax=docker/dockerfile:1`: BuildKit takes the newest Dockerfile 1.x frontend from Docker Hub, which knows `--start-interval`, so the image builds on an Engine older than 25 (its own frontend may refuse the flag). An Engine before 25 ignores the start interval: the first health answer then comes after 30 s instead of 2 s; nothing else changes. On the PC the build behaves as now (the frontend is fetched once and cached; the app needs the internet anyway).
- `HEALTHCHECK` stays as it is (`--start-interval=2s`: `.\start-bot.ps1` waits for «healthy» and gets it within seconds).
- **Needed at least:** Docker Engine 23 (BuildKit is the default builder) and Docker Compose v2 (the `docker compose` command, not `docker-compose`). With an Engine below 23 the guide builds with `DOCKER_BUILDKIT=1`. `init: true` (ADR 0015) is plain Compose: kept as long as the app is started by `docker compose` from this file (problem 4 of the guide).

### 3.3 The copies on another disk (decision 4)

- A new file **`docker-compose.override.example.yml`** in the repository (Compose does not read it under this name):

```yaml
# Only on the NAS: copy to docker-compose.override.yml (read by docker compose by itself, kept out of git)
# and put the folder of the copies on the HDD. The database stays in ./data on the SSD.
services:
  tracker:
    volumes:
      - /volume2/tracker-backups:/app/data/backups   # <copies folder on the HDD>:/app/data/backups
```

- `.gitignore` gets `docker-compose.override.yml`. On the PC there is no such file and nothing changes.
- Compose merges the volume by its target: `./data` stays mounted at `/app/data`, the HDD folder lies over `/app/data/backups`. The one-off containers of the restore get the same mounts (they are the same service), so the asking restore lists the copies of the HDD.
- `container_start` hands over the rights on the HDD folder too (it walks `data` with what is mounted in it). Its write check stays on `data` and `data/logs`: a copy that cannot be written is the event `backup_failed` and its message, not a bot that does not start.
- If the HDD folder does not exist when the container starts, Docker creates it — on the disk where the path then lies (the system disk, if the HDD is not mounted yet): the copies go there unnoticed until the HDD returns and hides them. Not fixed in code (a missing folder must not stop the bot): **KI-91**, and the guide's check after a NAS restart.
- **The HDD and its sleep (problem 9):** the hourly job lists `data/backups` every hour (the daily copy due, the newest copy for Google Drive). The listing is usually answered from the memory of the system without waking the disk, but not always. No cache in code now: the NAS project reports whether the tracker wakes the HDD (UGOS shows the disk's sleep); if it does, the copies go back to the SSD (delete the override) or 9.2 adds the cache. **KI-90.**

## 4. The guide `docs/nas-move.md`

English, for the agent of the NAS project (that agent speaks Russian to the owner); the owner hands it over as it is. Paths on the NAS are placeholders: `<app folder>` (code, `.env`, `data`; on an SSD volume), `<copies folder>` (on the HDD), `<NAS>` (its address). Sections in this order:

1. **What the app is** — one paragraph: a personal tracker, Telegram bot + web in one Python process in Docker (ADR 0007), SQLite in WAL mode in `data/tracker.db`, one instance per bot token (ADR 0001); code: `https://github.com/kukilvan/Telegram-bot`, branch `master` (public; stage 8 moves it to a new repository and the owner says so). Do not change files of the clone: local settings live only in `.env` and `docker-compose.override.yml` (out of git), so `git pull` always works.
2. **What moves and what stays.** Moves: the whole `data` folder (`tracker.db` with `tracker.db-wal` and `tracker.db-shm` if present, `backups`, `logs`, `web_secret`, `web_login.json`, `google_drive_token.json`, `google_drive_state.json`, and the rest as it is); `.env`. The code comes from git, not from the PC. Stays on the PC: `.venv`, the Docker image, the PC's `data` and `.env` (kept untouched as the way back; the tests of this project still use the PC).
3. **Where.** `data` on a local volume of the NAS (the SSD), **never** on a network share and never opened from the PC over the network (SQLite in WAL mode spoils on SMB/NFS, ADR 0005). The copies may go to `<copies folder>` on the HDD (3.3).
4. **Before the move, on the PC.** Google Drive connected in Settings if the owner wants it (the sign-in returns to `localhost`, ADR 0012; the connection moves with `data`); «Сделать копию сейчас» pressed; the NAS checked: `docker version` (Engine ≥ 23), `docker compose version` (v2), free space (≈ 1 GB for the image), the port free (`ss -ltn`).
5. **The order of the move** — numbered steps, each with its command:
   1. `git clone https://github.com/kukilvan/Telegram-bot.git <app folder>` on the NAS.
   2. **Stop the bot on the PC**: `.\stop-bot.ps1` in `E:\LocalAI\Bionic\Telegram-bot`; `docker compose ps` shows nothing. From now on the PC bot is never started again (problem 1).
   3. Copy `data` and `.env` from the PC into `<app folder>` (`scp -r` from the PC, or through the NAS's share into the folder — the copy may travel over the network, the database is only never *opened* there). `tracker.db`, `-wal`, `-shm` together, only while the bot is stopped. With the copies on the HDD: the content of `data/backups` into `<copies folder>`.
   4. `.env` on the NAS: no BOM and `\n` (`sed -i '1s/^\xEF\xBB\xBF//; s/\r$//' .env`), no `$` (`grep -n '\$' .env | cut -d= -f1` prints nothing; it shows only the line number and the name, never a value), `chmod 600 .env`; the values of section 6.
   5. The owner of `data`: `stat -c '%u %g' <app folder>/data` → `PUID`, `PGID` in `.env` (problem 3).
   6. With the copies on the HDD: `cp docker-compose.override.example.yml docker-compose.override.yml`, put `<copies folder>` in it.
   7. `docker compose up -d --build` in `<app folder>`; wait until `docker inspect --format '{{.State.Health.Status}}' $(docker compose ps -q tracker)` says `healthy` (up to 2 min).
   8. The checks of section 8.
   9. **The way back**, if the NAS does not work and cannot be fixed now: `docker compose down` on the NAS; if the NAS bot ever ran, copy its `data` back to the PC first (it is newer); then `.\start-bot.ps1` on the PC. Never both at once.
6. **`.env` for the NAS.** `APP_URL=https://tracker.<domain>` (once the tunnel works; until then empty or `http://<NAS LAN address>:<port>`), `WEB_HOST` (`127.0.0.1` when `cloudflared` reaches the app over a Docker network; `0.0.0.0` for the home network or a `cloudflared` reaching the NAS address), `WEB_PORT` (another free port if 8080 is taken, problem 6), `TRUSTED_PROXIES`, `PUID`/`PGID`, `BOT_TIMEZONE` the same as on the PC (problem 10). The domain part: `docs/outside-access.md`, points 1–3.
7. **Start, stop, log, restore, update by `docker compose`**, in `<app folder>`: `docker compose up -d --build` · `docker compose stop` · `docker compose logs --tail 50 tracker` (and `data/logs/bot.log`) · the three commands of 2.1 · update: `git pull`, then `docker compose up -d --build` (migrations run by themselves, a copy first). What `.\start-bot.ps1` checks on the PC, as a checklist by hand: `.env` exists and has no `$`; nothing else runs this bot; the build passed; health `healthy`; no `токен бота неверного вида` in the log. A downloaded Google Drive archive is restored from `data/restore/` (the container sees only `data`), then deleted.
8. **The checks after the move**, each with what is right and what is wrong: `curl -s http://localhost:<port>/health` → `{"status":"ok"}`; the log — no `Traceback`, within a minute `Job "Tracker.poll_due …" executed successfully`; Telegram — the owner sends `/start` and gets the answer, «📋 Сводка сейчас» answers; the web by the home address (if `WEB_HOST=0.0.0.0`) and by the domain — login, the list holds the titles of the PC; Settings → «Сделать копию сейчас» → a new file in the folder of the copies (`ls -l <copies folder>`); Google Drive — Settings shows the copy sent; **the restore rehearsed**: the three commands of 2.1, Enter at the number → `Отменено. Ничего не изменено.`; after a restart of the NAS — the app is back by itself, and `df <copies folder>` shows the HDD.
9. **Problems and solutions** — the twelve of the description plus these, each as «symptom → cause → what to do»:
   13. The HDD not mounted at the container's start → copies on the system disk (KI-91): check after a restart; `docker compose restart` once the HDD is there, move what landed on the system disk.
   14. A Docker GUI of UGOS that imports or edits the project may drop `init: true` or `stop_grace_period`: run the app by `docker compose` over SSH; if the GUI's project feature is used, it points to this `docker-compose.yml` unchanged.
   15. Commands outside `<app folder>` find no project: always `cd <app folder>` first (the project name comes from the folder name, so the container is named differently from the PC's `telegram-bot-tracker-1`; nothing depends on that name).
   16. `cloudflared` in another compose project: join its network in `docker-compose.override.yml` (`networks:` with `external: true`) and put that network in `TRUSTED_PROXIES`.
   17. The NAS clock: Telegram, Google sign-in and the copies' names need the right time — NTP on in UGOS; the zone of the app is `BOT_TIMEZONE`, not the NAS's.
   18. Local edits in the clone block `git pull`: `git status` clean; settings only in `.env` and the override.
   For problem 8 (Google Drive sign-in on the NAS later): `ssh -L 8080:127.0.0.1:<port> <user>@<NAS>` from the PC, then `http://localhost:8080` in the PC's browser, login, Settings → «Подключить Google Drive».
   For problem 4: Engine below 25 — the first health answer after 30 s, nothing to do; below 23 — `DOCKER_BUILDKIT=1 docker compose up -d --build`.
10. **Report back** — a template `nas-report.md` with the headings of decision 2 of the description (the NAS; Docker and Compose versions; other apps and ports; the folders of the code, `data`, the copies; the compose files; `PUID`/`PGID`; the container and its network; `cloudflared` side, `TRUSTED_PROXIES`, the domain; `WEB_HOST`/`WEB_PORT`; the zone; how the code gets there and is updated; the exact commands to start, stop, read the log, restore; SSH from the PC — the command, never a key; Google Drive connected or not; every check of section 8 with its result; whether the tracker wakes the HDD (KI-90); the problems met and what was done; what was left on the PC). No secret values anywhere in it. The owner brings it to this project («Приём переезда», stage 7.4).

Budget: none in the table of `docs/workflow.md`; aim under 20,000 bytes, each fact told once, pointers to `docs/outside-access.md` and `docs/backups.md` instead of repeating them.

## 5. Edge cases

| Case | Expected |
|---|---|
| Asking restore while the bot runs | `BOT_RUNNING` at once, exit 1, nothing asked |
| Bot started between the question and the change | `BOT_RUNNING` before `apply`, exit 1, base untouched |
| Container starting (migrations, web not listening yet) | counts as running (the name resolves) |
| `getaddrinfo` fails other than «no such name» | counts as running: `BOT_RUNNING` |
| Answers piped and ending early | as Enter / not `да`: `Отменено…`, exit 0 |
| Number out of range, letters | `Нет копии с номером …`, asked again |
| Path given that does not exist / wrong kind | `NOT_FOUND` / `WRONG_KIND`, exit 1 |
| `.7z` given, no `BACKUP_PASSWORD` | `NO_PASSWORD`, exit 1 |
| Garbage in `PUID` with a `user:` line | starts (KI-15) |
| `data` not writable with a `user:` line | the new refusal text with the real `uid:gid`, exit 1 |
| Copies folder on the HDD not writable | the bot starts; the daily copy fails → `backup_failed` and its message |
| HDD folder missing at start | Docker creates it where the path lies (KI-91) |
| Engine < 25 | builds; first health answer after 30 s |
| `restore-bot.ps1`, image cannot be built (no network) | Docker's lines + `Образ бота не собрать…`, exit 1, nothing changed |

## 6. Tests

Automated:
- `tests/test_restore.py`: the asking mode with fake input/output and a fake `bot_running` — list → number → `да` → applied (texts and the before-restore copy); Enter, end of input, `нет` → cancelled, base untouched; a wrong number asked again; a path argument; running at step 1 (nothing read from input) and at step 6 (base untouched); `apply` of the script refuses while running; `bot_running` with `getaddrinfo` faked: resolves → running, `EAI_NONAME` → stopped, `EAI_AGAIN` → running; the new texts exactly; `SERVICE_NAME` equals the service of `docker-compose.yml`; `RESTORE_COMMAND` quoted exactly in `docs/backups.md` and `docs/nas-move.md`.
- `restore-bot.ps1` (in `tests/test_restore.py`): builds with `docker compose build --quiet` before the first run; runs without `--build` and `--quiet-build`.
- `tests/test_container_start.py`: not root — `PUID=abc` ignored, identity from `getuid`/`getgid`, the refusal names it with the new text; root — unchanged.
- `tests/test_docker_files.py`: the `Dockerfile` starts with `# syntax=docker/dockerfile:1`; `docker-compose.override.example.yml` mounts only `/app/data/backups`; `.gitignore` has `docker-compose.override.yml`; `docker-compose.yml` unchanged (still mounts only `./data`).

Live on the PC (the session, then the owner): the three commands in PowerShell (refused while running; then stopped, a copy chosen, `нет`; `docker compose up -d`); the same with answers piped from Git Bash; a real restore of the newest copy and back from the copy «перед восстановлением»; `.\restore-bot.ps1` lists and restores as before; a `docker-compose.override.yml` on the PC putting the copies on drive C — a daily and a manual copy land there, the asking restore lists them, the Google Drive copy goes, then the override is removed; the image builds with the `# syntax` line. What the PC cannot show (an older Docker, the HDD's sleep, UGOS) is in the guide and in the report back.

## 7. Docs, terms, ADRs, known issues

- `docs/backups.md`: «Restoring the database» gets «Without PowerShell (the NAS)» — the three commands and a downloaded file in `data/restore/`; quoted texts with `/`; the table of copies says the folder may be on another disk (`docker-compose.override.yml`).
- `docs/outside-access.md`: one line at the top pointing to `docs/nas-move.md` for the move itself.
- `CONTEXT.md`: **Восстановление** — also by three `docker compose` commands with the asking restore; **Копия базы** — `data/backups` may be another disk; new **Переезд** (the move: the app from the PC to the NAS by the NAS project, by `docs/nas-move.md`; one instance — the PC bot is not started again) and **Отчёт о переезде** (the NAS project's report back, taken in by stage 7.4).
- `docs/code-map.md` rebuilt by `tools/code_map.py`; the non-Python list gets `docker-compose.override.example.yml` and `docs/nas-move.md` if the tool lists such files.
- No new ADR: the restore's guard by the service name is a detail of one module (its docstring says it), the override file is easy to undo.
- `KNOWN_ISSUES.md`: KI-15 and KI-70 → fixed by their tickets; new now (this session): **KI-90** (the hourly listing of copies on the HDD may wake it), **KI-91** (the HDD folder missing at the container's start: copies on the system disk).
- `PROJECT_CONTEXT.md` and `CLAUDE.md` do not change in this stage beyond the Next step: the NAS enters them in 7.4 (decision 6).

## 8. Proposed tickets

| # | Ticket | Complexity | Blocked by | Spec |
|---|---|---|---|---|
| 01 | The asking restore, the running guard, the texts with `/`, KI-70 in `restore-bot.ps1`, `docs/backups.md`, `CONTEXT.md` «Восстановление» | medium | — | 1, 2, 5, 6, 7 |
| 02 | KI-15, the `# syntax` line, the override example and `.gitignore`, the copies on another folder checked live, `CONTEXT.md` «Копия базы» | simple | — | 1, 3, 5, 6, 7 |
| 03 | The guide `docs/nas-move.md` with the report template, the pointer in `docs/outside-access.md`, `CONTEXT.md` «Переезд», «Отчёт о переезде», the test of `RESTORE_COMMAND` in the guide | medium | 01, 02 | 1, 3, 4, 7 |

Then the review of 7.3, then «Приём переезда» (7.4) after the NAS project's report.
