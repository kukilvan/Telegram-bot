"""The column `episodes.timing`: where the stored moment of an episode comes from (spec 1.1 and 11 of stage 9.1c,
KI-28, KI-32, KI-77). Values `exact`, `day`, `unknown`, stored as text like the other enums of the models.

The existing rows are filled by what their moment looks like, since nothing else says where it came from:
- an episode of a series: `day` (TMDb gives the day, stored as 00:00 UTC);
- an anime episode with no moment: `unknown`;
- an anime moment with seconds or microseconds: `unknown` (the moment of the check that found the episode);
- an anime moment at 00:00:00 UTC: `day` for the lowest number of its season with that moment, `unknown` for the other
  episodes of the season with the same moment (the start day of the entry that Shikimori gives to every episode out);
- any other anime moment (a whole minute): `exact`, a moment AniList or Shikimori named.

A lone anime episode at 00:00 that was a real AniList moment cannot be told from a premiere day, so it becomes `day`
and shows what it showed before. Rows of other kinds keep `exact` (they have no episodes).

Added with `ALTER TABLE ... ADD COLUMN` (a default fills the old rows first), dropped the same way: no rebuild of
`episodes` (see 0016). The copy of the database goes to `data/backups/` before, as for every migration.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-22

"""
from collections import defaultdict
from datetime import datetime, time
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0017"
down_revision: Union[str, Sequence[str], None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EXACT, DAY, UNKNOWN = "exact", "day", "unknown"  # the values of `EpisodeTiming` when this migration was written
SERIES, ANIME = "series", "anime"

_titles = sa.table("titles", sa.column("id", sa.Integer), sa.column("kind", sa.String))
_seasons = sa.table("seasons", sa.column("id", sa.Integer), sa.column("title_id", sa.Integer))
_episodes = sa.table(
    "episodes",
    sa.column("id", sa.Integer),
    sa.column("season_id", sa.Integer),
    sa.column("number", sa.Integer),
    sa.column("air_at", sa.DateTime),
    sa.column("timing", sa.String),
)


def timings(rows: Sequence[tuple[int, int, int, datetime | None, str]]) -> dict[int, str]:
    """The timing of every episode row (id, season id, number, moment, kind of its title) by the table of the module."""
    result: dict[int, str] = {}
    midnights: dict[tuple[int, datetime], list[tuple[int, int]]] = defaultdict(list)  # (season, moment) -> (number, id)
    for episode_id, season_id, number, air_at, kind in rows:
        if kind == SERIES:
            result[episode_id] = DAY
        elif kind != ANIME:
            result[episode_id] = EXACT
        elif air_at is None or air_at.second or air_at.microsecond:
            result[episode_id] = UNKNOWN
        elif air_at.time() == time(0):
            midnights[(season_id, air_at)].append((number, episode_id))
        else:
            result[episode_id] = EXACT
    for shared in midnights.values():
        shared.sort()
        result[shared[0][1]] = DAY
        result.update({episode_id: UNKNOWN for _, episode_id in shared[1:]})
    return result


def upgrade() -> None:
    op.add_column("episodes", sa.Column("timing", sa.String(16), nullable=False, server_default=EXACT))
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(_episodes.c.id, _episodes.c.season_id, _episodes.c.number, _episodes.c.air_at, _titles.c.kind)
        .join(_seasons, _seasons.c.id == _episodes.c.season_id)
        .join(_titles, _titles.c.id == _seasons.c.title_id)
    ).all()
    by_value: dict[str, list[int]] = defaultdict(list)
    for episode_id, value in timings(rows).items():
        if value != EXACT:
            by_value[value].append(episode_id)
    for value, ids in by_value.items():
        for start in range(0, len(ids), 500):  # SQLite caps the parameters of one statement
            connection.execute(
                _episodes.update().where(_episodes.c.id.in_(ids[start:start + 500])).values(timing=value)
            )


def downgrade() -> None:
    op.execute("ALTER TABLE episodes DROP COLUMN timing")
