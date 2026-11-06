"""Name candidates of an inbox item and the links of sources it carries (spec 3 and 4 of stage 6.4), pure: no database,
no network, no clock.

The rules pick the names that may be the title out of what the owner sent: cleaning line by line, the kinds of
candidates with their weights (a name message, an episode line, a bold piece, a Latin run, a quote, a Cyrillic name after
a kind word, the fallback of the first line), the stop list, merging into a longer name, the years, and the query
«Найти» searches by. One name key (`name_key`) compares every two names here. The links of an item are read into typed
values here; looking them up is the work of `offers`.

Counting: a weight is added to a name every time a rule finds it. A name found again in the text by a Latin run, a quote
or a Cyrillic name after a kind word adds 2 per extra time; a bold piece, a name message, an episode head, a slug and
the fallback are the same occurrence as the text they come from and add only their weight.
"""

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.tracker.models import TitleKind
from app.tracker.text import key

NAME_MESSAGE_WORDS = 8  # a name message is one line of at most this many words; a longer name is no name
QUERY_LENGTH = 60  # characters of the text «Найти» searches by when no candidate was found, cut at a word
MAX_LINKS = 3  # links of sources an item reads
MAX_CYRILLIC_WORDS = 6

WHOLE, EPISODE_HEAD, SLUG, BOLD, QUOTE, QUOTE_AFTER_MARKER, LATIN, CYRILLIC, FALLBACK = (
    100, 50, 50, 8, 3, 0.5, 6, 5, 1,
)
FIRST_LINE_BONUS = 4  # a Latin run, or a quote that starts the line
AFTER_KIND_WORD_BONUS = 4
AFTER_MARKER_PENALTY = 5
LONE_WORD_PENALTY = 1
REPEAT_BONUS = 2

_INVISIBLE = re.compile("[​-‏⁠﻿ㅤᅟᅠ­]")
_SIGNATURE = re.compile(r"подписаться|подпишись|підписатись|subscribe", re.I)
_URL = re.compile(r"https?://\S+|\b(?:www\.)?(?:t\.me|jut\.su|jutsu\.ru)/\S+", re.I)
_HANDLE = re.compile(r"(?<!\w)@\w+")
_SCORE_LINE = re.compile(r"\d+(?:[.,]\d+)?\s*/\s*10\b|\b(?:бал|балл|балів|бали|баллов|points)\b", re.I)
_YEAR = re.compile(r"(?<!\d)(19[5-9]\d|20\d\d)(?!\d)")

_LATIN_WORD = r"[A-Za-z0-9][A-Za-z0-9'’.&+]*(?:-[A-Za-z0-9'’]+)*"
# words join by a space, `: ` (not before a bare number: «Bleach: 3 серия») and ` - `
_LATIN_RUN = re.compile(rf"{_LATIN_WORD}(?:(?::\s+(?!\d+(?!\w))|\s+[-–]\s+|\s+){_LATIN_WORD})*")
_LATIN_WORDS = re.compile(_LATIN_WORD)
_QUOTE = re.compile(r"[«\"“„]([^«»\"“”„]{1,80})[»\"”“]")
_EPISODE_HEAD = re.compile(r"^(.+?):\s*\d+\s*(?:сери\w*|сері[яюї]\w*|епізод\w*|эпизод\w*)", re.I)
_PLATFORM_WORD = re.compile(r"xbox|nintendo|playstation|ps\d+|switch", re.I)
_SHOP_WORD = re.compile(r"steam|quest", re.I)  # dropped as the start of a run only when a word follows

_KIND_WORDS = (
    r"игр[аыуе]|гр[аиу]|сериал[аеу]?|серіал[уі]?|аниме|аніме|фильм[аеу]?|фільм[уі]?|мультфильм\w*|"
    r"экранизаци[яию]|екранізаці[яїю]|ремастер|ремейк|дорам[аыу]|экшн|экшен|лайфсим|симулятор|приключени[ея]"
)
# the serial «серии» after «известн… по» is not part of the marker: a name after it keeps its weight
_MARKERS = (
    r"смес\w*|как в|как у|вроде|наподобие|аналог\w*|в духе|похож\w*|наследник\w*|наступник\w*|преемник\w*|"
    r"известн\w* по|відом\w* за|вытеснив|помимо|кроме|после|на основе|по мотивам|от|від|from|студи\w*|студі\w*|"
    r"компани\w*|компані\w*|издател\w*|видав\w*|разработчик\w*|розробник\w*|выходцами из|из|магазин\w*|фестивал\w*"
)
_AFTER_KIND_WORD = re.compile(rf"\b(?:{_KIND_WORDS})\s*$", re.I)
_AFTER_MARKER = re.compile(rf"\b(?:{_MARKERS})\s*$", re.I)
_CYRILLIC_NAME = re.compile(rf"\b(?:{_KIND_WORDS})\s+((?-i:[А-ЯЁІЇЄҐ])[^.,!?:;—–(]*)", re.I)

STOP_NAMES = (
    "Steam", "PC", "ПК", "PS4", "PS5", "PlayStation", "Xbox", "Xbox One", "Xbox Series", "Xbox Series X|S", "Nintendo",
    "Nintendo Switch", "Nintendo Switch 2", "Switch", "Switch 2", "Quest", "Meta", "Meta Horizon", "Netflix", "HBO",
    "Apple TV+", "Disney+", "Amazon Prime Video", "YouTube", "Twitch", "Telegram", "IGN", "Metacritic", "Opencritic",
    "VR", "AR", "XR", "NPC", "AI", "DLC", "RU", "EU", "US", "UA", "Hard", "Easy", "Normal", "MAPPA", "A24", "Sony",
    "Microsoft", "Epic Games Store", "GOG", "itch.io",
)


@dataclass(frozen=True)
class Candidate:
    """A name the rules picked: the writing of its first appearance, its weight, where it first stands in the cleaned
    text (a count of characters)."""

    name: str
    weight: float
    first: int


@dataclass(frozen=True)
class SourceLink:
    """A link of a source read into what it points at: `source` is `steam`, `tmdb_movie`, `tmdb_tv`, `shikimori` or
    `imdb`; `ref` the number (`tt…` for IMDb); `kind` the kind of title it gives (`None` for IMDb, whose lookup
    finds out); `prefix` the letter before a Shikimori number, if any."""

    source: str
    ref: str
    kind: TitleKind | None
    prefix: str = ""


def name_key(name: str) -> str:
    """How two names are compared: `text.key`, then every run of characters that are not letters or digits is one
    space, outer spaces off («Control: Resonant» and «Control Resonant» are one key)."""
    return re.sub(r"[\W_]+", " ", key(name)).strip()


_STOP_KEYS = frozenset(name_key(name) for name in STOP_NAMES)


def years(text: str) -> tuple[int, ...]:
    """Every year 1950–2099 written in the text, each once, the earliest first."""
    return tuple(sorted({int(year) for year in _YEAR.findall(text)}))


def _lines(text: str) -> list[str]:
    """Lines of the text without invisible characters, the signature of a channel, URLs and handles; empty lines go."""
    lines = []
    for line in _INVISIBLE.sub("", text).splitlines():
        if _SIGNATURE.search(line):
            continue
        line = " ".join(_HANDLE.sub(" ", _URL.sub(" ", line)).split())
        if line:
            lines.append(line)
    return lines


def _readable(line: str) -> bool:
    """False for a press score («9/10», «85 балів») and a lone label left of a link («Main:»)."""
    if _SCORE_LINE.search(line):
        return False
    return not (line.endswith(":") and len(line.split()) == 1)


def _trim(raw: str) -> str:
    return re.sub(r"^[\W_]+|[\W_]+$", "", " ".join(raw.split()))


class _Pool:
    """The names found so far, by name key."""

    def __init__(self) -> None:
        self.names: dict[str, list] = {}  # key -> [name, weight, first, appearances]

    def add(self, raw: str, weight: float, at: int, *, again: bool = True) -> None:
        name = _trim(raw)
        name_k = name_key(name)
        if len(name_k) < 2 or name_k.replace(" ", "").isdigit() or name_k in _STOP_KEYS:
            return
        if len(name.split()) > NAME_MESSAGE_WORDS:
            return
        entry = self.names.setdefault(name_k, [name, 0.0, at, 0])
        entry[1] += weight
        entry[2] = min(entry[2], at)
        entry[3] += 1 if again else 0

    def merge_into_longer(self) -> None:
        """A name whose words stand inside a longer one is that longer name: its appearances count for it."""
        for short in sorted(self.names, key=lambda k: -len(k.split())):
            for longer in sorted(self.names, key=lambda k: -len(k.split())):
                if longer in self.names and len(longer.split()) > len(short.split()) and f" {short} " in f" {longer} ":
                    self.names[longer][3] += self.names[short][3]
                    self.names[longer][2] = min(self.names[longer][2], self.names[short][2])
                    del self.names[short]
                    break

    def ranked(self) -> list[Candidate]:
        found = [
            Candidate(name, weight + REPEAT_BONUS * max(0, count - 1), first)
            for name, weight, first, count in self.names.values()
        ]
        return sorted(found, key=lambda c: (-c.weight, c.first))


def _scan_line(pool: _Pool, line: str, at: int, first_line: bool) -> None:
    head = _EPISODE_HEAD.match(line)
    if head:
        pool.add(head.group(1), EPISODE_HEAD, at, again=False)
    spans = []
    for quote in _QUOTE.finditer(line):
        spans.append(quote.span())
        if _AFTER_MARKER.search(line[: quote.start()]):
            weight = QUOTE_AFTER_MARKER
        else:
            starts_line = first_line and not re.search(r"\w", line[: quote.start()])
            weight = QUOTE + (1 if starts_line else 0)
        pool.add(quote.group(1), weight, at + quote.start())
    for run in _LATIN_RUN.finditer(line):
        if any(start <= run.start() < end for start, end in spans):
            continue
        weight = _latin_weight(line, run, first_line)
        if weight is not None:
            pool.add(run.group(0), weight, at + run.start())
    for named in _CYRILLIC_NAME.finditer(line):
        words = named.group(1).split()[:MAX_CYRILLIC_WORDS]
        pool.add(" ".join(words), CYRILLIC, at + named.start(1))


def _latin_weight(line: str, run: re.Match, first_line: bool) -> float | None:
    """The weight of a Latin run, `None` for a dropped one (4.3)."""
    text = run.group(0)
    words = _LATIN_WORDS.findall(text)
    if not re.search(r"[A-Za-z]", text):
        return None  # digits and punctuation: «2027», «1.6.0»
    if _PLATFORM_WORD.fullmatch(words[0]) or (len(words) > 1 and _SHOP_WORD.fullmatch(words[0])):
        return None
    if len(words) == 1 and not first_line and len(_trim(text)) <= 3:
        return None  # «UG», «One», «NPC»
    before = line[: run.start()]
    weight = LATIN + (FIRST_LINE_BONUS if first_line else 0)
    weight += AFTER_KIND_WORD_BONUS if _AFTER_KIND_WORD.search(before) else 0
    weight -= AFTER_MARKER_PENALTY if _AFTER_MARKER.search(before) else 0
    if len(words) == 1 and not first_line and not text.isupper():
        weight -= LONE_WORD_PENALTY
    return weight


def _addresses(text: str, links: tuple[str, ...]) -> list[str]:
    """The addresses of an item: the entities first (in order of appearance), then the URLs left in the text."""
    found = [address.strip().rstrip(").,;") for address in [*links, *_URL.findall(text)]]
    return list(dict.fromkeys(address for address in found if address))


def _host_and_path(address: str) -> tuple[str, str]:
    """The host without `www.` in lower case and the path of an address; `("", "")` for one that cannot be read."""
    try:
        parts = urlsplit(address if "://" in address else f"https://{address}")
        host = parts.hostname or ""
    except ValueError:
        return "", ""
    return host.removeprefix("www."), parts.path


_NUMBER = r"(\d+)(?:-[^/]*)?(?:/|$)"
_TMDB_PREFIX = r"^/(?:[a-z]{2}(?:-[a-z]{2})?/)?"
_STEAM_HOST, _TMDB_HOST, _SHIKIMORI_HOST, _IMDB_HOST = (
    re.compile(host) for host in (r"store\.steampowered\.com", r"themoviedb\.org", r"shikimori\.[a-z]+", r"imdb\.com")
)
_STEAM_APP = re.compile(r"^/app/(\d+)", re.I)
_TMDB_MOVIE = re.compile(rf"{_TMDB_PREFIX}movie/{_NUMBER}", re.I)
_TMDB_TV = re.compile(rf"{_TMDB_PREFIX}tv/{_NUMBER}", re.I)
_SHIKIMORI_ANIME = re.compile(r"^/animes/([a-z]?\d+)(?:-[^/]*)?(?:/|$)", re.I)
_IMDB_TITLE = re.compile(r"^/(?:[a-z]{2}/)?title/(tt\d+)", re.I)
_GAME, _MOVIE, _SERIES, _ANIME = TitleKind.GAME, TitleKind.MOVIE, TitleKind.SERIES, TitleKind.ANIME
STEAM, IMDB = "steam", "imdb"  # the sources of links that are looked up in their own way (`offers`)
_LINK_RULES = (  # host, path, source, kind
    (_STEAM_HOST, _STEAM_APP, STEAM, _GAME),
    (_TMDB_HOST, _TMDB_MOVIE, "tmdb_movie", _MOVIE),
    (_TMDB_HOST, _TMDB_TV, "tmdb_tv", _SERIES),
    (_SHIKIMORI_HOST, _SHIKIMORI_ANIME, "shikimori", _ANIME),
    (_IMDB_HOST, _IMDB_TITLE, IMDB, None),
)


def source_links(text: str, links: tuple[str, ...] = ()) -> tuple[SourceLink, ...]:
    """The first `MAX_LINKS` links of sources of an item (its text and the addresses of its entities), in order of
    appearance, each once. Host match ignores `www.`, the scheme and the case; looking them up is not done here."""
    found: dict[tuple[str, str], SourceLink] = {}
    for address in _addresses(text, links):
        host, path = _host_and_path(address)
        for host_rule, path_rule, source, kind in _LINK_RULES:
            match = host_rule.fullmatch(host) and path_rule.search(path)
            if not match:
                continue
            ref, prefix = match.group(1), ""
            if source == "shikimori":
                prefix, ref = re.match(r"([a-z]?)(\d+)", ref, re.I).groups()
            found.setdefault((source, ref), SourceLink(source, ref, kind, prefix.lower()))
            break
    return tuple(found.values())[:MAX_LINKS]


def _slugs(text: str, links: tuple[str, ...]) -> list[str]:
    """The names hidden in the jut.su / jutsu.ru links: `kikansha-no-mahou` is «kikansha no mahou»."""
    slugs: dict[str, str] = {}  # the same slug on both sites is one name
    for address in _addresses(text, links):
        host, path = _host_and_path(address)
        match = re.match(r"^/([A-Za-z0-9][A-Za-z0-9_-]*)", path)
        if host in ("jut.su", "jutsu.ru") and match:
            name = match.group(1).replace("-", " ").replace("_", " ")
            slugs.setdefault(name_key(name), name)
    return list(slugs.values())


def _is_name_message(lines: list[str], forwarded: bool) -> bool:
    return len(lines) == 1 and len(lines[0].split()) <= NAME_MESSAGE_WORDS and not forwarded and _readable(lines[0])


def is_name_message(text: str, *, forwarded: bool = False) -> bool:
    """Whether the whole text is a name (4.2): one line of at most 8 words, not a forward (a joined item has two
    lines); only a name message has its typo corrected (5.4)."""
    return _is_name_message(_lines(text), forwarded)


def candidates(
    text: str, *, bold: tuple[str, ...] = (), links: tuple[str, ...] = (), forwarded: bool = False
) -> list[Candidate]:
    """The name candidates of an item, the most likely first (equal weights: the one that stands first in the text)."""
    lines = _lines(text)
    pool = _Pool()
    if _is_name_message(lines, forwarded):
        pool.add(lines[0], WHOLE, 0, again=False)
    at = 0
    for number, line in enumerate(lines):
        if _readable(line):
            _scan_line(pool, line, at, number == 0)
        at += len(line) + 1
    joined = "\n".join(lines)
    for slug in _slugs(text, links):
        pool.add(slug, SLUG, len(joined), again=False)
    for piece in bold:
        piece = " ".join(_INVISIBLE.sub("", piece).split())
        found = joined.find(piece)
        pool.add(piece, BOLD, found if found >= 0 else len(joined), again=False)
    if not pool.names:
        for line in filter(_readable, lines):
            pool.add(" ".join(re.split(r"[.!?—–]", line, maxsplit=1)[0].split()[:NAME_MESSAGE_WORDS]), FALLBACK, 0)
            break
    pool.merge_into_longer()
    return pool.ranked()


def text_query(text: str) -> str:
    """The first `QUERY_LENGTH` characters of the text, cut at a word."""
    flat = " ".join(text.split())
    if len(flat) <= QUERY_LENGTH:
        return flat
    head = flat[: QUERY_LENGTH + 1]
    head = head.rsplit(" ", 1)[0] if " " in head else flat[:QUERY_LENGTH]
    return head.rstrip(" ,.;:—-")


def query_of(
    text: str, *, bold: tuple[str, ...] = (), links: tuple[str, ...] = (), forwarded: bool = False
) -> str:
    """What «Найти» of the web searches by: the first candidate, none — the beginning of the text."""
    found = candidates(text, bold=bold, links=links, forwarded=forwarded)
    return found[0].name if found else text_query(text)
