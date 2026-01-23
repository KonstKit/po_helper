"""
Celery tasks for Confluence synchronization.
Provides robust background processing with retry logic and progress tracking.
"""

from typing import Optional, Dict, Any, cast
import logging
import json
import asyncio

import requests
from celery import Task
from sqlalchemy import select

from app.core.celery_app import celery_app
from app.core.database import AsyncSessionLocal
from app.services.confluence_service import confluence_service
from app.models.confluence import ConfluencePage
from app.core.cache import redis_client as _redis_client

logger = logging.getLogger(__name__)


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

    try:
        # Initialize progress
        self.update_progress("Starting Confluence sync...", 5)

        # Run async sync in sync context (Celery doesn't natively support async)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(_async_sync_space(self, space_key, query, full_sync))
        loop.close()

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

    async with AsyncSessionLocal() as db:
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

            for idx, page_summary in enumerate(pages, 1):
                page_id = page_summary.get("id")
                if not page_id:
                    continue

                # Fetch full page details
                full_page = confluence_service.get_page_by_id(
                    page_id, expand="body.storage,version,history,metadata.labels,space"
                )

                # Process page (create or update in DB)
                created = await _process_page(db, full_page)
                if created:
                    batch_created += 1
                else:
                    batch_updated += 1

                task.processed_pages += 1
                task.created_count = total_created + batch_created
                task.updated_count = total_updated + batch_updated

                # Update progress every 5 pages
                if idx % 5 == 0:
                    task.update_progress(f"Processing: {full_page.get('title', 'Untitled')}")

            # Commit batch
            if batch_created or batch_updated:
                await db.commit()

            total_synced += len(pages)
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

    if existing:
        # Update existing
        existing.space_key = space_key
        existing.title = page_data.get("title")
        existing.page_type = page_data.get("type")
        existing.url = url
        existing.version = (page_data.get("version") or {}).get("number")
        existing.created = _parse_dt((page_data.get("history") or {}).get("createdDate"))
        existing.updated = _parse_dt(
            (page_data.get("version") or {}).get("when")
            or (page_data.get("history") or {}).get("lastUpdated", {}).get("when")
        )
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
            created=_parse_dt((page_data.get("history") or {}).get("createdDate")),
            updated=_parse_dt(
                (page_data.get("version") or {}).get("when")
                or (page_data.get("history") or {}).get("lastUpdated", {}).get("when")
            ),
            labels=(page_data.get("metadata") or {}).get("labels"),
            html=(page_data.get("body") or {}).get("storage", {}).get("value"),
        )
        db.add(new_page)
        return True


# Scheduled sync task for Celery Beat
@celery_app.task(name="confluence.scheduled_sync")
def scheduled_confluence_sync():
    """Scheduled task to sync all configured Confluence spaces."""
    # Get all configured spaces from DB
    # For each space, spawn a sync task
    logger.info("Running scheduled Confluence sync")
    # Implementation would fetch spaces from IntegrationSettings
    pass


redis_client: Any = cast(Any, _redis_client)
