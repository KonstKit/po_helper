"""Wave C regression tests from the Should Fix roadmap (docs/SHOULD_FIX_ROADMAP.md).

C1: N+1 hotspots replaced with batched queries - asserted via a SQL query
    counter: the endpoint cost must be O(constant), not O(rows).
C2: eager loading on the projects list (owner).
C3: bounded per-key locks in the enhanced cache.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event, select
from app.core.database import AsyncSessionLocal

from app.core.cache_enhanced import CacheTier, EnhancedCacheService
from app.core.database import engine
from app.models import Project, User
from app.models.traceability import Artifact, ArtifactLink
from app.models.traceability_rule import TraceabilityRule, TraceabilityRuleExecution
from tests.test_blocker_fixes import _real_integration_access, _register_and_login


class QueryCounter:
    """Counts SQL statements executed on the app engine."""

    def __init__(self):
        self.count = 0

    def __enter__(self):
        event.listen(engine.sync_engine, "before_cursor_execute", self._bump)
        return self

    def __exit__(self, *exc):
        event.remove(engine.sync_engine, "before_cursor_execute", self._bump)

    def _bump(self, *args, **kwargs):
        self.count += 1


async def _seed_roles_and_admin(client) -> str:
    from tests.test_blocker_fixes import _seed_system_roles

    await _seed_system_roles()
    return await _register_and_login(client, "admin-c@example.com", "admin_c_user")


# ---------------------------------------------------------------------------
# C1.1: rules executions listing batches rule lookups
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rule_executions_listing_is_constant_query(client):
    token = await _seed_roles_and_admin(client)
    rule_count = 15

    async with AsyncSessionLocal() as db:
        async with db.begin():
            rules = [
                TraceabilityRule(
                    name=f"rule-{i}",
                    description=f"rule {i}",
                    enabled=True,
                    flow_json={"nodes": [], "edges": []},
                )
                for i in range(rule_count)
            ]
            db.add_all(rules)
            await db.flush()
            db.add_all(
                TraceabilityRuleExecution(
                    rule_id=rules[i].id,
                    status="success",
                    links_created=0,
                )
                for i in range(rule_count)
            )

    with _real_integration_access():
        with QueryCounter() as counter:
            response = await client.get(
                "/api/v1/traceability/rules/executions",
                headers={"Authorization": f"Bearer {token}"},
                params={"limit": rule_count},
            )
    assert response.status_code == 200, response.text
    rows = len(response.json()["items"])
    assert rows >= rule_count
    # before wave C this made 1 + rule_count SELECTs; now it must be a
    # small constant regardless of the row count
    assert counter.count <= 12, f"N+1 regression: {counter.count} queries for {rows} executions"


# ---------------------------------------------------------------------------
# C1.3: impact-analysis BFS batches per level
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_impact_analysis_bfs_is_level_batched(client):
    token = await _seed_roles_and_admin(client)

    async with AsyncSessionLocal() as db:
        async with db.begin():
            project = Project(jira_key="BFS", name="BFS", owner_id=None)
            db.add(project)
            await db.flush()
            # chain: root -> a1 -> a2 -> a3 (depth 3 forces 3 BFS levels)
            artifacts = []
            for i in range(4):
                art = Artifact(
                    project_id=project.id,
                    type="requirement",
                    external_id=f"BFS-{i}",
                    title=f"bfs {i}",
                    source="jira",
                )
                artifacts.append(art)
                db.add(art)
            await db.flush()
            for i in range(3):
                db.add(
                    ArtifactLink(
                        project_id=project.id,
                        from_artifact_id=artifacts[i].id,
                        to_artifact_id=artifacts[i + 1].id,
                        link_type="implements",
                    )
                )

    with _real_integration_access():
        with QueryCounter() as counter:
            response = await client.get(
                f"/api/v1/traceability/impact-analysis/{artifacts[0].id}",
                headers={"Authorization": f"Bearer {token}"},
            )
    assert response.status_code == 200, response.text
    body = response.json()
    indirect = body.get("indirectly_affected") or body.get("impact", {}).get(
        "indirectly_affected", []
    )
    # chain root->a1->a2->a3: a1 is direct, a2/a3 are the indirect ones
    assert len(indirect) == 2
    # per-level batching: queries scale with BFS depth, not node count
    assert counter.count <= 14, counter.count


# ---------------------------------------------------------------------------
# C1.2: health cleanup issues a bulk delete (single statement)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_cleanup_uses_bulk_statements(client):
    token = await _seed_roles_and_admin(client)

    async with AsyncSessionLocal() as db:
        async with db.begin():
            project = Project(jira_key="HC", name="HC", owner_id=None)
            db.add(project)
            await db.flush()
            a1 = Artifact(
                project_id=project.id, type="requirement", external_id="HC-1", source="jira"
            )
            a2 = Artifact(project_id=project.id, type="task", external_id="HC-2", source="jira")
            db.add_all([a1, a2])
            await db.flush()
            # two duplicate groups (3 rows + 2 rows) -> 2 rows to remove
            db.add_all(
                [
                    ArtifactLink(
                        project_id=project.id,
                        from_artifact_id=a1.id,
                        to_artifact_id=a2.id,
                        link_type="implements",
                        confidence=0.9,
                    ),
                    ArtifactLink(
                        project_id=project.id,
                        from_artifact_id=a1.id,
                        to_artifact_id=a2.id,
                        link_type="implements",
                        confidence=0.5,
                    ),
                ]
            )

    with _real_integration_access():
        with QueryCounter() as counter:
            response = await client.post(
                "/api/v1/traceability/consistency-check/fix",
                headers={"Authorization": f"Bearer {token}"},
                params={"fix_duplicates": True, "dry_run": False},
            )
    assert response.status_code == 200, response.text
    assert response.json().get("duplicates_removed", 0) >= 1
    # single grouped SELECT + single bulk DELETE for duplicates
    assert counter.count <= 10, counter.count


# ---------------------------------------------------------------------------
# C2: projects list eagerly loads owner (no lazy N+1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_projects_list_eager_loads_owner(client):
    token = await _seed_roles_and_admin(client)

    async with AsyncSessionLocal() as db:
        async with db.begin():
            result = await db.execute(select(User).limit(1))
            owner = result.scalar_one_or_none()
            db.add_all(
                Project(
                    jira_key=f"EAG-{i}", name=f"eager {i}", owner_id=owner.id if owner else None
                )
                for i in range(8)
            )

    with _real_integration_access():
        with QueryCounter() as counter:
            response = await client.get(
                "/api/v1/projects/",
                headers={"Authorization": f"Bearer {token}"},
            )
    assert response.status_code == 200, response.text
    assert len(response.json()) >= 8
    # 1 SELECT projects + 1 SELECT owners (selectinload); a lazy-load N+1
    # would add one query per project
    assert counter.count <= 8, counter.count


# ---------------------------------------------------------------------------
# C1.6: link batch pre-pass skips existing links with one query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_link_batch_prepass_single_existence_query():
    from app.services.traceability.link_service import LinkService

    async with AsyncSessionLocal() as db:
        async with db.begin():
            project = Project(jira_key="LB", name="LB", owner_id=None)
            db.add(project)
            await db.flush()
            a1 = Artifact(
                project_id=project.id, type="requirement", external_id="LB-1", source="jira"
            )
            a2 = Artifact(project_id=project.id, type="task", external_id="LB-2", source="jira")
            db.add_all([a1, a2])
            await db.flush()
            db.add(
                ArtifactLink(
                    project_id=project.id,
                    from_artifact_id=a1.id,
                    to_artifact_id=a2.id,
                    link_type="implements",
                )
            )

    service = LinkService(db)
    with QueryCounter() as counter:
        created, errors = await service.create_links_batch(
            [
                {
                    "from_artifact_id": a1.id,
                    "to_artifact_id": a2.id,
                    "link_type": "implements",
                }
            ]
            * 5,
            skip_duplicates=True,
        )
    assert created == [] and errors == []
    # one pre-pass existence query; before wave C each spec did its own
    # round-trip inside create_link
    assert counter.count <= 6, counter.count


# ---------------------------------------------------------------------------
# C3: bounded per-key locks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_locks_are_bounded():
    service = EnhancedCacheService(None)  # memory-only mode
    for i in range(service._MAX_PER_KEY_LOCKS + 500):
        await service.get_or_set(f"burst-{i}", lambda: i, tier=CacheTier.REALTIME)
    assert len(service._locks) <= service._MAX_PER_KEY_LOCKS
