"""Offers of an inbox item: the records the sources give for its links and its name candidates, in the order the owner
sees them, and the text of an offer card (spec 3, 5 and 6.1 of stage 6.4).

An offer («предложение») is a record of a source shown as «Это оно?» with «Да» / «Нет»; a search suggestion of the
source is a `Suggestion`. Every request goes through `Titles` (the search of the kind, or a lookup by the number of a
link): ahead of the paced polling, and each record marked with its title when it is in the list.

- Links: each of the first 3 links of a source is looked up (a Steam number IGDB does not know gives the name Steam
  calls it, a name candidate of the game); the item's kind is the kind of the first offer.
- Candidates: those whose weight is at least half of the first one's, at most 3; a candidate's records that match it
  by the name key — exact, then prefix — at most 2, new first (5.3); the first candidate alone, with no match, takes the
  source's first record as a weak offer. A name message of 2 words or more with no match is searched again without one
  word at a time to correct a typo (5.4).
- At most 3 offers in all, each record once. A source failing before the first offer fails the analysis; after it,
  the failure goes to the log and what was found is shown.
"""

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any

from app.tracker.candidates import IMDB, STEAM, WHOLE, Candidate, SourceLink, name_key
from app.tracker.cards import format_date
from app.tracker.errors import SourceFailed, SourceNotConfigured
from app.tracker.kinds import KINDS
from app.tracker.models import TitleKind
from app.tracker.sources.dates import parse_date

if TYPE_CHECKING:
    from app.tracker.polling import Pollers
    from app.tracker.titles import Titles

HEADING = "Это оно?"
CORRECTED = "Возможно, вы имели в виду:"  # the heading of the offers of a corrected typo
NO_DATE = "дата не объявлена"
MAX_OFFERS = 3
MAX_CANDIDATES = 3  # candidates searched
PER_CANDIDATE = 2  # records a candidate gives
MAX_TYPO_SEARCHES = 3  # searches of the name without one word
CLOSE = 0.85  # `difflib` ratio of the keys of a close name (5.4)
NEW_FOR_YEARS = 2  # a record is new from the same day this many years ago

EXACT, PREFIX = 2, 1


@dataclass(frozen=True)
class Offer:
    """A record of a source the owner is asked about. `shown`: its card was sent; `title_id`: the title in the list it
    is, as the search found it (not stored: it is checked again when the card is shown)."""

    kind: TitleKind
    external_id: str
    name: str
    original_name: str
    released: date | None
    details: str | None
    poster: str | None  # as the title stores it (`poster_path`)
    heading: str
    shown: bool = False
    title_id: int | None = None

    def stored(self) -> dict[str, Any]:
        """As the item keeps it (`inbox_items.offers`)."""
        return {
            "kind": self.kind.value,
            "external_id": self.external_id,
            "name": self.name,
            "original_name": self.original_name,
            "released": self.released.isoformat() if self.released else None,
            "details": self.details,
            "poster": self.poster,
            "heading": self.heading,
            "shown": self.shown,
        }

    @classmethod
    def read(cls, raw: dict[str, Any]) -> "Offer":
        """What `stored` wrote, strictly: garbage is a bug of ours (rule 9)."""
        return cls(
            kind=TitleKind(raw["kind"]),
            external_id=str(raw["external_id"]),
            name=raw["name"],
            original_name=raw.get("original_name") or "",
            released=parse_date(raw.get("released")),
            details=raw.get("details"),
            poster=raw.get("poster"),
            heading=raw["heading"],
            shown=bool(raw.get("shown")),
        )


def offer_of(suggestion: Any, heading: str) -> Offer:
    return Offer(
        kind=suggestion.kind,
        external_id=suggestion.external_id,
        name=suggestion.name,
        original_name=suggestion.original_name,
        released=suggestion.released,
        details=suggestion.details,
        poster=suggestion.poster_path,
        heading=heading,
        title_id=suggestion.title_id,
    )


@dataclass(frozen=True)
class Found:
    """What the searches of an item gave. No offers: `not_connected` (games without the keys of IGDB) or `failed` (a
    source did not answer) says why, else nothing was found."""

    offers: tuple[Offer, ...] = ()
    kind: TitleKind | None = None  # of the links: the kind of the first offer; None — the links gave nothing
    failed: bool = False
    not_connected: bool = False


def new_from(today: date) -> date:
    """The first day a record counts as new: the same day `NEW_FOR_YEARS` years ago (29 February → 28 February)."""
    try:
        return today.replace(year=today.year - NEW_FOR_YEARS)
    except ValueError:
        return today.replace(year=today.year - NEW_FOR_YEARS, day=28)


def searched(candidates: Sequence[Candidate]) -> list[Candidate]:
    """The candidates searched: those whose weight is at least half of the first one's, at most `MAX_CANDIDATES`."""
    if not candidates:
        return []
    return [c for c in candidates if c.weight >= candidates[0].weight / 2][:MAX_CANDIDATES]


def _names(record: Any) -> list[str]:
    return [name for name in (record.name, record.original_name, *record.other_names) if name]


def match(name: str, record: Any) -> int:
    """`EXACT` when a name of the record has the key of `name`, `PREFIX` when one starts with it and a space, else 0."""
    wanted = name_key(name)
    if not wanted:
        return 0
    found = 0
    for key in map(name_key, _names(record)):
        if key == wanted:
            return EXACT
        if key.startswith(f"{wanted} "):
            found = PREFIX
    return found


def _close_name(name: str, record: Any) -> tuple[float, str]:
    """The best ratio of the first words of a name of the record to `name` (as many words as `name` has) and those
    words without trailing punctuation; (0, "") when no name of the record is that long."""
    count = len(name.split())
    wanted = name_key(name)
    best = (0.0, "")
    for other in _names(record):
        words = other.split()
        if len(words) < count:
            continue
        head = " ".join(words[:count])
        ratio = SequenceMatcher(None, wanted, name_key(head)).ratio()
        if ratio > best[0]:
            best = (ratio, re.sub(r"[\W_]+$", "", head))
    return best


class _Gathered:
    """The offers so far, each record once, at most `MAX_OFFERS`, and the order of 5.3 for the records of a group."""

    def __init__(self, years: Sequence[int], new_since: date) -> None:
        self.years = set(years)
        self.new_since = new_since
        self.offers: list[Offer] = []

    @property
    def full(self) -> bool:
        return len(self.offers) >= MAX_OFFERS

    def add(self, records: Sequence[Any], heading: str) -> None:
        for record in records:
            taken = {(o.kind, o.external_id) for o in self.offers}
            if not self.full and (record.kind, record.external_id) not in taken:
                self.offers.append(offer_of(record, heading))

    def group(self, record: Any) -> int:
        """0 a year of the item, 1 new with a date, 2 without a date (counted as new), 3 the rest."""
        day = record.released
        if day is not None and day.year in self.years:
            return 0
        if day is not None and day >= self.new_since:
            return 1
        return 2 if day is None else 3

    def matching(self, name: str, records: Sequence[Any]) -> list[Any]:
        """The records that match `name`: exact first, then prefix, each group new first, then the order of the source;
        at most `PER_CANDIDATE`."""
        scored = [(match(name, record), index, record) for index, record in enumerate(records)]
        ordered = sorted((s for s in scored if s[0]), key=lambda s: (-s[0], self.group(s[2]), s[1]))
        return [record for _, _, record in ordered][:PER_CANDIDATE]


class OfferSearch:
    """The searches of an item through the sources of the core."""

    def __init__(self, titles: "Titles", pollers: "Pollers", imdb_source: Any = None) -> None:
        self.titles = titles
        self.pollers = pollers
        self.imdb_source = imdb_source

    async def by_kind(
        self, kind: TitleKind, candidates: Sequence[Candidate], *, name_message: bool, years: Sequence[int],
        new_since: date,
    ) -> Found:
        """The offers of the name candidates in the source of the kind the owner chose."""
        gathered = _Gathered(years, new_since)
        try:
            await self._of_candidates(kind, candidates, name_message, gathered)
        except SourceNotConfigured:
            return Found(kind=kind, not_connected=True)
        except SourceFailed as exc:
            logging.warning("searching the offers of an inbox item failed: %r", exc)
            return Found(kind=kind, failed=True)
        return Found(tuple(gathered.offers), kind)

    async def by_links(
        self, links: Sequence[SourceLink], candidates: Sequence[Candidate], *, years: Sequence[int], new_since: date
    ) -> Found:
        """The offers of the links, then of the name candidates in the source of the kind of the first one. A link that
        fails or that nobody knows gives nothing; no offer at all — the item goes on as one without links."""
        gathered = _Gathered(years, new_since)
        named: list[tuple[Candidate, TitleKind]] = []  # the names Steam gives the numbers IGDB does not know
        kind: TitleKind | None = None
        not_connected = False
        for link in links:
            try:
                records, steam_name = await self._look_up(link)
            except SourceNotConfigured:
                not_connected = True
                continue
            except SourceFailed as exc:
                logging.warning("looking up a link of an inbox item failed: %r", exc)
                continue
            gathered.add(records, HEADING)
            if records and kind is None:
                kind = records[0].kind
            if steam_name:
                named.append((Candidate(steam_name, WHOLE, -1), link.kind))
        # the kind of the first link that gave an offer; none did — the kind of a Steam name, searched below
        kind = kind or next((of_kind for _, of_kind in named), None)
        if kind is None:
            return Found(not_connected=not_connected)
        ours = [candidate for candidate, of_kind in named if of_kind is kind]  # a Steam name is a name of a game
        ranked = sorted([*ours, *candidates], key=lambda c: (-c.weight, c.first))
        try:
            await self._of_candidates(kind, ranked, False, gathered)
        except (SourceFailed, SourceNotConfigured) as exc:  # no offer yet: the item goes on as one without links
            logging.warning("searching the names of an inbox item with links failed: %r", exc)
        return Found(tuple(gathered.offers), kind if gathered.offers else None)

    # --- the requests ---------------------------------------------------------------------------

    async def _look_up(self, link: SourceLink) -> tuple[list[Any], str | None]:
        """The records a link names, and the name Steam gives a number IGDB does not know."""
        if link.source == IMDB:  # TMDb's `/find` answers a movie or a series
            if self.imdb_source is None:
                return [], None
            source = self.imdb_source
            return await self.titles.look_up(source, lambda: _listed(source.suggest_by_imdb(link.ref))), None
        try:
            source = self.pollers.of(link.kind).source
        except KeyError:  # the core has no source of that kind
            return [], None
        if link.source != STEAM:
            return await self.titles.look_up(source, lambda: _listed(source.suggest_by_id(link.ref))), None
        records = await self.titles.look_up(source, lambda: source.suggest_by_steam(link.ref))
        return records, (None if records else await source.steam_name(link.ref))

    async def _search(self, kind: TitleKind, query: str, tolerated: bool) -> list[Any] | None:
        """The search of the kind. A failure raises, unless `tolerated` (something was found already): then it goes to
        the log and the answer is None — no more searches."""
        try:
            return await self.titles.search(kind, query)
        except KeyError as exc:  # the core has no source of that kind: as if it failed
            failure = SourceFailed(kind.value)
            failure.__cause__ = exc
        except SourceFailed as exc:
            failure = exc
        if not tolerated:
            raise failure
        logging.warning("a search of an inbox item failed after an offer was found: %r", failure)
        return None

    # --- the candidates -------------------------------------------------------------------------

    async def _of_candidates(
        self, kind: TitleKind, candidates: Sequence[Candidate], name_message: bool, gathered: _Gathered
    ) -> None:
        for number, candidate in enumerate(searched(candidates)):
            if gathered.full:
                return
            records = await self._search(kind, candidate.name, bool(gathered.offers))
            if records is None:
                return
            picked = gathered.matching(candidate.name, records)
            if picked or number > 0:
                gathered.add(picked, HEADING)
                continue
            if name_message and len(candidate.name.split()) >= 2:
                corrected = await self._corrected(kind, candidate.name, gathered, bool(gathered.offers or records))
                gathered.add(corrected, CORRECTED)
            gathered.add(records[:1], HEADING)  # the weak offer: the source found it by a name it does not return

    async def _corrected(self, kind: TitleKind, name: str, gathered: _Gathered, tolerated: bool) -> list[Any]:
        """A typo of a name message (5.4): the name without one word, from the last word to the first, until a search
        gives a close record; then its corrected name is searched. Nothing close: no offers."""
        words = name.split()
        for dropped in list(reversed(range(len(words))))[:MAX_TYPO_SEARCHES]:
            records = await self._search(kind, " ".join(words[:dropped] + words[dropped + 1:]), tolerated)
            if records is None:
                return []
            scored = [(_close_name(name, record), index, record) for index, record in enumerate(records)]
            close = [s for s in scored if s[0][0] >= CLOSE]
            if not close:
                continue
            (_, corrected), _, record = max(close, key=lambda s: (s[0][0], -s[1]))
            found = await self._search(kind, corrected, tolerated)
            if found is None:
                return [record]
            return gathered.matching(corrected, found) or [record]
        return []


async def _listed(asked: Any) -> list[Any]:
    """A lookup that gives one record or None, as a list."""
    record = await asked
    return [] if record is None else [record]


# --- the card -------------------------------------------------------------------------------------


def released_line(released: date | None, today: date) -> str:
    """Out: the year («2026»); in the future: «выйдет 12 февраля 2027»; no date: «дата не объявлена»."""
    if released is None:
        return NO_DATE
    return f"выйдет {format_date(released)}" if released > today else str(released.year)


def card_text(offer: Offer, today: date) -> str:
    """The text of an offer card (6.1): the heading, the icon and the name, the original name when its key differs, the
    date and the details of the record (the platforms of a game)."""
    lines = [offer.heading, "", f"{KINDS[offer.kind].icon} {offer.name}"]
    if offer.original_name and name_key(offer.original_name) != name_key(offer.name):
        lines.append(offer.original_name)
    lines.append(" · ".join(part for part in (released_line(offer.released, today), offer.details) if part))
    return "\n".join(lines)


def shown(offers: Sequence[Offer], number: int) -> list[Offer]:
    """The offers with the card of `number` marked as sent."""
    return [replace(offer, shown=True) if index == number else offer for index, offer in enumerate(offers)]
