"""When the owner was last told that a title could not be checked (one notice per title in 24 hours).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("titles", sa.Column("failure_notified_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("titles", "failure_notified_at")
