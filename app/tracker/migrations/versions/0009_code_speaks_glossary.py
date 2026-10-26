"""Names from the glossary: `titles.title` → `titles.name`, `titles.original_title` → `titles.original_name`,
the setting `digest_at` → `summary_at`. Nothing changes in behaviour, no data is lost.

The columns are renamed with `ALTER TABLE ... RENAME COLUMN`, not with `batch_alter_table`: the batch way rebuilds
`titles` (a new table, the old one dropped), and with foreign keys on, dropping the parent would wipe `external_ids`,
seasons, events and the rest through their `ON DELETE CASCADE` keys. A rename touches no rows.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-26

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE titles RENAME COLUMN title TO name")
    op.execute("ALTER TABLE titles RENAME COLUMN original_title TO original_name")
    _rename_setting("digest_at", "summary_at")


def downgrade() -> None:
    op.execute("ALTER TABLE titles RENAME COLUMN name TO title")
    op.execute("ALTER TABLE titles RENAME COLUMN original_name TO original_title")
    _rename_setting("summary_at", "digest_at")


def _rename_setting(old: str, new: str) -> None:
    """Move the row to the new key; a row already under the new key wins, the old one just goes."""
    op.execute(f"UPDATE settings SET key = '{new}' WHERE key = '{old}' AND NOT EXISTS (SELECT 1 FROM settings WHERE key = '{new}')")
    op.execute(f"DELETE FROM settings WHERE key = '{old}'")
