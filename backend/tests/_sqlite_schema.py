from __future__ import annotations

import importlib
from pathlib import Path


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
]


async def reset_sqlite_schema() -> None:
    """Recreate the SQLite schema from scratch between tests."""

    from app.core.database import Base, engine, sync_engine

    for module_name in _MODEL_MODULES:
        importlib.import_module(module_name)

    await engine.dispose()
    sync_engine.dispose()

    for artifact_name in ("test.db", "test.db-wal", "test.db-shm"):
        Path(artifact_name).unlink(missing_ok=True)

    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        await conn.run_sync(Base.metadata.create_all)
