# 02: Export — «Скачать список (CSV)» and «Скачать всё (JSON)»

Status: accepted
Complexity: medium (two read-only downloads over many tables; exact formats, but no external service and no migration)
Blocked by: 01 (the block of Settings and the place of the buttons)

Spec: `../spec.md`, sections 3 (all), 6 (last row), 7 (Export), 9 (`CONTEXT.md` term «Выгрузка»). Terms — `CONTEXT.md`; standards — rules 1, 2, 5, 7, 9, 10, 11; the List order «по названию» is `text.py`, the status labels `cards.STATUS_LABELS`, the kind labels `kinds.py`, the visible score `scores.visible` — take the ready rules, no copies (rule 7, last bullet).

## What to do

- **Core** (`Tracker.export_list()`, `Tracker.export_all()`; a module of its own by rule 7, say which in the docstring): both read the database in **one** read session (a consistent picture), return the bytes and the file name; dates and times on the owner's clock (the zone of Settings, rule 2). Pure formatting (the CSV rows, the cell guard, the JSON values) is a pure module without the database.
- **CSV** (3.1): `/settings/export.csv`, `tracker-list-<YYYY-MM-DD>.csv`, `text/csv; charset=utf-8`, UTF-8 with BOM, `;`, `\r\n`, RFC 4180 quoting; header and one line per title, the archive too, in the order of the List; the eight columns of the table (the dates `ДД.ММ.ГГГГ`, «Завершён» only for «Просмотрено», «Пройдено», «Бросил»); a cell that begins with `=`, `+`, `-`, `@`, a tab or a carriage return gets a leading `'`; an empty list gives the header only.
- **JSON** (3.2): `/settings/export.json`, `tracker-all-<YYYY-MM-DD>.json`, `application/json`, UTF-8 without BOM, `ensure_ascii=False`, indent 2; the shape of version 1 exactly as in the spec (titles with sources, seasons with episodes and parts, franchise movies, platforms, `expansion_of`, price history; `settings` as stored; `inbox` newest first without the internal fields); moments in ISO 8601 with the owner's offset, days `YYYY-MM-DD`, `null` for none; `database_revision` from the database; the left-out parts stay left out (source snapshots, follow-up snapshots, events, the queue, `failure_notified_at`, anything of `.env` and `data/`). An empty database gives empty lists.
- **Web** (`app/web/settings.py` or a module of its own by the size, rule 7): the two `GET` addresses behind the sign-in with `Content-Disposition: attachment`, built in a worker thread through the facade (rule 10); a failure gives the web's page of an unexpected error and an error in the log.
- **The buttons and the hint** in the place ticket 01 left: «Скачать список (CSV)», «Скачать всё (JSON)» and the hint text of 2, item 4.
- **Docs:** module docstrings, `.venv\Scripts\python.exe tools\code_map.py`; `CONTEXT.md` — the term «Выгрузка» (export: the CSV list and the JSON of everything, download only; in code `export`; _Avoid_: импорт, дамп); `docs/tests-map.md`.

## Done when

- [ ] The CSV bytes are as 3.1 says: BOM, `;`, `\r\n`, quoting, the guard, the eight columns, the List order, the archive included, the header only for an empty list.
- [ ] The JSON is the shape of 3.2 for a database holding a movie, a series with parts, an anime, a game with platforms, an expansion and a price history, and the left-out parts are really absent.
- [ ] Both files come from one read session; both addresses need the sign-in; the file names carry the owner's date.
- [ ] Failure of an export shows the error page and an error line in the log.
- [ ] No module of the core over 400 lines; `pyflakes app tests` clean; the full suite green (the three known Windows failures are not new).

## Tests to add

- CSV: bytes of a prepared list (BOM, separator, line endings, quoting of `;` `"` and a line break, the `'` guard for each starting character, columns, order, an empty list, the date columns and the «Завершён» rule, the original name empty when equal).
- JSON: a prepared database with each kind of title; the shape and the values (labels, scores, offsets of the zone, enumerations as stored); the left-out parts; an empty database; the inbox without the internal fields.
- One read session (the two reads of the export see one picture); the web: the addresses behind the sign-in, the headers (`attachment`, the name with the date, the types), an error path.

## Owner check

The session starts the bot itself and writes the launch result in one line. The owner's check (browser, `http://localhost:8080/settings`, at the bottom, in «Копии и выгрузка»):

1. Press «Скачать список (CSV)». A file `tracker-list-<today>.csv` downloads. Open it by a double click in Excel: the Russian letters are readable (not «Р°Р»), one title per line, columns «Название», «Оригинальное название», «Тип», «Статус», «Оценка», «Год», «Добавлен», «Завершён»; the archive titles are there too.
2. Press «Скачать всё (JSON)». A file `tracker-all-<today>.json` downloads. Open it in Notepad (right-click → «Открыть с помощью» → «Блокнот»): at the top `"format": "release-tracker-export"`, then your titles with seasons, episodes and platforms; the Russian text is readable.
3. Compare: pick one title you know (e.g. a series you scored) — its status and score are the same as on its card.

«Не так»: crooked Russian letters in Excel, everything in one column, an error page instead of a file, a title that is on the card but not in the file.
