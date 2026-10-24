"""Alembic environment of the tracker database.

Run from code with a connection in `config.attributes["connection"]` (see `app.tracker.db.migrate`),
or from the command line with `alembic -c alembic_tracker.ini ...`.
"""

import os
import sys

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from alembic import context

from app.tracker.db import TRACKER_DATABASE_URL, create_tracker_engine
from app.tracker.models import TrackerBase

config = context.config
target_metadata = TrackerBase.metadata


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return

    engine = create_tracker_engine(config.get_main_option("sqlalchemy.url") or TRACKER_DATABASE_URL)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("Offline migrations are not supported for the tracker database")
run_migrations_online()
