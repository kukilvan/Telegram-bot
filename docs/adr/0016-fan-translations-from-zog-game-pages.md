# Fan translations are read from ZoG game pages

Status: accepted

Idea 002 shows the fan Russian of a game beside the official one: a «Русификатор» on Zone of Games (zoneofgames.ru), the one big catalog of Russian fan patches. ZoG has no API, and its own search is built by JavaScript; outside it, a game is found only through Google. Spec 9.1b (section 5.6) reads the game's own page instead: its address is made from the game's original name (`/games/<name>/`, with the Roman and Arabic numbers switched and the part before «:» tried — at most four requests), a found page is taken only when its name and year match the game, and the owner can paste the right link or say «Не та игра» (ticket 06). A page is read once a week, two games a polling pass, a second between requests, with a `User-Agent` that names the program and its pace and not the owner. The entries under «Переводы:» that start with «Русификатор (» give text («текст») and voice («звук»), PC or no platform only.

ADR 0009 rejected reading PlayStation Store pages because a page breaks without warning. Here a broken page costs little: a layout that cannot be read is shown as «unreadable» on the card, the last value read on the same page stays, one log line a day says so, and no message is invented — a fan part is told only when it appears on a page read as usual. No money depends on it (a wrong price would mislead a purchase; a missed patch is found by the owner on the page the card links to). A failure of ZoG (down, slow, a status other than 200) is not reported to the owner at all: a log line, the next try in six hours, and the card shows the day of the last read.

Considered and rejected:
- GamesVoice, Mechanics VoiceOver and other studios: each has only its own work, so several sites with their own layouts would still miss most patches.
- ZoG's own search: built by JavaScript, so it needs a browser engine.
- A search engine (Google): needs a key or scraping a page that is far less stable than ZoG's own, and terms that forbid automatic queries.
- Asking the owner for the page of every game: the owner would paste links for games that have no patch at all; the link stays as the fix for a page not found or a wrong one.

## Consequences

- A game whose ZoG page has another name than the game (a different word order, a subtitle in the middle) is «not found» until the owner pastes its link; the hint on the card says so.
- An older namesake (`prey`, 2006, for Prey of 2017) is refused by the year rule, so a game without a year can take a namesake; the owner fixes it with «Не та игра».
- If ZoG changes its layout, every card says «Страницу на ZoG не удалось прочитать» with the last fan part kept; the fix is a change of `sources/zog_pages` checked against new saved pages.
- When ZoG gets an API or a search without JavaScript, a new ADR replaces this one.
