import asyncio
import sys
import os
sys.path.append(os.path.dirname(__file__))

from app.core.database import engine, Base
# Import models so that metadata is populated
from app import models  # noqa: F401

async def create_tables():
    print("Creating database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Database tables created successfully!")

if __name__ == "__main__":
    asyncio.run(create_tables())
