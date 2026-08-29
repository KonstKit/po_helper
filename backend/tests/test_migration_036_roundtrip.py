"""Offline round-trip + idempotency regression for migration
036_add_execution_trigger_source.

This test does NOT touch the live application database. It loads the migration
module directly, builds a throwaway sync SQLite database with the minimal parent
table the migration targets, and drives the migration through a real Alembic
``Operations`` context.

The migration adds ``traceability_rule_executions.trigger_source`` (a nullable
VARCHAR) so execution history can record what initiated each run. Its
``upgrade()`` is guarded to be idempotent: re-running after a partial apply is a
no-op when the column already exists. ``downgrade()`` removes the column again.
This proves the full round-trip (upgrade -> upgrade -> downgrade) leaves the
schema in the expected state at every step.
"""

from __future__ import annotations

import importlib.util
import os
import tempfile

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

# Derive the migration path from this test's location (portable across machines
# and CI) instead of hardcoding an absolute path: tests/ -> backend/ -> alembic.
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MIGRATION_PATH = os.path.join(
    _BACKEND_DIR, "alembic", "versions", "036_add_execution_trigger_source.py"
)

_TABLE = "traceability_rule_executions"
_COLUMN = "trigger_source"


def _load_migration_module():
    spec = importlib.util.spec_from_file_location(
        "migration_036_add_execution_trigger_source", _MIGRATION_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _column_names(engine) -> list[str]:
    return [c["name"] for c in inspect(engine).get_columns(_TABLE)]


def test_migration_036_trigger_source_roundtrip_is_idempotent():
    mig = _load_migration_module()

    # A real on-disk SQLite file so a fresh inspector reflects committed DDL.
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(f"sqlite:///{db_path}")

    try:
        # Pre-create the parent table the migration targets. Only an id primary
        # key is strictly required; rule_id/status mirror the real shape.
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "CREATE TABLE traceability_rule_executions "
                "(id INTEGER PRIMARY KEY, rule_id INTEGER, status VARCHAR)"
            )

        assert _COLUMN not in _column_names(engine)

        # (1) First upgrade: the trigger_source column must now exist.
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                mig.upgrade()
            conn.commit()

        assert _COLUMN in _column_names(engine)

        # (2) Second upgrade (idempotent): must not raise, and the column must
        # still be present exactly once.
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                mig.upgrade()  # idempotent guard: column already exists -> no-op
            conn.commit()

        cols_after_second_upgrade = _column_names(engine)
        assert cols_after_second_upgrade.count(_COLUMN) == 1

        # (3) Downgrade: the trigger_source column must be removed again.
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                mig.downgrade()
            conn.commit()

        assert _COLUMN not in _column_names(engine)
    finally:
        engine.dispose()
        os.unlink(db_path)
