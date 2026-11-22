"""Genres as the owner picks them: one genre is one name, whatever the case, the «е» for «ё» or the source that wrote it.
Pure functions, no database. An own table `SYNONYMS` joins what two sources call alike («Боевик» of TMDb and «Экшен» of
Shikimori) and splits a TMDb genre of series that names two («НФ и Фэнтези»); the card and the Search keep the source's
names, only the Archive filter reads genres through the table (KI-30)."""

from collections.abc import Iterable

from app.tracker.text import key as text_key


def key_of(genre: str) -> str:
    """What makes two writings one genre: `text.key` of the genre without the spaces at its ends."""
    return text_key(genre.strip())


# a genre's key to the genres it counts as, the first one first; the merged genre is named by the TMDb word
SYNONYMS: dict[str, tuple[str, ...]] = {
    key_of("Экшен"): ("Боевик",),
    key_of("Тайна"): ("Детектив",),
    key_of("Боевик и Приключения"): ("Боевик", "Приключения"),
    key_of("НФ и Фэнтези"): ("Фантастика", "Фэнтези"),
    key_of("Война и Политика"): ("Военный", "Политика"),
}


def counts_as(genre: str) -> tuple[str, ...]:
    """The genres a written genre counts as: the table's answer, else the genre itself."""
    return SYNONYMS.get(key_of(genre), (genre.strip(),))


def label(writings: Iterable[str]) -> str:
    """The name of a merged genre: the first of its writings in alphabetical order, with a capital first letter
    («драма» and «Драма» are «Драма»; «Чёрная комедия» and «черная комедия» are «Черная комедия»)."""
    first = min((w.strip() for w in writings), key=lambda w: (w.casefold(), w))
    return first[:1].upper() + first[1:]


def chosen_key(genre: str) -> str:
    """The key of the genre an address or a call asks for: a synonym is its genre, a composite name is its first part
    («Экшен» is «боевик», «НФ и Фэнтези» is «фантастика»). Empty for an empty name."""
    return key_of(counts_as(genre)[0]) if genre.strip() else ""


def keys_of(genres: Iterable[object]) -> set[str]:
    """The keys of the genres a title stores, through the table; whatever is not a name is left out."""
    return {key_of(part) for g in genres if isinstance(g, str) and g.strip() for part in counts_as(g)}


def merge(genre_lists: Iterable[Iterable[object]]) -> list[str]:
    """The merged genres of many titles, through the table, by name in alphabetical order."""
    writings: dict[str, list[str]] = {}
    for genres in genre_lists:
        for genre in genres:
            if isinstance(genre, str) and genre.strip():
                for part in counts_as(genre):
                    writings.setdefault(key_of(part), []).append(part)
    return sorted((label(w) for w in writings.values()), key=lambda name: (name.casefold(), name))
