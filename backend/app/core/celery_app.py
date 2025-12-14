from __future__ import annotations

import platform
from celery import Celery

from app.core.config import settings


broker_url = settings.CELERY_BROKER_URL or settings.REDIS_URL
backend_url = settings.CELERY_RESULT_BACKEND or settings.REDIS_URL

celery_app = Celery(
    "po_helper",
    broker=broker_url,
    backend=backend_url,
)

# Determine the appropriate worker pool based on the platform
# Windows doesn't support fork(), so we use 'solo' or 'threads'
if platform.system() == 'Windows':
    worker_pool = 'solo'  # Use 'solo' for single-threaded execution
    # Alternative: use 'threads' for multi-threaded execution
    # worker_pool = 'threads'
else:
    worker_pool = 'prefork'  # Default for Unix-like systems

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    task_always_eager=settings.CELERY_TASK_ALWAYS_EAGER,
    task_eager_propagates=True,
    broker_connection_retry_on_startup=True,
    # Set the worker pool type
    worker_pool=worker_pool,
)

celery_app.autodiscover_tasks(["app"])
