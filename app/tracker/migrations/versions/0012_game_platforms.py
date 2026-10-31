"""The platforms of a game and the owner's mark «играю здесь» on each (spec 6.2 of part 6.1). The dates stay in the
snapshot; `titles.kind` and `titles.status` are plain text, so a game and «Пройдено» need no change of them. No title
is touched on the way up; on the way down the games go (the database deletes all that is theirs), then the table.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0012"
down_revision: Union[str, Sequence[str], None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "game_platforms",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title_id", sa.Integer(), sa.ForeignKey("titles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("playing", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("title_id", "platform", name="uq_game_platforms_title_platform"),
    )
    op.create_index("ix_game_platforms_title_id", "game_platforms", ["title_id"])


def downgrade() -> None:
    op.execute("DELETE FROM titles WHERE kind = 'game'")
    op.drop_index("ix_game_platforms_title_id", table_name="game_platforms")
    op.drop_table("game_platforms")
