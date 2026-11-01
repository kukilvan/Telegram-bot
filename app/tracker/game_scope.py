"""What the owner sees of the games: the country of the stores, «Мои платформы» and the marks «играю здесь».

The three are read together, in one session, and travel as one small value, so no place of the game poller reads them
one by one and they cannot come from two different moments of one operation (spec 7.3 of part 6.2).
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field

from sqlalchemy import Select, select

from app.tracker import game_events
from app.tracker.models import GamePlatformRecord
from app.tracker.platforms import Platform
from app.tracker.settings_store import SettingsStore


@dataclass(frozen=True)
class GameScope:
    """`country`: the code of the country of the stores; `mine`: «Мои платформы» in the order of the table; `marks`:
    for the games asked about, title → platform → the mark «играю здесь» (a game with no rows has no entry)."""

    country: str
    mine: tuple[Platform, ...]
    marks: Mapping[int, Mapping[str, bool]] = field(default_factory=dict)

    @classmethod
    def read(cls, settings: SettingsStore, session, title_ids: Select | Collection[int] = ()) -> "GameScope":
        """The scope for the games `title_ids` (a select of their numbers, or the numbers; none — no marks are read)."""
        marks: dict[int, dict[str, bool]] = {}
        if isinstance(title_ids, Select) or title_ids:
            rows = session.execute(
                select(GamePlatformRecord.title_id, GamePlatformRecord.platform, GamePlatformRecord.playing).where(
                    GamePlatformRecord.title_id.in_(title_ids)
                )
            )
            for title_id, platform, playing in rows:
                marks.setdefault(title_id, {})[platform] = playing
        return cls(settings.store_country_in(session), settings.my_platforms_in(session), marks)

    def marks_of(self, title_id: int) -> Mapping[str, bool]:
        return self.marks.get(title_id, {})

    def told(self, title_id: int) -> tuple[Platform, ...]:
        """The platforms the owner is told about in the game (`game_events.reported`)."""
        return game_events.reported(self.mine, self.marks_of(title_id))
