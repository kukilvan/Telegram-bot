"""How the owner's text is compared: one function for the order «по названию», the search by name and the merging of
genres. Pure, no database."""


def key(text: str) -> str:
    """What makes two writings one: case does not matter and «ё» is «е». The code points then put digits first, Latin
    letters next, Cyrillic last. Spaces at the ends are not touched: whoever must ignore them (a genre, a search query)
    strips before."""
    return text.casefold().replace("ё", "е")
