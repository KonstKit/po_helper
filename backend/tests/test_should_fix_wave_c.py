"""Wave C regression tests from the Should Fix roadmap (docs/SHOULD_FIX_ROADMAP.md).

C1: N+1 hotspots replaced with batched queries - asserted via a SQL query
    counter: the endpoint cost must be O(constant), not O(rows).
C2: eager loading on the projects list (owner).
C3: bounded per-key locks in the enhanced cache.
"""

from __future__ import annotations

import asyncio

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
    """Counts SQL statements executed on the app engine.

    ``table`` narrows counting to statements touching that table, which
    pins a specific N+1 (e.g. one SELECT per suggestion) without being
    diluted by unrelated business queries in the same request.
    """

    def __init__(self, table: str | None = None):
        self.count = 0
        self.table = table

    def __enter__(self):
        event.listen(engine.sync_engine, "before_cursor_execute", self._bump)
        return self

    def __exit__(self, *exc):
        event.remove(engine.sync_engine, "before_cursor_execute", self._bump)

    def _bump(self, conn, cursor, statement, parameters, *args, **kwargs):
        if self.table is not None and self.table not in statement:
            return
        if statement.lstrip().upper().startswith("SELECT"):
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
            # one duplicate group of two rows -> 1 row to remove
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
async def test_projects_list_has_no_owner_n_plus_one(client):
    """owner is serialized as owner_id (a plain column) - the list must
    stay O(constant) queries for a NON-ADMIN too (streaming branch)."""
    await _seed_roles_and_admin(client)  # first user becomes admin
    po_token = await _register_and_login(client, "po-eag@example.com", "po_eag_user")

    async with AsyncSessionLocal() as db:
        owner = (
            await db.execute(select(User).where(User.email == "po-eag@example.com"))
        ).scalar_one()
        db.add_all(
            Project(jira_key=f"EAG-{i}", name=f"eager {i}", owner_id=owner.id) for i in range(8)
        )
        await db.commit()

    with _real_integration_access():
        with QueryCounter() as counter:
            response = await client.get(
                "/api/v1/projects/",
                headers={"Authorization": f"Bearer {po_token}"},
            )
    assert response.status_code == 200, response.text
    assert len(response.json()) >= 8
    # every serialized field is a plain column: no per-row lazy loads
    assert counter.count <= 6, counter.count


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


# ---------------------------------------------------------------------------
# Review r1 regressions: health project scoping, link pre-pass scope,
# cache lease release and cap-under-load
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_cleanup_respects_project_scope(client):
    """A cleanup for project A must not touch project B's links even when
    they share the (from, to, link_type) tuple (review C-HEALTH-001)."""
    token = await _seed_roles_and_admin(client)

    async with AsyncSessionLocal() as db:
        async with db.begin():
            projects = [
                Project(jira_key="SC-1", name="scoped one"),
                Project(jira_key="SC-2", name="scoped two"),
            ]
            db.add_all(projects)
            await db.flush()
            arts = []
            for p in projects:
                a1 = Artifact(
                    project_id=p.id,
                    type="requirement",
                    external_id=f"{p.jira_key}-A",
                    source="jira",
                )
                a2 = Artifact(
                    project_id=p.id, type="task", external_id=f"{p.jira_key}-B", source="jira"
                )
                db.add_all([a1, a2])
                arts.append((p, a1, a2))
            await db.flush()
            # identical tuple in BOTH projects (twice in A -> duplicate)
            for p, a1, a2 in arts:
                db.add_all(
                    [
                        ArtifactLink(
                            project_id=p.id,
                            from_artifact_id=a1.id,
                            to_artifact_id=a2.id,
                            link_type="implements",
                            confidence=0.9,
                        ),
                        ArtifactLink(
                            project_id=p.id,
                            from_artifact_id=a1.id,
                            to_artifact_id=a2.id,
                            link_type="implements",
                            confidence=0.4,
                        ),
                    ]
                )

    with _real_integration_access():
        response = await client.post(
            "/api/v1/traceability/consistency-check/fix",
            headers={"Authorization": f"Bearer {token}"},
            params={"fix_duplicates": True, "dry_run": False, "project_id": projects[0].id},
        )
    assert response.status_code == 200, response.text

    async with AsyncSessionLocal() as db:
        remaining = (
            (
                await db.execute(
                    select(ArtifactLink).where(ArtifactLink.project_id == projects[1].id)
                )
            )
            .scalars()
            .all()
        )
        assert len(remaining) == 2, "cleanup leaked across projects"
        scoped = (
            (
                await db.execute(
                    select(ArtifactLink).where(ArtifactLink.project_id == projects[0].id)
                )
            )
            .scalars()
            .all()
        )
        assert len(scoped) == 1, "in-scope duplicates not fixed"


@pytest.mark.asyncio
async def test_link_prepass_is_scope_and_integrity_aware():
    """Review C-LINK-001: pre-pass must not skip specs that differ by
    tenant/project, and must not swallow validation via broken links."""
    from app.services.traceability.link_service import LinkService

    async with AsyncSessionLocal() as db:
        async with db.begin():
            project = Project(jira_key="LK", name="LK", owner_id=None)
            db.add(project)
            await db.flush()
            a1 = Artifact(
                project_id=project.id, type="requirement", external_id="LK-1", source="jira"
            )
            a2 = Artifact(project_id=project.id, type="task", external_id="LK-2", source="jira")
            db.add_all([a1, a2])
            await db.flush()
            # existing link scoped to tenant X
            db.add(
                ArtifactLink(
                    tenant_id="tenant-x",
                    project_id=project.id,
                    from_artifact_id=a1.id,
                    to_artifact_id=a2.id,
                    link_type="implements",
                )
            )

        service = LinkService(db)
        # same endpoints but NULL tenant -> different scope key -> NOT skipped
        created, _ = await service.create_links_batch(
            [{"from_artifact_id": a1.id, "to_artifact_id": a2.id, "link_type": "implements"}],
            skip_duplicates=True,
        )
        assert len(created) == 1, "pre-pass over-skipped a different-tenant spec"

        # same full scope as the existing row -> skipped silently
        created2, errors2 = await service.create_links_batch(
            [
                {
                    "from_artifact_id": a1.id,
                    "to_artifact_id": a2.id,
                    "link_type": "implements",
                    "tenant_id": "tenant-x",
                    "project_id": project.id,
                }
            ],
            skip_duplicates=True,
        )
        assert created2 == [] and errors2 == []

        # a broken existing link must not swallow the validation error for
        # a spec pointing at a missing artifact
        db.add(
            ArtifactLink(
                project_id=project.id,
                from_artifact_id=999_999,
                to_artifact_id=a2.id,
                link_type="implements",
            )
        )
        await db.commit()
        created3, errors3 = await service.create_links_batch(
            [{"from_artifact_id": 999_999, "to_artifact_id": a2.id, "link_type": "implements"}],
            skip_duplicates=True,
        )
        assert created3 == []
        assert errors3, "broken-link pre-pass swallowed the validation error"


@pytest.mark.asyncio
async def test_flight_release_is_atomic_compare_and_delete():
    """Review C-CACHE-001: the lease must be released via an atomic Lua
    compare-and-delete, never GET+compare+DELETE."""
    from unittest.mock import AsyncMock, MagicMock

    from app.core.cache_enhanced import _FLIGHT_RELEASE_LUA, EnhancedCacheService

    service = EnhancedCacheService(None)
    redis = MagicMock()
    redis.eval = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    redis.get = AsyncMock(return_value=None)
    redis.delete = AsyncMock()
    service._async_redis = redis
    service._initialized = True

    calls = {"n": 0}

    async def factory():
        calls["n"] += 1
        return {"v": 1}

    await service.get_or_set("atomic-release", factory, tier=CacheTier.HOT)

    assert redis.eval.await_count == 1
    args = redis.eval.await_args.args
    assert args[0] == _FLIGHT_RELEASE_LUA
    assert "del" in _FLIGHT_RELEASE_LUA and "get" in _FLIGHT_RELEASE_LUA
    # GET+DELETE race pattern must not be used for the release
    assert redis.delete.await_count == 0


@pytest.mark.asyncio
async def test_cache_lock_dict_never_exceeds_cap():
    """Review C-CACHE-002: with every registered lock held, a new key gets
    an unregistered lock (Redis-flight only) instead of growing the dict;
    idle entries are always prunable. The dict never exceeds the cap."""
    service = EnhancedCacheService(None)
    service._MAX_PER_KEY_LOCKS = 5  # type: ignore[misc]

    held = [asyncio.Lock() for _ in range(5)]
    for lock in held:
        await lock.acquire()
    service._locks = {f"held-{i}": lock for i, lock in enumerate(held)}

    # every registered lock is held -> new keys must not register
    for i in range(20):
        await service.get_or_set(f"burst-{i}", lambda: i, tier=CacheTier.REALTIME)
    assert len(service._locks) == 5, service._locks.keys()

    # releasing one slot lets exactly one new key register again
    held[0].release()
    await service.get_or_set("after-release", lambda: 1, tier=CacheTier.REALTIME)
    assert len(service._locks) <= 5
    # idle entries are prunable on the next overflow
    for i in range(30):
        await service.get_or_set(f"idle-{i}", lambda: i, tier=CacheTier.REALTIME)
    assert len(service._locks) <= 5


# ---------------------------------------------------------------------------
# Review r1 coverage gaps: remaining C1 hotspots get query-count gates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metrics_commits_for_issue_is_batched():
    from app.api.api_v1.endpoints.git.metrics import get_commits_for_issue
    from app.models.git import Commit, Repository

    async with AsyncSessionLocal() as db:
        async with db.begin():
            project = Project(jira_key="MT", name="MT", owner_id=None)
            db.add(project)
            await db.flush()
            issue = Artifact(
                project_id=project.id,
                type="jira_issue",
                external_id="MT-1",
                source="jira",
            )
            db.add(issue)
            await db.flush()
            repo = Repository(provider="github", repo_slug="org/repo")
            db.add(repo)
            await db.flush()
            for i in range(5):
                sha = f"sha{i:040d}"
                commit_art = Artifact(
                    project_id=project.id, type="commit", external_id=sha, source="git"
                )
                db.add(commit_art)
                await db.flush()
                db.add_all(
                    [
                        ArtifactLink(
                            project_id=project.id,
                            from_artifact_id=commit_art.id,
                            to_artifact_id=issue.id,
                            link_type="implements",
                        ),
                        Commit(
                            sha=sha,
                            repository_id=repo.id,
                            message=f"msg {i}",
                        ),
                    ]
                )

    async with AsyncSessionLocal() as db:
        with QueryCounter() as counter:
            result = await get_commits_for_issue(db, "MT-1")
    assert result["total"] == 5
    # 1 issue + 1 links + 1 commits-batch + 1 repos-batch = 4 (+ pragmas)
    assert counter.count <= 8, counter.count


@pytest.mark.asyncio
async def test_ci_attach_items_batched():
    from app.api.api_v1.endpoints.git.ci import _attach_ci_traceability_items
    from app.models.traceability import Baseline

    async with AsyncSessionLocal() as db:
        async with db.begin():
            project = Project(jira_key="CI", name="CI", owner_id=None)
            db.add(project)
            await db.flush()
            baseline = Baseline(project_id=project.id, name="b1")
            db.add(baseline)
            await db.flush()
            arts = [
                Artifact(
                    project_id=project.id,
                    type="commit",
                    external_id=f"CI-{i}",
                    source="git",
                )
                for i in range(6)
            ]
            db.add_all(arts)
            await db.flush()

    async with AsyncSessionLocal() as db:
        with QueryCounter() as counter:
            updates, created_id = await _attach_ci_traceability_items(
                db,
                baseline_ids=[baseline.id],
                projection_ids=[],
                artifact_ids=[a.id for a in arts],
                link_id=None,
                project_id=project.id,
            )
            await db.commit()
    assert created_id == baseline.id
    # one existence query for the artifact batch + a handful of lookups
    assert counter.count <= 12, counter.count

    # second call must be a no-op via the same batched existence check
    async with AsyncSessionLocal() as db:
        with QueryCounter() as counter2:
            updates2, _ = await _attach_ci_traceability_items(
                db,
                baseline_ids=[baseline.id],
                projection_ids=[],
                artifact_ids=[a.id for a in arts],
                link_id=None,
                project_id=project.id,
            )
        assert counter2.count <= 12, counter2.count


@pytest.mark.asyncio
async def test_suggestions_bulk_approve_is_batched(client):
    from app.models.traceability import SuggestedLink

    token = await _seed_roles_and_admin(client)

    async with AsyncSessionLocal() as db:
        async with db.begin():
            project = Project(jira_key="SG", name="SG", owner_id=None)
            db.add(project)
            await db.flush()
            a1 = Artifact(
                project_id=project.id, type="requirement", external_id="SG-1", source="jira"
            )
            a2 = Artifact(project_id=project.id, type="task", external_id="SG-2", source="jira")
            db.add_all([a1, a2])
            await db.flush()
            db.add_all(
                SuggestedLink(
                    project_id=project.id,
                    from_artifact_id=a1.id,
                    to_artifact_id=a2.id,
                    suggested_link_type="implements",
                    status="pending",
                    similarity_score=0.9,
                    method="auto",
                )
                for _ in range(6)
            )

    from sqlalchemy import select as sa_select

    from app.models.traceability import SuggestedLink as SL

    async with AsyncSessionLocal() as session:
        ids = [row[0] for row in (await session.execute(sa_select(SL.id).limit(6))).all()]

    with _real_integration_access():
        with QueryCounter(table="suggested_links") as counter:
            response = await client.post(
                "/api/v1/traceability/suggested-links/bulk-approve",
                headers={"Authorization": f"Bearer {token}"},
                json=ids,  # List[int] without Query() binds to the BODY
            )
    assert response.status_code == 200, response.text
    # the pre-load reads the whole payload in ONE SELECT (UPDATEs are
    # excluded by the counter's SELECT-only filter)
    assert counter.count == 1, counter.count


@pytest.mark.asyncio
async def test_jira_fields_import_is_batched(client, monkeypatch):
    token = await _seed_roles_and_admin(client)

    from unittest.mock import MagicMock

    from app.services.jira_service import jira_service

    config = {
        "base_url": "https://jira.example.com",
        "mappings": {f"field_{i}": f"customfield_{i:05d}" for i in range(8)},
    }
    # the mapper dependency 400s without a Jira transport; inject one so
    # the import handler (and its batch query) actually runs
    monkeypatch.setattr(jira_service, "http_client", MagicMock())
    monkeypatch.setattr(jira_service, "base_url", "https://jira.example.com")
    with _real_integration_access():
        with QueryCounter(table="jira_field_mappings") as counter:
            response = await client.post(
                "/api/v1/jira-fields/import-config",
                headers={"Authorization": f"Bearer {token}"},
                json=config,
            )
    assert response.status_code == 200, response.text
    # exactly one SELECT pre-loads the whole config (INSERTs are writes)
    assert counter.count == 1, counter.count
