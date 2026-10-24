"""Events and delivery queue.

Revision ID: 0001
Revises:
Create Date: 2026-10-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("title_id", sa.Integer(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("dedup_key", sa.String(255), nullable=False, unique=True),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "delivery_queue",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_delivery_queue_status", "delivery_queue", ["status"])


def downgrade() -> None:
    op.drop_index("ix_delivery_queue_status", table_name="delivery_queue")
    op.drop_table("delivery_queue")
    op.drop_table("events")
