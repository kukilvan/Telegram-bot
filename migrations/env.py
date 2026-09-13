"""Alembic migration environment."""

import os
import sys
from logging import config as logging_config

# Ensure the project root is on sys.path so we can import our own package,
# regardless of how Alembic was invoked (console script vs -m).
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from alembic import context
from sqlalchemy import create_engine

# Import our models so every table class registers with Base.metadata.
import app.database.models  # noqa — ensures model classes are registered
from app.database.base import Base  # noqa — declarative base for autogenerate
# Single source of truth for the DB URL: reuse the app's engine/session config.
from app.database.session import DATABASE_URL, ensure_data_dir

# this is the Alembic Config object, which provides access to the values
# within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    logging_config.fileConfig(config.config_file_name)

# Add our model's MetaData object here for 'autogenerate' support.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (no DBAPI required)."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = create_engine(DATABASE_URL)

    # SQLite cannot create a database file inside a missing directory.
    ensure_data_dir()

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
