import asyncio
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models import Project

async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Project).where(Project.jira_key == 'PRIM'))
        project = result.scalar_one_or_none()
        print('meta:', project.meta, type(project.meta))

asyncio.run(main())
