"""phase 7.5: add next_check_at to source_states for adaptive per-item polling

Revision ID: a7c3e91f2d48
Revises: 11f3f12cf425
Create Date: 2026-09-15 21:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c3e91f2d48'
down_revision: Union[str, Sequence[str], None] = '11f3f12cf425'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "source_states",
        sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("source_states", "next_check_at")
