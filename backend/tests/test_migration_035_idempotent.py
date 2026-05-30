"""Offline idempotency regression for migration 035_add_traceability_review_items.

Case #9. This test does NOT touch the live application database. It loads the
migration module directly, builds a throwaway sync SQLite database with the
minimal parent tables the migration's foreign keys reference, and drives the
migration through a real Alembic ``Operations`` context.

The migration's ``upgrade()`` is meant to be idempotent: when the table already
exists it (re)creates only the *missing* indexes, so a partially-applied
migration (table present but an index creation aborted) can be repaired by
re-running ``upgrade()``. This proves the partial-unique open index
``uq_traceability_review_items_open`` is restored on a second run rather than
silently left absent.
"""
from __future__ import annotations

import importlib.util
import os
import tempfile

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

# The FK targets referenced by the migration's create_table. Each only needs an
# id primary key so SQLite can resolve the foreign keys at CREATE TABLE time.
_PARENT_TABLES = (
    "projects",
    "users",
    "artifacts",
    "traceability_rules",
    "traceability_rule_executions",
)

# Derive the migration path from this test's location (portable across machines
# and CI) instead of hardcoding an absolute path: tests/ -> backend/ -> alembic.
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MIGRATION_PATH = os.path.join(
    _BACKEND_DIR, "alembic", "versions", "035_add_traceability_review_items.py"
)

_TABLE = "traceability_review_items"
_OPEN_INDEX = "uq_traceability_review_items_open"


def _load_migration_module():
    spec = importlib.util.spec_from_file_location(
        "migration_035_add_traceability_review_items", _MIGRATION_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _index_names(engine) -> set[str]:
    return {ix["name"] for ix in inspect(engine).get_indexes(_TABLE)}


def test_migration_035_upgrade_is_idempotent_for_open_index():
    mig = _load_migration_module()

    # A real on-disk SQLite file so a fresh inspector reflects committed DDL.
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(f"sqlite:///{db_path}")

    try:
        # Pre-create the minimal parent tables the migration's FKs point at.
        with engine.begin() as conn:
            for parent in _PARENT_TABLES:
                conn.exec_driver_sql(
                    f"CREATE TABLE {parent} (id INTEGER PRIMARY KEY)"
                )

        # (1) First upgrade: table + open partial-unique index must exist.
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                mig.upgrade()
            conn.commit()

        assert _TABLE in inspect(engine).get_table_names()
        assert _OPEN_INDEX in _index_names(engine)

        # (2) Simulate a partially-applied migration: drop ONLY the open index,
        # leaving the table and all other indexes in place.
        with engine.connect() as conn:
            conn.exec_driver_sql(f"DROP INDEX {_OPEN_INDEX}")
            conn.commit()
        assert _OPEN_INDEX not in _index_names(engine)

        # (3) Second upgrade: must not raise, and must re-create the open index
        # (the idempotent re-create guard repairs the missing index).
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                mig.upgrade()  # idempotent: no-op for table, re-creates index
            conn.commit()

        assert _TABLE in inspect(engine).get_table_names()
        assert _OPEN_INDEX in _index_names(engine)
    finally:
        engine.dispose()
        os.unlink(db_path)
