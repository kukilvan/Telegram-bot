# Checks behind spec 7.1

Run on 2026-11-07 by the spec session in throwaway Docker containers (`python:3.12-slim`, Debian 13.6), with the owner's permission; nothing was installed on the PC. The sample database was a copy of `data/backups/tracker_db_20261106_183236.db` (520,192 bytes).

## 1. Archive with a password: py7zr and pyzipper against real 7-Zip

Made with py7zr 1.1.4 (`SevenZipFile(path, "w", password=..., header_encryption=True)`) and pyzipper 0.4.0 (`AESZipFile(..., compression=ZIP_DEFLATED, encryption=WZ_AES)`), password `Тест-пароль 123` (Cyrillic and a space on purpose). Tested with 7-Zip 25.01 for Linux (Debian package `7zip`, the program of Igor Pavlov):

| | `.7z` (py7zr) | `.zip` (pyzipper) |
|---|---|---|
| Size of the 520 KB database | 45,324 bytes | 87,570 bytes |
| Time to make | 0.17 s | 0.02 s |
| `7z t -p<password>` | ok, `Method = LZMA2:24 7zAES:19`, `Encrypted = +` | ok, `Method = AES-256 Deflate` |
| `7z t -pwrong` | «Cannot open encrypted archive. Wrong password?» (names hidden: header encryption) | «Wrong password» (file names visible) |
| Added to the image | ~25 MB (site-packages 7 → 32 MB: py7zr, pycryptodomex, pyzstd, pyppmd, pybcj, brotli, inflate64, multivolumefile, texttable, psutil) | pycryptodomex only |

Errors of py7zr when reading back (they decide the texts of `restore-bot.ps1`):

| Case | What py7zr raises |
|---|---|
| no password, header encrypted | `py7zr.exceptions.PasswordRequired` |
| wrong password (two tries) | `TypeError: Unknown field: b'\xc0'` / `b'\x90'` — garbage, not a clean «wrong password» |
| not an archive | `py7zr.exceptions.Bad7zFile: not a 7z file`; `py7zr.is_7zfile()` → `False` |
| cut in half | `Bad7zFile: next header size 44 exceeds the archive size` |
| right password | extracts |

Not checked: 7-Zip for Windows with a Cyrillic password. The 7z format turns the password into UTF-16LE on both sides (py7zr and 7-Zip), so it should match; the owner's check of ticket 04 opens a real archive on Windows.

## 2. rclone

rclone (current, `downloads.rclone.org/rclone-current-linux-amd64.zip`): `rclone config create gdrive drive scope=drive.file config_is_local=false --non-interactive` stops at the state `client_id_warning`:

> rclone's shared Google Drive client_id is being retired and will stop working during 2026. Create your own to avoid interruption

`rclone authorize` has only `--auth-no-open-browser` and `--template`: no flag for the address of its sign-in listener (127.0.0.1:53682), so the sign-in cannot be done inside the container by a browser on the PC without a port forwarder.

## 3. Google (documentation, 2026-11-07)

- rclone.org/drive: making your own client id is «now required rather than merely recommended»; type «Desktop app»; External apps must be published, otherwise «any grants will expire after a week».
- developers.google.com/identity/protocols/oauth2: an External project in «Testing» status «is issued a refresh token expiring in 7 days» (unless only profile scopes); a limit of 100 refresh tokens per Google account per client.
- developers.google.com/workspace/drive/api/guides/api-specific-auth: `drive.file` is a **non-sensitive** scope (`drive` is restricted).
- developers.google.com/identity/protocols/oauth2/native-app: desktop apps are public clients (the secret is not secret), PKCE S256 recommended, loopback redirect `http://127.0.0.1:port` (`localhost` possible); the loopback flow stays supported for desktop clients.

Not checked live: the requests to Google (needs the owner's own client). Ticket 03 saves the first real answers (tokens masked) next to this file.

## 4. The real sign-in (ticket 03, 2026-11-08)

With the owner's own client «Desktop app», External, scope `drive.file`, the app in the bot in Docker on the PC, the browser on the PC at `http://localhost:8080/settings`.

- **The return address that works: `http://localhost:8080/settings/google-drive/callback`** — the first of the three (`google_drive.REDIRECT = Redirect.CALLBACK`). Google accepted `localhost` with a path for a desktop client; no `redirect_uri_mismatch`. The fallbacks (`127.0.0.1`, the path `/`) stay in the code behind the switch, tested by fakes; ADR 0012 holds unchanged.
- **The consent screen needs more than the spec said to publish it.** «Publish app» stays refused («To publish your app, you must complete your configuration on the Branding page») until «Branding» has «Application home page» and «Application privacy policy link» with their domain in «Authorized domains»; the owner gave the public repository `https://github.com/kukilvan/Telegram-bot` for both and `github.com`. No logo: a logo makes Google ask for a verification. `docs/backups.md` says so.
- **Google's answers** (the app logs no bodies; tokens never reach the log):
  - `POST https://oauth2.googleapis.com/token` (`grant_type=authorization_code`, PKCE) → `HTTP/1.1 200 OK`, with a refresh token (`prompt=consent`);
  - the token file `data/google_drive_token.json` — fields `connected_at`, `folder_id` (`null`), `refresh_token` (`***`); rights `600` inside the container.
- The «unverified app» warning came as expected: «Advanced» → «Go to Tracker (unsafe)».

## 5. The first real copy to Google Drive (ticket 04, 2026-11-08)

The bot in Docker on the PC, the owner's Google Drive connected in ticket 03 (no folder yet, no state file). At the start the hourly job sent the newest copy at once:

- Requests and Google's answers, in order: `POST oauth2.googleapis.com/token` (refresh) → 200; `GET drive/v3/files?q=name='Трекер — копии' and mimeType=…folder…` → 200, none; `POST drive/v3/files` (the folder) → 200; `GET drive/v3/files?q='<folder>' in parents…` → 200, empty; `POST upload/drive/v3/files?uploadType=resumable` → 200 with `Location`; `PUT <Location>` → 200. About 4 seconds in all.
- `data/google_drive_state.json`: `error: null`, `kept: 1`, `last_success_name: tracker_db_20261108_174444_manual.db`; the token file got the `folder_id`; `data/backups/upload/` empty after the attempt.
- The log showed the `upload_id` of the resumable session in httpx's request line: masked since (`secrets_mask`, `upload_id=***`).
- 7-Zip for Windows with the Cyrillic `BACKUP_PASSWORD`: checked by the owner on 2026-11-08 — the archive downloaded from «Трекер — копии» asks for the password and opens by it, one `.db` inside. The open point of section 1 is closed.
