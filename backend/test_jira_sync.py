import asyncio
from app.services.jira_service import jira_service
from app.core.database import AsyncSessionLocal
from app.services.jira_sync import perform_project_sync
from sqlalchemy import select, text
from app.models import Project
import json

async def test_sync():
    print("Testing PRIM project sync...")

    # Initialize Jira from stored settings if not connected
    if not jira_service.base_url:
        print("Jira not connected, loading from settings...")
        from app.models.settings import IntegrationSetting
        from app.core.crypto import decrypt_str
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            res = await db.execute(select(IntegrationSetting).where(IntegrationSetting.kind == 'jira'))
            row = res.scalar_one_or_none()
            if row and row.base_url and row.api_token:
                token = decrypt_str(row.api_token)
                email = row.email if row.email else None
                print(f"Connecting to Jira: {row.base_url} (email={email or 'PAT mode'})")
                try:
                    jira_service.connect(row.base_url, email, token)
                except Exception as e:
                    print(f"Connection error: {e}")
                    import traceback
                    traceback.print_exc()
                    return
            else:
                print("ERROR: No Jira settings found in database!")
                return

    # Check if Jira is connected
    if not jira_service.base_url:
        print("ERROR: Failed to connect to Jira!")
        return

    print(f"Jira connected to: {jira_service.base_url}")

    # Try to fetch issues directly from Jira
    try:
        jql = f"project = PRIM"
        print(f"Fetching issues with JQL: {jql}")
        issues = jira_service.get_project_issues("PRIM", max_results=5)
        print(f"Found {len(issues) if issues else 0} issues in PRIM project")
        if issues:
            for issue in issues[:3]:
                key = issue.get('key', 'N/A')
                fields = issue.get('fields', {})
                summary = fields.get('summary', 'N/A')
                print(f"  - {key}: {summary}")
    except Exception as e:
        print(f"ERROR fetching issues: {e}")
        return

    # Get project ID
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Project).where(Project.jira_key == "PRIM")
        )
        project = result.scalar_one_or_none()
        if not project:
            print("ERROR: PRIM project not found in database!")
            return
        project_id = project.id

    # Now try the sync
    print(f"\nRunning limited sync for project_id={project_id}...")
    print("NOTE: This is a test, syncing only first 10 issues...")

    # Import logger to see progress
    import logging
    logging.basicConfig(level=logging.INFO)

    try:
        # Temporarily limit issues for testing
        original_limit = getattr(jira_service, '_test_limit', None)
        jira_service._test_limit = 10

        await perform_project_sync("PRIM", project_id)

        if original_limit is not None:
            jira_service._test_limit = original_limit

        print("Sync completed successfully")

        # Check the database
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Project).where(Project.jira_key == "PRIM")
            )
            project = result.scalar_one_or_none()
            if project:
                print(f"\nProject in DB: {project.name}")
                if project.meta:
                    meta = json.loads(project.meta) if isinstance(project.meta, str) else project.meta
                    print(f"  Meta: {json.dumps(meta, indent=2)}")
                else:
                    print("  Meta: None")

                # Count tasks
                result = await db.execute(text(f"SELECT COUNT(*) FROM tasks WHERE project_id = {project.id}"))
                task_count = result.scalar()
                print(f"  Tasks in DB: {task_count}")
            else:
                print("ERROR: Project not found in database!")

    except Exception as e:
        print(f"ERROR during sync: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_sync())