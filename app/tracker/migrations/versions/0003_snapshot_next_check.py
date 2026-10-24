"""Time of the next check on every source snapshot.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NULL means "due now": titles added before this revision are checked on the first pass
    op.add_column("source_snapshots", sa.Column("next_check_at", sa.DateTime(), nullable=True))
    op.create_index("ix_source_snapshots_next_check_at", "source_snapshots", ["next_check_at"])


def downgrade() -> None:
    op.drop_index("ix_source_snapshots_next_check_at", table_name="source_snapshots")
    op.drop_column("source_snapshots", "next_check_at")
