# Copies go to Google Drive through its API with the owner's own Google client

Status: accepted

Stage 7.1 sends a copy of the database off the PC once a day (description of 7.1, decision 3: Google Drive, 30 kept, off by default, an archive 7-Zip opens by a password). The description named rclone as the carrier. The spec check of 2026-11-07 (`.scratch/7-1-backups-export/checks.md`) found that rclone's shared Google client «will stop working during 2026», so every user has to create a Google client of their own anyway, and that rclone's sign-in listens on `127.0.0.1:53682` inside the container with no flag to move it, so the one-time sign-in could not be finished from the browser on the PC. Decided: the app talks to the Google Drive API itself (`httpx`), with the owner's client of type «Desktop app» (`GOOGLE_DRIVE_CLIENT_ID`, `GOOGLE_DRIVE_CLIENT_SECRET` in `.env`), the scope `drive.file` only (the app sees only the files it made; a non-sensitive scope, so a published app needs no review by Google), and the sign-in is a button in Settings that returns to the app on `localhost`. The archive is 7z with AES-256 and hidden names, made by `py7zr` (`BACKUP_PASSWORD`).

Considered and rejected:
- rclone in the image with the owner's own client: a binary of tens of megabytes more, the sign-in done on the PC by a separate `rclone.exe authorize` and its answer pasted into the container — many steps for a non-programmer, for one upload a day that the API does in three requests.
- rclone's own encryption (`crypt`): its files open only with rclone and the same settings; a 7z opens with 7-Zip on any computer.
- zip with AES (`pyzipper`): lighter (no 25 MB of `py7zr`'s dependencies), but file names stay visible, it compresses half as well, and how 7-Zip for Windows turns a non-Latin password into bytes for zip is not defined, while 7z always uses UTF-16.
- A Google service account: it has no storage of its own in a personal Drive.

## Consequences

- Turning the copy on needs a Google Cloud project made once by the owner (`docs/backups.md`); the app must be **published** («In production»), otherwise Google ends the sign-in after 7 days.
- The refresh token lives in `data/google_drive_token.json`, outside the database (a restore does not bring back an old connection); it never goes into a copy or an export.
- The connection is made on the PC itself (`localhost`); on a NAS (stage 7.3) the token file moves with `data`, so no new sign-in is needed there.
- Restoring needs neither the app nor rclone: 7-Zip and the password open an archive by hand.
