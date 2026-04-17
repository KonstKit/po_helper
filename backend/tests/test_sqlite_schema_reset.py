from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models import Projection, ProjectionItem, Role, User, user_roles
from tests._sqlite_schema import reset_sqlite_schema


@pytest.mark.asyncio
async def test_sqlite_schema_reset_clears_user_roles_and_projection_items():
    await reset_sqlite_schema()

    async with AsyncSessionLocal() as session:
        user = User(email="reset@example.com", username="reset-user", full_name="Reset User")
        role = Role(name="reset-role", display_name="Reset Role", description=None, is_system=False)
        projection = Projection(name="Reset Projection")
        session.add_all([user, role, projection])
        await session.flush()

        await session.execute(user_roles.insert().values(user_id=user.id, role_id=role.id))
        session.add(ProjectionItem(projection_id=projection.id, artifact_id=None, link_id=None))
        await session.commit()

    async with AsyncSessionLocal() as session:
        user_role_count = (
            await session.execute(select(func.count()).select_from(user_roles))
        ).scalar_one()
        projection_item_count = (
            await session.execute(select(func.count()).select_from(ProjectionItem))
        ).scalar_one()

    assert user_role_count == 1
    assert projection_item_count == 1

    await reset_sqlite_schema()

    async with AsyncSessionLocal() as session:
        user_role_count = (
            await session.execute(select(func.count()).select_from(user_roles))
        ).scalar_one()
        projection_item_count = (
            await session.execute(select(func.count()).select_from(ProjectionItem))
        ).scalar_one()

    assert user_role_count == 0
    assert projection_item_count == 0
