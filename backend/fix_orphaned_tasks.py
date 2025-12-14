#!/usr/bin/env python3
"""
Fix orphaned tasks (tasks with NULL project_id) without restarting the server.
"""

import asyncio
import sys
from sqlalchemy import text
from app.core.database import engine
from app.core.config import settings

async def fix_orphaned_tasks():
    """Fix tasks with NULL project_id by assigning them to the first available project."""

    async with engine.begin() as conn:
        # Check for orphaned tasks
        result = await conn.execute(
            text("SELECT COUNT(*) FROM tasks WHERE project_id IS NULL")
        )
        orphaned_count = result.scalar()

        if orphaned_count == 0:
            print("✓ No orphaned tasks found. Everything is OK!")
            return

        print(f"Found {orphaned_count} orphaned tasks (with NULL project_id)")

        # Get the first project (likely WAB based on your screenshots)
        result = await conn.execute(
            text("SELECT id, jira_key, name FROM projects LIMIT 1")
        )
        project = result.fetchone()

        if not project:
            print("✗ No projects found in database. Cannot fix orphaned tasks.")
            print("  Please create a project first.")
            return

        project_id, jira_key, name = project
        print(f"Will assign orphaned tasks to project: {name} (key: {jira_key}, id: {project_id})")

        # Ask for confirmation
        response = input("Do you want to proceed? (yes/no): ")
        if response.lower() != 'yes':
            print("Operation cancelled.")
            return

        # Fix orphaned tasks
        result = await conn.execute(
            text("UPDATE tasks SET project_id = :project_id WHERE project_id IS NULL"),
            {"project_id": project_id}
        )

        print(f"✓ Fixed {result.rowcount} orphaned tasks")
        print("  The API should now work without errors.")
        print("  No need to restart the backend!")

async def check_current_status():
    """Check current database status."""
    async with engine.begin() as conn:
        # Count tasks by project
        result = await conn.execute(
            text("""
                SELECT
                    p.jira_key,
                    p.name,
                    COUNT(t.id) as task_count
                FROM projects p
                LEFT JOIN tasks t ON t.project_id = p.id
                GROUP BY p.id, p.jira_key, p.name
            """)
        )

        print("\nCurrent task distribution:")
        for row in result:
            print(f"  - {row.name} ({row.jira_key}): {row.task_count} tasks")

        # Check orphaned tasks
        result = await conn.execute(
            text("SELECT COUNT(*) FROM tasks WHERE project_id IS NULL")
        )
        orphaned = result.scalar()
        if orphaned > 0:
            print(f"  - [ORPHANED]: {orphaned} tasks without project")

if __name__ == "__main__":
    print("Task Database Fixer")
    print("=" * 50)

    asyncio.run(check_current_status())
    print()
    asyncio.run(fix_orphaned_tasks())