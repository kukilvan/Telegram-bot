# Workflow

How every session works. Every session reads this file first.

## Stages and steps

The project is split into stages (`docs/project-spec.md`; status in `PROJECT_CONTEXT.md`). A stage id is a roadmap number: `6.2`, `6.3`, `7`. Each stage takes this path, one step per session:

| Step | Session title | Output |
|---|---|---|
| Description | «Описание 6.3» | `.scratch/6-3-<slug>/description.md` |
| Spec | «Спека 6.3» | `.scratch/6-3-<slug>/spec.md` |
| Slicing | «Тикеты 6.3» | `.scratch/6-3-<slug>/issues/MM-<slug>.md` |
| Ticket | «Тикет 6.3.02» | code, tests, module docstrings (the code map is built from them) |
| Review | «Ревью 6.3» | `.scratch/6-3-<slug>/review.md` |

How a roadmap item is split into stages is decided by the agent: the split is proposed in the description and confirmed by the owner. Folders of stages finished or running before 2026-11-01 keep their names (`.scratch/games-2-steam-prices/`, `web-3-feed-archive-scores/`, …); their `Статус:` and `Сложность:` lines mean Status and Complexity (`открыт` open · `ждёт проверки` in review · `принят` accepted; `простой` simple · `средний` medium · `сложный` complex). File formats: `docs/formats.md`, the section for the file you write.

**Description.** What and why, in plain words. Before writing it:
- propose in chat (Russian) the nuances, ideas, risks and questions you see for this stage, and ask the owner for wishes (AskUserQuestion, with an option «Пожеланий нет»);
- pull in open `KNOWN_ISSUES.md` entries and wishes of earlier reviews that fit the stage;
- stage with UI: a rough mockup of every new screen — real texts in Russian, rough layout — saved as `.scratch/6-3-<slug>/mockups/<screen>.html` and shown to the owner (desktop app: the browser pane).

The approved description is the source of truth for its stage; when it changes the plan of later stages, update `docs/project-spec.md` in the same session.

**Spec.** Exact behaviour, texts, data, edge cases, tests. Built from the description; assumptions about external services checked against real responses where possible (answers saved next to the spec). Ends with a proposed ticket split.

**Slicing.** One file per ticket, numbered from `01`. Each ticket is a finished piece the owner can check on its own and fits one session. Its `Complexity:` (simple · medium · complex) picks the model of its session. The ticket names the spec sections it needs, so its session does not read the whole spec.

**Ticket.** Code, tests, then the docstring of every module it adds or changes: its first sentence says what the module holds and becomes the line of `docs/code-map.md`. Nobody edits the map by hand: run `.venv\Scripts\python.exe tools\code_map.py` (`tests/test_code_map.py` fails when the map is stale). Then the self-check, then the owner's check.

**Review.** The whole stage against its spec and `docs/coding-standards.md` — with the `code-review` skill: one pass for standards, one for the spec. Run things, not only read them. Each finding gets one decision in `review.md`:
- **fix now** — minutes of work and no design choice (typo, label, spacing): fixed in this session;
- **fix round** — needs design or tickets: the stage gets fix round k — `.scratch/6-3-<slug>-fix<k>/`, the same five steps, titles ending in « · правки k» («Описание 6.3 · правки 1» …);
- **defer** — small or rare: a `KNOWN_ISSUES.md` entry.

A review with no fix-round finding closes the stage; the next stage begins with its description.

**Ideas.** The owner adds features and ideas with `/add-idea`: each becomes `docs/ideas/NNN-<slug>.md`, listed in the Ideas column of its stage in `PROJECT_CONTEXT.md`. The stage's next description, spec or slicing — whichever comes first — takes the listed ideas in and sets each idea's `Status:` to the file that took it.

## One session — one step

A session does one step and never starts the next, even with time left. Outside the chain:
- **«Вопрос: …»** — a question or discussion; changes no files and no Next step.
- **«Идея: …»** — `/add-idea`; files an idea into a stage, the Next step stays.
- **«Срочная правка: …»** — only for a bug that blocks the owner: `KNOWN_ISSUES.md` entry, fix, test, self-check, end of session as usual; the Next step stays.

## Start of a session

1. Title the session from the table (desktop app: the session-title tool via ToolSearch; elsewhere skip).
2. Read what the step needs, no more:

| Session | Reads, besides `CLAUDE.md` (loaded by itself), `PROJECT_CONTEXT.md` and this file |
|---|---|
| Description | `docs/project-spec.md` (the stage and what it touches), the stage's ideas, `CONTEXT.md`, `KNOWN_ISSUES.md` index, the last review's wishes, ADRs of the area |
| Spec | the description, the stage's ideas not yet taken in, `CONTEXT.md`, ADRs of the area, `docs/code-map.md` |
| Slicing | the spec, the stage's ideas not yet taken in |
| Ticket | the ticket, only the spec sections it names, `CONTEXT.md`, `docs/coding-standards.md`, `docs/code-map.md` |
| Review | the spec, the tickets, `docs/coding-standards.md`, `docs/code-map.md`, the stage diff |

`docs/history.md`, `docs/tests-map.md` (which test file covers a module — for a ticket that adds tests) and full `KNOWN_ISSUES.md` entries (find one by its `## KI-<n>` heading with Grep) — only when a specific detail is needed; never read them whole.

3. Git: `git fetch origin`, `git switch master`, `git pull --ff-only`. The worktree must be clean; changes you did not make — touch nothing, ask the owner. Then `git switch -c claude/s<stage>-<step>` with the stage's dot written as a dash (`claude/s6-3-description`, `claude/s6-2-ticket-02`, `claude/s6-3-fix1-review`). A session the app already put in its own worktree keeps its branch and only brings it up to date with `master`.

## Session on the owner's PC

The owner works in Claude Code on the PC, in the folder `E:\LocalAI\Bionic\Telegram-bot`: here are `.env`, `data` (database, logs, copies) and `.venv`. The session works right in it, without a separate copy: the bot in Docker is built from these files.

- **Tests:** `.venv\Scripts\python.exe -m pytest tests/ -q` (about 3 minutes; run in the background). No dummy values needed: settings come from `.env` (never print them). Three process-launch tests fail on Windows without any change (`PROJECT_CONTEXT.md`, "Environment"); new failures do not.
- **The session starts the bot for the check, not the owner:** after the commit `.\start-bot.ps1` (stops the previous container and an old bot from `.venv`, rebuilds the image, waits for «Готово»), then `http://localhost:8080/health` and the log lines (`docker compose logs --tail 50`) — no red text. Never run the bot outside Docker (`python -m app.main`): it runs in one instance only.
- **Instruction to the owner:** only the check block (browser, Telegram: exact text and what should come) and the launch result in one line; "stop" and "start" the session did itself. `.\stop-bot.ps1` and `.\start-bot.ps1` are given only when the owner has to do it.
- After «ОК» and the move to `master` the folder stays on the session's branch (the same content as `master`); the next session switches to `master` itself.

## Self-check (ticket)

Before the owner sees a ticket:
1. The full test suite passes; failures listed as known in `PROJECT_CONTEXT.md` don't count, new ones do.
2. Start the app with `.\start-bot.ps1` (it stops the running one).
3. Walk the owner's check exactly as you will write it: web — in the browser pane or by HTTP requests; bot — logs and the health endpoint. Watch the log for 10–15 seconds: no red text, and within a minute a line `Job "Tracker.poll_due …" executed successfully` with no `polling title … failed` before it; no error message arrives in Telegram. What only the owner can do (their phone, Telegram, their accounts) stays theirs.
4. Fix what broke and repeat. The owner's check then lists what you could not verify, and one line says what you did.

## End of a session

1. Status line of the step's file → `in review`. Commit and `git push -u origin <branch>` — allowed without asking: the branch waits for review. Commit messages are English, `<Step>: <what>` (`Spec 6.3: …`, `Ticket 6.2.02: …`).
2. Message to the owner, Russian:
   - what was done, 2–4 lines;
   - ticket — the launch result in one line and the check (rules below);
   - description, spec, slicing, review — a retelling of the key points and every decision needed from the owner; they approve by the retelling; the file path for those who want to read.
3. AskUserQuestion: «ОК» (accept and move to `master`) / «Есть замечания» (the owner types them).
4. **«Есть замечания»:** fix, push, show the change, ask again.
5. **«ОК»:**
   - the step file → `accepted`; `PROJECT_CONTEXT.md` — State and Stages updated, a new Next step with model and effort (`docs/models.md`; a ticket by its `Complexity`), within budget; `docs/history.md` — a dated entry: what changed, where, which decisions;
   - commit, push the branch, then into `master`: if `master` has not moved — `git push origin HEAD:master`; if it has — merge `master` into the branch, run the tests, push, then `git push origin HEAD:master`. `master` history is never rewritten;
   - the closing message, in this shape:
     > Готово, всё в `master`. В следующей сессии мы будем делать <what, one line> («<session title>»). Это <простая / средняя / сложная> работа, поэтому рекомендую модель **<model>** с effort **<effort>**. Откройте новую сессию, выберите их и напишите «дальше».

## Instructions for the owner

The owner is not a programmer. For anything they do by hand:
- step by step, nothing skipped; for each step — where: which window (PowerShell, browser, Telegram, phone), which folder, which account;
- one command per code block, PowerShell (Windows);
- for a check — the exact text to type or button to press, what should appear, and what "wrong" looks like;
- each technical term explained in plain words the first time («журнал» — файл, куда программа пишет, что она делает; «traceback» — красный текст с ошибкой);
- «запустите» or «перезапустите» always comes with the command itself;
- when the owner launches the app: stop → start → check, in that order (`.\stop-bot.ps1`, `.\start-bot.ps1`, the check); when the session launched it: the launch result in one line, then the check. The bot in Docker stays running after the check — that is its normal state; the stop block is for when stopping is really needed.

## Documents

| File | Holds | Budget |
|---|---|---|
| `CLAUDE.md` | rules, run commands, pointers | 60 lines and 6,000 bytes |
| `PROJECT_CONTEXT.md` | Next step, state, stages, environment, gotchas | 20,000 bytes |
| `docs/project-spec.md` | the product and its stages | — |
| `CONTEXT.md` | glossary | — |
| `docs/adr/` | one decision per file with its reasons; replaced by a new ADR, never rewritten | — |
| `KNOWN_ISSUES.md` | index on top, entries below | one index line per entry |
| `docs/coding-standards.md` | rules with reason and check; added by the ticket that introduces a rule | — |
| `docs/code-map.md` | architecture, the files that are not Python, and the list of the modules of `app/` built from their docstrings by `tools/code_map.py` — never edited by hand | — |
| `docs/tests-map.md` | what each test module checks | read only on need |
| `docs/history.md` | dated details of accepted steps | read rarely |
| `docs/models.md` | model and effort per session | — |
| `docs/formats.md` | formats of step files | — |
| `docs/ideas/` | one idea spec per file, with its stage and status | — |
| `.scratch/<stage>/` | a stage's description, spec, tickets, review, mockups | — |

Budgets are in bytes (`wc -c`), not lines: a few very long lines pass a line budget and still cost tens of thousands of tokens in every session. Each fact has one home; other files point to it. Over budget → the oldest detail moves to `docs/history.md`.
