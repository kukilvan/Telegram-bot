"""When the owner last brought a title back from the archive («Вернуть в список»): the first check of its own source
after that moment records what it finds as the baseline, without events. Empty: never brought back.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010"
down_revision: Union[str, Sequence[str], None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("titles", sa.Column("restored_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("titles", "restored_at")
