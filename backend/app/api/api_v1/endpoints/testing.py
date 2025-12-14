from __future__ import annotations

from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.models import TestResult, CoverageReport, Artifact, ArtifactLink
from app.models.testing import FileCoverage

router = APIRouter()


async def _filter_commits_by_project(
    items: List[Any],
    project_id: Optional[int],
    db: AsyncSession,
) -> Optional[set[str]]:
    """
    Filter commit SHAs by project through commit->issue artifact links.

    This utility eliminates the repetitive 15-line pattern of:
    - Extracting commit SHAs from items
    - Querying Artifact table for commits
    - Querying ArtifactLink for commit->issue links
    - Querying Artifact table for issues in the project
    - Building set of allowed commit SHAs

    Usage:
        items = [list of TestResult/CoverageReport objects]
        allowed_shas = await _filter_commits_by_project(items, project_id, db)
        if allowed_shas is not None:
            items = [i for i in items if i.commit_sha in allowed_shas]

    Args:
        items: List of objects with commit_sha attribute (TestResult, CoverageReport, etc.)
        project_id: Project ID to filter by, or None to skip filtering
        db: Database session

    Returns:
        Set of allowed commit SHAs if project_id is provided, None otherwise
    """
    if project_id is None:
        return None

    shas = sorted({i.commit_sha for i in items if i.commit_sha})
    if not shas:
        return set()

    # Get commit artifacts
    res_commit = await db.execute(
        select(Artifact).where(Artifact.type == 'commit', Artifact.external_id.in_(shas))
    )
    commits = {a.id: a.external_id for a in res_commit.scalars().all()}

    # Get links from commits to issues
    res_links = await db.execute(
        select(ArtifactLink).where(ArtifactLink.from_artifact_id.in_(list(commits.keys())))
    )
    links = res_links.scalars().all()
    to_ids = [l.to_artifact_id for l in links]

    if not to_ids:
        return set()

    # Get issues for this project
    res_issues = await db.execute(
        select(Artifact).where(
            Artifact.id.in_(to_ids),
            Artifact.type == 'jira_issue',
            Artifact.project_id == project_id
        )
    )
    issues = res_issues.scalars().all()
    ok_issue_ids = {i.id for i in issues}
    ok_commit_ids = {l.from_artifact_id for l in links if l.to_artifact_id in ok_issue_ids}
    allowed_shas = {commits[cid] for cid in ok_commit_ids if cid in commits}

    return allowed_shas


@router.get("/runs")
async def list_test_runs(
    project_id: Optional[int] = None,
    provider: Optional[str] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    # naive grouping by (provider, commit_sha, pr_number)
    res = await db.execute(select(TestResult))
    items = res.scalars().all()
    # Filter by project via commit -> issue link if requested
    allowed_shas = await _filter_commits_by_project(items, project_id, db)
    runs: Dict[tuple, Dict[str, Any]] = {}
    for it in items:
        if provider and it.provider and it.provider.lower() != provider.lower():
            continue
        if allowed_shas is not None and it.commit_sha not in allowed_shas:
            continue
        key = (it.provider or 'generic', it.commit_sha or '', it.pr_number or 0)
        rec = runs.setdefault(key, {
            'provider': it.provider,
            'commit_sha': it.commit_sha,
            'pr_number': it.pr_number,
            'created_at': it.created_at,
            'total': 0,
            'failed': 0,
            'error': 0,
            'skipped': 0,
        })
        rec['created_at'] = max(rec['created_at'], it.created_at) if rec['created_at'] and it.created_at else (rec['created_at'] or it.created_at)
        rec['total'] += 1
        st = (it.status or '').lower()
        if st == 'failed':
            rec['failed'] += 1
        elif st == 'error':
            rec['error'] += 1
        elif st == 'skipped':
            rec['skipped'] += 1
    # sort desc by created_at
    out = sorted(runs.values(), key=lambda r: r.get('created_at') or 0, reverse=True)[: min(max(1, limit), 200)]
    return { 'total': len(out), 'runs': out }


@router.get("/results")
async def list_test_results(
    project_id: Optional[int] = None,
    commit_sha: Optional[str] = None,
    status: Optional[str] = None,
    since_days: Optional[int] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    q = select(TestResult)
    if commit_sha:
        q = q.where(TestResult.commit_sha == commit_sha)
    res = await db.execute(q)
    items = res.scalars().all()
    if since_days is not None and since_days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        items = [it for it in items if getattr(it, 'created_at', None) and it.created_at >= cutoff]
    allowed_shas = await _filter_commits_by_project(items, project_id, db)
    out = []
    for it in items:
        if allowed_shas is not None and it.commit_sha not in allowed_shas:
            continue
        if status and (it.status or '').lower() != status.lower():
            continue
        out.append({
            'id': it.id,
            'provider': it.provider,
            'commit_sha': it.commit_sha,
            'pr_number': it.pr_number,
            'suite': it.suite,
            'classname': it.classname,
            'name': it.name,
            'status': it.status,
            'duration': it.duration,
            'message': it.message,
            'created_at': it.created_at,
            'raw': it.raw,
        })
    out = sorted(out, key=lambda r: r.get('created_at') or 0, reverse=True)[: min(max(limit, 1), 500)]
    return { 'total': len(out), 'results': out }


@router.get("/coverage/list")
async def list_coverage(
    project_id: Optional[int] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(select(CoverageReport))
    items = res.scalars().all()
    allowed_shas = await _filter_commits_by_project(items, project_id, db)
    out = []
    for it in items:
        if allowed_shas is not None and it.commit_sha not in allowed_shas:
            continue
        out.append({
            'id': it.id,
            'provider': it.provider,
            'commit_sha': it.commit_sha,
            'pr_number': it.pr_number,
            'line_coverage': it.line_coverage,
            'branch_coverage': it.branch_coverage,
            'report_url': it.report_url,
            'created_at': it.created_at,
        })
    out = sorted(out, key=lambda r: r.get('created_at') or 0, reverse=True)[: min(max(limit, 1), 200)]
    return { 'total': len(out), 'coverage': out }


@router.get("/coverage/{commit_sha}/files")
async def list_coverage_files(
    commit_sha: str,
    limit: int = 1000,
    db: AsyncSession = Depends(get_db),
):
    # Get latest coverage report for this commit
    res = await db.execute(select(CoverageReport).where(CoverageReport.commit_sha == commit_sha).order_by(CoverageReport.created_at.desc()))
    cov = res.scalars().first()
    if not cov:
        return { 'total': 0, 'files': [] }
    resf = await db.execute(select(FileCoverage).where(FileCoverage.coverage_report_id == cov.id).limit(min(max(limit,1),5000)))
    rows = resf.scalars().all()
    out = []
    for r in rows:
        out.append({
            'file_path': r.file_path,
            'line_coverage': r.line_coverage,
            'branch_coverage': r.branch_coverage,
            'lines_covered': r.lines_covered,
            'lines_total': r.lines_total,
        })
    return { 'total': len(out), 'files': out }
