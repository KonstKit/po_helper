"""
Test script for GitLab commit synchronization with pagination fix.
Usage: python test_gitlab_sync.py
"""
import asyncio
import logging
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from app.services.git_import_service import GitImportService
from app.core.crypto import encrypt_str
from app.core.database import Base
from app.models import IntegrationSetting, Repository, Project
import json

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Test configuration
GITLAB_URL = "https://git.andersenlab.com"
GITLAB_TOKEN = "wSiGrq8iP1qm_yWyR7hS"  # Common token

# Test repositories - use one accessible by the token
TEST_REPOS = [
    "Andersen/primacare/backend",  # This token has access to this project
]


async def setup_test_database():
    """Create test database and setup GitLab integration."""
    engine = create_async_engine("sqlite+aiosqlite:///./test_gitlab.db", echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Create test project
        project = Project(
            id=1,
            name="WaBank Test",
            jira_key="WABANK",
            description="Test project for GitLab sync"
        )
        session.add(project)

        # Setup GitLab integration
        token_bundle = json.dumps({"api_token": GITLAB_TOKEN})
        encrypted_token = encrypt_str(token_bundle)

        gitlab_setting = IntegrationSetting(
            kind="gitlab",
            base_url=GITLAB_URL,
            api_token=encrypted_token
        )
        session.add(gitlab_setting)

        # Add test repositories
        for idx, repo_slug in enumerate(TEST_REPOS, start=1):
            repo = Repository(
                id=idx,
                provider="gitlab",
                repo_slug=repo_slug,
                default_branch="dev"  # Use dev branch which has commits
            )
            session.add(repo)

            # Link repository to project via ProjectRepository
            from app.models import ProjectRepository
            proj_repo = ProjectRepository(
                project_id=1,
                repository_id=idx
            )
            session.add(proj_repo)

        await session.commit()
        logger.info(f"Test database created with {len(TEST_REPOS)} repositories")

    return async_session


async def test_gitlab_sync():
    """Test GitLab synchronization with pagination."""
    logger.info("=" * 80)
    logger.info("Starting GitLab Synchronization Test")
    logger.info("=" * 80)

    async_session = await setup_test_database()
    service = GitImportService()

    try:
        async with async_session() as session:
            logger.info("\n" + "=" * 80)
            logger.info("SYNCING PROJECT 1 - All repositories")
            logger.info("=" * 80)

            result = await service.sync_project(
                db=session,
                project_id=1,
                include_commits=True,
                include_pull_requests=True
            )

            logger.info("\n" + "=" * 80)
            logger.info("SYNC RESULTS")
            logger.info("=" * 80)

            print(f"\nProject ID: {result['project_id']}")
            print(f"Repositories processed: {len(result['repositories'])}\n")

            for repo_result in result['repositories']:
                print(f"\n{'=' * 60}")
                print(f"Repository: {repo_result['repo_slug']}")
                print(f"Provider: {repo_result['provider']}")
                print(f"Default branch: {repo_result['default_branch']}")

                if 'commits' in repo_result:
                    commits_data = repo_result['commits']
                    if 'error' in commits_data:
                        print(f"  [X] Commits ERROR: {commits_data['error']}")
                    else:
                        print(f"  [OK] Commits created: {commits_data.get('created', 0)}")
                        print(f"  [OK] Commits updated: {commits_data.get('updated', 0)}")
                        print(f"  [OK] Links created: {commits_data.get('links_created', 0)}")
                        print(f"  [INFO] Suggestions: {len(commits_data.get('suggestions', []))}")

                if 'pull_requests' in repo_result:
                    pr_data = repo_result['pull_requests']
                    if 'error' in pr_data:
                        print(f"  [X] MRs ERROR: {pr_data['error']}")
                    else:
                        print(f"  [OK] MRs processed: {pr_data.get('processed', 0)}")
                        print(f"  [OK] MR links created: {pr_data.get('links_created', 0)}")

            logger.info("\n" + "=" * 80)
            logger.info("TEST COMPLETED SUCCESSFULLY")
            logger.info("=" * 80)

    except Exception as e:
        logger.error(f"\n❌ TEST FAILED: {e}", exc_info=True)
        raise
    finally:
        service.close()


if __name__ == "__main__":
    asyncio.run(test_gitlab_sync())
