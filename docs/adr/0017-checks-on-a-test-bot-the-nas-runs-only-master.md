# After the move, checks run on a test bot on the PC; the NAS runs only `master`

Status: accepted

Until the move every session checks its work by starting the bot on the PC (`docs/workflow.md`, «Session on the owner's PC»). After the move the real bot lives on the NAS, and a PC bot with the same token would be a second instance (ADR 0001, problem 1 of `docs/nas-move.md`). The NAS project asked how the checks will work then, and which versions its update command must deploy. The owner decided (2026-11-25): **a second, test bot with its own token, its own `.env` and its own `data` on the PC** takes every check, as the PC bot does now; **the NAS gets only `master`, after the owner's «ОК»**, by the NAS project's update command, which this project runs.

Considered and rejected:
- A ticket branch deployed to the NAS for the owner's check, with `master` put back after «Есть замечания»: no second bot, but unaccepted code would run on the real database, and a migration goes forward only, so putting `master` back would need a restore of the copy made before the migration. The golden rule (nothing reaches real use without the owner's «ОК») is kept more simply when the NAS never sees a branch.

## Consequences

- Stage 7.4 sets it up: the owner makes the test bot in BotFather; the PC's `.env` gets its token; the PC's `data` becomes a copy for checks, **without `google_drive_token.json`** (otherwise the test bot would send its copies to the owner's Drive folder and rotate the real archives), with `APP_URL` empty or the PC's address. The PC's real `data` and `.env` are kept aside, untouched, as the way back of the move.
- `.\start-bot.ps1` refuses the real token after 7.4: the number before the colon of a token is the bot's id; 7.4 keeps the real bot's id in a git-ignored file and the script refuses a `.env` whose token starts with it.
- An owner's check in Telegram goes to the test bot; the web check is on the PC (`http://localhost:8080`). What only the real setup shows (the domain, Access, the phone over `https`) is checked on the NAS after «ОК» and the update.
- The update command deploys a `master` commit. A change that needs more than a rebuild (a new `.env` name, a change to `docker-compose.yml`, a runtime setting of the `Dockerfile`, a one-off step) has an entry in `docs/nas-changes.md` in the same commit.
- ADR 0001 stands: one instance per token. The test bot is another bot with its own token and data, not a second instance of the real one.
