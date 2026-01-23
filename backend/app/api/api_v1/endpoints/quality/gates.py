"""Quality Gate endpoints for PR coverage checks and GitHub status updates."""

from .common import (
    APIRouter,
    Depends,
    HTTPException,
    AsyncSession,
    Optional,
    Dict,
    Any,
    select,
    get_db,
    settings,
    requests,
    CoverageReport,
    PullRequest,
    Repository,
    QualityGateHistory,
    check_gate_thresholds,
    persist_quality_history,
)

router = APIRouter()


@router.get("/gates/{pr_number}")
async def quality_gate_pr(
    pr_number: int,
    min_line: float = 0.8,
    min_branch: Optional[float] = None,
    project_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    """Check quality gate for a PR based on coverage thresholds."""
    # If project_id provided, attempt to read thresholds from Project
    if project_id is not None:
        from app.models import Project as ProjectModel

        r = await db.execute(select(ProjectModel).where(ProjectModel.id == project_id))
        proj = r.scalars().first()
        if proj and getattr(proj, "quality_thresholds", None):
            q = proj.quality_thresholds or {}
            min_line = float(q.get("min_line", min_line))
            min_branch_val = q.get("min_branch")
            if min_branch_val is not None:
                min_branch = float(min_branch_val)

    res = await db.execute(
        select(CoverageReport)
        .where(CoverageReport.pr_number == pr_number)
        .order_by(CoverageReport.created_at.desc())
    )
    cov = res.scalars().first()
    if not cov:
        return {
            "pr_number": pr_number,
            "pass": False,
            "reasons": ["no_coverage_found"],
            "line_coverage": None,
            "branch_coverage": None,
        }
    out = check_gate_thresholds(cov.line_coverage, cov.branch_coverage, min_line, min_branch)
    return {
        "pr_number": pr_number,
        **out,
        "line_coverage": cov.line_coverage,
        "branch_coverage": cov.branch_coverage,
    }


@router.post("/gates/assess")
async def quality_gate_assess(
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
):
    """Assess quality gate based on PR number or commit SHA."""
    pr_number = payload.get("pr_number")
    commit_sha = payload.get("commit_sha")
    min_line = float(payload.get("min_line", 0.8))
    min_branch = payload.get("min_branch")
    min_branch = float(min_branch) if min_branch is not None else None
    project_id = payload.get("project_id")

    # project thresholds override defaults when present
    if project_id is not None:
        from app.models import Project as ProjectModel

        r = await db.execute(select(ProjectModel).where(ProjectModel.id == int(project_id)))
        proj = r.scalars().first()
        if proj and getattr(proj, "quality_thresholds", None):
            q = proj.quality_thresholds or {}
            min_line = float(q.get("min_line", min_line))
            min_branch_val = q.get("min_branch")
            if min_branch_val is not None:
                min_branch = float(min_branch_val)

    cov = None
    if pr_number is not None:
        res = await db.execute(
            select(CoverageReport)
            .where(CoverageReport.pr_number == pr_number)
            .order_by(CoverageReport.created_at.desc())
        )
        cov = res.scalars().first()
    elif commit_sha is not None:
        res = await db.execute(
            select(CoverageReport)
            .where(CoverageReport.commit_sha == commit_sha)
            .order_by(CoverageReport.created_at.desc())
        )
        cov = res.scalars().first()
    else:
        raise HTTPException(status_code=400, detail="Provide pr_number or commit_sha")

    if not cov:
        return {
            "pass": False,
            "reasons": ["no_coverage_found"],
            "line_coverage": None,
            "branch_coverage": None,
        }
    out = check_gate_thresholds(cov.line_coverage, cov.branch_coverage, min_line, min_branch)
    return {**out, "line_coverage": cov.line_coverage, "branch_coverage": cov.branch_coverage}


async def update_github_status(
    pr_number: int,
    gate_result: Dict[str, Any],
    db: AsyncSession,
) -> Dict[str, Any]:
    """Update GitHub commit status for the PR's head SHA based on gate_result.
    Requires GITHUB_API_TOKEN and repository info.
    """
    if not settings.GITHUB_API_TOKEN:
        return {"updated": False, "reason": "no_token"}
    res = await db.execute(select(PullRequest).where(PullRequest.number == pr_number))
    pr = res.scalars().first()
    if not pr:
        return {"updated": False, "reason": "pr_not_found"}
    if not pr.head_sha:
        return {"updated": False, "reason": "no_head_sha"}
    repo = None
    if pr.repository_id:
        r = await db.execute(select(Repository).where(Repository.id == pr.repository_id))
        repo = r.scalars().first()
    if not repo:
        return {"updated": False, "reason": "repo_not_found"}

    slug = repo.repo_slug
    sha = pr.head_sha
    state = "success" if gate_result.get("pass") else "failure"
    line = gate_result.get("line_coverage")
    branch = gate_result.get("branch_coverage")
    desc = ""
    try:
        if line is not None:
            desc = f"Line {float(line) * 100:.1f}%"
        if branch is not None:
            desc = (desc + " ").strip() + f" Branch {float(branch) * 100:.1f}%"
    except Exception:
        desc = "Quality gate assessed"
    status = {
        "state": state,
        "context": "po-helper/quality-gate",
        "description": desc or ("Passed" if state == "success" else "Failed"),
    }
    url = f"https://api.github.com/repos/{slug}/statuses/{sha}"
    try:
        resp = requests.post(
            url,
            json=status,
            headers={
                "Authorization": f"Bearer {settings.GITHUB_API_TOKEN}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "po-helper",
            },
            timeout=15,
        )
        ok = 200 <= resp.status_code < 300
        return {
            "updated": ok,
            "status_code": resp.status_code,
            "response": resp.json()
            if resp.headers.get("content-type", "").startswith("application/json")
            else None,
        }
    except Exception as e:
        return {"updated": False, "reason": str(e)}


@router.post("/gates/assess-and-update")
async def quality_gate_assess_and_update(
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
):
    """Assess quality gate and update GitHub commit status."""
    result = await quality_gate_assess(payload, db)
    pr_number = payload.get("pr_number")
    provider = (payload.get("provider") or "").lower()
    if provider == "github" and pr_number is not None:
        upd = await update_github_status(int(pr_number), result, db)
        result["github_status"] = upd
    await persist_quality_history(payload, result, db)
    return result


async def update_github_check_run(
    pr_number: int,
    gate_result: Dict[str, Any],
    db: AsyncSession,
) -> Dict[str, Any]:
    """Create a GitHub Check Run for the PR's head SHA."""
    if not settings.GITHUB_API_TOKEN:
        return {"updated": False, "reason": "no_token"}
    res = await db.execute(select(PullRequest).where(PullRequest.number == pr_number))
    pr = res.scalars().first()
    if not pr or not pr.head_sha:
        return {"updated": False, "reason": "no_pr_or_sha"}
    # Find repository slug
    repo = None
    if pr.repository_id:
        r = await db.execute(select(Repository).where(Repository.id == pr.repository_id))
        repo = r.scalars().first()
    if not repo:
        return {"updated": False, "reason": "repo_not_found"}
    slug = repo.repo_slug
    sha = pr.head_sha
    conclusion = "success" if gate_result.get("pass") else "failure"
    line = gate_result.get("line_coverage")
    branch = gate_result.get("branch_coverage")
    title = "Coverage Report"
    parts = []
    if line is not None:
        try:
            parts.append(f"Line: {float(line) * 100:.1f}%")
        except Exception:
            pass
    if branch is not None:
        try:
            parts.append(f"Branch: {float(branch) * 100:.1f}%")
        except Exception:
            pass
    summary = ", ".join(parts) if parts else ("Passed" if conclusion == "success" else "Failed")
    check_payload = {
        "name": "PO Helper Quality Gate",
        "head_sha": sha,
        "status": "completed",
        "conclusion": conclusion,
        "output": {
            "title": title,
            "summary": summary,
        },
    }
    url = f"https://api.github.com/repos/{slug}/check-runs"
    try:
        resp = requests.post(
            url,
            json=check_payload,
            headers={
                "Authorization": f"Bearer {settings.GITHUB_API_TOKEN}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "po-helper",
            },
            timeout=15,
        )
        ok = 200 <= resp.status_code < 300
        data = None
        try:
            data = resp.json()
        except Exception:
            pass
        return {"updated": ok, "status_code": resp.status_code, "response": data}
    except Exception as e:
        return {"updated": False, "reason": str(e)}


@router.post("/gates/assess-and-check")
async def quality_gate_assess_and_check(
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
):
    """Assess quality gate and create GitHub Check Run."""
    result = await quality_gate_assess(payload, db)
    pr_number = payload.get("pr_number")
    provider = (payload.get("provider") or "").lower()
    if provider == "github" and pr_number is not None:
        upd = await update_github_check_run(int(pr_number), result, db)
        result["github_check"] = upd
    await persist_quality_history(payload, result, db)
    return result


@router.get("/history")
async def quality_history(
    project_id: Optional[int] = None,
    pr_number: Optional[int] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """Get quality gate history with optional filtering."""
    q = select(QualityGateHistory)
    if project_id is not None:
        q = q.where(QualityGateHistory.project_id == project_id)
    if pr_number is not None:
        q = q.where(QualityGateHistory.pr_number == pr_number)
    q = q.order_by(QualityGateHistory.created_at.desc())
    res = await db.execute(q.limit(min(max(limit, 1), 200)))
    rows = res.scalars().all()
    out = []
    for r in rows:
        out.append(
            {
                "id": r.id,
                "project_id": r.project_id,
                "provider": r.provider,
                "pr_number": r.pr_number,
                "commit_sha": r.commit_sha,
                "passed": r.passed,
                "line_coverage": r.line_coverage,
                "branch_coverage": r.branch_coverage,
                "reasons": r.reasons,
                "result_payload": r.result_payload,
                "created_at": r.created_at,
            }
        )
    return {"total": len(out), "history": out}
