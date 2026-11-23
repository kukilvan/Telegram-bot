# 03: Candidates — the middle name, «from» and `: N`, the companies of IGDB — KI-58, KI-60, KI-59

Status: in review
Complexity: medium (one rule module and one request; the samples of 6.4 guard it)
Blocked by: 01

Spec: `../spec.md`, section 7 (7.1 KI-58, 7.2 KI-60, 7.3 KI-59), the lines of section 8.4 about the companies request, section 13 (the IGDB `/companies` row and the failures paragraph), the candidate rows of section 14, the «Candidates» line of the tests of section 15, the `CONTEXT.md` and `PROJECT_CONTEXT.md` lines of section 16. Terms — `CONTEXT.md` («Кандидат», «Входящие»). ADRs to read: 0010 (the bot takes posts and names by rules, no AI), 0015 (the polling queue: the request goes at once, ahead of the paced polling). Standards — rules 2, 7, 9, 11. Fixtures: `../answers/igdb-companies-or-2026-11-23.json` → `tests/fixtures/igdb/companies.json` (the answers of the `~ … | …` request: Ubisoft, Mojang, Remedy, Bethesda, Control, Halo, Portal, Hades, Metro, Arcane, Marvel …); `igdb-companies-exact` and `-case` only to read (they show why `~` and `|` are used). The 18 samples of 6.4 are in `tests/fixtures/inbox/` (`inbox_samples.md`).

## What to do

Work in this order; the samples of 6.4 stay green at every step (a changed first offer is explained in the commit message and in the ticket's closing note).

1. **KI-58, the middle name (7.1).** A rule of `candidates` for a run of capitalised Cyrillic words (first letter `А–Я Ё І Ї Є Ґ`, then lower case; one space; at most 4 words), weight `MIDDLE = 2`. Not a middle name: the first word of a sentence (start of a line after emoji, dashes, quotes, spaces; after `.`, `!`, `?`, `…`) — the run then starts at its second word; a run inside a quote, a bold piece or after a kind word (those rules have it); a run right after a marker (`_MARKERS`); a word of `COMMON_WORDS` (list of 7.1, in `candidate_words`), which ends a run. A repeat adds `REPEAT_BONUS`. Examples of 7.1 must come out exactly: «Вчера вышла новая Дюна, и все рады» → «Дюна» (2); «Смотрю Мастер и Маргарита вечером» → «Мастер», «Маргарита»; «Новый трейлер Дюны» → «Дюны».
2. **KI-60 (7.2).** A Latin run whose first word is «from» (any case) loses it, the rest weighed as after a marker (`AFTER_MARKER_PENALTY`; a kind word before «from» no longer counts); a run of «from» alone is nothing. `: <number>` joins a run unless an episode word follows (`сери…`, `сері…`, `епізод…`, `эпизод…`, `episode`, `ep`, any case): «Fallout: 76» in, «Bleach: 3 серия» stays the episode line.
3. **KI-59, the companies (7.3).** `IgdbProvider.companies(body)` on `/companies` (at once, like the search); `IgdbGameSource.companies(names) -> frozenset[str]` (name keys). The request text is exactly that of 7.3 (`name ~ "<n>" | name ~ "<n> <word>" …`, `COMPANY_WORDS`, `limit 500`); a name with `"` or `\` is not asked. A name is a company when one of its answers has `len(developed) + len(published) >= COMPANY_GAMES` (20). `OfferSearch` (`by_kind` and the candidate part of `by_links`) asks once per analysis for the first 10 candidates by rank that have a Latin letter, except a name message (`WHOLE`) and a name Steam gave a link; none to ask — no request; the companies are dropped before `searched` picks the ones to search. `Tracker.company_source` (the game source, None — not asked) is passed to `InboxAnswers` and `OfferSearch` like `imdb_source`, so the core asks no kind (two lines of assembly; `core.py` stays ≤ 470 lines). No keys (`SourceNotConfigured`), a failure or a 429: a warning in the log, the candidates stay as the fixed list left them, the analysis goes on.
4. **The stop list (7.3).** `STOP_NAMES` grows by the services IGDB does not know: Crunchyroll, Kinopoisk, Кинопоиск, Okko, Иви, Wink, Amediateka, Prime Video, Apple TV, Hulu, Paramount+, Game Pass, PS Plus, Gamescom, The Game Awards, Summer Game Fest, State of Play, Nintendo Direct, Reddit, VK, Kotaku, Polygon, Eurogamer, GameSpot, StopGame, Игромания, DTF.
5. **Docs.** `CONTEXT.md` «Кандидат»: the companies of IGDB are dropped (`companies`, 20 games); `PROJECT_CONTEXT.md`: the IGDB row (the companies request), the Gotcha «Ubisoft» is no company name in IGDB — the variants; `tools\code_map.py`; `docs/tests-map.md`; `KNOWN_ISSUES.md`: KI-58, KI-59, KI-60 → `fixed (test: …)` (entry and index).

## Done when

- [ ] The three examples of 7.1 give exactly the stated candidates and weights; «АНОНС», the first word of a sentence, a quote, bold, a marker run and a common word are not middle names.
- [ ] «Игра from Software вышла вчера…» gives «Software» with a low weight; «Fallout: 76» is one name; «Bleach: 3 серия» is the episode line with «Bleach».
- [ ] On the saved answers Ubisoft, Mojang, Remedy, Bethesda, Blizzard, Capcom, FromSoftware, Valve, Netflix, Rockstar are companies and Control, Halo, Portal, Hades, Metro, Arcane, Marvel, Dune, Doom, Fallout, Batman, Witcher, Frostpunk, Silksong, Elden Ring are not.
- [ ] «Ubisoft анонсировала новую игру, и все очень этому рады сегодня» + «Игра» searches no «Ubisoft»; with no other candidate: «Не нашёл — сохранил во «Входящие»…».
- [ ] No Latin candidate — no request; a name message and a Steam name are not asked; no keys, a failure and a 429 go on with a warning.
- [ ] The 18 samples of 6.4 keep their first offers (or each change is explained); pyflakes clean; code map rebuilt; `core.py` ≤ 470 lines; the full suite green.

## Tests to add

The «Candidates» list of section 15: KI-58 examples and the sentence-start, quote, marker and common-word cases; KI-60 both rules and the kept episode line; the samples of 6.4; companies — the request text for given candidates (and a name with a quote not asked), the 20-games rule on the saved answers, the drop moves the next candidate up, no keys / failure / 429, `WHOLE` and Steam names not asked, nothing asked without a Latin candidate, a Cyrillic company («Юбисофт») stays a candidate of weight 2.

## Owner check

The session starts the bot and writes the launch result in one line. In Telegram, to the bot (a post is sent as a plain message; wait about 3 seconds for the question «Что это?»):

1. «Ubisoft анонсировала новую игру, и все очень этому рады сегодня» — press «Игра». There must be no offer «Ubisoft»; the bot answers «Не нашёл — сохранил во «Входящие»…» or offers another name.
2. «Вчера вышла новая Дюна, и все рады» — press «Фильм». The offer must be «Дюна».
3. «Вышел Fallout: 76 вчера и все очень этому рады сегодня вечером» — press «Игра». The offer must be «Fallout 76».

«Не так»: an offer «Ubisoft»; no offer at all for the Дюна post; «Fallout» without 76. The test messages end up in «Входящие» of the web or are answered «Нет» — the owner removes them there with «Убрать» (the session says so).
