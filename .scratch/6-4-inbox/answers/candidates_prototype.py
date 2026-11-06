"""Prototype of the candidate rules of spec 6.4 (throwaway; the ticket writes the real module)."""
import re
from dataclasses import dataclass, field

INVISIBLE = re.compile("[​-‏⁠﻿ㅤᅟᅠ­]")
URL = re.compile(r"https?://\S+|\b(?:t\.me|jut\.su|jutsu\.ru)/\S+", re.I)
SIGNATURE = re.compile(r"(підписатись|подписаться|подпишись|subscribe)", re.I)
HANDLE = re.compile(r"(?<!\w)@\w+")
SCORE_LINE = re.compile(r"(\d+(?:[.,]\d+)?\s*/\s*10\b|\bбал(л|ів|и|ов)?\b|\bpoints?\b)", re.I)
QUOTE = re.compile(r"[«\"“„]([^«»\"“”„]{1,80})[»\"”“]")
LATIN_WORD = r"[A-Za-z0-9][A-Za-z0-9'’.&+]*(?:-[A-Za-z0-9'’]+)*"
LATIN_RUN = re.compile(rf"{LATIN_WORD}(?:(?::\s+|\s+[-–]\s+|\s+){LATIN_WORD})*")
EPISODE_HEAD = re.compile(r"^(.+?):\s*\d+\s*(серия|эпизод|серія)", re.I)
YEAR = re.compile(r"\b(19[5-9]\d|20\d\d)\b")
KIND_WORDS = re.compile(
    r"\b(игр[аыуе]|гр[аиу]|сериал[аеу]?|серіал[уі]?|аниме|аніме|фильм[аеу]?|фільм[уі]?|мультфильм[аеу]?|"
    r"экранизаци[яию]|екранізаці[яію]|ремастер|ремейк|дорам[аыу]|экшн|экшен|лайфсим|симулятор|приключение|приключени[ея])\s*$",
    re.I,
)
MARKERS = re.compile(
    r"(смес\w*|как в|как у|вроде|наподобие|аналог\w*|в духе|похож\w*|наследник\w*|наступник\w*|преемник\w*|"
    r"известн\w* по|відом\w* за|вытеснив|помимо|кроме|после|на основе|по мотивам|"
    r"\bот\b|\bвід\b|\bfrom\b|студи\w*|студі\w*|компани\w*|компані\w*|издател\w*|видав\w*|разработчик\w*|розробник\w*|"
    r"выходцами из|\bиз\b|магазин\w*|фестивал\w*)\s*$",
    re.I,
)
# not titles: stores, platforms, services, outlets, abbreviations
STOP = {s.casefold() for s in """steam pc пк ps4 ps5 playstation xbox xbox series xbox one xbox series x|s nintendo switch switch
switch 2 nintendo switch 2 quest meta meta horizon netflix hbo apple tv+ disney+ amazon prime video youtube twitch ign
metacritic opencritic vr ar xr npc ai dlc ru eu us ua hard easy normal mappa a24 sony microsoft nintendo epic games store
gog itch.io telegram""".split("\n")}
STOP |= {w.casefold() for w in "steam pc ps4 ps5 playstation xbox nintendo switch quest meta netflix ign metacritic opencritic vr ar xr npc ai dlc ru hard mappa a24 sony microsoft gog telegram".split()}


PLATFORM = re.compile(r"(xbox|nintendo|playstation|ps\d|switch|steam\s|quest\s)", re.I)


@dataclass
class Cand:
    text: str
    score: float = 0.0
    first: int = 10**6  # position of the first occurrence
    count: int = 0
    why: list = field(default_factory=list)


def norm(s: str) -> str:
    s = s.casefold().replace("ё", "е")
    s = re.sub(r"[^\w]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def clean_lines(text: str) -> list[str]:
    lines = []
    for line in INVISIBLE.sub("", text).splitlines():
        line = line.strip()
        if not line or SIGNATURE.search(line):
            continue
        line = HANDLE.sub(" ", URL.sub(" ", line)).strip()
        if line:
            lines.append(line)
    return lines


def extract(text: str, bold: list[str] = (), short_limit: int = 8):
    lines = clean_lines(text)
    found: dict[str, Cand] = {}
    pos = 0

    def add(raw: str, weight: float, why: str, at: int) -> None:
        raw = raw.strip(" .,;:!?—–-·•▫️➖‼️")
        key = norm(raw)
        if not key or len(key) < 2 or key.isdigit() or key in STOP or len(key.split()) > 8:
            return
        c = found.setdefault(key, Cand(raw))
        c.score += weight
        c.count += 1
        c.first = min(c.first, at)
        c.why.append(why)

    one_line = len(lines) == 1 and len(lines[0].split()) <= short_limit
    if one_line:
        add(lines[0], 100, "whole", 0)
    for n, line in enumerate(lines):
        if SCORE_LINE.search(line):
            continue  # a list of scores of the press
        if line.endswith(":") and len(line.split()) <= 1:
            continue  # a label left of a link («Main:», «Ru:»)
        head = n == 0
        m = EPISODE_HEAD.match(line)
        if m:
            add(m.group(1), 50, "episode-head", pos)
        quoted_spans = []
        for q in QUOTE.finditer(line):
            quoted_spans.append(q.span())
            before = line[: q.start()]
            w = 3 if not MARKERS.search(before) else 0.5
            if head and q.start() < 3:
                w += 1
            add(q.group(1), w, "quote", pos + q.start())
        for r in LATIN_RUN.finditer(line):
            if any(a <= r.start() < b for a, b in quoted_spans):
                continue
            run = r.group(0)
            if re.fullmatch(r"[\d\s:.\-–]+", run):
                continue
            before = line[: r.start()]
            w = 6
            if head:
                w += 4
            if KIND_WORDS.search(before):
                w += 4
            if MARKERS.search(before):
                w -= 5
            if PLATFORM.match(run):
                continue
            if len(run.split()) == 1 and not head and len(run) <= 3:
                continue
            if len(run.split()) == 1 and not head and not run.isupper():
                w -= 1
            add(run, w, "latin", pos + r.start())
        pos += len(line) + 1
    for b in bold:
        add(b, 8, "bold", text.find(b))
    keys = sorted(found, key=lambda k: -len(k.split()))
    for k in keys:  # a candidate inside a longer one is the longer one
        for longer in keys:
            if len(longer.split()) > len(k.split()) and f" {k} " in f" {longer} " and k in found and longer in found:
                found[longer].count += found[k].count
                found.pop(k)
                break
    for c in found.values():
        c.score += 2 * (c.count - 1)  # repeated in the post
    return sorted(found.values(), key=lambda c: (-c.score, c.first)), [int(y) for y in YEAR.findall(text)]
