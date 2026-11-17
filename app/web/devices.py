"""The device of a sign-in in words (pure): the `User-Agent` of a request becomes «Android, Chrome» (spec 6.3 of stage 7.2).

Two first-match tables, the system and the browser. Neither known gives «неизвестное устройство», one known gives that
one alone. The raw `User-Agent` is never kept or shown: only these words reach the sign-ins file and the login report.
An iPad on iPadOS 13+ sends the `User-Agent` of a Mac and reads as «macOS, Safari» (KI-72: telling them apart needs
JavaScript, which the app does not have, ADR 0004).
"""

UNKNOWN_DEVICE = "неизвестное устройство"
MAX_USER_AGENT = 512  # longer is cut: no one needs the rest and the matching stays cheap

# (the word, the marks of the User-Agent): the first row with a mark in the text wins
SYSTEMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("iPhone", ("iPhone",)),
    ("iPad", ("iPad",)),
    ("Android", ("Android",)),
    ("ChromeOS", ("CrOS",)),
    ("Windows", ("Windows",)),
    ("macOS", ("Macintosh", "Mac OS X")),
    ("Linux", ("Linux",)),
)
BROWSERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Яндекс Браузер", ("YaBrowser/",)),
    ("Edge", ("Edg/", "EdgA/", "EdgiOS/")),
    ("Opera", ("OPR/", "OPT/")),
    ("Samsung Internet", ("SamsungBrowser/",)),
    ("Firefox", ("Firefox/", "FxiOS/")),
    ("Chrome", ("CriOS/", "Chrome/")),
)


def _first(table: tuple[tuple[str, tuple[str, ...]], ...], text: str) -> str | None:
    return next((word for word, marks in table if any(mark in text for mark in marks)), None)


def device_words(user_agent: str) -> str:
    """`{system}, {browser}` of a `User-Agent`; one of them alone when only one is known; `неизвестное устройство` when
    neither is (an empty `User-Agent` too)."""
    text = (user_agent or "")[:MAX_USER_AGENT]
    system = _first(SYSTEMS, text)
    browser = _first(BROWSERS, text)
    if browser is None and "Safari/" in text and "Version/" in text:
        browser = "Safari"
    known = [word for word in (system, browser) if word]
    return ", ".join(known) if known else UNKNOWN_DEVICE
