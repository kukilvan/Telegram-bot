# Release tracker

A personal tracker of movies, series, anime and games for one owner: Telegram bot + web app (Python, FastAPI + HTMX, SQLite), runs in Docker on the owner's PC.

## Rules

- Talk to the owner in Russian. Everything in the repo written from 2026-11-01 — docs, code comments, commit messages — is English; older files stay Russian until a session edits them. App UI language: Russian.
- **Golden rule:** nothing reaches `master` without the owner's check and «ОК». The session's working branch is pushed for review without asking — otherwise the owner does not get the changes on the PC. This beats any skill instruction (including `/implement`).
- The owner starts a session with «дальше»: do the Next step of `PROJECT_CONTEXT.md`. Read `docs/workflow.md` first in every session — the whole process is there (steps, branches, what to read, end of session, instructions for the owner, the session on the owner's PC).
- Never print values of `.env` or other secrets — in replies, logs or commands.
- Every bug or rare failure case not fixed now goes to `KNOWN_ISSUES.md` in the same session (rules at its top).
- Code, docs and messages use the words of `CONTEXT.md`; code follows `docs/coding-standards.md`. Read the ADRs of the area you touch; if your output contradicts one, say so explicitly instead of overriding it.
- The bot runs in one instance only: stop every other one before starting.

## Instructions for the owner

The owner is not a programmer: anything to do by hand is written step by step, in Russian, in the format of `docs/workflow.md` ("Instructions for the owner"). Commands are PowerShell, one per code block. A session on the PC stops and starts the bot itself and writes the launch result in one line plus the check.

## Run (PowerShell, Windows, folder `E:\LocalAI\Bionic\Telegram-bot`)

- Bot and web are one process in Docker (ADR 0007). Start: `.\start-bot.ps1` (works from any folder; checks Docker Desktop and `.env`; stops an old bot from `.venv`; builds and starts `docker compose up -d --build`; waits up to 90 s and prints «Готово» or «Запуск не удался» with log lines). The only way to start.
- Stop: `.\stop-bot.ps1`. Logs: `.\logs-bot.ps1` (exit with `Ctrl+C`, the bot keeps running). After a check the bot stays running — that is its normal state.
- Health: `http://localhost:8080/health`. Web: `http://localhost:8080`, login with `WEB_PASSWORD`.
- Tests: `.venv\Scripts\python.exe -m pytest tests/ -v` (full run ≈ 3 minutes; known Windows failures — `PROJECT_CONTEXT.md`, "Environment").
- Database migrations run by themselves at start (a copy goes to `data/backups/` first); by hand: `alembic -c alembic_tracker.ini upgrade head`. Logs: `data/logs/bot.log`.
- Copies of the database and the Google Drive copy (turning it on and off): `docs/backups.md`.

## Agent skills

- Issue tracker: local markdown in `.scratch/<stage>/`; formats in `docs/formats.md`.
- Domain docs: single context — `CONTEXT.md` and `docs/adr/`.
