"""The column `titles.failure_notified_at` goes (spec 4.4 of stage 9.1a, KI-45). The 24-hour window of a «could not
check» notice is per title and source now, read from the events `source_failure` themselves.

Dropped with `ALTER TABLE ... DROP COLUMN`, not with `batch_alter_table`: the batch way rebuilds `titles`, and with
foreign keys on, dropping the old table would wipe the tables that cascade from it (see 0009). A drop of a column that
no index, key or view names touches no other row.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0016"
down_revision: Union[str, Sequence[str], None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE titles DROP COLUMN failure_notified_at")


def downgrade() -> None:
    op.add_column("titles", sa.Column("failure_notified_at", sa.DateTime(), nullable=True))
