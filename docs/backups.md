# Copies of the database

The owner's guide to the copies: what is copied where, how to turn the Google Drive copy on and off, how to open its
archive by hand, and how to bring the database back from a copy. Rules behind it: spec of stage 7.1 (`.scratch/7-1-backups-export/spec.md`), ADR 0005 and ADR 0012.

## What is copied where

| What | Where | When | Kept |
|---|---|---|---|
| Daily copy `tracker_db_<time>.db` | `data\backups\` on this PC | by itself, once a day (checked every hour) | 14 newest and one for each of 12 months |
| Manual copy `tracker_db_<time>_manual.db` | `data\backups\` | the button «Сделать копию сейчас» in Settings | 10 newest |
| Copy before an update `…_before-<revision>.db` | `data\backups\` | before every change of the database structure | never deleted |
| Copy before a restore `…_before-restore.db` | `data\backups\` | by `.\restore-bot.ps1`, just before it replaces the database | never deleted |
| Google Drive copy `tracker_db_<time>[_manual].7z` | the folder «Трекер — копии» in your Google Drive | after each daily copy and each «Сделать копию сейчас», and at once after «Подключить Google Drive» (off by default); a copy that did not go is tried again every hour | 30 newest |

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
6. «Branding» (left): Google publishes the app only with the «App domain» filled. «Application home page» and
   «Application privacy policy link»: `https://github.com/kukilvan/Telegram-bot` (the tracker has no site of its own);
   «Authorized domains» → «Add domain» → `github.com`. Leave «App logo» empty: a logo makes Google ask for a
   verification. Press «Save».
7. **Publish the app:** «Audience» (left) → «Publishing status: Testing» → «Publish app» → «Confirm». The status
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

## Opening an archive by hand with 7-Zip

Needed when the PC is lost, or the archive was made with an older password (see below). On Windows:

1. Install 7-Zip if you have none: https://www.7-zip.org → «Download» the «64-bit Windows x64» line → run the file →
   «Install».
2. Download the archive: https://drive.google.com → «Мой диск» → the folder «Трекер — копии» → right click on a file
   `tracker_db_….7z` → «Скачать». It lands in «Загрузки».
3. In «Загрузки», right click on the file → «7-Zip» → «Extract Here» («Распаковать здесь»; on Windows 11 first «Show
   more options»).
4. 7-Zip asks for the password: type `BACKUP_PASSWORD` (the one that was in `.env` when the archive was made) → «OK».
5. Next to the archive appears one file `tracker_db_<time>.db` (or `…_manual.db`): the copy of the database.

A wrong password: 7-Zip says «Wrong password?» or shows no file names at all (the names are encrypted too). Restoring
the database from that `.db`: «Restoring the database» below, «From a `.db` taken out by 7-Zip».

## Restoring the database

`.\restore-bot.ps1` in PowerShell, in the tracker folder `E:\LocalAI\Bionic\Telegram-bot`. It replaces the whole
database by a copy: everything that changed after that copy is gone from the app (it is kept apart, see «The way back»).
The work is done inside Docker, so nothing has to be installed on the PC; Docker Desktop must be running. Until you
answer `да` nothing is changed and the bot keeps working; after `да` the script stops the bot, replaces the database
and starts the bot again (also when the bot was stopped before).

### From the list of copies on this PC

1. PowerShell in the tracker folder: `.\restore-bot.ps1`.
2. The list appears, newest first: `1) сегодня в 07:58`, `2) вчера в 18:32 — сделана вручную`, … (the kind after the
   dash; a daily copy has none).
3. Type the number of the copy and press Enter. Enter alone — «Отменено. Ничего не изменено.».
4. The script checks the copy («Копия от … в порядке, тайтлов в ней: …») and asks «Вернуть базу к копии от …?».
   Type `да` and press Enter; anything else cancels.
5. The bot stops, «Нынешняя база сохранена: data\backups\…_before-restore.db», «База восстановлена из копии от …»,
   the bot starts, and the last line is «Готово: бот работает на копии от …».

A copy made by an older version of the tracker is restored too: the line «Копия от более старой версии…» says so, and
the start brings the database up to date by itself. A copy of a newer version is refused: update the tracker first.

### From a downloaded archive (Google Drive)

1. Download the archive: https://drive.google.com → «Мой диск» → «Трекер — копии» → right click on
   `tracker_db_….7z` → «Скачать». It lands in «Загрузки».
2. PowerShell in the tracker folder: `.\restore-bot.ps1 "C:\Users\<you>\Downloads\tracker_db_….7z"` (the path in
   quotes; dragging the file into the PowerShell window types its path).
3. The archive is opened inside Docker by `BACKUP_PASSWORD` of `.env`; then the same question as above.

«Пароль из .env не подходит к этой копии…» — the archive was made with another password (it was changed later) or it is
damaged: open it with 7-Zip by hand and the old password (above), then restore the `.db` as below.

### From a `.db` taken out by 7-Zip

`.\restore-bot.ps1 "C:\Users\<you>\Downloads\tracker_db_….db"`: the file is checked as it is, then the same question.
Without `BACKUP_PASSWORD` in `.env` (on another PC, say) this is the way for an archive: 7-Zip by hand, then this.

### The way back

Every restore first saves the database it replaces as the copy «перед восстановлением» (never deleted). To undo a
restore: `.\restore-bot.ps1`, choose the copy «перед восстановлением» of that minute, `да`. The same when the last line
is «База восстановлена, но бот не запустился — ошибка выше…»: that copy is the database the bot worked with.

### What the restore does not touch

Only the database file `data\tracker.db` is replaced. `.env`, `data\web_secret` (the web sign-in), the Google Drive
connection (`data\google_drive_*.json`), the logs and the other copies stay as they are. The Google Drive copy goes on:
its next archive is of the restored database. A downloaded file is copied into `data\restore\` for Docker to see it;
that folder is emptied when the script ends.

## When something goes wrong

- **The line in Settings says «Копия в Google Drive не ушла: … — нет связи с Google Drive»** (or «Google Drive сейчас
  недоступен»): nothing to do, the copy is tried again every hour. A message in Telegram comes only from the second
  failure in a row, at most one a day.
- **«Google Drive не принял вход — подключите его заново в Настройках»**: the access was ended (revoked in your Google
  account, or the app is back in «Testing»). Press «Подключить Google Drive» in Settings; until then nothing is tried.
- **«в Google Drive нет места»**: free space in your Google Drive; the copy is tried again every hour.
- **You changed `BACKUP_PASSWORD`**: new archives use the new password; the older ones in the folder still open only
  with the old one (7-Zip by hand, as above). Keep the old password until those archives rotate out (30 copies).
- **You deleted the folder «Трекер — копии»**: the next copy makes it anew; the archives that were in it are gone.
- **You moved archives out of the folder**: they are no longer counted nor deleted by the app.
