from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.models import Task

router = APIRouter()


@router.get("/projects/{project_id}/budget-hours-simple")
async def simple_budget_hours(project_id: int, db: AsyncSession = Depends(get_db)):
    """Simple working version of budget-hours endpoint."""
    try:
        # Simple query without any complications
        stmt = select(
            func.coalesce(func.sum(Task.estimate_hours), 0).label("estimate"),
            func.coalesce(func.sum(Task.spent_hours), 0).label("spent"),
        ).where(Task.project_id == project_id)

        result = await db.execute(stmt)
        row = result.first()

        total_estimate = float(row.estimate) if row else 0.0
        total_spent = float(row.spent) if row else 0.0

        return {
            "total_estimate_hours": round(total_estimate, 2),
            "total_spent_hours": round(total_spent, 2),
            "remaining_hours": round(max(0, total_estimate - total_spent), 2),
            "overrun": total_spent > total_estimate,
            "overrun_hours": round(max(0, total_spent - total_estimate), 2),
            "top_overruns": [],
        }
    except Exception as e:
        return {
            "total_estimate_hours": 0.0,
            "total_spent_hours": 0.0,
            "remaining_hours": 0.0,
            "overrun": False,
            "overrun_hours": 0.0,
            "top_overruns": [],
            "error": str(e),
        }
