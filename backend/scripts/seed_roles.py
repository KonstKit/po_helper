"""
Seed RBAC roles into the database.

This script ensures all system roles exist in the database.
Safe to run multiple times - updates existing roles.

Usage:
    cd backend
    python scripts/seed_roles.py
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models import Role, SYSTEM_ROLES
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def seed_roles(session: AsyncSession):
    """Create or update system roles."""
    logger.info("=" * 80)
    logger.info("SEEDING RBAC ROLES")
    logger.info("=" * 80)

    created = 0
    updated = 0
    skipped = 0

    for role_name, role_config in SYSTEM_ROLES.items():
        # Check if role exists
        result = await session.execute(select(Role).where(Role.name == role_name))
        role = result.scalar_one_or_none()

        if role:
            # Update existing role
            role.display_name = role_config["display_name"]
            role.description = role_config["description"]
            role.is_system = role_config["is_system"]
            role.permissions = role_config["permissions"]
            updated += 1
            logger.info(f"✓ Updated role: {role_name} ({role.display_name})")
            logger.info(f"  Permissions: {len(role.permissions)} - {role.permissions[:3]}...")
        else:
            # Create new role
            role = Role(
                name=role_name,
                display_name=role_config["display_name"],
                description=role_config["description"],
                is_system=role_config["is_system"],
                permissions=role_config["permissions"],
            )
            session.add(role)
            created += 1
            logger.info(f"✓ Created role: {role_name} ({role.display_name})")
            logger.info(f"  Permissions: {len(role.permissions)} - {role.permissions[:3]}...")

    await session.commit()

    logger.info("")
    logger.info("=" * 80)
    logger.info("SEED SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Created: {created}")
    logger.info(f"Updated: {updated}")
    logger.info(f"Skipped: {skipped}")
    logger.info("=" * 80)

    if created > 0 or updated > 0:
        logger.info("✓ Roles seeded successfully")
    else:
        logger.info("✓ All roles already up to date")


async def main():
    """Main entry point."""
    logger.info("Starting role seeding...")

    async with AsyncSessionLocal() as session:
        try:
            await seed_roles(session)
        except Exception as e:
            logger.error(f"Error seeding roles: {e}", exc_info=True)
            sys.exit(1)

    logger.info("✓ Done")


if __name__ == "__main__":
    asyncio.run(main())
