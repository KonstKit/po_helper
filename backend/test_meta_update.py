import asyncio
from app.core.database import AsyncSessionLocal
from sqlalchemy import select, text
from app.models import Project
import json
from datetime import datetime

async def test_meta_update():
    print("Testing metadata update for PRIM project...")

    async with AsyncSessionLocal() as db:
        # Get the project
        result = await db.execute(
            select(Project).where(Project.jira_key == "PRIM")
        )
        project = result.scalar_one_or_none()

        if not project:
            print("ERROR: PRIM project not found!")
            return

        print(f"Project: {project.name} (id={project.id})")
        print(f"Current meta: {project.meta}")

        # Update meta manually like jira_sync does
        metadata = project.meta or {}
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except:
                metadata = {}

        metadata['last_sync_at'] = datetime.now().isoformat()
        metadata['issues_count'] = 123  # Test value

        project.meta = metadata
        print(f"New meta: {metadata}")

        # Commit the change
        await db.commit()
        print("Committed changes")

        # Verify it was saved
        await db.refresh(project)
        print(f"After refresh meta: {project.meta}")

    # Check again in new session
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Project).where(Project.jira_key == "PRIM")
        )
        project = result.scalar_one_or_none()
        print(f"\nIn new session, meta: {project.meta}")

if __name__ == "__main__":
    asyncio.run(test_meta_update())