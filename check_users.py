import asyncio
import sys
sys.path.append('backend')
from app.db.session import SessionLocal
from app.models import User
from sqlalchemy import select

async def get_users():
    async with SessionLocal() as db:
        result = await db.execute(select(User.email))
        return result.scalars().all()

if __name__ == "__main__":
    users = asyncio.run(get_users())
    print("Users in database:")
    for user in users:
        print(f"  - {user}")
    if not users:
        print("  No users found")