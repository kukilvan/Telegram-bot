# Web sign-ins and the login lock live in a file in `data/`, outside the database

Status: accepted

Until stage 7.2 a sign-in to the web was only a signed cookie: the server kept nothing, so «Выйти» could not end a copied cookie (KI-8), and the count of wrong passwords lived in memory and was cleared by a restart (KI-7). Before the app reaches the internet (ADR 0013) the server has to know its sign-ins: to end one, to end all of them («Выйти на всех устройствах»), to say where the last login came from. Spec 7.2 (section 4) keeps them, the last login and the lock in one file, `data/web_login.json`, next to the database and not in it; the cookie carries the id of its sign-in.

Considered and rejected:
- A table in `tracker.db`: a restore of an older copy would bring back sign-ins ended since — a stolen cookie revived by a restore; the copies (also the Google Drive ones) and the JSON export would carry them; and it needs a migration for state that is not the owner's data.
- A generation number in the cookie, bumped by «Выйти на всех устройствах», plus a list of ended ids: ends cookies but cannot count or describe the sign-ins that live, and is no simpler.
- Keeping the cookie alone: KI-7 and KI-8 stay open on the internet.

## Consequences

- A restore never touches sign-ins; the NAS move carries the file with `data/`.
- One process writes it (ADR 0007); every change is written at once by a temporary file and `os.replace`. A spoiled file counts as empty: every device logs in again and the lock count is zero.
- The update that brings it logs every device out once (an old cookie has no id).
- `data/` holds one more file the owner must not share (it names the devices and the last address, though no secret: a sign-in works only with a cookie signed by `data/web_secret`).
