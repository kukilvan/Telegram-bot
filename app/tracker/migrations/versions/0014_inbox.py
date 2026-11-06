"""«Входящие» (spec 10 of stage 6.4): the table `inbox_items`, one row per inbox item — what the owner sent to the bot.
`AUTOINCREMENT`, so the number of a deleted item never comes back and an old button never acts on another item.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0014"
down_revision: Union[str, Sequence[str], None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "inbox_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(24), nullable=True),
        sa.Column("kind", sa.String(16), nullable=True),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("media", sa.String(16), nullable=True),
        sa.Column("bold", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("links", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("post_url", sa.Text(), nullable=True),
        sa.Column("forwarded", sa.Boolean(), nullable=False),
        sa.Column("media_group_id", sa.String(64), nullable=True),
        sa.Column("query", sa.Text(), nullable=False, server_default=""),
        sa.Column("offers", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("last_message_at", sa.DateTime(), nullable=False),
        sa.Column("moved_at", sa.DateTime(), nullable=True),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_inbox_items_state", "inbox_items", ["state"])


def downgrade() -> None:
    op.drop_index("ix_inbox_items_state", table_name="inbox_items")
    op.drop_table("inbox_items")
