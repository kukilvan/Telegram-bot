"""Parts of anime seasons (each with its own source ids) and movies of anime franchises.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "season_parts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title_id", sa.Integer(), sa.ForeignKey("titles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("season_id", sa.Integer(), sa.ForeignKey("seasons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("first_episode", sa.Integer(), nullable=False),
        sa.Column("episode_count", sa.Integer(), nullable=True),
        sa.Column("shikimori_id", sa.String(32), nullable=False),
        sa.Column("mal_id", sa.String(32), nullable=True),
        sa.Column("anilist_id", sa.String(32), nullable=True),
        sa.UniqueConstraint("season_id", "number", name="uq_season_parts_season_number"),
        sa.UniqueConstraint("title_id", "shikimori_id", name="uq_season_parts_title_shikimori"),
        sa.UniqueConstraint("title_id", "mal_id", name="uq_season_parts_title_mal"),
        sa.UniqueConstraint("title_id", "anilist_id", name="uq_season_parts_title_anilist"),
    )
    op.create_index("ix_season_parts_title_id", "season_parts", ["title_id"])
    op.create_index("ix_season_parts_season_id", "season_parts", ["season_id"])

    op.create_table(
        "franchise_movies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title_id", sa.Integer(), sa.ForeignKey("titles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("aired_on", sa.Date(), nullable=True),
        sa.Column("released", sa.Boolean(), nullable=False),
        sa.Column("shikimori_id", sa.String(32), nullable=False),
        sa.Column("mal_id", sa.String(32), nullable=True),
        sa.Column("anilist_id", sa.String(32), nullable=True),
        sa.UniqueConstraint("title_id", "shikimori_id", name="uq_franchise_movies_title_shikimori"),
        sa.UniqueConstraint("title_id", "mal_id", name="uq_franchise_movies_title_mal"),
        sa.UniqueConstraint("title_id", "anilist_id", name="uq_franchise_movies_title_anilist"),
    )
    op.create_index("ix_franchise_movies_title_id", "franchise_movies", ["title_id"])


def downgrade() -> None:
    op.drop_index("ix_franchise_movies_title_id", table_name="franchise_movies")
    op.drop_table("franchise_movies")
    op.drop_index("ix_season_parts_season_id", table_name="season_parts")
    op.drop_index("ix_season_parts_title_id", table_name="season_parts")
    op.drop_table("season_parts")
