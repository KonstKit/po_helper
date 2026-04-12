from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Artifact, ConfluencePage, Project, Task
from app.models.traceability import ConnectorConfig
from app.services.integration_config import get_connector_overrides

logger = logging.getLogger(__name__)


@dataclass
class TraceabilityArtifactSyncResult:
    created: int = 0
    updated: int = 0
    warnings: list[str] = field(default_factory=list)
    per_project: dict[int, dict[str, int]] = field(default_factory=dict)

    @property
    def artifact_delta(self) -> int:
        return self.created + self.updated

    @property
    def project_ids(self) -> list[int]:
        return sorted(self.per_project)

    def add_warning(self, warning: str) -> None:
        if warning and warning not in self.warnings:
            self.warnings.append(warning)

    def add_project_delta(self, project_id: int, *, created: int = 0, updated: int = 0) -> None:
        bucket = self.per_project.setdefault(project_id, {"created": 0, "updated": 0})
        bucket["created"] += created
        bucket["updated"] += updated
        self.created += created
        self.updated += updated

    def merge(self, other: "TraceabilityArtifactSyncResult") -> None:
        for warning in other.warnings:
            self.add_warning(warning)
        for project_id, bucket in other.per_project.items():
            self.add_project_delta(
                project_id,
                created=int(bucket.get("created", 0) or 0),
                updated=int(bucket.get("updated", 0) or 0),
            )


class TraceabilityArtifactSyncService:
    async def sync_jira_project_artifacts(
        self,
        db: AsyncSession,
        project_id: int,
        *,
        tasks: Optional[Sequence[Task]] = None,
        ingestion_run_id: Optional[str] = None,
        source_metadata: Optional[dict[str, Any]] = None,
    ) -> TraceabilityArtifactSyncResult:
        result = TraceabilityArtifactSyncResult()
        task_rows = list(tasks or [])
        if not task_rows:
            query = select(Task).where(Task.project_id == project_id).order_by(Task.id.asc())
            task_rows = list((await db.execute(query)).scalars().all())

        if not task_rows:
            result.add_warning(f"No Jira tasks found for project {project_id}")
            return result

        external_ids = [
            str(task.key or task.jira_id).strip()
            for task in task_rows
            if (task.key or task.jira_id)
        ]
        existing = await self._load_existing_artifacts(
            db,
            project_id=project_id,
            artifact_type="jira_issue",
            source="jira",
            external_ids=external_ids,
        )

        for task in task_rows:
            external_id = str(task.key or task.jira_id or "").strip()
            if not external_id:
                result.add_warning(
                    f"Skipped Jira task {task.id} in project {project_id}: missing key/jira_id"
                )
                continue

            artifact = existing.get(external_id)
            meta = self._merge_meta(
                artifact.meta if artifact else None,
                {
                    "jira_id": task.jira_id,
                    "summary": task.summary,
                    "description": task.description,
                    "task_type": task.task_type,
                    "priority": task.priority,
                    "assignee_email": task.assignee_email,
                    "assignee_name": task.assignee_name,
                    "reporter_email": task.reporter_email,
                    "reporter_name": task.reporter_name,
                    "estimate_hours": task.estimate_hours,
                    "spent_hours": task.spent_hours,
                    "remaining_hours": task.remaining_hours,
                    "is_blocker": task.is_blocker,
                    "blocked_by": task.blocked_by,
                    "blocks": task.blocks,
                    "labels": task.labels,
                    "components": task.components,
                    "updated_date": task.updated_date.isoformat() if task.updated_date else None,
                },
                source_metadata,
            )

            if artifact is None:
                artifact = Artifact(
                    project_id=project_id,
                    type="jira_issue",
                    source="jira",
                    external_id=external_id,
                    display_key=str(task.key or external_id),
                    title=task.summary,
                    status=task.status,
                    meta=meta,
                    source_system="jira",
                    source_reference_id=str(task.jira_id) if task.jira_id else None,
                    ingestion_run_id=ingestion_run_id,
                )
                db.add(artifact)
                existing[external_id] = artifact
                result.add_project_delta(project_id, created=1)
            else:
                artifact.display_key = str(task.key or external_id)
                artifact.title = task.summary
                artifact.status = task.status
                artifact.meta = meta
                artifact.source_system = "jira"
                artifact.source_reference_id = str(task.jira_id) if task.jira_id else None
                artifact.ingestion_run_id = ingestion_run_id
                result.add_project_delta(project_id, updated=1)

        if result.artifact_delta:
            await db.flush()

        return result

    async def sync_confluence_project_artifacts(
        self,
        db: AsyncSession,
        project_id: int,
        *,
        pages: Optional[Sequence[ConfluencePage]] = None,
        ingestion_run_id: Optional[str] = None,
        source_metadata: Optional[dict[str, Any]] = None,
    ) -> TraceabilityArtifactSyncResult:
        result = TraceabilityArtifactSyncResult()
        page_rows = list(pages or [])

        if not page_rows:
            space_keys = await self._project_confluence_space_keys(db, project_id)
            if not space_keys:
                result.add_warning(
                    f"Project {project_id} has no Confluence space mapping for artifact repair"
                )
                return result

            query = (
                select(ConfluencePage)
                .where(ConfluencePage.space_key.in_(sorted(space_keys)))
                .order_by(ConfluencePage.updated.desc(), ConfluencePage.confluence_id.asc())
            )
            page_rows = list((await db.execute(query)).scalars().all())

        if not page_rows:
            result.add_warning(f"No Confluence pages matched project {project_id}")
            return result

        external_ids = [
            str(page.confluence_id).strip()
            for page in page_rows
            if page.confluence_id
        ]
        existing = await self._load_existing_artifacts(
            db,
            project_id=project_id,
            artifact_type="confluence_page",
            source="confluence",
            external_ids=external_ids,
        )

        for page in page_rows:
            external_id = str(page.confluence_id or "").strip()
            if not external_id:
                result.add_warning(
                    f"Skipped Confluence page in project {project_id}: missing confluence_id"
                )
                continue

            artifact = existing.get(external_id)
            meta = self._merge_meta(
                artifact.meta if artifact else None,
                {
                    "space_key": page.space_key,
                    "page_type": page.page_type,
                    "version": page.version,
                    "labels": page.labels,
                    "body": page.html,
                    "updated": page.updated.isoformat() if page.updated else None,
                },
                source_metadata,
            )

            if artifact is None:
                artifact = Artifact(
                    project_id=project_id,
                    type="confluence_page",
                    source="confluence",
                    external_id=external_id,
                    display_key=external_id,
                    title=page.title,
                    status=None,
                    url=page.url,
                    meta=meta,
                    source_system="confluence",
                    source_reference_id=external_id,
                    ingestion_run_id=ingestion_run_id,
                )
                db.add(artifact)
                existing[external_id] = artifact
                result.add_project_delta(project_id, created=1)
            else:
                artifact.display_key = external_id
                artifact.title = page.title
                artifact.url = page.url
                artifact.meta = meta
                artifact.source_system = "confluence"
                artifact.source_reference_id = external_id
                artifact.ingestion_run_id = ingestion_run_id
                result.add_project_delta(project_id, updated=1)

        if result.artifact_delta:
            await db.flush()

        return result

    async def sync_confluence_page_artifacts(
        self,
        db: AsyncSession,
        page: ConfluencePage,
        *,
        ingestion_run_id: Optional[str] = None,
        source_metadata: Optional[dict[str, Any]] = None,
    ) -> TraceabilityArtifactSyncResult:
        result = TraceabilityArtifactSyncResult()
        project_ids = await self._infer_projects_for_confluence_page(db, page)
        if not project_ids:
            result.add_warning(
                f"No project mapping found for Confluence page {page.confluence_id} (space={page.space_key})"
            )
            return result

        for project_id in project_ids:
            project_result = await self.sync_confluence_project_artifacts(
                db,
                project_id,
                pages=[page],
                ingestion_run_id=ingestion_run_id,
                source_metadata=source_metadata,
            )
            result.merge(project_result)

        return result

    async def _load_existing_artifacts(
        self,
        db: AsyncSession,
        *,
        project_id: int,
        artifact_type: str,
        source: str,
        external_ids: Iterable[str],
    ) -> dict[str, Artifact]:
        identifiers = sorted({external_id for external_id in external_ids if external_id})
        if not identifiers:
            return {}

        query = (
            select(Artifact)
            .where(
                Artifact.project_id == project_id,
                Artifact.type == artifact_type,
                Artifact.source == source,
                Artifact.version == 1,
                Artifact.external_id.in_(identifiers),
            )
            .order_by(Artifact.id.asc())
        )
        rows = (await db.execute(query)).scalars().all()
        return {artifact.external_id: artifact for artifact in rows}

    async def _project_confluence_space_keys(
        self,
        db: AsyncSession,
        project_id: int,
    ) -> set[str]:
        keys: set[str] = set()
        project = await db.get(Project, project_id)
        if project and project.jira_key:
            keys.add(str(project.jira_key))

        overrides = await get_connector_overrides(db, project_id, "confluence")
        if overrides and overrides.enabled:
            keys.update(self._extract_space_keys(overrides.settings))

        return {key for key in keys if key}

    async def _infer_projects_for_confluence_page(
        self,
        db: AsyncSession,
        page: ConfluencePage,
    ) -> list[int]:
        if not page.space_key:
            return []

        project_ids: set[int] = set()

        project_result = await db.execute(
            select(Project.id).where(Project.jira_key == page.space_key)
        )
        project_ids.update(int(project_id) for project_id in project_result.scalars().all())

        connector_result = await db.execute(
            select(ConnectorConfig).where(
                ConnectorConfig.provider == "confluence",
                ConnectorConfig.is_enabled.is_(True),
                ConnectorConfig.project_id.is_not(None),
            )
        )
        for connector in connector_result.scalars().all():
            if connector.project_id is None:
                continue
            if page.space_key in self._extract_space_keys(connector.settings_json or {}):
                project_ids.add(int(connector.project_id))

        return sorted(project_ids)

    def _extract_space_keys(self, settings_json: dict[str, Any]) -> set[str]:
        keys: set[str] = set()
        for candidate_key in ("space_key", "space", "spaceKey"):
            value = settings_json.get(candidate_key)
            if isinstance(value, str) and value.strip():
                keys.add(value.strip())
            elif isinstance(value, list):
                keys.update(
                    str(item).strip() for item in value if str(item).strip()
                )
        return keys

    def _merge_meta(self, *parts: Optional[dict[str, Any]]) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for part in parts:
            if not isinstance(part, dict):
                continue
            for key, value in part.items():
                if value is not None:
                    merged[key] = value
        return merged


artifact_sync_service = TraceabilityArtifactSyncService()


def get_traceability_artifact_sync_service() -> TraceabilityArtifactSyncService:
    return artifact_sync_service
