# Copies of the database

The owner's guide to the copies: what is copied where, and how to turn the Google Drive copy on and off. Rules behind
it: spec of stage 7.1 (`.scratch/7-1-backups-export/spec.md`), ADR 0005 and ADR 0012.

## What is copied where

| What | Where | When | Kept |
|---|---|---|---|
| Daily copy `tracker_db_<time>.db` | `data\backups\` on this PC | by itself, once a day (checked every hour) | 14 newest and one for each of 12 months |
| Manual copy `tracker_db_<time>_manual.db` | `data\backups\` | the button «Сделать копию сейчас» in Settings | 10 newest |
| Copy before an update `…_before-<revision>.db` | `data\backups\` | before every change of the database structure | never deleted |
| Google Drive copy `tracker_db_<time>.7z` | the folder «Трекер — копии» in your Google Drive | once a day, after the daily copy (off by default) | 30 newest |

The Google Drive copy is an archive 7-Zip opens: the copy of the database inside, encrypted with AES-256 by the password
`BACKUP_PASSWORD` from `.env` (even the file name inside is hidden). The app sees only the files it made itself in your
Google Drive (the permission `drive.file`); it cannot read anything else there.

The connection to Google is the file `data\google_drive_token.json`. It is secret: do not send it to anyone. It is not
inside the database, so restoring an old copy does not bring back an old connection.

## Turning the Google Drive copy on

Once, about 15 minutes. You need the Google account whose Google Drive will keep the copies, and a browser on this PC.

### 1. A Google Cloud project

1. Open https://console.cloud.google.com and sign in with that Google account. Accept the terms if asked.
2. At the top, press the project list (next to «Google Cloud») → «New project». Name: `Трекер копии`. Press «Create»
   and wait until the bell at the top says it is ready; make sure this project is chosen in the list at the top.

### 2. The Google Drive API

1. In the search field at the top type `Google Drive API` and open it (Marketplace / «APIs & Services»).
2. Press «Enable».

### 3. The consent screen

1. Menu ☰ → «APIs & Services» → «OAuth consent screen» (it may be called «Google Auth Platform»). Press «Get started».
2. «App name»: `Трекер`; «User support email»: your address. «Next».
3. «Audience»: **External**. «Next».
4. «Contact information»: your address. «Next», tick the agreement, «Continue», «Create».
5. «Data Access» (left) → «Add or remove scopes». In the filter type `drive.file`, tick the line
   `.../auth/drive.file` («See, edit, create, and delete only the specific Google Drive files you use with this app»),
   press «Update», then «Save» at the bottom.
6. **Publish the app:** «Audience» (left) → «Publishing status: Testing» → «Publish app» → «Confirm». The status
   becomes «In production». This matters: in «Testing» Google ends the connection after 7 days. The scope `drive.file`
   is not sensitive, so Google does not ask for a review.

### 4. The client «Desktop app»

1. «Clients» (left) → «Create client».
2. «Application type»: **Desktop app**. Name: `Трекер`. Press «Create».
3. A window shows «Client ID» and «Client secret». Copy both now (Google may not show the secret again; then press
   «Download JSON» and keep the file somewhere safe, or make a new secret in the client later).

### 5. `.env`

Open `.env` in the tracker folder (`E:\LocalAI\Bionic\Telegram-bot`) in Notepad and fill three lines (they are in
`.env.example` with comments; add them if your `.env` has none):

```
BACKUP_PASSWORD=
GOOGLE_DRIVE_CLIENT_ID=
GOOGLE_DRIVE_CLIENT_SECRET=
```

- `GOOGLE_DRIVE_CLIENT_ID` — the «Client ID» (ends in `.apps.googleusercontent.com`);
- `GOOGLE_DRIVE_CLIENT_SECRET` — the «Client secret» (begins with `GOCSPX-`);
- `BACKUP_PASSWORD` — a password you make up: at least 12 characters, no `$` sign. **Save it in your password manager
  too**: without it the archives in Google Drive cannot be opened, also if this PC is lost.

Save the file.

### 6. Start and connect

1. PowerShell in the tracker folder: `.\start-bot.ps1`, wait for «Готово».
2. Browser **on this PC**: http://localhost:8080/settings (the port is `WEB_PORT` of `.env`). The block «Копии и
   выгрузка» says «Google Drive не подключён.» with the button «Подключить Google Drive».
3. Press it. Google's page opens: choose your account. Google may warn «Google hasn't verified this app» — press
   «Advanced» («Дополнительно») → «Go to Трекер (unsafe)» («Перейти»). Allow the access to the files the app creates,
   press «Continue».
4. You are back in Settings with «Google Drive подключён…» and the button «Отключить Google Drive».

From a phone the button is replaced by a sentence: the connection is made only on this PC, because Google sends the
browser back to `localhost`.

## Turning the Google Drive copy off

1. Settings → «Отключить Google Drive». The app ends its access at Google and forgets the connection. The archives
   already sent stay in the folder «Трекер — копии»; delete them there by hand if you do not need them.
2. To switch the copy off completely, empty the three lines of `.env` (`BACKUP_PASSWORD=`, `GOOGLE_DRIVE_CLIENT_ID=`,
   `GOOGLE_DRIVE_CLIENT_SECRET=`) and run `.\start-bot.ps1`. Settings then says «Копия в Google Drive выключена».
3. Optional: in https://console.cloud.google.com delete the project «Трекер копии» («IAM & Admin» → «Settings» →
   «Shut down»).

To connect again later, fill the lines back and press «Подключить Google Drive» again.
