"""The blocks of the web card that depend on the kind: the platforms, the line of an expansion and the follow lists.

The follow lists are the sequels of a watched film and the expansions and the games of the series of a game — one row type
and one block type for all three. The rest of the card, its routes and its parts every kind has, is in `card`.

The blocks are made of what the core gives (`TitleCard`) and carry the words of the page; the template compares no kind
and no status. «Следить» of a row goes to `card_follow` with the kind, the id of the row and the key of its block, so an
error can be shown in the block the press came from (spec 7.2 of stage 6.3).
"""

from datetime import datetime
from typing import NamedTuple

from fastapi import Request

from app.tracker.cards import (
    PARENT_LINE_START, FollowLine, FollowUpsView, SequelsView, TitleCard, format_past_moment,
)
from app.tracker.kinds import KINDS

PLATFORMS_HINT = "Галочка — «играю здесь»: о выходе на отмеченных платформах придёт сообщение; у ПК — ещё цены и скидки Steam"
SETTINGS_WORD = "Настройках"  # in the line of a game on none of the owner's platforms: a link to the settings

NO_SEQUELS = "Продолжений пока нет. Проверяю раз в неделю"
NOT_CHECKED = "Ещё не проверял — проверю в ближайшие минуты"
SEQUELS_KEY = "sequels"  # the keys of the blocks: the ids of their headings and the `block` a press sends
EXPANSIONS_KEY = "expansions"
FOLLOW_UPS_KEY = "follow-ups"  # the one block of a game that was not checked yet


def address(request: Request, name: str, **path: int | str) -> str:
    return str(request.app.url_path_for(name, **path))


# --- the platforms of a game ----------------------------------------------------------------------------------------


class PlatformLine(NamedTuple):
    text: str  # «PS5 — 27 марта 2015 (версия для PS4)»
    playing: bool  # the mark «играю здесь»
    address: str  # where the mark is sent


class NotePart(NamedTuple):
    text: str
    link: str  # the address the piece leads to; empty: plain text


class StoreLine(NamedTuple):
    label: str  # «Открыть в Steam»
    url: str


class PlatformsBlock(NamedTuple):
    """«Платформы» of a game: the rows with their marks, or the line of why there are none; the links to the stores."""

    lines: list[PlatformLine]
    note: list[NotePart]  # empty: there are rows
    stores: list[StoreLine]


def _note_parts(request: Request, note: str) -> list[NotePart]:
    """The line of why a game lists no platform, with «Настройках» as a link to them where it says so."""
    before, word, after = note.partition(SETTINGS_WORD)
    if not word:
        return [NotePart(note, "")]
    parts = [NotePart(before, ""), NotePart(word, address(request, "settings"))]
    return parts + [NotePart(after, "")] if after else parts


def platforms(request: Request, card: TitleCard) -> PlatformsBlock | None:
    """The block of a game, which always has either rows or the line of why there are none; other kinds have none."""
    if not (card.platforms or card.platform_note):
        return None
    lines = [
        PlatformLine(
            row.text, row.playing,
            str(request.app.url_path_for("card_platform", title_id=card.id, platform=row.platform)),
        )
        for row in card.platforms
    ]
    note = [] if lines else _note_parts(request, card.platform_note)
    return PlatformsBlock(lines, note, [StoreLine(link.label, link.url) for link in card.store_links])


# --- the line of an expansion ---------------------------------------------------------------------------------------


class ParentLine(NamedTuple):
    """«Дополнение к игре «Ведьмак 3: Дикая охота»»: the name is a link to the card when the game is in the list."""

    start: str  # «Дополнение к игре «»
    name: str
    link: str  # the card of the game; empty: plain text


def parent_of(request: Request, card: TitleCard) -> ParentLine | None:
    if card.parent is None:
        return None
    link = address(request, "card", title_id=card.parent.title_id) if card.parent.title_id is not None else ""
    return ParentLine(PARENT_LINE_START, card.parent.name, link)


# --- the follow lists -----------------------------------------------------------------------------------------------


class FollowRow(NamedTuple):
    name: str
    when: str  # «15 декабря 2028», «2027» or «дата не объявлена»
    external_id: str  # what «Следить» sends
    card: str | None  # the card of the title when it is in the list already


class FollowBlock(NamedTuple):
    """A list of titles to follow: a heading, a sentence, the rows (maybe none), where «Следить» is sent."""

    key: str  # `SEQUELS_KEY`, `EXPANSIONS_KEY` or `FOLLOW_UPS_KEY`
    heading: str
    sentence: str  # empty: none
    rows: list[FollowRow]
    address: str  # where «Следить» is sent
    kind: str  # the kind «Следить» sends: the one of the card
    error: str = ""  # what went wrong with the last «Следить» of this block; empty: nothing


class FollowError(NamedTuple):
    """What went wrong with a «Следить» and the block it came from; empty `text`: nothing went wrong."""

    block: str = ""
    text: str = ""


def _rows(request: Request, lines: tuple[FollowLine, ...]) -> list[FollowRow]:
    return [
        FollowRow(
            line.name, line.when, line.external_id,
            None if line.title_id is None else address(request, "card", title_id=line.title_id),
        )
        for line in lines
    ]


def series_sentence(collections: tuple[str, ...]) -> str:
    """«Новые игры серии «The Witcher» на ваших платформах»; two series or more: «серий «A», «B»»; none: «серии»."""
    if not collections:
        return "Новые игры серии на ваших платформах"
    word = "серии" if len(collections) == 1 else "серий"
    return f"Новые игры {word} {', '.join(f'«{name}»' for name in collections)} на ваших платформах"


def _film_block(request: Request, card: TitleCard, view: SequelsView, where: str) -> FollowBlock:
    if not view.checked:  # the first look runs right after «Посмотрел»
        sentence = f"Ищу продолжения в коллекции {KINDS[card.kind].source_name} — обновите страницу через минуту"
    else:
        sentence = "" if view.lines else NO_SEQUELS
    return FollowBlock(SEQUELS_KEY, "Продолжения", sentence, _rows(request, view.lines), where, card.kind.value)


def _game_blocks(request: Request, card: TitleCard, view: FollowUpsView, where: str, now: datetime) -> list[FollowBlock]:
    kind = card.kind.value
    if not view.checked or view.checked_at is None:
        return [FollowBlock(FOLLOW_UPS_KEY, "Дополнения и продолжения", NOT_CHECKED, [], where, kind)]
    checked = f"Проверяю раз в неделю, последняя проверка — {format_past_moment(view.checked_at, now.astimezone(view.checked_at.tzinfo))}"
    expansions = FollowBlock(
        EXPANSIONS_KEY, "Дополнения", checked if view.expansions else f"Дополнений пока нет. {checked}",
        _rows(request, view.expansions), where, kind,
    )
    sequels = FollowBlock(
        SEQUELS_KEY, "Продолжения", series_sentence(view.collections) if view.sequels else NO_SEQUELS,
        _rows(request, view.sequels), where, kind,
    )
    return [expansions, sequels]


def follow_blocks(request: Request, card: TitleCard, now: datetime, error: FollowError) -> list[FollowBlock]:
    """The follow lists of the card, in the order they are shown: a watched film's sequels, or a game's expansions and
    sequels (one block while it was not checked yet); none for any other title. The error of a press stands in the block
    it came from, else in the first one. `now` is any aware moment."""
    where = address(request, "card_follow", title_id=card.id)
    blocks: list[FollowBlock] = []
    if card.sequels is not None:
        blocks.append(_film_block(request, card, card.sequels, where))
    if card.follow_ups is not None:
        blocks += _game_blocks(request, card, card.follow_ups, where, now)
    if error.text and blocks:
        index = next((i for i, block in enumerate(blocks) if block.key == error.block), 0)
        blocks[index] = blocks[index]._replace(error=error.text)
    return blocks
