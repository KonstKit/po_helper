"""
Debug script to identify why PRIM project sync is not saving data.
Run this to see detailed logging of the sync process.
"""

import asyncio
import logging
from datetime import datetime
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models import Project, Task
from app.services.jira_service import jira_service
from app.services.jira_sync import perform_project_sync

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_sync_with_logging():
    """Test PRIM project sync with enhanced logging."""

    project_key = "PRIM"

    # 1. Check initial state
    async with AsyncSessionLocal() as db:
        # Get project
        result = await db.execute(select(Project).where(Project.jira_key == project_key))
        project = result.scalar_one_or_none()

        if not project:
            logger.error(f"Project {project_key} not found in database!")
            return

        project_id = project.id
        logger.info(f"Found project: {project_key} with id={project_id}")

        # Count existing tasks
        count_result = await db.execute(
            select(func.count(Task.id)).where(Task.project_id == project_id)
        )
        initial_count = count_result.scalar()
        logger.info(f"Initial task count: {initial_count}")

    # 2. Run the sync
    logger.info("=" * 80)
    logger.info("Starting sync...")
    logger.info("=" * 80)

    try:
        # Call the sync function directly
        await perform_project_sync(project_key, project_id)
        logger.info("Sync completed successfully")
    except Exception as e:
        logger.error(f"Sync failed with error: {e}", exc_info=True)
        return

    # 3. Check final state
    logger.info("=" * 80)
    logger.info("Checking results...")
    logger.info("=" * 80)

    async with AsyncSessionLocal() as db:
        # Count tasks after sync
        count_result = await db.execute(
            select(func.count(Task.id)).where(Task.project_id == project_id)
        )
        final_count = count_result.scalar()
        logger.info(f"Final task count: {final_count}")

        # Get a few sample tasks
        sample_result = await db.execute(
            select(Task).where(Task.project_id == project_id).limit(5)
        )
        samples = sample_result.scalars().all()

        if samples:
            logger.info("Sample tasks:")
            for task in samples:
                logger.info(f"  - {task.key}: {task.summary}")
        else:
            logger.warning("No tasks found after sync!")

        # Check project metadata
        project_result = await db.execute(select(Project).where(Project.id == project_id))
        project = project_result.scalar_one_or_none()
        if project and project.meta:
            logger.info(f"Project metadata: {project.meta}")

if __name__ == "__main__":
    # Import after logging is configured
    from app.core.config import settings
    from sqlalchemy import func

    # Ensure Jira is connected
    if not jira_service.base_url:
        logger.info("Initializing Jira connection from settings...")
        from app.models.settings import IntegrationSetting
        from app.core.crypto import decrypt_str

        async def setup_jira():
            async with AsyncSessionLocal() as db:
                res = await db.execute(select(IntegrationSetting).where(IntegrationSetting.kind == 'jira'))
                row = res.scalar_one_or_none()
                if row and row.base_url and row.api_token:
                    token = decrypt_str(row.api_token)
                    email = None if getattr(settings, 'JIRA_FORCE_PAT', True) else (row.email or None)
                    jira_service.connect(row.base_url, email, token)
                    logger.info(f'Jira connected: base_url={row.base_url}, mode={"PAT" if email is None else "Basic"}')
                else:
                    logger.error("No Jira settings found in database!")

        asyncio.run(setup_jira())

    # Run the test
    asyncio.run(test_sync_with_logging())