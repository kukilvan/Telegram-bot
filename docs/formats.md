# File formats

Read the section for the file you are writing.

Every step file opens with `Status: open | in review | accepted`. A ticket adds `Complexity: simple | medium | complex` and `Blocked by: MM, MM` (or `—`).

Files written before 2026-11-01 are in Russian with the same fields as `Статус:` (`открыт` · `ждёт проверки` · `принят`), `Сложность:` (`простой` · `средний` · `сложный`) and `Blocked by:`; they keep their form. Comments and conversation history append to the bottom of a file under a `## Comments` heading.

## Description — `.scratch/NN-<slug>/description.md`

- Goal: why, in plain words.
- What the owner will see at the end: scenarios, screens (mockups in `mockups/`).
- In scope · out of scope.
- Pulled-in `KNOWN_ISSUES.md` entries and review wishes.
- Decisions taken with the owner: what and why.
- Open questions for the spec.

## Spec — `spec.md`

- Behaviour per scenario: exact texts, states, errors.
- Data: what is stored; migrations.
- External services: requests, limits, failure handling — checked against real responses where possible.
- Edge cases, each with its expected behaviour.
- Tests: what is automated, what the owner checks live.
- Docs to update; new `CONTEXT.md` terms; new ADRs; new `KNOWN_ISSUES.md` entries.
- Proposed tickets: order, complexity, dependencies.

## Ticket — `issues/MM-<slug>.md`

- Spec sections it implements.
- What to do: a concrete list.
- Done when: checkable criteria.
- Tests to add.
- Owner check: the live check, in plain words.

## Review — `review.md`

- What was reviewed: commit range, tickets.
- Tests: results at the start and at the end.
- What was verified by running, not only by reading.
- Findings: `F<n>` — what, where, decision (fix now · fix round · defer `KI-<n>`), why.
- Wishes for later stages.

## ADR — `docs/adr/NNNN-<slug>.md`

Written when a decision is hard to reverse, surprising without context, or a real trade-off.

```text
# <The decision, as a statement>

Status: accepted | superseded by NNNN

Context and decision in 1–3 paragraphs; options considered and why they lost.

## Consequences

- What follows from it.
```

## Commit messages

English, `<Step>: <what>` — `Spec 2: login and sessions`, `Ticket 2.3: add login page`, `Review 2: fix button labels`.
