"""
Task manager for handling long-running operations with progress tracking.
Supports background task execution, progress reporting, and cancellation.
"""
import uuid
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Callable, Awaitable
from enum import Enum
from app.core.config import settings
import json

logger = logging.getLogger(__name__)

class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class TaskInfo:
    def __init__(self, task_id: str, name: str, user_id: Optional[str] = None):
        self.id = task_id
        self.name = name
        self.user_id = user_id
        self.status = TaskStatus.PENDING
        self.progress = 0.0
        self.message = ""
        self.result = None
        self.error = None
        self.created_at = datetime.utcnow()
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.cancellation_token = asyncio.Event()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "user_id": self.user_id,
            "status": self.status.value,
            "progress": self.progress,
            "message": self.message,
            "result": self.result,
            "error": str(self.error) if self.error else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": (
                (self.completed_at - self.started_at).total_seconds()
                if self.started_at and self.completed_at else None
            ),
        }

class TaskManager:
    def __init__(self):
        self._tasks: Dict[str, TaskInfo] = {}
        self._cleanup_interval = 3600  # Clean up completed tasks after 1 hour
        self._max_tasks = 1000  # Maximum number of tasks to keep in memory
        self._redis_client = None
        self._init_redis()

    def _init_redis(self):
        """Initialize Redis for distributed task tracking."""
        try:
            if settings.REDIS_URL:
                import redis
                self._redis_client = redis.from_url(
                    settings.REDIS_URL,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2
                )
                self._redis_client.ping()
                logger.info("Task manager Redis initialized")
        except Exception as e:
            logger.warning(f"Task manager Redis init failed: {e}")
            self._redis_client = None

    def create_task(self, name: str, user_id: Optional[str] = None) -> str:
        """Create a new task and return its ID."""
        task_id = str(uuid.uuid4())
        task = TaskInfo(task_id, name, user_id)
        self._tasks[task_id] = task

        # Store in Redis if available
        if self._redis_client:
            try:
                key = f"task:{task_id}"
                self._redis_client.setex(
                    key,
                    86400,  # 24 hours TTL
                    json.dumps(task.to_dict())
                )
            except Exception as e:
                logger.debug(f"Failed to store task in Redis: {e}")

        # Clean up old tasks if needed
        self._cleanup_old_tasks()

        return task_id

    def get_task(self, task_id: str) -> Optional[TaskInfo]:
        """Get task by ID."""
        # Try memory first
        if task_id in self._tasks:
            return self._tasks[task_id]

        # Try Redis
        if self._redis_client:
            try:
                key = f"task:{task_id}"
                data = self._redis_client.get(key)
                if data:
                    task_dict = json.loads(data)
                    task = TaskInfo(task_id, task_dict["name"], task_dict.get("user_id"))
                    task.status = TaskStatus(task_dict["status"])
                    task.progress = task_dict.get("progress", 0)
                    task.message = task_dict.get("message", "")
                    task.result = task_dict.get("result")
                    task.error = task_dict.get("error")
                    return task
            except Exception as e:
                logger.debug(f"Failed to get task from Redis: {e}")

        return None

    def update_task(self, task_id: str, **kwargs):
        """Update task properties."""
        task = self.get_task(task_id)
        if not task:
            return

        # Update properties
        for key, value in kwargs.items():
            if hasattr(task, key):
                setattr(task, key, value)

        # Store in memory
        self._tasks[task_id] = task

        # Update Redis
        if self._redis_client:
            try:
                key = f"task:{task_id}"
                self._redis_client.setex(
                    key,
                    86400,  # 24 hours TTL
                    json.dumps(task.to_dict())
                )
            except Exception as e:
                logger.debug(f"Failed to update task in Redis: {e}")

        # Send progress notification if available
        self._send_progress_notification(task)

    def update_progress(self, task_id: str, progress: float, message: str = ""):
        """Update task progress."""
        self.update_task(task_id, progress=progress, message=message)

    def complete_task(self, task_id: str, result: Any = None):
        """Mark task as completed."""
        self.update_task(
            task_id,
            status=TaskStatus.COMPLETED,
            progress=100.0,
            result=result,
            completed_at=datetime.utcnow()
        )

    def fail_task(self, task_id: str, error: Any):
        """Mark task as failed."""
        self.update_task(
            task_id,
            status=TaskStatus.FAILED,
            error=error,
            completed_at=datetime.utcnow()
        )

    def cancel_task(self, task_id: str) -> bool:
        """Request task cancellation."""
        task = self.get_task(task_id)
        if not task:
            return False

        if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            return False

        task.cancellation_token.set()
        self.update_task(task_id, status=TaskStatus.CANCELLED, completed_at=datetime.utcnow())
        return True

    def is_cancelled(self, task_id: str) -> bool:
        """Check if task is cancelled."""
        task = self.get_task(task_id)
        return task.cancellation_token.is_set() if task else False

    async def run_async(
        self,
        task_id: str,
        func: Callable[..., Awaitable[Any]],
        *args,
        **kwargs
    ) -> Any:
        """Run an async function with progress tracking."""
        task = self.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        try:
            # Mark as running
            self.update_task(
                task_id,
                status=TaskStatus.RUNNING,
                started_at=datetime.utcnow()
            )

            # Inject task_id into kwargs for progress updates
            kwargs["task_id"] = task_id
            kwargs["task_manager"] = self

            # Run the function with timeout
            timeout = kwargs.pop("timeout", 300)  # Default 5 minutes
            result = await asyncio.wait_for(
                func(*args, **kwargs),
                timeout=timeout
            )

            # Mark as completed
            self.complete_task(task_id, result)
            return result

        except asyncio.TimeoutError:
            error = "Task exceeded timeout"
            self.fail_task(task_id, error)
            raise

        except asyncio.CancelledError:
            self.update_task(task_id, status=TaskStatus.CANCELLED)
            raise

        except Exception as e:
            self.fail_task(task_id, str(e))
            raise

    def get_user_tasks(self, user_id: str, include_completed: bool = False) -> list[Dict[str, Any]]:
        """Get all tasks for a user."""
        tasks = []
        for task in self._tasks.values():
            if task.user_id == user_id:
                if include_completed or task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                    tasks.append(task.to_dict())

        # Sort by created_at descending
        tasks.sort(key=lambda x: x["created_at"], reverse=True)
        return tasks

    def _cleanup_old_tasks(self):
        """Remove old completed tasks to prevent memory leak."""
        if len(self._tasks) <= self._max_tasks:
            return

        cutoff = datetime.utcnow() - timedelta(seconds=self._cleanup_interval)
        to_remove = []

        for task_id, task in self._tasks.items():
            if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                if task.completed_at and task.completed_at < cutoff:
                    to_remove.append(task_id)

        for task_id in to_remove:
            del self._tasks[task_id]

        if to_remove:
            logger.info(f"Cleaned up {len(to_remove)} old tasks")

    def _send_progress_notification(self, task: TaskInfo):
        """Send progress update via WebSocket if available."""
        try:
            from app.core.notifications import connections
            asyncio.create_task(
                connections.broadcast_json({
                    "type": "task_progress",
                    "task": task.to_dict()
                })
            )
        except Exception:
            pass  # Notifications are optional


# Global task manager instance
task_manager = TaskManager()


# Helper decorator for background tasks
def background_task(name: str):
    """Decorator to run a function as a background task with progress tracking."""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            user_id = kwargs.pop("user_id", None)
            task_id = task_manager.create_task(name, user_id)

            # Run in background
            asyncio.create_task(
                task_manager.run_async(task_id, func, *args, **kwargs)
            )

            return {"task_id": task_id, "status": "started"}

        return wrapper
    return decorator