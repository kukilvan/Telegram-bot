"""Data only: the Shikimori snapshot of every anime title is due at the moment of the migration (spec 4.6 and 12 of
stage 9.1d, KI-81).

Since 9.1d a premiere Shikimori knows only by its month or year is stored as the approximate stub (`episodes.timing`
`month` or `year`) instead of a made-up first day. The stubs cannot be told from real first-of-month days by the base
alone, so no episode row is rewritten here: the first polling pass after the start (within a minute) reads the premieres
again and stores the stubs. Nothing else changes; the downgrade has nothing to undo. The copy of the database goes to
`data/backups/` before, as for every migration.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-23

"""
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0018"
down_revision: Union[str, Sequence[str], None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SHIKIMORI, ANIME = "shikimori", "anime"  # the snapshot source and the title kind when this migration was written

_titles = sa.table("titles", sa.column("id", sa.Integer), sa.column("kind", sa.String))
_snapshots = sa.table(
    "source_snapshots",
    sa.column("title_id", sa.Integer),
    sa.column("source", sa.String),
    sa.column("next_check_at", sa.DateTime),
)


def upgrade() -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC, as every moment of the tracker
    anime = sa.select(_titles.c.id).where(_titles.c.kind == ANIME)
    op.get_bind().execute(
        _snapshots.update()
        .where(_snapshots.c.source == SHIKIMORI, _snapshots.c.title_id.in_(anime))
        .values(next_check_at=now)
    )


def downgrade() -> None:
    pass  # a check that came earlier is nothing to undo
