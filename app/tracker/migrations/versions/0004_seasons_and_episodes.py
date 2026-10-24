"""Seasons of a series and their episodes.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "seasons",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title_id", sa.Integer(), sa.ForeignKey("titles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("episode_count", sa.Integer(), nullable=True),
        sa.Column("watched", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("title_id", "number", name="uq_seasons_title_number"),
    )
    op.create_index("ix_seasons_title_id", "seasons", ["title_id"])

    op.create_table(
        "episodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("season_id", sa.Integer(), sa.ForeignKey("seasons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("air_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("season_id", "number", name="uq_episodes_season_number"),
    )
    op.create_index("ix_episodes_season_id", "episodes", ["season_id"])


def downgrade() -> None:
    op.drop_index("ix_episodes_season_id", table_name="episodes")
    op.drop_table("episodes")
    op.drop_index("ix_seasons_title_id", table_name="seasons")
    op.drop_table("seasons")
