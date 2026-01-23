"""GitLab projects discovery endpoint."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_str
from app.core.database import get_db
from app.models import IntegrationSetting

logger = logging.getLogger(__name__)

router = APIRouter()

DEFAULT_GITLAB_API = "https://gitlab.com/api/v4"
REQUEST_TIMEOUT = 15
MAX_PER_PAGE = 100


def _decode_token(raw_token: Optional[str]) -> Optional[str]:
    if not raw_token:
        return None
    decrypted = decrypt_str(raw_token)
    if not decrypted:
        return None
    try:
        bundle = json.loads(decrypted)
    except (json.JSONDecodeError, TypeError):
        return decrypted
    return bundle.get("api_token") or bundle.get("token") or decrypted


async def _load_gitlab_config(db: AsyncSession) -> tuple[str, str]:
    res = await db.execute(select(IntegrationSetting).where(IntegrationSetting.kind == "gitlab"))
    row = res.scalar_one_or_none()
    if not row or not row.api_token:
        raise HTTPException(status_code=400, detail="GitLab integration is not configured")

    token = _decode_token(row.api_token)
    if not token:
        raise HTTPException(status_code=400, detail="GitLab API token is missing")

    base_url = (row.base_url or "").strip()
    if base_url:
        api_base = base_url.rstrip("/")
        if not api_base.endswith("/api/v4"):
            api_base = f"{api_base}/api/v4"
    else:
        api_base = DEFAULT_GITLAB_API

    return api_base, token


async def _request_json(
    url: str, token: str, params: Dict[str, Any]
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    def _do_request() -> requests.Response:
        headers = {"PRIVATE-TOKEN": token}
        return requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)

    resp = await asyncio.to_thread(_do_request)
    if resp.status_code >= 400:
        detail = resp.text[:200]
        raise HTTPException(status_code=resp.status_code, detail=f"GitLab request failed: {detail}")

    try:
        data = resp.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"Invalid JSON from GitLab: {exc}") from exc

    pagination = {
        "next_page": resp.headers.get("X-Next-Page"),
        "prev_page": resp.headers.get("X-Prev-Page"),
        "total_pages": resp.headers.get("X-Total-Pages"),
        "total_items": resp.headers.get("X-Total"),
    }

    return data or [], pagination


def _summarize_project(project: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": project.get("id"),
        "name": project.get("name"),
        "path": project.get("path"),
        "path_with_namespace": project.get("path_with_namespace"),
        "description": project.get("description"),
        "default_branch": project.get("default_branch"),
        "visibility": project.get("visibility"),
        "ssh_url_to_repo": project.get("ssh_url_to_repo"),
        "http_url_to_repo": project.get("http_url_to_repo"),
        "web_url": project.get("web_url"),
        "last_activity_at": project.get("last_activity_at"),
        "namespace": project.get("namespace", {}).get("full_path"),
    }


@router.get("/gitlab/projects")
async def list_gitlab_projects(
    group_id: Optional[int] = Query(None, description="Numeric GitLab group ID"),
    group_path: Optional[str] = Query(None, description="Group path, e.g. company/platform"),
    search: Optional[str] = Query(None, description="Filter projects by name"),
    include_subgroups: bool = Query(True, description="Include projects from subgroups"),
    page: Optional[int] = Query(None, ge=1),
    per_page: int = Query(50, ge=1, le=MAX_PER_PAGE),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Return projects available in GitLab (optionally restricted to a group)."""
    api_base, token = await _load_gitlab_config(db)

    if group_id is not None and group_path is not None:
        raise HTTPException(
            status_code=400, detail="Specify either group_id or group_path, not both"
        )

    params: Dict[str, Any] = {"per_page": per_page}
    if page is not None:
        params["page"] = page
    if search:
        params["search"] = search
    if include_subgroups:
        params["include_subgroups"] = True

    if group_id is not None:
        group_segment = str(group_id)
        url = f"{api_base}/groups/{group_segment}/projects"
    elif group_path:
        group_segment = quote(group_path.strip("/"), safe="")
        url = f"{api_base}/groups/{group_segment}/projects"
    else:
        url = f"{api_base}/projects"
        # Without a group filter, return only projects accessible by the token owner
        params.setdefault("membership", True)

    projects, pagination = await _request_json(url, token, params)
    summary = [_summarize_project(item) for item in projects]

    return {
        "count": len(summary),
        "projects": summary,
        "pagination": pagination,
        "source": url,
    }
