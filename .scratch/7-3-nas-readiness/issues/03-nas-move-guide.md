# 03: The guide `docs/nas-move.md` with the report template, «Переезд» and «Отчёт о переезде»

Status: accepted
Complexity: medium (one long document in English, a test that binds it to the code, a few doc lines; no code change)
Blocked by: 01, 02

Spec: `../spec.md`, section 1 (all facts), section 2.1 (the three commands), section 3 (3.1–3.3: what the container does and the override), section 4 (the guide, its ten sections, the twelve problems of the description plus 13–18, the report template, the budget), the `docs/outside-access.md` and `CONTEXT.md` lines of section 7. Also `description.md` of this stage: decision 2 (the headings of the report), problems 1–12, the NAS project's role. Terms — `CONTEXT.md`. ADRs to read: 0001, 0005, 0006, 0007, 0012, 0013, 0015. Read `docs/backups.md` and `docs/outside-access.md` to point to them, not to repeat them.

## What to do

1. **`docs/nas-move.md` (4).** English, for the agent of the NAS project; the sections in the order of 4: what the app is · what moves and what stays · where (never a network share) · before the move on the PC · the order of the move (nine numbered steps with their commands, the way back last) · `.env` for the NAS · start, stop, log, restore, update by `docker compose` · the checks after the move, each with right and wrong · problems and solutions (the twelve of the description and 13–18, «symptom → cause → what to do») · the report back. Paths are placeholders `<app folder>`, `<copies folder>`, `<NAS>`. The three commands are `RESTORE_COMMAND` of ticket 01, quoted exactly; the override file is that of ticket 02; the texts the guide says the app prints are the real ones of the code (read them there, do not recall). No secret value anywhere; the commands that touch `.env` never print a value. Aim under 20,000 bytes: each fact told once, pointers to `docs/outside-access.md` and `docs/backups.md`.
2. **The report template** (section 10 of the guide, `nas-report.md`): the headings of decision 2 of the description and the checks of section 8 of the guide, each as a heading with an empty line to fill; a line on top: no secret values.
3. **Pointers and terms.** `docs/outside-access.md`: one line at the top pointing to `docs/nas-move.md` for the move itself. `CONTEXT.md`: new **Переезд** (the app from the PC to the NAS by the NAS project, by `docs/nas-move.md`; one instance — the PC bot is not started again) and **Отчёт о переезде** (the NAS project's report back, taken in by stage 7.4).
4. `tools\code_map.py` (the non-Python list takes `docs/nas-move.md` if the tool lists such files); `docs/tests-map.md`.
5. **A walk-through.** Read the guide once as the NAS project's agent who has only this file and the repository: every command is complete, every placeholder named, nothing assumes the PC. Fix what stops such a reader; list in the closing note what the guide cannot settle without the NAS (the HDD sleep — KI-90, an older Docker, UGOS).

## Done when

- [ ] `docs/nas-move.md` has all ten sections in the order of 4, the problems 1–18, the report template; under about 20,000 bytes.
- [ ] Its three restore commands equal `RESTORE_COMMAND`; every file, variable and command it names exists in the repository (`docker-compose.override.example.yml`, `PUID`, `PGID`, `TRUSTED_PROXIES`, `WEB_HOST`, `WEB_PORT`, `APP_URL`, `BOT_TIMEZONE`, `restore-bot.ps1`…).
- [ ] No value of a secret, no real domain or address of the owner in it.
- [ ] `docs/outside-access.md` points to it; «Переезд» and «Отчёт о переезде» are in `CONTEXT.md` and used by the guide in the same words.
- [ ] The code map and tests map are updated; the full suite green (the known Windows failures do not count).

## Tests to add

`tests/test_restore.py` (or `tests/test_docs.py` where the doc tests live — the ticket picks by `docs/tests-map.md`): `docs/nas-move.md` quotes `RESTORE_COMMAND` exactly; the file names and variables it names exist (the example override, the `.env` names in `Settings` or `docker-compose.yml`); the file is under its size aim.

## Owner check

The session writes the launch result in one line (nothing changed in the app, the bot keeps running). The owner reads the retelling in chat: what the guide tells the NAS project, in what order, and what the report brings back. The file: `docs/nas-move.md`; the owner may hand it to the NAS project as it is. «Не так»: a step the owner cannot imagine the NAS project doing, a missing question the owner wants answered in the report.
