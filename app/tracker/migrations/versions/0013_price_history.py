"""The price history of the games (spec 4.5 of part 6.2): a record of a Steam price each time a price check saw it change.
The price snapshots themselves are rows of `source_snapshots` (source `steam`), so the way up only adds the table; the
way down takes those snapshots away first (nothing of the older code reads them), then the table.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0013"
down_revision: Union[str, Sequence[str], None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "price_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title_id", sa.Integer(), sa.ForeignKey("titles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seen_at", sa.DateTime(), nullable=False),
        sa.Column("appid", sa.String(16), nullable=False),
        sa.Column("country", sa.String(2), nullable=False),
        sa.Column("currency", sa.String(32), nullable=False),
        sa.Column("final", sa.Integer(), nullable=False),
        sa.Column("original", sa.Integer(), nullable=True),
        sa.Column("pct", sa.Integer(), nullable=False),
    )
    op.create_index("ix_price_history_title_id", "price_history", ["title_id"])


def downgrade() -> None:
    op.execute("DELETE FROM source_snapshots WHERE source = 'steam'")
    op.drop_index("ix_price_history_title_id", table_name="price_history")
    op.drop_table("price_history")
