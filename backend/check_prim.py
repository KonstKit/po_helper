import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.core.config import settings
import json

async def check():
    engine = create_async_engine(str(settings.DATABASE_URL))
    async with engine.begin() as conn:
        # Check PRIM project
        result = await conn.execute(text("SELECT id, jira_key, name, meta FROM projects WHERE jira_key = 'PRIM'"))
        row = result.fetchone()
        print(f"Project PRIM: id={row[0]}, key={row[1]}, name={row[2]}")
        if row[3]:
            try:
                meta = json.loads(row[3]) if isinstance(row[3], str) else row[3]
                print(f"  Meta: {json.dumps(meta, indent=2)}")
            except (json.JSONDecodeError, TypeError, ValueError):
                print(f"  Meta (raw): {row[3]}")
        else:
            print("  Meta: None (no sync data)")

        # Check if there are tasks
        result = await conn.execute(text("SELECT COUNT(*) FROM tasks WHERE project_id = (SELECT id FROM projects WHERE jira_key = 'PRIM')"))
        task_count = result.scalar()
        print(f"  Tasks count: {task_count}")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(check())
