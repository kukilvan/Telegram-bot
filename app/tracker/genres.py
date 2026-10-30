"""Genres as the owner picks them: the same genre written in two cases or with «е» for «ё» is one genre. Pure functions,
no database. Synonyms of different sources («Боевик», «Экшен») stay different genres (KI-30)."""

from collections.abc import Iterable


def key(genre: str) -> str:
    """What makes two writings one genre: case does not matter, «ё» is «е», spaces at the ends do not count."""
    return genre.strip().casefold().replace("ё", "е")


def label(writings: Iterable[str]) -> str:
    """The name of a merged genre: the first of its writings in alphabetical order, with a capital first letter
    («драма» and «Драма» are «Драма»; «Чёрная комедия» and «черная комедия» are «Черная комедия»)."""
    first = min((w.strip() for w in writings), key=lambda w: (w.casefold(), w))
    return first[:1].upper() + first[1:]


def keys_of(genres: Iterable[object]) -> set[str]:
    """The keys of the genres a title stores; whatever is not a name is left out."""
    return {key(g) for g in genres if isinstance(g, str) and g.strip()}


def merge(genre_lists: Iterable[Iterable[object]]) -> list[str]:
    """The merged genres of many titles, by name in alphabetical order."""
    writings: dict[str, list[str]] = {}
    for genres in genre_lists:
        for genre in genres:
            if isinstance(genre, str) and genre.strip():
                writings.setdefault(key(genre), []).append(genre)
    return sorted((label(w) for w in writings.values()), key=lambda name: (name.casefold(), name))
