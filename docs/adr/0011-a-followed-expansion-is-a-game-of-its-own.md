# A followed expansion is a game of its own in the list

Status: accepted

Stage 6.3 tells the owner about the big expansions of the games they follow (Blood and Wine, Shadow of the Erdtree). The owner wants to know when such an expansion comes out on their platforms and when Steam sells it at a discount — what a game already gets. Decided with the owner on 2026-11-04 (description of 6.3, decision 4): «Следить» on an expansion adds it to the list as a title of kind «игра», added by its IGDB id like any game. The link to the game it belongs to is not a column or a table: it lives in the expansion's own IGDB snapshot (`GameState.expansion` and `parent`, refreshed by every poll), and the card and the List read it from there («Дополнение к игре «…»», the mark «дополнение»).

Considered and rejected:
- An expansion as a part of its game, like a season of a series (rows inside the game, with their own dates). It needs its own dates per platform, its own marks «играю здесь», its own Steam number and price history — a second copy of everything a game has, and a new kind of row in the Feed and the messages.
- A link table between titles (`parent_title_id`). The parent is often not in the list (an expansion of a game the owner removed, or never added), so the link would need an IGDB id anyway; IGDB already gives it with every poll.

## Consequences

- An expansion has platforms, release dates, «вышла» messages, statuses, a score, Steam prices and discounts with no new code: it is a game.
- An expansion that needs its game has no check of expansions and sequels of its own; a standalone one (it plays without its game) has.
- The List counts an expansion as one more game; the filter «Игры» shows it with the mark «дополнение».
- Search still shows only games: an expansion comes into the list only through «Следить».
- A game stored before 6.3 learns that it is an expansion only with its next own poll; a game in the archive is not polled, so it does not (KI-52).
