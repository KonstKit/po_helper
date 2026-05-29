from __future__ import annotations

import importlib


_MODEL_MODULES = [
    "app.models.user",
    "app.models.rbac",
    "app.models.project",
    "app.models.task",
    "app.models.sprint",
    "app.models.confluence",
    "app.models.settings",
    "app.models.traceability",
    "app.models.git",
    "app.models.project_repository",
    "app.models.testing",
    "app.models.quality",
    "app.models.jira_field_mapping",
    "app.models.audit",
    "app.models.capacity",
    "app.models.traceability_rule",
    "app.models.traceability_review",
]


async def reset_sqlite_schema() -> None:
    """Recreate the SQLite schema from scratch between tests.

    The schema is reset by dropping and recreating every table via the ORM
    metadata rather than deleting the database file. File deletion is unsafe
    on Windows because the WAL-mode connection pool keeps ``test.db``,
    ``test.db-wal`` and ``test.db-shm`` handles open; unlinking a locked file
    raises ``PermissionError`` once enough handles accumulate during a long
    full-suite run. ``drop_all`` + ``create_all`` produces an equally clean
    schema without touching the file handles.
    """

    from app.core.database import Base, engine, sync_engine

    for module_name in _MODEL_MODULES:
        importlib.import_module(module_name)

    # Release pooled connections first so a leaked/idle connection that still
    # holds the SQLite WAL write lock cannot make drop_all fail with "database
    # is locked". We deliberately do NOT delete the db file (unsafe on Windows
    # while WAL handles are open); drop_all + create_all yields a clean schema.
    await engine.dispose()
    sync_engine.dispose()

    async with engine.begin() as conn:
        # FK enforcement is left at the SQLite default (OFF) for the test
        # engine, so tables can be dropped in any order.
        await conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
