"""Mixed-batch regression test for bulk-approve (Case #10).

Builds a single bulk-approve request mixing a VALID pending suggestion, a
DUPLICATE (link already exists), a CYCLE (DAG-enforced edge would be closed),
and a non-existent id, then asserts per-item correctness:

- VALID    -> approved, a new ArtifactLink is created.
- DUPLICATE -> approved, no second ArtifactLink created (link pre-exists).
- CYCLE    -> auto-rejected, counted in results.cycle_prevented, no link.
- BAD ID   -> surfaced in results.errors[].

All artifacts/suggestions use project_id=None so ensure_project_access is never
invoked (the default superuser test user carries TRACEABILITY_MANAGE). Post-API
state is read from a fresh AsyncSessionLocal() to avoid WAL snapshot staleness.

Mirrors the seed helpers and _suggestion_status pattern from
tests/test_traceability_suggestions_workflow.py.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.traceability import Artifact, ArtifactLink, SuggestedLink


async def _suggestion_status(sug_id: int) -> str:
    """Read suggestion status from a fresh session (avoids WAL snapshot staleness)."""
    async with AsyncSessionLocal() as s:
        return (
            await s.execute(select(SuggestedLink.status).where(SuggestedLink.id == sug_id))
        ).scalar_one()


async def _link_exists(from_id: int, to_id: int, link_type: str) -> bool:
    """Check (in a fresh session) whether an ArtifactLink for the triple exists."""
    async with AsyncSessionLocal() as s:
        row = (
            await s.execute(
                select(ArtifactLink.id).where(
                    ArtifactLink.from_artifact_id == from_id,
                    ArtifactLink.to_artifact_id == to_id,
                    ArtifactLink.link_type == link_type,
                )
            )
        ).first()
    return row is not None


async def _link_count() -> int:
    """Total ArtifactLink rows, read from a fresh session."""
    async with AsyncSessionLocal() as s:
        return (await s.execute(select(func.count()).select_from(ArtifactLink))).scalar()


async def _artifact(db, external_id: str, title: str) -> Artifact:
    art = Artifact(
        project_id=None,
        type="requirement",
        source="internal",
        external_id=external_id,
        title=title,
    )
    db.add(art)
    await db.flush()
    return art


async def _suggestion(
    db, frm: int, to: int, link_type: str = "relates_to", score: float = 0.8
) -> SuggestedLink:
    s = SuggestedLink(
        project_id=None,
        from_artifact_id=frm,
        to_artifact_id=to,
        suggested_link_type=link_type,
        similarity_score=score,
        method="tfidf",
        reason="similar text",
        status="pending",
    )
    db.add(s)
    await db.flush()
    return s


@pytest_asyncio.fixture
async def mixed_batch(db_session):
    """Seed four artifacts and the four mixed-batch suggestions.

    Returns a dict describing each case so assertions stay readable.

    Artifacts:
      a, b -> VALID pending suggestion a->b (relates_to); no pre-existing link.
      c, d -> DUPLICATE: pre-existing ArtifactLink c->d (relates_to) plus a
              pending suggestion for the same pair+type.
      e, f -> CYCLE: pre-existing DAG edge e->f (implements) plus a pending
              suggestion f->e (implements) that would close the cycle.
    """
    a = await _artifact(db_session, "REQ-A", "Login must be secure")
    b = await _artifact(db_session, "REQ-B", "Authentication security rules")
    c = await _artifact(db_session, "REQ-C", "Password rotation policy")
    d = await _artifact(db_session, "REQ-D", "Credential lifecycle policy")
    e = await _artifact(db_session, "REQ-E", "Session timeout requirement")
    f = await _artifact(db_session, "REQ-F", "Session implementation detail")

    # VALID: pending suggestion, no existing link.
    valid = await _suggestion(db_session, a.id, b.id, link_type="relates_to")

    # DUPLICATE: pre-create the ArtifactLink, then a pending suggestion for the
    # same pair + type -> should be approved without creating a 2nd link.
    db_session.add(
        ArtifactLink(
            project_id=None,
            from_artifact_id=c.id,
            to_artifact_id=d.id,
            link_type="relates_to",
        )
    )
    duplicate = await _suggestion(db_session, c.id, d.id, link_type="relates_to")

    # CYCLE: existing e->f 'implements' edge; suggestion f->e 'implements' would
    # close a cycle on a DAG-enforced type -> cycle_prevented + auto-rejected.
    db_session.add(
        ArtifactLink(
            project_id=None,
            from_artifact_id=e.id,
            to_artifact_id=f.id,
            link_type="implements",
        )
    )
    cycle = await _suggestion(db_session, f.id, e.id, link_type="implements")

    await db_session.commit()

    return {
        "valid": {"id": valid.id, "from": a.id, "to": b.id, "type": "relates_to"},
        "duplicate": {"id": duplicate.id, "from": c.id, "to": d.id, "type": "relates_to"},
        "cycle": {"id": cycle.id, "from": f.id, "to": e.id, "type": "implements"},
        "bad_id": 999999,
    }


@pytest.mark.asyncio
async def test_bulk_approve_mixed_batch_per_item_correctness(
    client, mixed_batch, auth_headers
):
    valid = mixed_batch["valid"]
    duplicate = mixed_batch["duplicate"]
    cycle = mixed_batch["cycle"]
    bad_id = mixed_batch["bad_id"]

    # Two ArtifactLinks pre-exist (duplicate's link + cycle's e->f edge).
    assert await _link_count() == 2

    resp = await client.post(
        "/api/v1/traceability/suggested-links/bulk-approve",
        json=[valid["id"], duplicate["id"], cycle["id"], bad_id],
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["success"] is True
    results = body["results"]

    # Aggregate counts: VALID + DUPLICATE both count as approved; CYCLE is
    # auto-rejected and counted under cycle_prevented; BAD ID lands in errors[].
    assert results["approved"] == 2
    assert results["cycle_prevented"] == 1
    assert results["already_processed"] == 0

    # The non-existent id surfaces in errors[] (and nothing else does).
    assert len(results["errors"]) == 1
    bad = results["errors"][0]
    assert bad["id"] == bad_id
    assert bad["error"] == "Not found"

    # --- Per-item persisted state ---

    # VALID: suggestion approved and exactly one new link created for its triple.
    assert await _suggestion_status(valid["id"]) == "approved"
    assert await _link_exists(valid["from"], valid["to"], valid["type"]) is True

    # DUPLICATE: suggestion approved but no second link for the pre-existing triple.
    assert await _suggestion_status(duplicate["id"]) == "approved"
    async with AsyncSessionLocal() as s:
        dup_links = (
            await s.execute(
                select(func.count())
                .select_from(ArtifactLink)
                .where(
                    ArtifactLink.from_artifact_id == duplicate["from"],
                    ArtifactLink.to_artifact_id == duplicate["to"],
                    ArtifactLink.link_type == duplicate["type"],
                )
            )
        ).scalar()
    assert dup_links == 1  # still just the pre-created link, no duplicate

    # CYCLE: suggestion auto-rejected; the cycle-closing edge was NOT created.
    assert await _suggestion_status(cycle["id"]) == "rejected"
    assert await _link_exists(cycle["from"], cycle["to"], cycle["type"]) is False

    # Net effect on link table: only the VALID suggestion added a link.
    # Started with 2 (duplicate + cycle edge) -> now 3.
    assert await _link_count() == 3
