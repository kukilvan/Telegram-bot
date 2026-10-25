"""Foreign keys with cascade: `events.title_id` → `titles.id`, `delivery_queue.event_id` → `events.id`.

Deleting a title now removes its events and their queue entries in the database itself. SQLite cannot add a foreign key
to an existing table, so both tables are rebuilt (the batch way, written out by hand: the old keys have no names).
Events of titles that no longer exist (left behind by the old deletion) go first, with their queue entries.
The queue is set aside in a plain table while `events` is swapped: a table with a cascading key must not lose its
parent's rows, and a table with a plain key must not have them dropped from under it.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: Union[str, Sequence[str], None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "DELETE FROM delivery_queue WHERE event_id IN "
        "(SELECT id FROM events WHERE title_id IS NOT NULL AND title_id NOT IN (SELECT id FROM titles))"
    )
    op.execute("DELETE FROM delivery_queue WHERE event_id NOT IN (SELECT id FROM events)")
    op.execute("DELETE FROM events WHERE title_id IS NOT NULL AND title_id NOT IN (SELECT id FROM titles)")

    _stash_queue()
    _rebuild_events(sa.ForeignKey("titles.id", ondelete="CASCADE"))
    _restore_queue(sa.ForeignKey("events.id", ondelete="CASCADE"))
    op.create_index("ix_events_title_id", "events", ["title_id"])
    op.create_index("ix_delivery_queue_status", "delivery_queue", ["status"])


def downgrade() -> None:
    _stash_queue()
    op.drop_index("ix_events_title_id", table_name="events")
    _rebuild_events(None)
    _restore_queue(sa.ForeignKey("events.id"))
    op.create_index("ix_delivery_queue_status", "delivery_queue", ["status"])


def _stash_queue() -> None:
    op.execute("CREATE TABLE delivery_queue_stash AS SELECT * FROM delivery_queue")
    op.drop_index("ix_delivery_queue_status", table_name="delivery_queue")
    op.drop_table("delivery_queue")


def _rebuild_events(title_key) -> None:
    op.create_table(
        "events_new",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("title_id", sa.Integer(), *([title_key] if title_key is not None else []), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("dedup_key", sa.String(255), nullable=False, unique=True),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
    )
    op.execute(
        "INSERT INTO events_new (id, type, title_id, payload, dedup_key, detected_at) "
        "SELECT id, type, title_id, payload, dedup_key, detected_at FROM events"
    )
    op.drop_table("events")
    op.rename_table("events_new", "events")


def _restore_queue(event_key) -> None:
    op.create_table(
        "delivery_queue",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), event_key, nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
    )
    op.execute(
        "INSERT INTO delivery_queue (id, event_id, status, attempts, last_error, created_at, delivered_at) "
        "SELECT id, event_id, status, attempts, last_error, created_at, delivered_at FROM delivery_queue_stash"
    )
    op.drop_table("delivery_queue_stash")
