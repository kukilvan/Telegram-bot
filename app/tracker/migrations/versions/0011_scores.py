"""The owner's scores: of a title (a film's only one; a series' own one over the average of its seasons) and of a
season. A whole number of thirds of a point (`app.tracker.scores`); empty: not scored. Every row starts without one.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0011"
down_revision: Union[str, Sequence[str], None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("titles", sa.Column("score", sa.Integer(), nullable=True))
    op.add_column("seasons", sa.Column("score", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("seasons", "score")
    op.drop_column("titles", "score")
