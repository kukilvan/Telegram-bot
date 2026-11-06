# 02: Candidates — the pure module that picks names from a post and reads links of sources

Status: in review
Complexity: medium (one pure module with many small rules, checked on 18 real samples; no database, no network)
Blocked by: —

Spec: `../spec.md`, sections 3 (parsing the links only, not the lookups), 4 (all), 11 (row `candidates.py`), 13 (two entries), 14 (the candidates test), 15 (rule 7 row `candidates`). Samples: the 18 posts of `docs/ideas/001-telegram-inbox-examples.md` (section «N. …» is sample N; the table of 4.6 lists the expected first candidates). The throwaway `../answers/candidates_prototype.py` was checked on those samples; it shows the shape of the rules but **the spec wins** over it and the real module is written clean, not copied. Terms — `CONTEXT.md` (the new «Кандидат» comes in ticket 04); standards — rules 5, 7, 11.

## What to do

- **`app/tracker/candidates.py`** (pure: no database, no network, no clock; `text.key` is its only helper, rule 7 pure list):
  - cleaning line by line (4.1);
  - the kinds of candidates with their weights, the Latin run, quotes, bold, the Cyrillic name after a kind word, the head of an episode line, a name message, the fallback of the first line (4.2–4.3);
  - the kind words and markers (4.4), the stop list and merging into a longer candidate, the drops (4.5);
  - the years of an item (4.5);
  - the **name key** (4.7) in one place — «Control: Resonant» and «Control Resonant» are one key;
  - ranking: weight from the highest, equal weights by the first appearance (4.2);
  - **reading the links** (section 3, parsing only): the links of an item — its text and its `url` / `text_link` addresses — in order of appearance, without repeats; the first 3 that are links of a source, as a typed value per link (the kind it gives and the number or the text to look up: Steam app, TMDb movie, TMDb tv, Shikimori entry with the optional letter, IMDb `tt…`, jut.su / jutsu.ru slug as a name candidate of weight 50). Host match ignores `www.`, the scheme and the case; a TMDb language prefix and a `-slug` after the number are accepted. The lookups of these links are ticket 04.
  - the **query of an item** as a function: the first candidate, none — the first 60 characters of the text cut at a word (ticket 05 calls it).
- The result is a plain value (a list of candidates with name, weight, first position), easy to print in a test.
- **Docs:** module docstring, `.venv\Scripts\python.exe tools\code_map.py`; rule 7 of `docs/coding-standards.md` — the row `candidates` and the pure list; `docs/tests-map.md`; `KNOWN_ISSUES.md` — two entries of 13: "a Cyrillic name in the middle of a post without quotes, kind word or bold is not a candidate" and "the stop list is a fixed list".

## Done when

- [ ] Each of the 18 samples gives the first candidate of the table of 4.6, and the "next" names of the table come after it with the weights shown; samples 13 and 14 also give their jut.su slugs at weight 50.
- [ ] Every rule of 4.1–4.5 is checked on its own by a made-up text: score lines, signature, invisible characters, URLs and handles, a lone `Main:` line, platforms and stores at the start of a run, short words not on the first line, the stop list, merging («SQL» into «Ghost in the SQL Data»), kind words, markers, quotes, bold, a Cyrillic name after a kind word, the fallback, +2 for a repeat.
- [ ] The links of section 3: every form of the table (`www.`, `http`, language prefix, `-slug`, a letter before the Shikimori id, IMDb), no duplicates, at most 3, a hidden `text_link` is a link and never a name, `t.me` / `youtube` are not sources.
- [ ] The name key is used wherever two names are compared in this module and is the only such place.
- [ ] The module is pure (no import of the database, a source or the clock), at most 400 lines (split into two modules behind one entry if needed); rules 5, 7, 11; `pyflakes app tests` clean; the full suite green (the three known Windows failures are not new).

## Tests to add

- The 18 samples (the texts are taken from the idea file into the test as data) against 4.6.
- One test per rule of 4.1–4.5, the years, the name key, the links, the query of an item.

## Owner check

Nothing the owner can see: this ticket has no screen and no message. The session runs the tests and writes in one line how many samples gave the expected first name (18 of 18). The owner has nothing to do; «ОК» accepts the code.
