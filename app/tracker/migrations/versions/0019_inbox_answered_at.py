"""The column `inbox_items.answered_at`: when the pause of an inbox item got its answer — the question «Что это?» or the
first offer card (spec 9 and 12 of stage 9.1d, KI-57). An item still waiting without it is asked when the bot starts.

Existing rows get their `last_message_at`: they are answered already, or in «Входящие». Added and dropped with
`ALTER TABLE`, not with `batch_alter_table`, as in 0016: the batch way rebuilds the table.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-24

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0019"
down_revision: Union[str, Sequence[str], None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE inbox_items ADD COLUMN answered_at DATETIME")
    op.execute("UPDATE inbox_items SET answered_at = last_message_at")


def downgrade() -> None:
    op.execute("ALTER TABLE inbox_items DROP COLUMN answered_at")
