"""ZoG pages (pure): the address of a game's page by its name and its variants, the match key and the year rule, reading a page into the fan support, and the page of a link.

Spec 5.6 and 5.7 of stage 9.1b, ADR 0016. Pure: no database, no network, no clock; the client is
`app/providers/zog.py`.

- **The address** of a name (`address_of`): accents dropped (NFKD), lower case, «'», «’» and «.» removed, every other
  run of characters outside `[a-z0-9]` → «_», trimmed. Finding a page tries, in order and each once, at most four
  addresses (`addresses`): the name, the name with its numbers switched (a Roman word II–X to Arabic, or, when it has
  none, an Arabic word 2–10 to Roman), the name before the first «:» or « - » / « – », and the switch of that.
- **A found page is taken** (`matches`) only when the match key of ZoG's name (accents dropped, lower case, «ё» → «е»,
  everything but letters, digits and spaces dropped, Roman words II–X → Arabic, spaces squeezed) equals the key of
  one of the game's names (the original, the Russian, either before its «:»), and the page's year, when both have
  one, is not earlier than the year before the game's.
- **Reading a page** (`read_page`): the `<title>` «Ошибка» — no such page (ZoG answers 200 for it, `None`); «<name> |
  Игровой архив на Zone of Games» — a game page; any other title — the layout is unreadable (`UnreadablePage`). The
  year is the first `/games/year/<YYYY>.html` after «В официальной продаже с». The entries are the links to
  `/games/<page>/files/<n>.html` after «Переводы:» up to the next `</table>`: no «Переводы:» — no translations
  (Support(no, no)); «Переводы:» with no such link — the entries are unreadable (`GamePage.support` None). An entry
  counts when its text starts with «Русификатор (»: «текст» in the first brackets gives text, «звук» voice; one «для
  <X>-версии» (or «-версий») whose X has no word «ПК» is not counted: another platform, of one word or more («Xbox
  360», «PS4- и PS5»).
- **The page of a link** (`page_of`): `http(s)://(www.)zoneofgames.ru/games/<page>/…` → `<page>`, lower case.
"""

import html
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.tracker.russian import Support
from app.tracker.text import key

PAGE_URL = "https://www.zoneofgames.ru/games/{page}/"
MAX_ADDRESSES = 4  # requests to find a page
ERROR_TITLE = "Ошибка"
TITLE_END = " | Игровой архив на Zone of Games"
_HOSTS = ("zoneofgames.ru", "www.zoneofgames.ru")

_ROMAN = {"II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10}
_ARABIC = {number: roman for roman, number in _ROMAN.items()}
_ROMAN_WORD = re.compile(r"\b(" + "|".join(sorted(_ROMAN, key=len, reverse=True)) + r")\b")
_ARABIC_WORD = re.compile(r"(?<![\w.])(10|[2-9])(?!\w|\.\d)")
_SPLIT = re.compile(r":| - | – ")
_DROPPED = re.compile(r"['’.]")
_NOT_ADDRESS = re.compile(r"[^a-z0-9]+")
_LINK_PATH = re.compile(r"/games/([a-z0-9_]+)(?:/.*)?", re.IGNORECASE)

_TITLE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_SOLD_FROM = "В официальной продаже с"
_YEAR = re.compile(r"/games/year/(\d{4})\.html")
_TRANSLATIONS = "Переводы:"
_ENTRY = re.compile(r"""<a\s+href=['"]/games/[a-z0-9_]+/files/\d+\.html['"][^>]*>(.*?)</a>""", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_RUSSIAN_ENTRY = "Русификатор ("
_PLATFORM = re.compile(r"для\s+(.+?)-верси[ийя]")  # «для Xbox 360-версии», «для PS4- и PS5-версий»
_PC = "ПК"


class UnreadablePage(ValueError):
    """The page is not «Ошибка» and not a game page by its title: ZoG changed its layout."""


@dataclass(frozen=True)
class GamePage:
    """A game page: ZoG's `name`, its `year` (None — none), and the fan support (None — the entries are unreadable)."""

    name: str
    year: int | None
    support: Support | None


# --- addresses -------------------------------------------------------------------------------------------------------

def _plain(text: str) -> str:
    """Accents dropped: the letters without their combining marks (NFKD)."""
    return "".join(char for char in unicodedata.normalize("NFKD", text) if not unicodedata.combining(char))


def address_of(name: str) -> str:
    """The page address of a name: «Baldur's Gate 3» → `baldurs_gate_3`; empty — the name has no Latin letter or
    digit."""
    text = _DROPPED.sub("", _plain(name).lower())
    return _NOT_ADDRESS.sub("_", text).strip("_")


def switch_numbers(name: str) -> str:
    """The Roman words II–X to Arabic; a name with none — its Arabic words 2–10 to Roman; no number — the same name."""
    if _ROMAN_WORD.search(name):
        return _ROMAN_WORD.sub(lambda found: str(_ROMAN[found.group(1)]), name)
    return _ARABIC_WORD.sub(lambda found: _ARABIC[int(found.group(1))], name)


def before_split(name: str) -> str:
    """The name before the first «:» or « - » / « – »; none — the whole name."""
    return _SPLIT.split(name, maxsplit=1)[0].strip()


def addresses(name: str) -> list[str]:
    """The addresses to try for a game, in order, each once, at most four: the name, its numbers switched, the name
    before «:» or a dash, and the switch of that. Empty addresses are skipped."""
    short = before_split(name)
    found: list[str] = []
    for variant in (name, switch_numbers(name), short, switch_numbers(short)):
        address = address_of(variant)
        if address and address not in found:
            found.append(address)
    return found[:MAX_ADDRESSES]


def page_url(page: str) -> str:
    """The address of the game page on ZoG: `https://www.zoneofgames.ru/games/<page>/`."""
    return PAGE_URL.format(page=page)


def page_of(link: str) -> str | None:
    """The page of a link to a game on ZoG (`http(s)://(www.)zoneofgames.ru/games/<page>/…`, the rest of the path, the
    query and the fragment ignored), lower case; None — not such a link."""
    try:
        parts = urlsplit(link.strip())
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or (parts.hostname or "") not in _HOSTS:
        return None
    found = _LINK_PATH.fullmatch(parts.path)
    return found.group(1).lower() if found else None


# --- the match ---------------------------------------------------------------------------------------------------------

def match_key(name: str) -> str:
    """«S.T.A.L.K.E.R. 2: Heart of Chornobyl*» → «stalker 2 heart of chornobyl»; «Hades II» → «hades 2»."""
    text = _plain(key(name))  # case and «ё» as everywhere (`text.key`), then the accents
    text = "".join(char for char in text if char.isalnum() or char.isspace())
    words = [str(_ROMAN[word.upper()]) if word.upper() in _ROMAN else word for word in text.split()]
    return " ".join(words)


def matches(page: GamePage, names: tuple[str, ...], year: int | None) -> bool:
    """The page is the game's: ZoG's name has the key of one of `names` (the original and the Russian name) or of
    either before its «:», and the page's year, when both have one, is not earlier than the year before the game's."""
    keys = {match_key(name) for name in names if name} | {match_key(name.split(":", 1)[0]) for name in names if name}
    keys.discard("")
    if match_key(page.name) not in keys:
        return False
    return page.year is None or year is None or page.year >= year - 1


# --- reading a page --------------------------------------------------------------------------------------------------

def read_page(text: str) -> GamePage | None:
    """The page as ZoG gave it: None — no such page («Ошибка»); a `GamePage`; `UnreadablePage` — another title."""
    found = _TITLE.search(text)
    title = html.unescape(found.group(1)).strip() if found else ""
    if title == ERROR_TITLE:
        return None
    if not title.endswith(TITLE_END) or not title[: -len(TITLE_END)].strip():
        raise UnreadablePage(f"not a ZoG game page title: {title[:80]!r}")
    return GamePage(title.split(" | ", 1)[0].strip(), _sold_from_year(text), _support(text))


def _sold_from_year(text: str) -> int | None:
    start = text.find(_SOLD_FROM)
    found = _YEAR.search(text, start) if start >= 0 else None
    return int(found.group(1)) if found else None


def _support(text: str) -> Support | None:
    """The fan support of the entries after «Переводы:»; no such word — Support(no, no); no entry link — None."""
    start = text.find(_TRANSLATIONS)
    if start < 0:
        return Support(False, False)
    end = text.find("</table>", start)
    entries = [_entry_text(entry) for entry in _ENTRY.findall(text, start, end if end >= 0 else len(text))]
    if not entries:
        return None
    counted = [parts for parts in map(entry_parts, entries) if parts is not None]
    return Support(any(parts.text for parts in counted), any(parts.voice for parts in counted))


def _entry_text(raw: str) -> str:
    return " ".join(html.unescape(_TAG.sub("", raw)).split())


def entry_parts(entry: str) -> Support | None:
    """What one entry gives: None — not counted (not a Russian patch, another platform, nothing in the brackets);
    «Русификатор (текст и звук) - для ПК-версии» → Support(yes, yes)."""
    if not entry.startswith(_RUSSIAN_ENTRY) or ")" not in entry[len(_RUSSIAN_ENTRY):]:
        return None
    inside, rest = entry[len(_RUSSIAN_ENTRY):].split(")", 1)
    platform = _PLATFORM.search(rest)
    if platform is not None and _PC not in re.findall(r"\w+", platform.group(1).upper()):
        return None
    words = set(re.findall(r"\w+", inside.lower()))
    parts = Support("текст" in words, "звук" in words)
    return parts if parts.any else None
