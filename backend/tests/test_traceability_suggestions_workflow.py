"""End-to-end suggestion review workflow tests (plan_72).

Covers approve (link creation), duplicate handling, cycle prevention, reject,
bulk approve with item-level partial results, already-processed handling,
stats, and audit records.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.traceability import Artifact, ArtifactLink, AuditLog, SuggestedLink


async def _suggestion_status(sug_id: int) -> str:
    """Read suggestion status from a fresh session (avoids WAL snapshot staleness)."""
    async with AsyncSessionLocal() as s:
        return (
            await s.execute(select(SuggestedLink.status).where(SuggestedLink.id == sug_id))
        ).scalar_one()


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
async def two_artifacts(db_session):
    a = await _artifact(db_session, "REQ-A", "Login must be secure")
    b = await _artifact(db_session, "REQ-B", "Authentication security rules")
    await db_session.commit()
    return a.id, b.id


@pytest.mark.asyncio
async def test_approve_creates_link_and_audit(client, db_session, two_artifacts, auth_headers):
    a_id, b_id = two_artifacts
    sug = await _suggestion(db_session, a_id, b_id)
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/traceability/suggested-links/{sug.id}/approve",
        json=None,
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["link_id"] is not None

    # Link persisted
    links = (await db_session.execute(select(ArtifactLink))).scalars().all()
    assert len(links) == 1
    assert links[0].from_artifact_id == a_id and links[0].to_artifact_id == b_id

    # Suggestion marked approved
    assert await _suggestion_status(sug.id) == "approved"

    # Audit recorded
    audits = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "suggestion_approve")
        )
    ).scalars().all()
    assert len(audits) == 1


@pytest.mark.asyncio
async def test_double_approve_returns_400(client, db_session, two_artifacts, auth_headers):
    a_id, b_id = two_artifacts
    sug = await _suggestion(db_session, a_id, b_id)
    await db_session.commit()

    first = await client.post(
        f"/api/v1/traceability/suggested-links/{sug.id}/approve", headers=auth_headers
    )
    assert first.status_code == 200
    second = await client.post(
        f"/api/v1/traceability/suggested-links/{sug.id}/approve", headers=auth_headers
    )
    assert second.status_code == 400


@pytest.mark.asyncio
async def test_approve_duplicate_does_not_create_second_link(
    client, db_session, two_artifacts, auth_headers
):
    a_id, b_id = two_artifacts
    # Pre-existing identical link
    db_session.add(
        ArtifactLink(
            project_id=None,
            from_artifact_id=a_id,
            to_artifact_id=b_id,
            link_type="relates_to",
        )
    )
    sug = await _suggestion(db_session, a_id, b_id, link_type="relates_to")
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/traceability/suggested-links/{sug.id}/approve", headers=auth_headers
    )
    assert resp.status_code == 200
    assert "already exist" in resp.json()["message"].lower()

    count = (
        await db_session.execute(select(func.count()).select_from(ArtifactLink))
    ).scalar()
    assert count == 1  # no duplicate created


@pytest.mark.asyncio
async def test_approve_cycle_is_prevented(client, db_session, two_artifacts, auth_headers):
    a_id, b_id = two_artifacts
    # Existing DAG edge A -> B (implements is a DAG-enforced type)
    db_session.add(
        ArtifactLink(
            project_id=None,
            from_artifact_id=a_id,
            to_artifact_id=b_id,
            link_type="implements",
        )
    )
    # Suggestion B -> A (implements) would close a cycle
    sug = await _suggestion(db_session, b_id, a_id, link_type="implements")
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/traceability/suggested-links/{sug.id}/approve", headers=auth_headers
    )
    assert resp.status_code == 409

    assert await _suggestion_status(sug.id) == "rejected"
    # No B->A link created
    count = (
        await db_session.execute(select(func.count()).select_from(ArtifactLink))
    ).scalar()
    assert count == 1


@pytest.mark.asyncio
async def test_reject_marks_rejected(client, db_session, two_artifacts, auth_headers):
    a_id, b_id = two_artifacts
    sug = await _suggestion(db_session, a_id, b_id)
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/traceability/suggested-links/{sug.id}/reject",
        params={"note": "not useful"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert await _suggestion_status(sug.id) == "rejected"


@pytest.mark.asyncio
async def test_bulk_approve_reports_item_level_results(
    client, db_session, two_artifacts, auth_headers
):
    a_id, b_id = two_artifacts
    c = await _artifact(db_session, "REQ-C", "third artifact")
    valid = await _suggestion(db_session, a_id, b_id)
    # already-processed suggestion
    processed = await _suggestion(db_session, a_id, c.id)
    processed.status = "approved"
    await db_session.commit()

    resp = await client.post(
        "/api/v1/traceability/suggested-links/bulk-approve",
        json=[valid.id, processed.id, 999999],
        headers=auth_headers,
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert results["approved"] == 1
    assert results["already_processed"] == 1
    assert any(e["id"] == 999999 for e in results["errors"])


@pytest.mark.asyncio
async def test_bulk_approve_rejects_empty_and_oversize(client, auth_headers):
    empty = await client.post(
        "/api/v1/traceability/suggested-links/bulk-approve", json=[], headers=auth_headers
    )
    assert empty.status_code == 400
    oversize = await client.post(
        "/api/v1/traceability/suggested-links/bulk-approve",
        json=list(range(1, 200)),
        headers=auth_headers,
    )
    assert oversize.status_code == 400


@pytest.mark.asyncio
async def test_stats_reflect_status_counts(client, db_session, two_artifacts, auth_headers):
    a_id, b_id = two_artifacts
    s1 = await _suggestion(db_session, a_id, b_id)
    s1.status = "approved"
    c = await _artifact(db_session, "REQ-D", "fourth")
    await _suggestion(db_session, a_id, c.id)  # pending
    await db_session.commit()

    resp = await client.get(
        "/api/v1/traceability/suggested-links/stats", headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert body["by_status"].get("approved") == 1
    assert body["by_status"].get("pending") == 1
