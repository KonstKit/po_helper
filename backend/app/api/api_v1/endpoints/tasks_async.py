"""
API endpoints for managing asynchronous tasks with progress tracking.
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from app.services.task_manager import task_manager

router = APIRouter()


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    """Get the status and progress of a background task."""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return task.to_dict()


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    """Cancel a running task."""
    success = task_manager.cancel_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="Task cannot be cancelled")

    return {"status": "cancelled", "task_id": task_id}


@router.get("/tasks")
async def list_tasks(
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    include_completed: bool = Query(False, description="Include completed tasks"),
):
    """List background tasks."""
    if user_id:
        tasks = task_manager.get_user_tasks(user_id, include_completed)
    else:
        # Return all active tasks
        tasks = []
        for task in task_manager._tasks.values():
            if include_completed or task.status.value in ("pending", "running"):
                tasks.append(task.to_dict())

    return {"total": len(tasks), "tasks": tasks}


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str):
    """Delete a completed task from memory."""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status.value in ("pending", "running"):
        raise HTTPException(status_code=400, detail="Cannot delete running task")

    if task_id in task_manager._tasks:
        del task_manager._tasks[task_id]

    return {"status": "deleted", "task_id": task_id}
