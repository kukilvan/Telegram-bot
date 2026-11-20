"""The table `issued_ids` (spec 5 of stage 9.1a, KI-24): the last number given to a title, so a deleted title's number
never comes back. An old button or link then never names another title. Not `AUTOINCREMENT`: that needs a rebuild of
`titles`, and eight tables cascade from it (see 0009).

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0015"
down_revision: Union[str, Sequence[str], None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "issued_ids",
        sa.Column("name", sa.String(32), primary_key=True),
        sa.Column("last_id", sa.Integer(), nullable=False),
    )
    # the numbers given so far: the biggest one of the titles there are (the numbers of earlier deleted titles are lost)
    op.execute("INSERT INTO issued_ids (name, last_id) SELECT 'titles', COALESCE(MAX(id), 0) FROM titles")


def downgrade() -> None:
    op.drop_table("issued_ids")
