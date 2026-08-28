from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException, Depends, Request, Response
from fastapi.responses import StreamingResponse
from typing import Optional, AsyncGenerator, Any, cast
from pydantic import BaseModel
from app.api.deps import require_integration_access, require_integration_permission
from app.models.rbac import Permissions
from app.services.confluence_service import confluence_service
from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.crypto import encrypt_integration_secret
from app.core.rate_limit import limiter
from app.core.config import settings
from app.core.database import get_db
from app.models.confluence import ConfluencePage
from app.models import User
from app.models.settings import IntegrationSetting
from app.utils import transactional_session, handle_api_error
from datetime import datetime, timezone
import re
import json
import asyncio
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


class ConfluenceConnectRequest(BaseModel):
    base_url: str
    api_token: str
    email: Optional[str] = None
    is_cloud: Optional[bool] = None
    save: bool = False


def _encrypt_saved_token(token: str) -> str:
    try:
        encrypted = encrypt_integration_secret(token)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if encrypted is None:
        raise HTTPException(status_code=503, detail="Failed to persist Confluence credentials.")
    return encrypted


def _normalize_http_base_url(base_url: str, provider: str) -> str:
    normalized = base_url.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {provider} base_url. Only http/https URLs are allowed.",
        )
    return normalized


async def _call_confluence(func, *args, **kwargs):
    """Run blocking Confluence service call off the event loop."""
    return await asyncio.to_thread(func, *args, **kwargs)


@router.post("/connect")
async def connect_confluence(
    payload: ConfluenceConnectRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(
        require_integration_permission(Permissions.INTEGRATION_MANAGE)
    ),
):
    """Connect to Confluence instance.

    Args:
        base_url: Base URL of the Confluence instance
        email: Email for authentication (required for Cloud, optional for Data Center)
        api_token: API token for Cloud or Personal Access Token for Data Center
        is_cloud: True for Cloud, False for Data Center/Server, None for auto-detect (default)
        save: Whether to save credentials to database
    """
    del current_user
    with handle_api_error(operation="connect_confluence"):
        normalized_base_url = _normalize_http_base_url(payload.base_url, "confluence")
        await _call_confluence(
            confluence_service.connect,
            normalized_base_url,
            payload.email,
            payload.api_token,
            is_cloud=payload.is_cloud,
        )
        await _call_confluence(confluence_service.validate)
        if payload.save:
            result = await db.execute(
                select(IntegrationSetting).where(IntegrationSetting.kind == "confluence")
            )
            row = result.scalar_one_or_none()
            async with transactional_session(db):
                if not row:
                    row = IntegrationSetting(kind="confluence")
                    db.add(row)
                row.base_url = (
                    (confluence_service.base_url or normalized_base_url).rstrip("/")
                    if (confluence_service.base_url or normalized_base_url)
                    else None
                )
                row.email = payload.email or None
                row.api_token = (
                    _encrypt_saved_token(payload.api_token) if payload.api_token else row.api_token
                )
        return {"status": "connected", **confluence_service.status()}


@router.get("/status")
async def status(current_user: User | None = Depends(require_integration_access)):
    del current_user
    return confluence_service.status()


@router.get("/search")
async def search_cql(
    cql: str,
    limit: int = 50,
    current_user: User | None = Depends(require_integration_access),
):
    del current_user
    with handle_api_error(operation="search_cql"):
        results = await _call_confluence(confluence_service.search_content, cql, limit)
        items = []
        for r in results:
            links = r.get("_links", {})
            items.append(
                {
                    "id": r.get("id"),
                    "title": r.get("title"),
                    "type": r.get("type"),
                    "url": f"{confluence_service.base_url}{links.get('webui', '')}"
                    if confluence_service.base_url
                    else links.get("webui"),
                    "version": (r.get("version") or {}).get("number"),
                    "last_updated": (r.get("version") or {}).get("when")
                    or (r.get("history") or {}).get("lastUpdated", {}).get("when"),
                }
            )
        return {"count": len(items), "results": items}


@router.get("/spaces")
async def list_spaces(
    q: Optional[str] = None,
    limit: int = 50,
    current_user: User | None = Depends(require_integration_access),
):
    del current_user
    with handle_api_error(operation="list_spaces"):
        items = await _call_confluence(confluence_service.list_spaces, q=q, limit=limit)
        return {"count": len(items), "results": items}


@router.get("/pages")
async def list_pages(
    space: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 50,
    start: int = 0,
    current_user: User | None = Depends(require_integration_access),
):
    del current_user
    with handle_api_error(operation="list_pages"):
        items = await _call_confluence(
            confluence_service.list_pages, space=space, q=q, limit=limit, start=start
        )
        return {"count": len(items), "results": items}


@router.get("/spaces/{space_key}/tree")
async def get_space_tree(
    space_key: str,
    limit: int = 100,
    max_pages: Optional[int] = None,
    current_user: User | None = Depends(require_integration_access),
):
    del current_user
    with handle_api_error(operation="get_space_tree", context={"space_key": space_key}):
        tree = await _call_confluence(
            confluence_service.list_space_tree, space_key, page_limit=limit, max_pages=max_pages
        )
        return {"count": len(tree), "tree": tree}


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        m = re.match(r"(.+)([+-]\d{2})(\d{2})$", s)
        if m:
            s = f"{m.group(1)}{m.group(2)}:{m.group(3)}"
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        parsed = datetime.fromisoformat(s)
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return None


async def _upsert_confluence_page(
    pid: str,
    db: AsyncSession,
) -> tuple[int, int]:
    """
    Fetch and upsert a single Confluence page to the database.

    This utility eliminates the repetitive 55-line pattern of:
    - Fetching full page data from Confluence API
    - Extracting fields from Confluence response
    - Upserting ConfluencePage record (create or update)

    Args:
        pid: Confluence page ID
        db: Database session

    Returns:
        Tuple of (created_count, updated_count) - either (1, 0) or (0, 1)
    """
    full_page = await _call_confluence(
        confluence_service.get_page_by_id,
        pid,
        expand="body.storage,version,history,metadata.labels,space",
    )
    cid = full_page.get("id")
    title = full_page.get("title")
    ptype = full_page.get("type")
    space_key = (
        ((full_page.get("space") or {}).get("key"))
        if isinstance(full_page.get("space"), dict)
        else None
    )
    links = full_page.get("_links", {})
    url = (
        f"{confluence_service.base_url}{links.get('webui', '')}"
        if confluence_service.base_url
        else links.get("webui")
    )
    version = (full_page.get("version") or {}).get("number")
    created_at = (full_page.get("history") or {}).get("createdDate")
    last_updated = (full_page.get("version") or {}).get("when") or (
        full_page.get("history") or {}
    ).get("lastUpdated", {}).get("when")
    labels_raw = (full_page.get("metadata") or {}).get("labels")
    labels = labels_raw if isinstance(labels_raw, list) else None
    html = (full_page.get("body") or {}).get("storage", {}).get("value") or ""
    space_val = str(space_key) if space_key is not None else ""
    title_val = title or ""
    ptype_val = ptype or "page"
    url_val = url or ""
    version_val = int(version or 0)
    created_dt = _parse_dt(created_at) or datetime.now(timezone.utc)
    updated_dt = _parse_dt(last_updated) or created_dt

    result = await db.execute(
        select(ConfluencePage).where(ConfluencePage.confluence_id == str(cid))
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = ConfluencePage(
            confluence_id=str(cid),
            space_key=space_val,
            title=title_val,
            page_type=ptype_val,
            url=url_val,
            version=version_val,
            created=created_dt,
            updated=updated_dt,
            labels=labels,
            html=html,
        )
        db.add(row)
        return (1, 0)  # created
    else:
        row.space_key = space_val
        row.title = title_val
        row.page_type = ptype_val
        row.url = url_val
        row.version = version_val
        row.created = created_dt
        row.updated = updated_dt
        row.labels = labels
        row.html = html
        return (0, 1)  # updated


@router.post("/sync")
@limiter.limit(settings.RATE_LIMIT_SYNC)
async def sync_confluence(
    request: Request,
    response: Response,
    space: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 50,
    start: int = 0,
    full: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_integration_permission(Permissions.PROJECT_UPDATE)),
):
    """Sync Confluence pages to local database.

    Args:
        space: Space key to sync (optional)
        q: Search query (optional)
        limit: Batch size for API requests (default: 50)
        start: Starting offset (default: 0)
        full: If True, sync ALL pages; if False, only one batch (default: False)
    """
    del current_user
    import logging

    logger = logging.getLogger(__name__)

    page_start = max(0, start)
    total_synced = 0
    total_created = 0
    total_updated = 0
    batch_number = 0

    logger.info(f"Starting sync - space: {space}, query: {q}, full: {full}, limit: {limit}")

    try:
        while True:
            batch_number += 1
            logger.info(f"Fetching batch {batch_number} (start={page_start}, limit={limit})")

            pages = await _call_confluence(
                confluence_service.list_pages, space=space, q=q, limit=limit, start=page_start
            )
            if not pages:
                logger.info("No more pages to sync")
                break

            logger.info(f"Processing {len(pages)} pages in batch {batch_number}")
            batch_created = 0
            batch_updated = 0

            for idx, p in enumerate(pages, 1):
                pid = p.get("id")
                if not pid:
                    continue

                # Log progress every 10 pages
                if idx % 10 == 0:
                    logger.info(f"Processing page {idx}/{len(pages)} in batch {batch_number}")

                created, updated = await _upsert_confluence_page(pid, db)
                batch_created += created
                batch_updated += updated

            if batch_created or batch_updated:
                async with transactional_session(db):
                    pass  # All db operations already executed above

            total_synced += len(pages)
            total_created += batch_created
            total_updated += batch_updated

            logger.info(
                f"Batch {batch_number} complete - created: {batch_created}, updated: {batch_updated}"
            )

            # If not full sync or reached the end of results
            if not full or len(pages) < limit:
                logger.info(
                    f"Stopping sync - full: {full}, pages_in_batch: {len(pages)}, limit: {limit}"
                )
                break

            # Move to next batch
            page_start += len(pages)

        logger.info(
            f"Sync complete - total synced: {total_synced}, created: {total_created}, updated: {total_updated}"
        )
        return {"synced": total_synced, "created": total_created, "updated": total_updated}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/sync-sse")
@limiter.limit(settings.RATE_LIMIT_SYNC)
async def sync_confluence_sse(
    request: Request,
    response: Response,
    space: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 50,
    start: int = 0,
    full: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_integration_permission(Permissions.PROJECT_UPDATE)),
):
    """Sync Confluence pages with real-time progress updates via Server-Sent Events."""
    del current_user

    async def generate_events() -> AsyncGenerator[str, None]:
        page_start = max(0, start)
        total_synced = 0
        total_created = 0
        total_updated = 0
        batch_number = 0
        total_pages_estimate = 0
        last_keepalive = asyncio.get_event_loop().time()

        # Send initial event
        yield f"data: {json.dumps({'type': 'start', 'message': 'Initializing sync...', 'percent': 5})}\n\n"
        await asyncio.sleep(0.1)

        try:
            # First, try to estimate total pages
            logger.info(f"Starting SSE sync for space: {space}, query: {q}")

            # Get first batch to estimate total
            first_batch = await _call_confluence(
                confluence_service.list_pages, space=space, q=q, limit=limit, start=0
            )
            if first_batch:
                # Estimate based on first batch (confluence doesn't give exact total)
                # If we got full batch, there might be more
                if len(first_batch) == limit:
                    total_pages_estimate = limit * 10  # Rough estimate
                else:
                    total_pages_estimate = len(first_batch)

                yield f"data: {json.dumps({'type': 'progress', 'percent': 10, 'message': f'Found approximately {total_pages_estimate} pages to sync...', 'synced': 0, 'created': 0, 'updated': 0})}\n\n"
                await asyncio.sleep(0.1)

            while True:
                batch_number += 1

                # Calculate progress based on synced vs estimated
                if total_pages_estimate > 0:
                    progress_percent = min(95, int(10 + (total_synced / total_pages_estimate) * 85))
                else:
                    progress_percent = min(95, 10 + (batch_number - 1) * 15)

                yield f"data: {json.dumps({'type': 'progress', 'percent': progress_percent, 'message': f'Loading batch {batch_number} (synced {total_synced} pages)...', 'synced': total_synced, 'created': total_created, 'updated': total_updated})}\n\n"
                await asyncio.sleep(0.1)

                pages = await _call_confluence(
                    confluence_service.list_pages, space=space, q=q, limit=limit, start=page_start
                )
                if not pages:
                    logger.info(f"No more pages to sync. Total synced: {total_synced}")
                    break

                logger.info(f"Processing batch {batch_number} with {len(pages)} pages")
                batch_created = 0
                batch_updated = 0

                # Adjust estimate if we're getting more pages than expected
                if total_synced + len(pages) > total_pages_estimate:
                    total_pages_estimate = total_synced + len(pages) + limit

                for idx, p in enumerate(pages, 1):
                    pid = p.get("id")
                    if not pid:
                        continue

                    # Send keepalive if needed (every 20 seconds)
                    current_time = asyncio.get_event_loop().time()
                    if current_time - last_keepalive > 20:
                        yield ": keepalive\n\n"
                        last_keepalive = current_time

                    # Send detailed progress for every 3rd page or last page
                    if idx % 3 == 0 or idx == len(pages):
                        current_total = total_synced + idx
                        if total_pages_estimate > 0:
                            item_progress = min(
                                95, int(10 + (current_total / total_pages_estimate) * 85)
                            )
                        else:
                            item_progress = progress_percent + int((idx / len(pages)) * 5)

                        page_title = p.get("title", "Untitled")
                        yield f"data: {json.dumps({'type': 'progress', 'percent': item_progress, 'message': f'Processing page {current_total}: {page_title}...', 'synced': current_total, 'created': total_created + batch_created, 'updated': total_updated + batch_updated})}\n\n"
                        await asyncio.sleep(0.05)  # Small delay to ensure client receives update
                        last_keepalive = current_time  # Update keepalive time after sending data

                    created, updated = await _upsert_confluence_page(pid, db)
                    batch_created += created
                    batch_updated += updated

                if batch_created or batch_updated:
                    async with transactional_session(db):
                        pass  # All db operations already executed above

                total_synced += len(pages)
                total_created += batch_created
                total_updated += batch_updated

                # If not full sync or reached the end
                if not full or len(pages) < limit:
                    logger.info(
                        f"Stopping sync. Full: {full}, Pages in batch: {len(pages)}, Limit: {limit}"
                    )
                    break

                page_start += len(pages)

            # Send completion event
            logger.info(
                f"Sync complete. Total: {total_synced}, Created: {total_created}, Updated: {total_updated}"
            )
            yield f"data: {json.dumps({'type': 'complete', 'percent': 100, 'message': f'Sync complete! Synced {total_synced} pages (created {total_created}, updated {total_updated}).', 'synced': total_synced, 'created': total_created, 'updated': total_updated})}\n\n"

        except Exception as e:
            await db.rollback()
            error_msg = str(e)
            logger.error(f"Sync error: {error_msg}")
            yield f"data: {json.dumps({'type': 'error', 'message': error_msg})}\n\n"

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "X-Accel-Buffering": "no",  # Disable Nginx buffering
            "Connection": "keep-alive",
        },
    )


@router.post("/sync-celery")
@limiter.limit(settings.RATE_LIMIT_SYNC)
async def start_celery_sync(
    request: Request,
    response: Response,
    space: Optional[str] = None,
    q: Optional[str] = None,
    full: bool = True,
    current_user: User | None = Depends(require_integration_permission(Permissions.PROJECT_UPDATE)),
):
    """Start Confluence sync using Celery for robust background processing."""
    del current_user
    with handle_api_error(
        operation="start_celery_sync", status_code=500, exception_map={ImportError: 503}
    ):
        from app.tasks.confluence_tasks import sync_confluence_space
        import uuid

        # Generate unique channel ID for this sync
        channel_id = str(uuid.uuid4())

        # Start Celery task
        task = sync_confluence_space.delay(
            space_key=space, query=q, channel_id=channel_id, full_sync=full
        )

        return {
            "task_id": task.id,
            "channel_id": channel_id,
            "status": "started",
            "message": "Sync task started in background",
        }


@router.get("/sync-celery-stream/{channel_id}")
async def stream_celery_sync(
    channel_id: str,
    current_user: User | None = Depends(require_integration_access),
):
    """Stream Celery sync progress via SSE."""
    del current_user
    from app.core.cache import redis_client

    async def generate_events() -> AsyncGenerator[str, None]:
        if not redis_client:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Redis not configured'})}\n\n"
            return

        # Subscribe to Redis channel
        pubsub = cast(Any, redis_client).pubsub()
        pubsub.subscribe(f"confluence_sync_{channel_id}")

        try:
            # Send initial connection event
            yield f"data: {json.dumps({'type': 'connected', 'channel': channel_id})}\n\n"

            # Listen for messages
            for message in pubsub.listen():
                if message["type"] == "message":
                    # Forward message to SSE
                    yield f"data: {message['data'].decode('utf-8')}\n\n"

                    # Check if complete or error
                    try:
                        data = json.loads(message["data"])
                        if data.get("type") in ["complete", "error"]:
                            break
                    except (json.JSONDecodeError, TypeError):
                        pass

                # Send keepalive every 30 seconds
                await asyncio.sleep(0.1)

        finally:
            pubsub.unsubscribe(f"confluence_sync_{channel_id}")
            pubsub.close()

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/subtree/{page_id}/sync")
@limiter.limit(settings.RATE_LIMIT_SYNC)
async def sync_subtree(
    request: Request,
    response: Response,
    page_id: str,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_integration_permission(Permissions.PROJECT_UPDATE)),
):
    del current_user
    try:
        ids = await _call_confluence(confluence_service.iter_subtree, page_id, limit=limit)
        created = 0
        updated = 0
        for pid in ids:
            full = await _call_confluence(
                confluence_service.get_page_by_id,
                pid,
                expand="body.storage,version,history,metadata.labels,space",
            )
            cid = full.get("id")
            title = full.get("title")
            ptype = full.get("type")
            space_key = (
                ((full.get("space") or {}).get("key"))
                if isinstance(full.get("space"), dict)
                else None
            )
            links = full.get("_links", {})
            url = (
                f"{confluence_service.base_url}{links.get('webui', '')}"
                if confluence_service.base_url
                else links.get("webui")
            )
            version = (full.get("version") or {}).get("number")
            created_at = (full.get("history") or {}).get("createdDate")
            last_updated = (full.get("version") or {}).get("when") or (
                full.get("history") or {}
            ).get("lastUpdated", {}).get("when")
            labels_raw = (full.get("metadata") or {}).get("labels")
            labels = labels_raw if isinstance(labels_raw, list) else None
            html = (full.get("body") or {}).get("storage", {}).get("value") or ""
            space_val = str(space_key) if space_key is not None else ""
            title_val = title or ""
            ptype_val = ptype or "page"
            url_val = url or ""
            version_val = int(version or 0)
            created_dt = _parse_dt(created_at) or datetime.now(timezone.utc)
            updated_dt = _parse_dt(last_updated) or created_dt

            result = await db.execute(
                select(ConfluencePage).where(ConfluencePage.confluence_id == str(cid))
            )
            row = result.scalar_one_or_none()
            if row is None:
                row = ConfluencePage(
                    confluence_id=str(cid),
                    space_key=space_val,
                    title=title_val,
                    page_type=ptype_val,
                    url=url_val,
                    version=version_val,
                    created=created_dt,
                    updated=updated_dt,
                    labels=labels,
                    html=html,
                )
                db.add(row)
                created += 1
            else:
                row.space_key = space_val
                row.title = title_val
                row.page_type = ptype_val
                row.url = url_val
                row.version = version_val
                row.created = created_dt
                row.updated = updated_dt
                row.labels = labels
                row.html = html
                updated += 1
        if created or updated:
            async with transactional_session(db):
                pass  # All db operations already executed above
        return {"synced": len(ids), "created": created, "updated": updated}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/local/pages")
async def list_local_pages(
    space: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_integration_access),
):
    del current_user
    with handle_api_error(operation="list_local_pages"):
        stmt = select(ConfluencePage)
        if space:
            stmt = stmt.where(ConfluencePage.space_key == space)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(ConfluencePage.title.like(like))
        # Order by updated desc (nulls last)
        stmt = stmt.order_by(ConfluencePage.updated.desc().nullslast())
        stmt = stmt.offset(offset).limit(limit)
        result = await db.execute(stmt)
        rows = result.scalars().all()
        out = []
        for r in rows:
            out.append(
                {
                    "id": r.confluence_id,
                    "title": r.title,
                    "space": r.space_key,
                    "url": r.url,
                    "version": r.version,
                    "last_updated": r.updated.isoformat() if r.updated else None,
                }
            )
        return {"count": len(out), "results": out}


@router.get("/pages/{page_id}")
async def get_page(
    page_id: str,
    current_user: User | None = Depends(require_integration_access),
):
    del current_user
    with handle_api_error(operation="get_page", context={"page_id": page_id}):
        page = await _call_confluence(confluence_service.get_page_by_id, page_id)
        links = page.get("_links", {})
        return {
            "id": page.get("id"),
            "title": page.get("title"),
            "url": f"{confluence_service.base_url}{links.get('webui', '')}"
            if confluence_service.base_url
            else links.get("webui"),
            "html": page.get("body", {}).get("storage", {}).get("value"),
            "labels": (page.get("metadata") or {}).get("labels"),
            "version": (page.get("version") or {}).get("number"),
        }


@router.get("/prd/{page_id}/requirements")
async def extract_prd_requirements(
    page_id: str,
    current_user: User | None = Depends(require_integration_access),
):
    del current_user
    with handle_api_error(operation="extract_prd_requirements", context={"page_id": page_id}):
        page = await _call_confluence(
            confluence_service.get_page_by_id,
            page_id,
            expand="body.storage,version,metadata.labels",
        )
        html = page.get("body", {}).get("storage", {}).get("value", "")
        soup = BeautifulSoup(html, "html.parser")
        requirements: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        parsed_rows = 0

        id_header_tokens = (
            "id",
            "requirement id",
            "req id",
            "story id",
            "key",
            "identifier",
            "#",
        )
        desc_header_tokens = (
            "requirement",
            "description",
            "summary",
            "user story",
            "story",
            "acceptance criteria",
            "criteria",
            "details",
            "behavior",
            "context",
            "decision",
        )
        prio_header_tokens = (
            "priority",
            "severity",
            "importance",
            "type",
            "category",
            "status",
        )
        requirement_signal_tokens = (
            "require",
            "story",
            "scenario",
            "acceptance",
            "criteria",
            "pre-condition",
            "post-condition",
            "constraint",
            "rule",
            "validation",
            "behavior",
            "goal",
            "epic",
            "feature",
        )
        noise_id_tokens = (
            "jira link",
            "link to design",
            "attachment",
            "attachments",
            "screenshot",
            "image",
            "figma",
        )
        ui_type_tokens = (
            "button",
            "page",
            "section",
            "dropdown",
            "dropdown menu",
            "input field",
            "chip",
            "snackbar",
            "checkbox",
            "table row",
            "pop-up",
            "popup",
            "menu",
        )

        def _clean_text(text: str) -> str:
            value = (text or "").replace("\xa0", " ")
            value = re.sub(r"\s+", " ", value).strip()
            return value

        def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
            t = text.lower()
            return any(token in t for token in tokens)

        def _looks_like_url(text: str) -> bool:
            t = text.lower()
            return bool(
                re.search(r"https?://|www\.", t)
                or any(ext in t for ext in (".png", ".jpg", ".jpeg", ".gif", ".svg", "/download/"))
            )

        def _direct_cells(row) -> list[Any]:
            return row.find_all(["td", "th"], recursive=False)

        def _extract_headers(table) -> list[str]:
            thead = table.find("thead")
            if thead:
                header_row = thead.find("tr")
                if header_row:
                    headers = [
                        _clean_text(cell.get_text(" ", strip=True))
                        for cell in _direct_cells(header_row)
                    ]
                    return [h for h in headers if h]

            first_row = table.find("tr")
            if not first_row:
                return []

            headers = [
                _clean_text(cell.get_text(" ", strip=True))
                for cell in first_row.find_all("th", recursive=False)
            ]
            return [h for h in headers if h]

        def _looks_like_header_row(row, headers: list[str]) -> bool:
            if not headers:
                return False
            row_cells = [_clean_text(cell.get_text(" ", strip=True)) for cell in _direct_cells(row)]
            if len(row_cells) < len(headers):
                return False
            return row_cells[: len(headers)] == headers

        def _find_header_index(headers_l: list[str], tokens: tuple[str, ...]) -> Optional[int]:
            for idx, header in enumerate(headers_l):
                if any(token in header for token in tokens):
                    return idx
            return None

        def _score_candidate(
            req_id_norm: str, desc_norm: str, prio_norm: str, structured: bool
        ) -> int:
            req_l = req_id_norm.lower()
            desc_l = desc_norm.lower()
            prio_l = prio_norm.lower()
            score = 0

            if structured:
                score += 1
            if _contains_any(req_l, requirement_signal_tokens):
                score += 2
            if _contains_any(desc_l, ("given", "when", "then", "must", "should", "shall")):
                score += 1
            if _contains_any(desc_l, requirement_signal_tokens):
                score += 1
            if len(desc_norm.split()) >= 4:
                score += 1
            if prio_l in {"low", "medium", "high", "critical", "blocker"}:
                score += 1
            if _contains_any(prio_l, ui_type_tokens):
                score += 1

            if _contains_any(req_l, noise_id_tokens):
                score -= 3
            if _contains_any(desc_l, ("logo", "icon", "powered by", "report a bug")):
                score -= 2
            if _looks_like_url(desc_l) and len(desc_norm.split()) <= 8:
                score -= 2
            if len(desc_norm) < 3:
                score -= 2

            return score

        def _add_requirement(
            req_id: str,
            desc: str,
            prio: str,
            *,
            min_score: int,
            structured: bool,
        ) -> None:
            nonlocal parsed_rows
            req_id_norm = _clean_text(req_id)
            desc_norm = _clean_text(desc)
            prio_norm = _clean_text(prio)

            if not req_id_norm or not desc_norm:
                return
            if req_id_norm.lower() in {"id", "requirement"} and desc_norm.lower() in {
                "description",
                "summary",
            }:
                return
            score = _score_candidate(req_id_norm, desc_norm, prio_norm, structured)
            if score < min_score:
                return
            if prio_norm.lower() in {"", "-", "n/a"}:
                prio_norm = "Medium"
            if len(prio_norm) > 40:
                prio_norm = "Medium"
            if len(desc_norm) > 4000:
                desc_norm = desc_norm[:3997] + "..."

            dedupe_key = (req_id_norm.casefold(), desc_norm.casefold())
            if dedupe_key in seen:
                return
            seen.add(dedupe_key)
            parsed_rows += 1
            requirements.append(
                {"id": req_id_norm, "description": desc_norm, "priority": prio_norm or "Medium"}
            )

        tables = soup.find_all("table")
        for table in tables:
            headers = _extract_headers(table)
            headers_l = [h.lower() for h in headers]
            header_blob = " ".join(headers_l)

            tbody = table.find("tbody")
            rows = (
                tbody.find_all("tr", recursive=False)
                if tbody
                else table.find_all("tr", recursive=False)
            )
            if not rows:
                continue

            first_col_sample = []
            for r in rows[:8]:
                cells = _direct_cells(r)
                if cells:
                    first_col_sample.append(_clean_text(cells[0].get_text(" ", strip=True)).lower())
            first_col_blob = " ".join([x for x in first_col_sample if x])

            # Adaptive detection: explicit header signals OR semantic signals in first column.
            is_candidate = bool(headers) and (
                _contains_any(header_blob, requirement_signal_tokens) or len(headers) >= 2
            )
            if not is_candidate and first_col_blob:
                is_candidate = _contains_any(first_col_blob, requirement_signal_tokens)
            if not is_candidate:
                continue

            if _looks_like_header_row(rows[0], headers):
                rows = rows[1:]

            id_idx = _find_header_index(headers_l, id_header_tokens)
            desc_idx = _find_header_index(headers_l, desc_header_tokens)
            prio_idx = _find_header_index(headers_l, prio_header_tokens)
            structured = _contains_any(header_blob, requirement_signal_tokens)
            min_score = 0 if structured else 1

            for row in rows:
                cells = _direct_cells(row)
                if len(cells) < 2:
                    continue

                fallback_id_idx = 0
                fallback_desc_idx = 1 if len(cells) > 1 else 0
                use_id_idx = (
                    id_idx if id_idx is not None and id_idx < len(cells) else fallback_id_idx
                )
                use_desc_idx = (
                    desc_idx
                    if desc_idx is not None and desc_idx < len(cells)
                    else fallback_desc_idx
                )
                use_prio_idx = prio_idx if prio_idx is not None and prio_idx < len(cells) else None

                req_id = _clean_text(cells[use_id_idx].get_text(" ", strip=True))
                desc = _clean_text(cells[use_desc_idx].get_text(" ", strip=True))
                if not desc and len(cells) > 2:
                    # Some Confluence pages keep narrative text in the 3rd+ column.
                    desc = _clean_text(cells[2].get_text(" ", strip=True))
                prio = (
                    _clean_text(cells[use_prio_idx].get_text(" ", strip=True))
                    if use_prio_idx is not None
                    else (
                        _clean_text(cells[2].get_text(" ", strip=True))
                        if len(cells) > 2
                        else "Medium"
                    )
                )
                _add_requirement(req_id, desc, prio, min_score=min_score, structured=structured)

        logger.info(
            "PRD extraction for page_id=%s: tables=%d rows_kept=%d requirements=%d",
            page_id,
            len(tables),
            parsed_rows,
            len(requirements),
        )
        return {"count": len(requirements), "requirements": requirements}


def _extract_section_text(soup: BeautifulSoup, titles: list[str]) -> str:
    # Find a header whose text matches any of the titles, return text until next header of same or higher level
    headers = soup.find_all(["h1", "h2", "h3", "h4"])
    target = None
    level = None
    for h in headers:
        txt = (h.get_text() or "").strip().lower()
        for t in titles:
            if t.lower() in txt:
                target = h
                level = int(h.name[1])
                break
        if target:
            break
    if not target:
        return ""
    texts: list[str] = []
    for el in target.next_siblings:
        if getattr(el, "name", None) in ("h1", "h2", "h3", "h4"):
            if int(el.name[1]) <= (level or 6):
                break
        if hasattr(el, "get_text"):
            texts.append(el.get_text(" ", strip=True))
    return "\n".join([t for t in texts if t])


@router.get("/adr/{page_id}")
async def extract_adr(
    page_id: str,
    current_user: User | None = Depends(require_integration_access),
):
    del current_user
    with handle_api_error(operation="extract_adr", context={"page_id": page_id}):
        page = await _call_confluence(
            confluence_service.get_page_by_id,
            page_id,
            expand="body.storage,version,metadata.labels",
        )
        html = page.get("body", {}).get("storage", {}).get("value", "")
        soup = BeautifulSoup(html, "html.parser")
        data = {
            "id": page.get("id"),
            "title": page.get("title"),
            "status": _extract_section_text(soup, ["status"]).split("\n")[0] if html else None,
            "context": _extract_section_text(soup, ["context"]),
            "decision": _extract_section_text(soup, ["decision"]),
            "consequences": _extract_section_text(soup, ["consequences", "consequence"]),
            "alternatives": _extract_section_text(soup, ["alternatives", "alternative"]),
        }
        return data


@router.get("/research/{page_id}")
async def extract_research(
    page_id: str,
    current_user: User | None = Depends(require_integration_access),
):
    del current_user
    with handle_api_error(operation="extract_research", context={"page_id": page_id}):
        page = await _call_confluence(
            confluence_service.get_page_by_id,
            page_id,
            expand="body.storage,version,metadata.labels",
        )
        html = page.get("body", {}).get("storage", {}).get("value", "")
        soup = BeautifulSoup(html, "html.parser")

        def collect_bullets():
            items = []
            for ul in soup.find_all("ul"):
                for li in ul.find_all("li", recursive=False):
                    txt = li.get_text(" ", strip=True)
                    if txt:
                        items.append(txt)
            return items

        bullets = collect_bullets()

        def cat(t: str) -> str:
            tl = t.lower()
            if any(
                k in tl for k in ["love", "like", "good", "great", "works well", "+", "рџ‘Ќ", "рџЉ"]
            ):
                return "positive"
            if any(
                k in tl
                for k in ["bug", "issue", "problem", "error", "pain", "hard", "confusing", "slow"]
            ):
                return "pain_points"
            if any(
                k in tl for k in ["feature", "request", "would like", "should have", "wishlist"]
            ):
                return "feature_requests"
            if any(k in tl for k in ["usability", "ux", "confusing", "difficult", "complex"]):
                return "usability_issues"
            return "other"

        grouped: dict[str, list[str]] = {
            k: []
            for k in ["positive", "pain_points", "feature_requests", "usability_issues", "other"]
        }
        for b in bullets:
            grouped[cat(b)].append(b)

        return {
            "id": page.get("id"),
            "title": page.get("title"),
            "insights": grouped,
        }
