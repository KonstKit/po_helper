"""
Test script to verify database operations are working correctly.
This will help identify if the issue is with the database itself or the sync logic.
"""

import asyncio
import logging
from datetime import datetime
from sqlalchemy import select, func
from app.core.database import AsyncSessionLocal, engine
from app.models import Project, Task

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def test_database_operations():
    """Test basic database operations to ensure they're working."""

    project_key = "PRIM"

    # Test 1: Basic connection and query
    logger.info("Test 1: Testing basic database connection...")
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(func.count(Project.id)))
            count = result.scalar()
            logger.info(f"  ✓ Database connected. Found {count} projects.")
    except Exception as e:
        logger.error(f"  ✗ Database connection failed: {e}")
        return

    # Test 2: Find PRIM project
    logger.info("Test 2: Finding PRIM project...")
    project_id = None
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Project).where(Project.jira_key == project_key))
            project = result.scalar_one_or_none()
            if project:
                project_id = project.id
                logger.info(f"  ✓ Found project PRIM with id={project_id}")
            else:
                logger.error(f"  ✗ Project PRIM not found!")
                return
    except Exception as e:
        logger.error(f"  ✗ Error finding project: {e}")
        return

    # Test 3: Count existing tasks
    logger.info("Test 3: Counting existing tasks for PRIM...")
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(func.count(Task.id)).where(Task.project_id == project_id)
            )
            count = result.scalar()
            logger.info(f"  ✓ Found {count} tasks for PRIM")
    except Exception as e:
        logger.error(f"  ✗ Error counting tasks: {e}")

    # Test 4: Try to create a test task
    logger.info("Test 4: Creating a test task...")
    test_key = f"TEST-{datetime.now().timestamp()}"
    try:
        async with AsyncSessionLocal() as db:
            # Create task
            task = Task(
                project_id=project_id,
                key=test_key,
                summary="Test task created by debug script",
                status="Open",
                created_date=datetime.utcnow()
            )
            db.add(task)
            await db.flush()
            logger.info(f"  - Task added to session: {test_key}")

            # Commit
            await db.commit()
            logger.info(f"  - Commit successful")

            # Verify it was saved
            result = await db.execute(select(Task).where(Task.key == test_key))
            saved_task = result.scalar_one_or_none()
            if saved_task:
                logger.info(f"  ✓ Test task successfully created and verified: {saved_task.key}")
            else:
                logger.error(f"  ✗ Task was not found after commit!")

    except Exception as e:
        logger.error(f"  ✗ Error creating test task: {e}", exc_info=True)

    # Test 5: Test batch operations
    logger.info("Test 5: Testing batch operations...")
    batch_keys = [f"BATCH-{i}-{datetime.now().timestamp()}" for i in range(5)]
    try:
        async with AsyncSessionLocal() as db:
            # Add batch
            for key in batch_keys:
                task = Task(
                    project_id=project_id,
                    key=key,
                    summary=f"Batch test task {key}",
                    status="Open"
                )
                db.add(task)

            await db.flush()
            await db.commit()
            logger.info(f"  - Batch of {len(batch_keys)} tasks committed")

            # Verify
            result = await db.execute(
                select(func.count(Task.id)).where(Task.key.in_(batch_keys))
            )
            count = result.scalar()
            if count == len(batch_keys):
                logger.info(f"  ✓ All {count} batch tasks successfully saved")
            else:
                logger.error(f"  ✗ Only {count} of {len(batch_keys)} tasks were saved")

    except Exception as e:
        logger.error(f"  ✗ Error in batch operations: {e}", exc_info=True)

    # Test 6: Check database file
    logger.info("Test 6: Checking database file...")
    import os
    db_path = "po_helper.db"
    if os.path.exists(db_path):
        size = os.path.getsize(db_path) / 1024 / 1024  # MB
        logger.info(f"  ✓ Database file exists: {os.path.abspath(db_path)} ({size:.2f} MB)")
    else:
        logger.error(f"  ✗ Database file not found at {os.path.abspath(db_path)}")

    # Test 7: Check SQLite WAL files
    wal_path = "po_helper.db-wal"
    shm_path = "po_helper.db-shm"
    if os.path.exists(wal_path):
        size = os.path.getsize(wal_path) / 1024  # KB
        logger.info(f"  - WAL file exists: {wal_path} ({size:.2f} KB)")
    if os.path.exists(shm_path):
        logger.info(f"  - SHM file exists: {shm_path}")

    # Clean up test data
    logger.info("\nCleaning up test data...")
    try:
        async with AsyncSessionLocal() as db:
            # Delete test tasks
            all_test_keys = [test_key] + batch_keys
            await db.execute(
                select(Task).where(Task.key.in_(all_test_keys)).delete()
            )
            await db.commit()
            logger.info(f"  ✓ Cleaned up {len(all_test_keys)} test tasks")
    except Exception as e:
        logger.error(f"  ✗ Error cleaning up: {e}")

if __name__ == "__main__":
    asyncio.run(test_database_operations())