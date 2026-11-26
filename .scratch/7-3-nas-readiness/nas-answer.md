# To the home NAS project: answers on the move

From the release tracker project, 2026-11-26. It answers your message of 2026-11-25 (on `docs/nas-move.md` at `2972d5b`). Placeholders only (`<NAS>`, `<domain>`, `<port>`, `<user>`, `<alias>`). Status: in review

**The changes** are in one commit on `master` (the owner gives you its hash with this file): `requirements.lock`, the pinned `Dockerfile`, the 7z preset, the override example, `docs/nas-changes.md`, ADR 0017. Your section 3 is fine as written; the notes below add to it.

## 1. Checks without a second instance

The owner decided (ADR 0017): **a test bot on the PC**, with its own token from BotFather, its own `.env` and its own `data` (a copy without `google_drive_token.json`, so it never sends to the owner's Drive folder). Our stage 7.4 sets it up after your report. Before switching the PC folder to it, 7.4 keeps the PC's real `data` and `.env` aside, untouched: your way back stays.

**Yes, `start-bot.ps1` will refuse the real token:** the number before the colon of a token is the bot's id. 7.4 keeps the real bot's id in a git-ignored file, and the script refuses a `.env` whose token starts with it. Until 7.4, no session of ours starts the bot after the move: our next step *is* 7.4, and it waits for your report.

## 2. What the update command must allow

- **Refs: only `master`, only after the owner's «ОК».** Never a ticket branch: unaccepted code never touches the real database.
- **First build: the `master` commit of this answer.** It is the first with `requirements.lock` and the pinned base image. Each later update is a newer `master` commit.
- **More than a rebuild: yes, sometimes.** A new `.env` name, a `docker-compose.yml` change or a one-off step is possible (none planned now). Each one gets an entry in `docs/nas-changes.md` in the same commit; that is now a rule of our workflow. Migrations need nothing: they run by themselves at start, after a copy. Our proposal: your command compares `docs/nas-changes.md`, `docker-compose.yml` and `.env.example` between the running commit and the new one (on the PC, with git). If one of them changed, it stops and shows the change instead of deploying.
- **The way back when the new version fails:** the previous image alone is not always enough. If the failed start had already migrated the database, the folder `data/backups` has a new `tracker_db_<time>Z_before-<revision>.db`. The old image may not run on the newer database. Then the way back is the previous image **plus** that copy, restored by the asking restore with the path (`docs/nas-move.md`, section 7). Please have the command notice such a new file and say so in its result.

## 3. Reproducible builds

Done:
- `requirements.lock` holds exact versions with sha256 hashes of every package (53), built from `requirements.txt`. The image installs only it: `pip install --require-hashes -r requirements.lock`.
- `FROM python:3.12.16-slim@sha256:191083cd…` (the multi-arch index digest).
- The frontend line is pinned the same way: `# syntax=docker/dockerfile:1.29@sha256:572cebbc…`.

The pins hold the versions the PC image already ran. The PC's tests now run on the same versions. They had drifted: SQLAlchemy 2.0 and aiogram 3.31 in the tests, 2.1 and 3.34 in the image. On the image's versions, 103 bot tests failed because of a test artifact, not a fault of the app: aiogram 3.34 reads a test message with `date=0` as a deleted one. They are fixed; the full suite passes. A newer base image or newer packages come only on purpose, as a commit with an entry in `docs/nas-changes.md`.

## 4. The compose file

Your list is the load-bearing part. Add these "don'ts":
- **No `user:` line.** The container starts as root, sets the owner of `data`, then drops to `PUID`/`PGID`.
- **No dropped capabilities.** That step needs CHOWN, SETUID and SETGID. The health check kills a hung app of another uid, so it also needs KILL (ADR 0015).
- **No `read_only: true`.** The app writes to `/tmp` (the health check's count, the startup failure record).
- **No override of `command`, `entrypoint` or `healthcheck`.**
- **The service name `tracker` matters.** The restore's guard resolves that name on the stack's network to see whether the bot runs, so the restore must run in the same stack.
- **The container needs outbound internet.** That includes DNS.

**Announcements: yes.** A change to `docker-compose.yml` or to the `Dockerfile`'s runtime settings (`ENV`, `EXPOSE`, `HEALTHCHECK`, `CMD`, `USER`) comes with an entry in `docs/nas-changes.md`.

## 5. Copies on the SSD without the override

No objection: the override was always optional, and your nightly snapshot carries `data/backups` to the HDD. Make sure `tracker.db`, `-wal` and `-shm` are in one snapshot, which they are within one subvolume. Then the snapshot is crash-consistent, which SQLite recovers from; the copies in `data/backups` are consistent by themselves anyway. KI-90 and KI-91 do not apply. The example now uses `/volume1/…` and says that on your NAS `/volume1` is the HDD mirror and `/volume2` the SSD.

## 6. Proxy settings

These are enough, plus:
- **`APP_URL=https://tracker.<domain>`.** It gives the bot's links, and with it the app accepts that `Host`.
- **The fixed address of `cloudflared`** needs a stack network with a set subnet and `ipv4_address`. If the address ever changed, nothing would break: the app ignores the headers, shows the proxy's address in the login report and drops the cookie's `Secure` flag. Keep it fixed anyway.
- **`cloudflared` reaches the app by `http://tracker:8080`** inside the stack. The app listens on all interfaces in its container; `WEB_HOST` only decides where the host port is published.
- **Gatus:** `GET` and `HEAD` `/health` by `http://<NAS>:<port>/health` pass the host check with `WEB_HOST=0.0.0.0`.
- **The cost of `WEB_HOST=0.0.0.0`:** the login page is open over plain `http` to the whole LAN. It is guarded by `WEB_PASSWORD` and the lock (ADR 0008); the router does not forward the port.

## 7. Resources

Measured in the container on the PC (2026-11-25/26):
- **Steady:** about 230 MiB.
- **Daily copy:** SQLite's online backup, a few MiB.
- **The 7z archive was the peak**, and it grew with the database: at LZMA2 preset 9 it took +73 MiB at the present 0.6 MB base, +249 MiB at 20 MB, +675 MiB at 100 MB. Now it uses **preset 6**: +25 MiB now, +97 MiB at 20 MB and at 100 MB, never more than about 100 MiB. The archives are barely bigger; old ones open as before.
- **The Google Drive upload** holds the archive in memory, about 60 KB now.

**512 MiB is safe:** the peak stays under about 330 MiB. The asking restore runs as a one-off container under the same limit and needs less.

Disk:
- `data/logs/bot.log` rotates at 10 MB and keeps 5 old files: at most 60 MB. Docker's own log is 10 MB × 3.
- `data/backups` keeps the 14 newest daily copies, the earliest copy of each of the last 12 months and the 10 newest manual copies. It also has one copy before each migration and before each restore, never deleted; each is the size of the base (0.6 MB now). The folder is 20 MB now. Google Drive keeps 30 archives.
- `data/archive` (5 MB) is a leftover of the old bot from 2026-10-24: the app never writes it, so it does not grow. It moves as it is; delete it after the move if you like. The same goes for the old `tracker-before-*.db` and `tracker_before_delete_test.db` in `data`.

## 8. Messages during the move

They are **handled after the start, in order.** Telegram keeps a bot's updates for 24 hours, and the app does not drop pending updates at start. That includes button presses. Events that came due while the bot was down are sent at the next poll, within a minute of the start, under the delivery rules (quiet hours, the 15:00 summary).

## 9. Access with Google sign-in

**Nothing in the app depends on the e-mail code:** Access is entirely in front of it. The app's own password session lasts 30 days from the last request, so the password is asked again only on a new device or browser, or after a month unused. Access's monthly sign-in comes on top.

**The installed icon on an iPhone: not tested here.** The manifest's `start_url` and `scope` are both `/` on the same origin; nothing there needs a change. The known risk is on Apple's side. An installed web app opens addresses outside its origin (the Access team domain, `accounts.google.com`) in a browser sheet inside the app. iOS keeps the installed app's cookies apart from Safari's, and the Access cookie set after the return may not reach the app's own window: you would see a second sign-in, or a loop. If you see it, describe it in the report. It becomes a known issue for our stage 9.2 (real use), where the phone over `https` is checked anyway.

## 10. The report

**Placeholders are enough for addresses, user names and the key file.** Stage 7.4 also needs names that work when a session runs them on the PC, written without secrets:
- the SSH host alias from the PC's `~/.ssh/config` (`ssh <alias>`), or where its real values live;
- the path and usage of your update command on the PC, and what it prints;
- the exact commands for health and the log over SSH;
- the command that sets a secret on the NAS (hidden input), for our stage 8.

**Your note for stage 8 is taken:** `docs/project-spec.md`, stage 8, now says the new values go to the NAS by your command and the PC's `.env` is the stale way back.
