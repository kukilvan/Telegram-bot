# Stage 7.1: backups and export — and the split of stage 7

Status: in review

Terms come from `CONTEXT.md`. Roadmap item 7 «Backups, NAS and phone» (`docs/project-spec.md`) is split into three stages here; this file is the description of the first one, 7.1, and holds the decisions already taken for 7.2 and 7.3 so their descriptions start from them. Decisions it leans on: ADR 0005 (SQLite; a copy is made by SQLite's online backup, not by copying the file), ADR 0006 (Docker on the owner's PC until a NAS), ADR 0007 (one process: copies are made by the same scheduler). Mockups: `mockups/settings-backups.html`, `mockups/restore.html`; for 7.2 — `../7-2-access-phone/mockups/bot-links.html`, `../7-2-access-phone/mockups/settings-test-event.html`.

## The split of stage 7

| Stage | What | Needs |
|---|---|---|
| 7.1 Копии и выгрузка | export of the list to CSV and JSON, restore from a copy, an encrypted copy in Google Drive, «Сделать копию сейчас» | nothing — done on the PC now |
| 7.2 Доступ вне дома и телефон | Tailscale with `https`, the address of the app in `.env`, the bot buttons become links to the web card, «Тестовое событие» moves to the web, the phone installation checked, the login hardened for the outside | the owner's Tailscale account and the app on the phone |
| 7.3 Переезд на NAS | the move of `data` and the container to the NAS, rights on files, start and stop without PowerShell, Tailscale on the NAS | the NAS itself — not bought yet (2026-11-07) |

**Order (owner, 2026-11-07):** 7.1 → 7.2 → 9 (1–2 weeks of real use, now with the phone) → 8 (the GitHub template) → 7.3 when the NAS appears, as a stage of its own. Stage 8 is published before the NAS move; the NAS instructions join the template's README in 7.3.

## Goal

Today the app makes copies of the database (at start, daily, before a migration), but all of them lie on the same disk as the database: a dead disk or a stolen PC loses everything. And there is no way back: nobody ever restored from a copy, and the owner would not know how. After this stage the owner can get the data back, from the PC or from Google Drive, with one command, and can download the list as a table or as a whole file whenever they want.

## What the owner will see at the end

**Web, Settings — a new block «Копии и выгрузка»** at the bottom (mockup `settings-backups.html`):
- «Копии базы на этом ПК: 14, последняя — сегодня в 07:58.» and how often they are made and how many are kept.
- The line of the Google Drive copy in one of three states: done («сегодня в 07:59, там хранятся 30 последних»), off («выключена» — the default), failed (when and why, and the last good one).
- «Сделать копию сейчас» — a copy at once (and to Google Drive when it is on), e.g. before the owner tries something risky.
- «Скачать список (CSV)» — one title per line (name, kind, status, score, year, when added, when finished); opens in Excel with Russian letters intact.
- «Скачать всё (JSON)» — the whole data in one file: titles with seasons and checkmarks, statuses, scores, games with platforms, settings, «Входящие». For keeping or moving; it cannot be loaded back.

**Google Drive copy (off by default).**
- Turned on by the owner in `.env`: the password of the copies and the Google Drive link set up once by step-by-step instructions (rclone).
- Once a day, after the daily copy, the copy goes to a folder of the owner's Google Drive as an archive with a password; 7-Zip opens it by that password, so a copy can be opened by hand even without the app. The folder keeps the 30 newest.
- A failure (no internet, Google refused the sign-in, full Drive) comes as a failure report to Telegram at most once a day, like other failures, and shows in Settings.

**Restore — `.\restore-bot.ps1`** (mockup `restore.html`):
- Without arguments: lists the copies of `data\backups`, newest first, with their dates in words; the owner types a number and confirms with «да».
- With the path of an archive downloaded from Google Drive: opens it with the password from `.env`.
- Before replacing, the current database is kept as a copy of its own (`…_before-restore.db`), so a restore can itself be undone. The script stops the bot, puts the copy in place, starts the bot and prints «Готово» or what went wrong; a file that is not a copy of the tracker database changes nothing.

**Owner's check at the end of the stage:** download both files and open the CSV in Excel; «Сделать копию сейчас» and see the new copy in Settings; turn the Google Drive copy on, see the archive appear in Drive, open it with 7-Zip; mark a title as watched, restore yesterday's copy and see the mark gone; restore the `…_before-restore` copy and see it back.

## In scope · out of scope

**In 7.1:** the block «Копии и выгрузка», the two downloads, «Сделать копию сейчас», the encrypted Google Drive copy with its status and failure report, `restore-bot.ps1` for a local copy and for a downloaded archive, the instructions for the owner (setting up Google Drive, restoring), the `.env` variables described in `PROJECT_CONTEXT.md`.

**Out:**
- Loading an export back (owner, 2026-11-07: restore is from a copy of the database; an import would mean merging and duplicates).
- Restore from the web: a button that replaces the running database is too easy to press; the script asks twice and keeps the old base.
- Copies of `.env` and `data/web_secret`: secrets never leave the PC. Without `.env` the keys are taken again from TMDb, IGDB and Telegram; the session key is made anew (the owner just signs in again).
- Other clouds (Yandex Disk, OneDrive), and the copy sent to Telegram — Google Drive was chosen.
- Everything of 7.2 and 7.3.

## Pulled-in `KNOWN_ISSUES.md` entries and review wishes

- **7.1:** no open entry is about copies.
- **7.2** (recorded here so its description takes them): KI-7 (a restart resets the login lockout), KI-8 (logout does not revoke a stolen session cookie), KI-12 (a list of allowed `Host` names against DNS rebinding), KI-13 (a spoiled session key file is not made anew) — each entry says itself «more important once the web is open outside the home». The 6.4 review wish «split `bot/tracker_handlers.py` when it grows» — 7.2 removes «Мои тайтлы» and the test-event menu from it, so the split, if still needed, goes there.
- **7.3:** KI-15 (the container start checks `PUID`/`PGID` even when not started as root — met on a NAS with `user:`).

## Decisions taken with the owner

1. **Split into 7.1 / 7.2 / 7.3 and the order 7.1 → 7.2 → 9 → 8 → 7.3** — the NAS is not bought; outside access and the phone do not need it, and real use (stage 9) is worth more with the phone working. `docs/project-spec.md` is updated by this session.
2. **Outside access by Tailscale (7.2)**: free, no domain, the app opens only on the owner's devices with Tailscale on, and Tailscale gives the `https` address that installing on the phone needs. Cloudflare Tunnel rejected: a domain (~$10 a year) and the app open to the whole internet with only the password in front. **This contradicts ADR 0006 and ADR 0008**, which leave outside access «until the NAS appears»: 7.2 opens it on the PC already. The new ADR is written by 7.2 (its description or spec), superseding that part of 0006; until then 0006 stands.
3. **Off-site copy to Google Drive with rclone, once a day, 30 kept, off by default.** The archive is encrypted before upload and opens in 7-Zip by the password — so restoring needs neither rclone nor the app (rclone's own encryption rejected: its files open only with rclone and the same settings). The password lives in `.env` and **must also be kept outside the PC** (a password manager, a note): without it a Drive copy is useless when the PC is lost. The instructions say so.
4. **Export: CSV and JSON, download only**, from Settings.
5. **Restore by a PowerShell script** (`restore-bot.ps1`, like `start-bot.ps1`), keeping the current database aside first. On the NAS (7.3) the same is done without PowerShell.
6. **Bot buttons (7.2):** under messages and cards «📄 Карточка» becomes a link to the web card (and the card after adding gets «Открыть в приложении»); «📚 Мои тайтлы» goes; «📋 Сводка сейчас» stays; «🧪 Тестовое событие» and the delivery-rules check move to the web Settings. When the address of the app is not set in `.env` (the template's default, or Tailscale off), the bot stays as it is today. The change of ADR 0010's context («Мои тайтлы» leaves in 7) is just carried out.
7. **«Сделать копию сейчас» in Settings** — proposed by the session, approved with this description.

## Open questions for the spec

- The archive: 7z with AES-256 (`py7zr`) or zip with AES (`pyzipper`) — whichever 7-Zip and Windows open, made inside the container without other tools; the name of the password variable (`BACKUP_PASSWORD`?) and the rules for it (length, the `$` ban of `.env`).
- rclone: inside the image (its size) or the Google Drive API from Python; how the one-time sign-in is done by a non-programmer on Windows (`rclone authorize "drive"` needs a browser and a local port); access only to the app's own folder (`drive.file`); where its settings file lives (`data/`, never printed).
- When the upload runs (after the daily copy and «Сделать копию сейчас»; a retry within the day after a failure?), how it is counted against the 30 kept, and the texts of the status lines and of the failure report.
- CSV: columns, separator and encoding Excel opens with Cyrillic (UTF-8 with BOM, `;`?), dates in the owner's zone. JSON: the exact shape, a version field, what is left out (price history? snapshots of follow-ups?).
- Restore: the `-wal` / `-shm` files of the running database; a copy of an older schema (migrations run at start — check), a copy of a newer schema than the code (refuse); a damaged file (check before replacing); the bot not stopping in time.
- The ticket split: likely 3–4 (export, Google Drive copy, restore script, the Settings block).
