"""Titles, external ids and source snapshots.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "titles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("original_title", sa.String(500), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("genres", sa.JSON(), nullable=False),
        sa.Column("poster_path", sa.String(255), nullable=True),
        sa.Column("overview", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("tracking_enabled", sa.Boolean(), nullable=False),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.Column("status_changed_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_titles_kind", "titles", ["kind"])
    op.create_index("ix_titles_status", "titles", ["status"])

    op.create_table(
        "external_ids",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title_id", sa.Integer(), sa.ForeignKey("titles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(64), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.UniqueConstraint("source", "external_id", name="uq_external_ids_source_id"),
        sa.UniqueConstraint("title_id", "source", "role", name="uq_external_ids_title_source_role"),
    )
    op.create_index("ix_external_ids_title_id", "external_ids", ["title_id"])

    op.create_table(
        "source_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title_id", sa.Integer(), sa.ForeignKey("titles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("title_id", "source", name="uq_source_snapshots_title_source"),
    )
    op.create_index("ix_source_snapshots_title_id", "source_snapshots", ["title_id"])


def downgrade() -> None:
    op.drop_index("ix_source_snapshots_title_id", table_name="source_snapshots")
    op.drop_table("source_snapshots")
    op.drop_index("ix_external_ids_title_id", table_name="external_ids")
    op.drop_table("external_ids")
    op.drop_index("ix_titles_status", table_name="titles")
    op.drop_index("ix_titles_kind", table_name="titles")
    op.drop_table("titles")
