"""A season is marked and scored by its record (`SeasonRow.id`); the tests name it by its number, as the owner sees it."""

import asyncio


def season_id(tracker, title_id: int, number: int) -> int:
    """The record of the title's season with this number, as the card gives it."""
    card = asyncio.run(tracker.title_card(title_id))
    return next(row.id for row in card.season_rows if row.number == number)
