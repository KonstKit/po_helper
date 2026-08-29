"""
Assign role to demo user.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionLocal
from app.models import User, Role


async def main():
    """Assign admin role to demo user."""
    async with AsyncSessionLocal() as db:
        # Get demo user with roles
        result = await db.execute(
            select(User).options(selectinload(User.roles)).where(User.email == "demo@example.com")
        )
        user = result.scalar_one_or_none()

        if not user:
            print("[ERROR] Demo user not found")
            return

        print(f"User: {user.email} (ID: {user.id})")
        print(f"Superuser: {user.is_superuser}")
        print(f"Current roles: {[r.name for r in user.roles]}")

        # Get admin role
        result = await db.execute(select(Role).where(Role.name == "admin"))
        admin_role = result.scalar_one_or_none()

        if not admin_role:
            print("[ERROR] Admin role not found")
            return

        # Check if already has admin role
        if admin_role in user.roles:
            print("[OK] User already has admin role")
            return

        # Assign admin role
        user.roles.append(admin_role)
        await db.commit()

        print(f"[OK] Assigned 'admin' role to {user.email}")


if __name__ == "__main__":
    asyncio.run(main())
