from __future__ import annotations

import platform

import httpx
import redis
import requests
from sqlalchemy.exc import OperationalError
from celery import Celery
from celery.schedules import crontab

from app.core.config import settings


broker_url = settings.CELERY_BROKER_URL or settings.REDIS_URL
backend_url = settings.CELERY_RESULT_BACKEND or settings.REDIS_URL

# Transient failures worth retrying in background tasks. Business errors
# (ValueError and friends) must NOT be retried - they fail deterministically.
# NB: narrow transport-level classes only - requests.RequestException and
# httpx.HTTPError include permanent 4xx status errors which must not retry.
TRANSIENT_TASK_ERRORS = (
    ConnectionError,
    TimeoutError,
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    httpx.TransportError,
    httpx.TimeoutException,
    redis.exceptions.RedisError,
    OperationalError,
)

TASK_RETRY_KWARGS = {
    "autoretry_for": TRANSIENT_TASK_ERRORS,
    "retry_backoff": True,
    "retry_backoff_max": 600,
    "retry_jitter": True,
    "max_retries": 3,
}


celery_app = Celery(
    "po_helper",
    broker=broker_url,
    backend=backend_url,
)

# Determine the appropriate worker pool based on the platform
# Windows doesn't support fork(), so we use 'solo' or 'threads'
if platform.system() == "Windows":
    worker_pool = "solo"  # Use 'solo' for single-threaded execution
    # Alternative: use 'threads' for multi-threaded execution
    # worker_pool = 'threads'
else:
    worker_pool = "prefork"  # Default for Unix-like systems

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
    worker_concurrency=settings.CELERY_WORKER_CONCURRENCY,
    worker_prefetch_multiplier=settings.CELERY_WORKER_PREFETCH_MULTIPLIER,
    beat_schedule={
        "jira-sync-every-15-min": {
            "task": "jira.scheduled_sync",
            "schedule": crontab(minute="*/15"),
        },
        "confluence-sync-every-30-min": {
            "task": "confluence.scheduled_sync",
            "schedule": crontab(minute="*/30"),
        },
        "git-sync-every-30-min": {
            "task": "git.scheduled_sync",
            "schedule": crontab(minute="*/30"),
        },
        "testrail-sync-every-6-hours": {
            "task": "testrail.scheduled_sync",
            "schedule": crontab(minute=0, hour="*/6"),
        },
        "cleanup-exports-daily": {
            "task": "maintenance.cleanup_exports",
            "schedule": crontab(minute=0, hour=2),
        },
        "cleanup-baselines-daily": {
            "task": "maintenance.cleanup_baselines",
            "schedule": crontab(minute=30, hour=2),
        },
        "cleanup-token-sessions-daily": {
            "task": "maintenance.cleanup_token_sessions",
            "schedule": crontab(minute=15, hour=3),
        },
        "cleanup-analytics-events-daily": {
            "task": "maintenance.cleanup_analytics_events",
            "schedule": crontab(minute=45, hour=2),
        },
        "recover-stale-sync-tasks-every-5-min": {
            "task": "maintenance.recover_stale_sync_tasks",
            "schedule": crontab(minute="*/5"),
        },
        "traceability-rule-scheduler-every-minute": {
            "task": "traceability.scheduled_rule_execution",
            "schedule": crontab(minute="*"),
        },
    },
)

celery_app.autodiscover_tasks(["app"])
