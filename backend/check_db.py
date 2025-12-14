import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.core.config import settings

async def check():
    engine = create_async_engine(str(settings.DATABASE_URL))
    async with engine.begin() as conn:
        # First check the table schema
        result = await conn.execute(text("PRAGMA table_info(projects)"))
        columns = result.fetchall()
        print("Projects table columns:", columns)

        result = await conn.execute(text("SELECT * FROM projects"))
        rows = result.fetchall()
        print("Projects in DB:", rows)

        result2 = await conn.execute(text("SELECT COUNT(*) FROM projects"))
        count = result2.scalar()
        print(f"Total projects: {count}")
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(check())