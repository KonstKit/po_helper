"""Escaped Defects CRUD endpoints."""

from .common import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    AsyncSession,
    Optional,
    List,
    select,
    get_db,
    transactional_session,
    EscapedDefect,
    EscapedDefectCreate,
    EscapedDefectUpdate,
    EscapedDefectSchema,
)
from app.core.cache_enhanced import CacheInvalidator

router = APIRouter()


@router.post("/defects", response_model=EscapedDefectSchema)
async def create_escaped_defect(
    defect: EscapedDefectCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new escaped defect record."""
    db_defect = EscapedDefect(**defect.model_dump())
    async with transactional_session(db):
        db.add(db_defect)
    await db.refresh(db_defect)
    # Invalidate quality caches affected by defect creation
    await CacheInvalidator.on_quality_data_change(db_defect.project_id)
    return db_defect


@router.get("/defects", response_model=List[EscapedDefectSchema])
async def list_escaped_defects(
    project_id: int,
    sprint_id: Optional[int] = None,
    severity: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """List escaped defects with optional filtering."""
    q = select(EscapedDefect).where(EscapedDefect.project_id == project_id)
    if sprint_id is not None:
        q = q.where(EscapedDefect.sprint_id == sprint_id)
    if severity:
        q = q.where(EscapedDefect.severity == severity)
    if status:
        q = q.where(EscapedDefect.status == status)
    q = q.order_by(EscapedDefect.detected_at.desc()).offset(offset).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/defects/{defect_id}", response_model=EscapedDefectSchema)
async def get_escaped_defect(
    defect_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific escaped defect by ID."""
    result = await db.execute(select(EscapedDefect).where(EscapedDefect.id == defect_id))
    defect = result.scalars().first()
    if not defect:
        raise HTTPException(status_code=404, detail="Defect not found")
    return defect


@router.patch("/defects/{defect_id}", response_model=EscapedDefectSchema)
async def update_escaped_defect(
    defect_id: int,
    update: EscapedDefectUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update an escaped defect."""
    result = await db.execute(select(EscapedDefect).where(EscapedDefect.id == defect_id))
    defect = result.scalars().first()
    if not defect:
        raise HTTPException(status_code=404, detail="Defect not found")

    update_data = update.model_dump(exclude_unset=True)

    # Calculate time_to_resolve if resolved_at is being set
    if "resolved_at" in update_data and update_data["resolved_at"]:
        resolved_at = update_data["resolved_at"]
        if defect.detected_at:
            delta = resolved_at - defect.detected_at
            update_data["time_to_resolve_hours"] = delta.total_seconds() / 3600

    for key, value in update_data.items():
        setattr(defect, key, value)

    async with transactional_session(db):
        db.add(defect)
    await db.refresh(defect)
    # Invalidate quality caches affected by defect update
    await CacheInvalidator.on_quality_data_change(defect.project_id)
    return defect


@router.delete("/defects/{defect_id}")
async def delete_escaped_defect(
    defect_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete an escaped defect."""
    result = await db.execute(select(EscapedDefect).where(EscapedDefect.id == defect_id))
    defect = result.scalars().first()
    if not defect:
        raise HTTPException(status_code=404, detail="Defect not found")

    # Store project_id before deletion for cache invalidation
    project_id = defect.project_id
    async with transactional_session(db):
        await db.delete(defect)
    # Invalidate quality caches affected by defect deletion
    await CacheInvalidator.on_quality_data_change(project_id)
    return {"deleted": True, "id": defect_id}
