import csv
from datetime import datetime, timezone
from io import StringIO
from typing import Any, Dict, List, Optional, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.api.deps import ensure_project_access, require_permission
from app.models import User, Permissions
from app.models.traceability import Baseline as BaselineModel
from app.models.traceability import BaselineItem as BaselineItemModel
from app.schemas.traceability import (
    Baseline,
    BaselineBase,
    BaselineCompareRequest,
    BaselineCompareResponse,
    BaselineCompareSummary,
    BaselineExportItem,
    BaselineExportResponse,
    BaselineItem,
    BaselineItemBase,
)
from app.services.audit_log import record_audit_event
from app.utils import get_by_id_or_404, transactional_session

router = APIRouter()


async def _load_baseline_items(
    db: AsyncSession, baseline_id: int
) -> List[BaselineItemModel]:
    result = await db.execute(
        select(BaselineItemModel)
        .where(BaselineItemModel.baseline_id == baseline_id)
        .order_by(BaselineItemModel.id.asc())
    )
    return list(result.scalars().all())


def _baseline_item_kind(item: BaselineItemModel) -> str:
    if item.artifact_id is not None:
        return "artifact"
    if item.link_id is not None:
        return "link"
    return "empty"


def _baseline_item_ids(items: List[BaselineItemModel]) -> Dict[str, List[int]]:
    artifact_ids = sorted({item.artifact_id for item in items if item.artifact_id is not None})
    link_ids = sorted({item.link_id for item in items if item.link_id is not None})
    return {"artifact_ids": artifact_ids, "link_ids": link_ids}


def _baseline_export_response(
    baseline: BaselineModel, items: List[BaselineItemModel]
) -> BaselineExportResponse:
    item_ids = _baseline_item_ids(items)
    return BaselineExportResponse(
        format="json",
        baseline=baseline,
        exported_at=datetime.now(timezone.utc),
        item_count=len(items),
        artifact_ids=item_ids["artifact_ids"],
        link_ids=item_ids["link_ids"],
        items=[
            BaselineExportItem(
                item_id=item.id,
                item_type=_baseline_item_kind(item),
                artifact_id=item.artifact_id,
                link_id=item.link_id,
                included_at=item.included_at,
            )
            for item in items
        ],
    )


def _render_baseline_csv(
    baseline: BaselineModel, items: List[BaselineItemModel]
) -> StringIO:
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "baseline_id",
            "baseline_name",
            "project_id",
            "item_id",
            "item_type",
            "artifact_id",
            "link_id",
            "included_at",
        ],
    )
    writer.writeheader()
    for item in items:
        writer.writerow(
            {
                "baseline_id": baseline.id,
                "baseline_name": baseline.name,
                "project_id": baseline.project_id if baseline.project_id is not None else "",
                "item_id": item.id,
                "item_type": _baseline_item_kind(item),
                "artifact_id": item.artifact_id if item.artifact_id is not None else "",
                "link_id": item.link_id if item.link_id is not None else "",
                "included_at": item.included_at.isoformat(),
            }
        )
    output.seek(0)
    return output


def _compare_baseline_items(
    baseline_items: List[BaselineItemModel], against_items: List[BaselineItemModel]
) -> tuple[Dict[str, List[int]], Dict[str, List[int]], BaselineCompareSummary]:
    baseline_refs = _baseline_item_ids(baseline_items)
    against_refs = _baseline_item_ids(against_items)

    added_artifact_ids = sorted(
        set(baseline_refs["artifact_ids"]) - set(against_refs["artifact_ids"])
    )
    removed_artifact_ids = sorted(
        set(against_refs["artifact_ids"]) - set(baseline_refs["artifact_ids"])
    )
    added_link_ids = sorted(set(baseline_refs["link_ids"]) - set(against_refs["link_ids"]))
    removed_link_ids = sorted(set(against_refs["link_ids"]) - set(baseline_refs["link_ids"]))

    summary = BaselineCompareSummary(
        added_artifacts=len(added_artifact_ids),
        removed_artifacts=len(removed_artifact_ids),
        added_links=len(added_link_ids),
        removed_links=len(removed_link_ids),
        total_added=len(added_artifact_ids) + len(added_link_ids),
        total_removed=len(removed_artifact_ids) + len(removed_link_ids),
    )
    return (
        {"artifact_ids": added_artifact_ids, "link_ids": added_link_ids},
        {"artifact_ids": removed_artifact_ids, "link_ids": removed_link_ids},
        summary,
    )


@router.get("/baselines", response_model=List[Baseline])
async def list_baselines(
    project_id: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    stmt = select(BaselineModel).order_by(BaselineModel.created_at.desc())
    if project_id is not None:
        await ensure_project_access(project_id, db, current_user)
        stmt = stmt.where(BaselineModel.project_id == project_id)
    elif not current_user.has_permission(Permissions.ADMIN):
        raise HTTPException(status_code=403, detail="project_id is required")
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("/baselines", response_model=Baseline)
async def create_baseline(
    payload: BaselineBase,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_MANAGE)),
):
    if payload.project_id is None:
        raise HTTPException(status_code=400, detail="project_id is required")
    await ensure_project_access(payload.project_id, db, current_user)
    baseline = BaselineModel(**payload.model_dump())
    async with transactional_session(db):
        db.add(baseline)
        await db.flush()
        await record_audit_event(
            db,
            action="create",
            entity_type="baseline",
            entity_id=baseline.id,
            actor_id=current_user.id,
            project_id=baseline.project_id,
            payload={"name": baseline.name},
        )
    await db.refresh(baseline)
    return baseline


@router.post("/baselines/compare", response_model=BaselineCompareResponse)
async def compare_baselines(
    payload: BaselineCompareRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    baseline = await get_by_id_or_404(db, BaselineModel, payload.baseline_id)
    against_baseline = await get_by_id_or_404(db, BaselineModel, payload.against_baseline_id)

    if baseline.project_id is not None:
        await ensure_project_access(baseline.project_id, db, current_user)
    if against_baseline.project_id is not None:
        await ensure_project_access(against_baseline.project_id, db, current_user)

    baseline_items = await _load_baseline_items(db, baseline.id)
    against_items = await _load_baseline_items(db, against_baseline.id)
    added, removed, summary = _compare_baseline_items(baseline_items, against_items)

    async with transactional_session(db):
        await record_audit_event(
            db,
            action="compare",
            entity_type="baseline",
            entity_id=baseline.id,
            actor_id=current_user.id,
            project_id=baseline.project_id,
            payload={
                "against_baseline_id": against_baseline.id,
                "baseline_item_count": len(baseline_items),
                "against_item_count": len(against_items),
                "summary": summary.model_dump(),
            },
        )

    return BaselineCompareResponse(
        baseline_id=baseline.id,
        against_baseline_id=against_baseline.id,
        baseline_name=baseline.name,
        against_baseline_name=against_baseline.name,
        project_id=baseline.project_id,
        against_project_id=against_baseline.project_id,
        summary=summary,
        added_artifact_ids=added["artifact_ids"],
        removed_artifact_ids=removed["artifact_ids"],
        added_link_ids=added["link_ids"],
        removed_link_ids=removed["link_ids"],
    )


@router.get("/baselines/{baseline_id}", response_model=Baseline)
async def get_baseline(
    baseline_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    baseline = await get_by_id_or_404(db, BaselineModel, baseline_id)
    if baseline.project_id is not None:
        await ensure_project_access(baseline.project_id, db, current_user)
    return baseline


@router.get("/baselines/{baseline_id}/export", response_model=BaselineExportResponse)
async def export_baseline(
    baseline_id: int,
    format: Literal["json", "csv"] = Query(default="json"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    baseline = await get_by_id_or_404(db, BaselineModel, baseline_id)
    if baseline.project_id is not None:
        await ensure_project_access(baseline.project_id, db, current_user)

    items = await _load_baseline_items(db, baseline.id)
    export_payload = _baseline_export_response(baseline, items)

    async with transactional_session(db):
        await record_audit_event(
            db,
            action="export",
            entity_type="baseline",
            entity_id=baseline.id,
            actor_id=current_user.id,
            project_id=baseline.project_id,
            payload={
                "format": format,
                "item_count": len(items),
                "artifact_count": len(export_payload.artifact_ids),
                "link_count": len(export_payload.link_ids),
            },
        )

    if format == "json":
        return export_payload

    csv_output = _render_baseline_csv(baseline, items)
    return StreamingResponse(
        iter([csv_output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="baseline_{baseline.id}_export.csv"'
        },
    )


@router.delete("/baselines/{baseline_id}")
async def delete_baseline(
    baseline_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_MANAGE)),
):
    baseline = await get_by_id_or_404(db, BaselineModel, baseline_id)
    if baseline.project_id is not None:
        await ensure_project_access(baseline.project_id, db, current_user)
    async with transactional_session(db):
        await record_audit_event(
            db,
            action="delete",
            entity_type="baseline",
            entity_id=baseline.id,
            actor_id=current_user.id,
            project_id=baseline.project_id,
            payload={"name": baseline.name},
        )
        await db.delete(baseline)
    return {"status": "deleted", "id": baseline_id}


@router.get("/baselines/{baseline_id}/items", response_model=List[BaselineItem])
async def list_baseline_items(
    baseline_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    baseline = await get_by_id_or_404(db, BaselineModel, baseline_id)
    if baseline.project_id is not None:
        await ensure_project_access(baseline.project_id, db, current_user)
    result = await db.execute(
        select(BaselineItemModel).where(BaselineItemModel.baseline_id == baseline_id)
    )
    return list(result.scalars().all())


@router.post("/baselines/{baseline_id}/items", response_model=BaselineItem)
async def add_baseline_item(
    baseline_id: int,
    payload: BaselineItemBase,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_MANAGE)),
):
    baseline = await get_by_id_or_404(db, BaselineModel, baseline_id)
    if baseline.project_id is not None:
        await ensure_project_access(baseline.project_id, db, current_user)
    if payload.baseline_id != baseline_id:
        raise HTTPException(status_code=400, detail="baseline_id mismatch")
    if payload.artifact_id is None and payload.link_id is None:
        raise HTTPException(status_code=400, detail="artifact_id or link_id is required")
    item = BaselineItemModel(**payload.model_dump())
    async with transactional_session(db):
        db.add(item)
        await db.flush()
        await record_audit_event(
            db,
            action="add_item",
            entity_type="baseline",
            entity_id=baseline_id,
            actor_id=current_user.id,
            project_id=baseline.project_id,
            payload={
                "item_id": item.id,
                "artifact_id": item.artifact_id,
                "link_id": item.link_id,
            },
        )
    await db.refresh(item)
    return item


@router.delete("/baselines/{baseline_id}/items/{item_id}")
async def delete_baseline_item(
    baseline_id: int,
    item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_MANAGE)),
):
    baseline = await get_by_id_or_404(db, BaselineModel, baseline_id)
    if baseline.project_id is not None:
        await ensure_project_access(baseline.project_id, db, current_user)
    item = await get_by_id_or_404(db, BaselineItemModel, item_id)
    if item.baseline_id != baseline_id:
        raise HTTPException(status_code=400, detail="baseline_id mismatch")
    async with transactional_session(db):
        await record_audit_event(
            db,
            action="delete_item",
            entity_type="baseline",
            entity_id=baseline_id,
            actor_id=current_user.id,
            project_id=baseline.project_id,
            payload={
                "item_id": item.id,
                "artifact_id": item.artifact_id,
                "link_id": item.link_id,
            },
        )
        await db.delete(item)
    return {"status": "deleted", "id": item_id}
