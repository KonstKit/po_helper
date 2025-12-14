import asyncio
from sqlalchemy import select, func, cast, Integer
from app.core.database import AsyncSessionLocal
from app.models import Project, Task
from app.schemas.project import ProjectWithStats

async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Project).where(Project.id == 3))
        project = result.scalar_one()
        stats_result = await db.execute(
            select(
                func.count(Task.id).label('total'),
                func.sum(cast((Task.status == 'Done'), Integer)).label('completed'),
                func.sum(cast((Task.status == 'In Progress'), Integer)).label('in_progress'),
                func.sum(Task.estimate_hours).label('total_estimate'),
                func.sum(Task.spent_hours).label('total_spent'),
            ).where(Task.project_id == project.id)
        )
        stats = stats_result.first()
        total = (stats.total or 0) if stats else 0
        completed = (stats.completed or 0) if stats else 0
        in_progress = (stats.in_progress or 0) if stats else 0
        total_estimate = (stats.total_estimate or 0) if stats else 0
        total_spent = (stats.total_spent or 0) if stats else 0
        completion_percentage = (completed / total * 100) if total else 0
        project_dict = {
            **project.__dict__,
            'total_tasks': total,
            'completed_tasks': completed,
            'in_progress_tasks': in_progress,
            'total_estimate_hours': total_estimate,
            'total_spent_hours': total_spent,
            'completion_percentage': completion_percentage,
        }
        model = ProjectWithStats.model_validate(project_dict)
        print(model.meta)

asyncio.run(main())
