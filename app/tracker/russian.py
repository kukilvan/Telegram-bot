"""Russian in a game (pure): what a source says (`Support`), the official look and its strict reading, the line «Русский: …», what appeared and «(ПК)».

Spec 5.1, 5.2 and 5.5 of stage 9.1b (idea 002). Pure: no database, no network, no clock.

A source says something about Russian (`Support`: text — the interface or subtitles, voice — full voice, each yes or
no) or nothing («no data»: None, never a `Support` with both no). The official part comes from Steam when Steam has
data for the game's Steam number (about the PC version), else from IGDB (about the game). The fan part comes from ZoG
(ticket 9.1b.05); until then it is always «no data». A source that once had data and later says nothing keeps the
previous value: «no data» never overwrites known data (`next_look`), and a failure is never shown as «нет».

The official look (`Look`) is what one official check stored in the snapshot `russian_official`: the source of its
data (`STEAM`, `IGDB` or None — checked, no data) and the Steam number the check knew (None — the game had no Steam
page). Its first look, a look of another Steam number (a Steam page appeared, went or changed) and the first look after
«Вернуть в список» are reference points (`is_reference`); otherwise each part that is yes now and was not yes before is
news (`appeared`; no data counts as no), and Russian that disappears is silent. A change of the data source under the
same Steam number (IGDB's data, then Steam's) is no reference point: an announced game whose languages Steam lists for
the first time with Russian is told.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

from app.tracker.platforms import Platform

STEAM = "steam"
IGDB = "igdb"
SOURCES = (STEAM, IGDB)

# The bodies of the line without a segment (spec 5.2)
NONE = "нет"  # official no and fan no
OFFICIAL_NONE = "официально нет"  # official no, fan no data
NO_DATA = "нет данных"  # official no data
PC_MARK = "(ПК)"

_OFFICIAL = {(True, True): "текст и озвучка — официально", (True, False): "текст — официально",
             (False, True): "озвучка — официально"}
_FAN = {(True, True): "текст и озвучка — народные", (True, False): "текст — народный", (False, True): "озвучка — народная"}


@dataclass(frozen=True)
class Support:
    """What one source says about Russian when it says something: text (interface or subtitles), voice (full voice)."""

    text: bool
    voice: bool

    def state(self) -> dict[str, bool]:
        return {"text": self.text, "voice": self.voice}

    @classmethod
    def from_state(cls, data: Any) -> "Support":
        """Strict: a mapping of exactly the booleans `text` and `voice`; anything else raises ValueError."""
        if not isinstance(data, Mapping) or set(data) != {"text", "voice"}:
            raise ValueError(f"not a Russian support: {data!r}")
        if not all(isinstance(data[key], bool) for key in ("text", "voice")):
            raise ValueError(f"not a Russian support: {data!r}")
        return cls(data["text"], data["voice"])

    @property
    def any(self) -> bool:
        return self.text or self.voice


class _NotAsked:
    """The own snapshot of a game from before stage 9.1b: IGDB was not asked about the languages yet."""

    _instance = None

    def __new__(cls) -> "_NotAsked":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "NOT_ASKED"


NOT_ASKED = _NotAsked()

# What IGDB says in the own snapshot (`GameState.russian`): a support, None (no languages), or not asked yet
IgdbRussian = Support | None | _NotAsked


def igdb_from_state(data: Mapping[str, Any]) -> IgdbRussian:
    """The key `russian` of a stored own snapshot, strictly: absent — not asked yet; null — IGDB has no languages; else
    a `Support` (a wrong value raises ValueError)."""
    if "russian" not in data:
        return NOT_ASKED
    value = data["russian"]
    return None if value is None else Support.from_state(value)


def igdb_state(russian: IgdbRussian) -> dict[str, Any]:
    """The key `russian` for the own snapshot: none while not asked, null for no languages, else the support."""
    if russian is NOT_ASKED:
        return {}
    return {"russian": None if russian is None else russian.state()}


@dataclass(frozen=True)
class Look:
    """One official look: `source` of its data (`STEAM`, `IGDB`, None — checked, no data), `appid` the Steam number the
    check knew (None — no Steam page), `support` the data (None exactly when `source` is None)."""

    source: str | None
    appid: str | None
    support: Support | None = None

    def state(self) -> dict[str, Any]:
        state: dict[str, Any] = {"source": self.source, "appid": self.appid}
        if self.support is not None:
            state.update(self.support.state())
        return state

    @classmethod
    def from_state(cls, data: Any) -> "Look | None":
        """Strict: the snapshot `russian_official`; `{}` — nothing looked at yet (None); a wrong source, a number that
        is not text, a source without its data or data without a source raises ValueError."""
        if not isinstance(data, Mapping):
            raise ValueError(f"not an official Russian look: {data!r}")
        if not data:
            return None
        source, appid = data.get("source"), data.get("appid")
        if source is not None and source not in SOURCES:
            raise ValueError(f"unknown source of an official Russian look: {source!r}")
        if appid is not None and not isinstance(appid, str):
            raise ValueError(f"the Steam number of an official Russian look is not text: {appid!r}")
        rest = {key: value for key, value in data.items() if key not in ("source", "appid")}
        if source is None:
            if rest:
                raise ValueError(f"an official Russian look without a source has data: {data!r}")
            return cls(None, appid)
        return cls(source, appid, Support.from_state(rest))

    @property
    def pc_only(self) -> bool:
        """The data is about the PC version (Steam's)."""
        return self.source == STEAM


def next_look(previous: Look | None, steam: Support | None, igdb: IgdbRussian, appid: str | None) -> Look | None:
    """The look of a check (spec 5.5): Steam data when it has some, else IGDB data, else none. «No data» never
    overwrites known data of the same Steam number: Steam silent keeps a previous Steam look, and with neither source
    saying anything the previous look with data stays. None — nothing to store: Steam has none and IGDB is «not asked
    yet» (the first look with data must be a reference point, not news)."""
    same = previous if previous is not None and previous.appid == appid else None
    if steam is not None:
        return Look(STEAM, appid, steam)
    if same is not None and same.source == STEAM:
        return same
    if isinstance(igdb, Support):
        return Look(IGDB, appid, igdb)
    if same is not None and same.support is not None:
        return same
    if igdb is NOT_ASKED:
        return None
    return Look(None, appid)


def is_reference(previous: Look | None, new: Look, restored: bool) -> bool:
    """The check is the reference point (stored, no events): nothing was looked at before, the Steam number changed (a
    Steam page appeared, went or is another one), or it is the first check after «Вернуть в список» (`restored`)."""
    return previous is None or previous.appid != new.appid or restored


def appeared(previous: Support | None, now: Support | None) -> Support | None:
    """The parts that are yes now and were not yes before (no data counts as no); None — nothing appeared."""
    if now is None:
        return None
    text = now.text and not (previous is not None and previous.text)
    voice = now.voice and not (previous is not None and previous.voice)
    return Support(text, voice) if text or voice else None


def parts_key(parts: Support) -> str:
    """`text`, `voice` or `text_voice`: the parts in a key and a payload."""
    return "_".join(name for name, yes in (("text", parts.text), ("voice", parts.voice)) if yes)


def elsewhere(told: Collection[Platform]) -> bool:
    """The owner has «играю здесь» on a platform other than PC (`GameScope.told` minus PC is not empty)."""
    return any(platform != Platform.PC for platform in told)


@dataclass(frozen=True)
class Line:
    """The line «Русский: …» without the word: its body and whether «(ПК)» ends it."""

    body: str
    pc: bool = False

    @property
    def text(self) -> str:
        return f"{self.body} {PC_MARK}" if self.pc else self.body

    @property
    def no_data(self) -> bool:
        return self.body == NO_DATA


def line(official: Support | None, official_pc: bool, fan: Support | None, played_elsewhere: bool) -> Line:
    """The line of spec 5.2. The fan part fills only what the official lacks; no segment — «нет» (official no, fan no),
    «официально нет» (official no, fan no data), «нет данных» (official no data). «(ПК)» when the owner plays on another
    platform too (`played_elsewhere`) and the body rests on PC-only data: the official segment or «нет» / «официально
    нет» from Steam (`official_pc`), or a fan segment (always PC-only); never after «нет данных»."""
    segments: list[str] = []
    if official is not None and official.any:
        segments.append(_OFFICIAL[(official.text, official.voice)])
    fan_text = fan is not None and fan.text and not (official is not None and official.text)
    fan_voice = fan is not None and fan.voice and not (official is not None and official.voice)
    if fan_text or fan_voice:
        segments.append(_FAN[(fan_text, fan_voice)])
    if segments:
        pc_data = (official is not None and official.any and official_pc) or fan_text or fan_voice
        return Line("; ".join(segments), played_elsewhere and pc_data)
    if official is None:
        return Line(NO_DATA)
    return Line(NONE if fan is not None else OFFICIAL_NONE, played_elsewhere and official_pc)
