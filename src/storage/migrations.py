"""
Simple migration script for the workplace demand library database.

Handles initial table creation and graceful addition of new columns to
existing tables without requiring a full migration framework like Alembic.
"""

import logging
from typing import Optional

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from .models import Base

logger = logging.getLogger(__name__)


def _add_missing_columns(engine: Engine) -> None:
    """Inspect every mapped table and add any columns missing from the database.

    This is intentionally simple: it handles the common case of new nullable
    columns being appended to an existing table.  It does **not** handle
    column renames, type changes, or dropping columns.

    Args:
        engine: A SQLAlchemy ``Engine`` connected to the target database.
    """
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    for table_name, table in Base.metadata.tables.items():
        if table_name not in existing_tables:
            continue

        existing_columns = {col["name"] for col in inspector.get_columns(table_name)}

        for column in table.columns:
            if column.name in existing_columns:
                continue

            # Build a minimal ALTER TABLE statement for SQLite
            col_type = column.type.compile(dialect=engine.dialect)
            nullable = "" if column.nullable else " NOT NULL"
            default = ""
            if column.default is not None:
                default_val = column.default.arg
                if callable(default_val):
                    # Skip server-side defaults that can't be expressed as literals
                    default = ""
                elif isinstance(default_val, str):
                    default = f" DEFAULT '{default_val}'"
                else:
                    default = f" DEFAULT {default_val}"

            ddl = f"ALTER TABLE {table_name} ADD COLUMN {column.name} {col_type}{nullable}{default}"
            logger.info("Migration: %s", ddl)

            with engine.begin() as conn:
                conn.execute(text(ddl))


def run_migrations(engine: Optional[Engine] = None) -> None:
    """Ensure all tables, indexes and columns are up-to-date.

    1. Creates any tables that do not yet exist (via ``create_all``).
    2. Adds missing columns to existing tables.

    Args:
        engine: A SQLAlchemy ``Engine``.  When *None* the module-level
                engine from :mod:`database` is used.
    """
    if engine is None:
        from .database import get_engine
        engine = get_engine()

    logger.info("Running migrations — creating tables if needed …")
    Base.metadata.create_all(engine)

    logger.info("Checking for missing columns …")
    _add_missing_columns(engine)

    logger.info("Migrations complete.")
