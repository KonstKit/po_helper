"""
Celery tasks for Confluence synchronization.
Provides robust background processing with retry logic and progress tracking.
"""

from typing import Optional, Dict, Any, cast
import logging
import json
from datetime import datetime, timezone

import requests
from celery import Task
from sqlalchemy import select

from app.core.celery_async_runner import run_async
from app.core.celery_app import celery_app
from app.core.database import AsyncSessionLocal
from app.core.config import settings
from app.core.crypto import decrypt_str
from app.services.confluence_service import confluence_service
from app.models.confluence import ConfluencePage
from app.models.settings import IntegrationSetting
from app.core.cache import redis_client as _redis_client

logger = logging.getLogger(__name__)


def _load_confluence_setting() -> Optional[IntegrationSetting]:
    async def _fetch_setting() -> Optional[IntegrationSetting]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(IntegrationSetting).where(IntegrationSetting.kind == "confluence")
            )
            return result.scalar_one_or_none()

    return run_async(_fetch_setting())


def _ensure_confluence_connection() -> bool:
    status = confluence_service.status()
    if status.get("configured"):
        return True

    row = _load_confluence_setting()
    base_url = row.base_url if row else settings.CONFLUENCE_BASE_URL
    email = row.email if row else settings.CONFLUENCE_EMAIL
    token: Optional[str] = None
    if row and row.api_token:
        token = decrypt_str(row.api_token)
    elif settings.CONFLUENCE_API_TOKEN:
        token = settings.CONFLUENCE_API_TOKEN

    if not base_url or not token:
        return False

    try:
        confluence_service.connect(base_url, email or None, token)
    except Exception as exc:
        logger.warning("Confluence connect failed: %s", exc)
        return False

    return True


class ConfluenceSyncTask(Task):
    """Base task class with progress tracking for Confluence sync."""

    def __init__(self):
        super().__init__()
        self.total_pages = 0
        self.processed_pages = 0
        self.created_count = 0
        self.updated_count = 0
        self.channel_id = None

    def update_progress(self, message: str, percent: Optional[int] = None):
        """Update task progress and send SSE update if channel is configured."""
        effective_percent = (
            percent
            if percent is not None
            else int((self.processed_pages / max(self.total_pages, 1)) * 100)
        )

        # Update Celery task state
        self.update_state(
            state="PROGRESS",
            meta={
                "current": self.processed_pages,
                "total": self.total_pages,
                "percent": effective_percent,
                "message": message,
                "created": self.created_count,
                "updated": self.updated_count,
            },
        )

        # Send SSE update if channel is configured
        if self.channel_id and redis_client:
            try:
                redis_client.publish(
                    f"confluence_sync_{self.channel_id}",
                    json.dumps(
                        {
                            "type": "progress",
                            "percent": effective_percent,
                            "message": message,
                            "synced": self.processed_pages,
                            "created": self.created_count,
                            "updated": self.updated_count,
                            "task_id": self.request.id,
                        }
                    ),
                )
            except Exception as e:
                logger.warning(f"Failed to send SSE update: {e}")


@celery_app.task(
    bind=True,
    base=ConfluenceSyncTask,
    name="confluence.sync_space",
    max_retries=3,
    soft_time_limit=900,  # 15 minutes soft limit
    time_limit=1200,  # 20 minutes hard limit
    acks_late=True,
    reject_on_worker_lost=True,
)
def sync_confluence_space(
    self,
    space_key: str,
    query: Optional[str] = None,
    channel_id: Optional[str] = None,
    full_sync: bool = True,
) -> Dict[str, Any]:
    """
    Sync Confluence space with robust error handling and progress tracking.

    Args:
        space_key: Confluence space key
        query: Optional CQL query to filter pages
        channel_id: Optional SSE channel for real-time updates
        full_sync: Whether to sync all pages or just one batch

    Returns:
        Dictionary with sync statistics
    """
    self.channel_id = channel_id

    if not _ensure_confluence_connection():
        logger.warning("Confluence not configured; skipping sync for space %s", space_key)
        return {"synced": 0, "created": 0, "updated": 0, "skipped": True}

    try:
        # Initialize progress
        self.update_progress("Starting Confluence sync...", 5)

        # Run async sync in sync context (Celery doesn't natively support async)
        result = run_async(_async_sync_space(self, space_key, query, full_sync))

        # Send completion
        if channel_id and redis_client:
            redis_client.publish(
                f"confluence_sync_{channel_id}",
                json.dumps(
                    {
                        "type": "complete",
                        "percent": 100,
                        "message": f"Sync complete! Synced {result['synced']} pages.",
                        "synced": result["synced"],
                        "created": result["created"],
                        "updated": result["updated"],
                        "task_id": self.request.id,
                    }
                ),
            )

        return result

    except requests.RequestException as exc:
        # Exponential backoff retry for API errors
        logger.error(f"Confluence API error: {exc}")
        raise self.retry(exc=exc, countdown=2**self.request.retries * 60)

    except Exception as exc:
        logger.error(f"Unexpected error in sync task: {exc}")

        # Send error notification
        if channel_id and redis_client:
            redis_client.publish(
                f"confluence_sync_{channel_id}",
                json.dumps({"type": "error", "message": str(exc), "task_id": self.request.id}),
            )
        raise


async def _async_sync_space(
    task: ConfluenceSyncTask, space_key: str, query: Optional[str], full_sync: bool
) -> Dict[str, Any]:
    """Async implementation of space sync."""
    page_start = 0
    limit = 50
    total_synced = 0
    total_created = 0
    total_updated = 0

    # Get first batch to estimate total
    pages = confluence_service.list_pages(
        space=space_key, q=query, limit=limit, start=page_start
    )

    if pages:
        # Estimate total
        if len(pages) == limit:
            task.total_pages = limit * 10  # Rough estimate
        else:
            task.total_pages = len(pages)

        task.update_progress(f"Found approximately {task.total_pages} pages to sync", 10)

    batch_number = 0

    while pages:
        batch_number += 1
        batch_created = 0
        batch_updated = 0

        task.update_progress(f"Processing batch {batch_number} ({len(pages)} pages)...")

        full_pages: list[Dict[str, Any]] = []
        for idx, page_summary in enumerate(pages, 1):
            page_id = page_summary.get("id")
            if not page_id:
                continue

            # Fetch network payloads before opening a DB transaction.
            full_page = confluence_service.get_page_by_id(
                page_id, expand="body.storage,version,history,metadata.labels,space"
            )
            full_pages.append(full_page)

            if idx % 5 == 0:
                task.update_progress(f"Fetched: {full_page.get('title', 'Untitled')}")

        if full_pages:
            async with AsyncSessionLocal() as db:
                for full_page in full_pages:
                    created = await _process_page(db, full_page)
                    if created:
                        batch_created += 1
                    else:
                        batch_updated += 1

                    task.processed_pages += 1
                    task.created_count = total_created + batch_created
                    task.updated_count = total_updated + batch_updated

                if batch_created or batch_updated:
                    await db.commit()

        total_synced += len(full_pages)
        total_created += batch_created
        total_updated += batch_updated

        # Adjust estimate if needed
        if total_synced > task.total_pages:
            task.total_pages = total_synced + limit

        # Check if should continue
        if not full_sync or len(pages) < limit:
            break

        # Fetch next batch
        page_start += len(pages)
        pages = confluence_service.list_pages(
            space=space_key, q=query, limit=limit, start=page_start
        )

    logger.info(
        f"Sync complete: synced={total_synced}, "
        f"created={total_created}, updated={total_updated}"
    )

    return {"synced": total_synced, "created": total_created, "updated": total_updated}


async def _process_page(db, page_data: Dict[str, Any]) -> bool:
    """Process a single Confluence page. Returns True if created, False if updated."""
    from app.api.api_v1.endpoints.confluence import _parse_dt

    page_id = page_data.get("id")
    space_key = (
        page_data.get("space", {}).get("key") if isinstance(page_data.get("space"), dict) else None
    )
    links = page_data.get("_links", {})

    # Build URL
    base_url = confluence_service.base_url or ""
    url = f"{base_url}{links.get('webui', '')}" if base_url else links.get("webui")

    # Check if page exists
    result = await db.execute(
        select(ConfluencePage).where(ConfluencePage.confluence_id == str(page_id))
    )
    existing = result.scalar_one_or_none()

    created_dt = _parse_dt((page_data.get("history") or {}).get("createdDate"))
    updated_dt = _parse_dt(
        (page_data.get("version") or {}).get("when")
        or (page_data.get("history") or {}).get("lastUpdated", {}).get("when")
    )
    if created_dt is None:
        if existing is not None and existing.created is not None:
            created_dt = existing.created
        else:
            created_dt = updated_dt or datetime.now(timezone.utc)
    if updated_dt is None:
        if existing is not None and existing.updated is not None:
            updated_dt = existing.updated
        else:
            updated_dt = created_dt
    row_updated_at = datetime.now(timezone.utc)

    if existing:
        # Update existing
        existing.space_key = space_key
        existing.title = page_data.get("title")
        existing.page_type = page_data.get("type")
        existing.url = url
        existing.version = (page_data.get("version") or {}).get("number")
        existing.created = created_dt
        existing.updated = updated_dt
        existing.updated_at = row_updated_at
        existing.labels = (page_data.get("metadata") or {}).get("labels")
        existing.html = (page_data.get("body") or {}).get("storage", {}).get("value")
        return False
    else:
        # Create new
        new_page = ConfluencePage(
            confluence_id=str(page_id),
            space_key=space_key,
            title=page_data.get("title"),
            page_type=page_data.get("type"),
            url=url,
            version=(page_data.get("version") or {}).get("number"),
            created=created_dt,
            updated=updated_dt,
            updated_at=row_updated_at,
            labels=(page_data.get("metadata") or {}).get("labels"),
            html=(page_data.get("body") or {}).get("storage", {}).get("value"),
        )
        db.add(new_page)
        return True


# Scheduled sync task for Celery Beat
@celery_app.task(name="confluence.scheduled_sync")
def scheduled_confluence_sync():
    """Scheduled task to sync all configured Confluence spaces."""
    logger.info("Running scheduled Confluence sync")
    if not _ensure_confluence_connection():
        logger.info("Confluence not configured; skipping scheduled sync")
        return {"status": "skipped", "dispatched": 0}

    spaces = confluence_service.list_spaces(limit=200)
    if not spaces:
        logger.info("No Confluence spaces found; skipping scheduled sync")
        return {"status": "skipped", "dispatched": 0}

    dispatched = 0
    for space in spaces:
        space_key = space.get("key")
        if not space_key:
            continue
        sync_confluence_space.delay(space_key, None, None, True)
        dispatched += 1

    logger.info("Scheduled Confluence sync dispatched for %d space(s)", dispatched)
    return {"status": "ok", "dispatched": dispatched}


redis_client: Any = cast(Any, _redis_client)
