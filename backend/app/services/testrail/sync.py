from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_str
from app.models.settings import IntegrationSetting
from app.models.traceability import Artifact, SyncState
from app.services.integration_config import get_connector_overrides
from app.services.sync_tracking import (
    finish_sync_task,
    get_or_create_source,
    start_sync_task,
    upsert_sync_state,
)
from app.services.testrail.client import TestRailClient
from app.utils import execute_with_lock, transactional_session, parse_datetime

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 90


@dataclass
class TestRailSyncResult:
    cases_created: int = 0
    cases_updated: int = 0
    runs_created: int = 0
    runs_updated: int = 0
    results_created: int = 0
    results_updated: int = 0
    cases_scanned: int = 0
    runs_scanned: int = 0
    results_scanned: int = 0
    errors: List[Tuple[str, str]] = field(default_factory=list)
    cursor_in: Optional[int] = None
    cursor_out: Optional[int] = None


class TestRailSyncService:
    """Sync TestRail cases and results into traceability artifacts."""

    def __init__(self, client: TestRailClient, override_settings: Optional[Dict[str, Any]] = None):
        self.client = client
        self.override_settings = override_settings or {}

    @classmethod
    async def from_settings(
        cls,
        db: AsyncSession,
        project_id: Optional[int],
    ) -> Tuple["TestRailSyncService", Dict[str, Any]]:
        settings_row = await _load_testrail_settings(db)
        overrides = await get_connector_overrides(db, project_id, "testrail")
        if overrides and not overrides.enabled:
            raise ValueError("TestRail connector is disabled for this project")

        override_settings = overrides.settings if overrides else {}
        base_url = str(
            override_settings.get("base_url") or (settings_row.base_url if settings_row else "")
        ).strip()
        email = str(
            override_settings.get("email") or (settings_row.email if settings_row else "")
        ).strip()

        token = None
        if override_settings.get("api_token") or override_settings.get("token"):
            token = str(override_settings.get("api_token") or override_settings.get("token"))
        elif settings_row and settings_row.api_token:
            token = decrypt_str(settings_row.api_token)

        if not base_url or not email or not token:
            raise ValueError("TestRail settings are incomplete (base_url/email/token required)")

        client = TestRailClient(
            base_url=base_url,
            email=email,
            api_token=token,
            timeout_seconds=_as_int(override_settings.get("request_timeout_seconds")),
            max_retries=_as_int(override_settings.get("max_retries")),
            backoff_base_seconds=_as_float(override_settings.get("backoff_base_seconds")),
            backoff_max_seconds=_as_float(override_settings.get("backoff_max_seconds")),
            retry_after_header=_as_bool(
                override_settings.get("retry_after_header"), default=True
            ),
        )
        return cls(client, override_settings=override_settings), override_settings

    async def sync_project(
        self,
        db: AsyncSession,
        *,
        project_id: Optional[int],
        testrail_project_id: Optional[int] = None,
        suite_ids: Optional[List[int]] = None,
        cursor: Optional[int] = None,
        lookback_days: Optional[int] = DEFAULT_LOOKBACK_DAYS,
        trigger: Optional[str] = "manual",
    ) -> TestRailSyncResult:
        if testrail_project_id is None:
            testrail_project_id = _as_int(self.override_settings.get("testrail_project_id"))
        if testrail_project_id is None:
            raise ValueError("testrail_project_id is required for TestRail sync")

        if suite_ids is None:
            suite_ids = _extract_suite_ids(self.override_settings)

        result = TestRailSyncResult()
        sync_task_id: Optional[int] = None
        sync_source_id: Optional[int] = None
        cursor_in = cursor

        try:
            source = await get_or_create_source(
                db,
                provider="testrail",
                project_id=project_id,
                base_url=self.client.base_url,
                settings={"testrail_project_id": testrail_project_id},
            )
            sync_source_id = source.id

            if cursor_in is None:
                cursor_in = await _load_sync_cursor(db, sync_source_id, project_id)

            if cursor_in is None and lookback_days is not None:
                cursor_in = int(
                    (datetime.now(timezone.utc) - timedelta(days=lookback_days)).timestamp()
                )

            result.cursor_in = cursor_in

            task = await start_sync_task(
                db,
                task_type="testrail_sync",
                project_id=project_id,
                source_id=sync_source_id,
                trigger=trigger,
                cursor_in=str(cursor_in) if cursor_in is not None else None,
            )
            sync_task_id = task.id

            await self._sync_cases(
                db,
                testrail_project_id,
                project_id=project_id,
                suite_ids=suite_ids,
                updated_after=cursor_in,
                result=result,
            )

            await self._sync_runs_and_results(
                db,
                testrail_project_id,
                project_id=project_id,
                updated_after=cursor_in,
                result=result,
            )

            status = "success"
            error_message = None
        except Exception as exc:
            logger.exception("TestRail sync failed: %s", exc)
            result.errors.append(("sync", str(exc)))
            status = "failed"
            error_message = str(exc)

        try:
            cursor_out = result.cursor_out or cursor_in
            item_counts = {
                "cases_created": result.cases_created,
                "cases_updated": result.cases_updated,
                "runs_created": result.runs_created,
                "runs_updated": result.runs_updated,
                "results_created": result.results_created,
                "results_updated": result.results_updated,
                "cases_scanned": result.cases_scanned,
                "runs_scanned": result.runs_scanned,
                "results_scanned": result.results_scanned,
                "errors": len(result.errors),
            }

            async with transactional_session(db):
                if sync_task_id is not None:
                    await finish_sync_task(
                        db,
                        sync_task_id,
                        status=status,
                        item_counts=item_counts,
                        error_message=error_message,
                        cursor_out=str(cursor_out) if cursor_out is not None else None,
                    )

                if sync_source_id is not None:
                    lag_seconds = None
                    if cursor_out is not None:
                        lag_seconds = max(
                            0.0,
                            datetime.now(timezone.utc).timestamp() - float(cursor_out),
                        )
                    await upsert_sync_state(
                        db,
                        source_id=sync_source_id,
                        project_id=project_id,
                        last_cursor=str(cursor_out) if cursor_out is not None else None,
                        last_event_id=str(cursor_out) if cursor_out is not None else None,
                        lag_seconds=lag_seconds,
                    )
        except Exception as exc:
            logger.warning("Failed to finalize TestRail sync tracking: %s", exc)

        return result

    async def _sync_cases(
        self,
        db: AsyncSession,
        testrail_project_id: int,
        *,
        project_id: Optional[int],
        suite_ids: Optional[List[int]],
        updated_after: Optional[int],
        result: TestRailSyncResult,
    ) -> None:
        case_batches = await _fetch_cases(
            self.client,
            testrail_project_id,
            suite_ids=suite_ids,
            updated_after=updated_after,
        )
        if not case_batches:
            return

        async with transactional_session(db):
            for case in case_batches:
                case_id = _as_int(case.get("id"))
                if case_id is None:
                    continue

                result.cases_scanned += 1
                cursor_ts = _extract_timestamp(case.get("updated_on")) or _extract_timestamp(
                    case.get("created_on")
                )
                _update_cursor(result, cursor_ts)

                created = await _upsert_artifact(
                    db,
                    artifact_type="testrail_case",
                    source="testrail",
                    external_id=str(case_id),
                    project_id=project_id,
                    display_key=f"C{case_id}",
                    title=case.get("title"),
                    status="deleted" if case.get("is_deleted") else "active",
                    url=_testrail_url(self.client.base_url, "cases", case_id),
                    meta=_case_meta(case, testrail_project_id),
                )
                if created:
                    result.cases_created += 1
                else:
                    result.cases_updated += 1

    async def _sync_runs_and_results(
        self,
        db: AsyncSession,
        testrail_project_id: int,
        *,
        project_id: Optional[int],
        updated_after: Optional[int],
        result: TestRailSyncResult,
    ) -> None:
        runs = await self.client.get_runs(testrail_project_id)
        if not runs:
            return

        case_titles = await _load_case_titles(db, project_id=project_id, source="testrail")

        for run in runs:
            run_id = _as_int(run.get("id"))
            if run_id is None:
                continue

            run_updated = _extract_timestamp(run.get("updated_on")) or _extract_timestamp(
                run.get("created_on")
            )
            if updated_after is not None and run_updated is not None and run_updated <= updated_after:
                continue

            result.runs_scanned += 1
            _update_cursor(result, run_updated)

            async with transactional_session(db):
                created = await _upsert_artifact(
                    db,
                    artifact_type="testrail_run",
                    source="testrail",
                    external_id=str(run_id),
                    project_id=project_id,
                    display_key=f"R{run_id}",
                    title=run.get("name"),
                    status="completed" if run.get("is_completed") else "active",
                    url=_testrail_url(self.client.base_url, "runs", run_id),
                    meta=_run_meta(run, testrail_project_id),
                )
                if created:
                    result.runs_created += 1
                else:
                    result.runs_updated += 1

            results = await self.client.get_results(run_id)
            if not results:
                continue

            async with transactional_session(db):
                for res in results:
                    res_id = _as_int(res.get("id"))
                    if res_id is None:
                        continue
                    res_created = _extract_timestamp(res.get("created_on"))
                    if (
                        updated_after is not None
                        and res_created is not None
                        and res_created <= updated_after
                    ):
                        continue

                    result.results_scanned += 1
                    _update_cursor(result, res_created)

                    case_id = _as_int(res.get("case_id"))
                    title = None
                    if case_id is not None:
                        title = case_titles.get(case_id)
                    if not title:
                        title = f"TestRail result {res_id}"

                    created = await _upsert_artifact(
                        db,
                        artifact_type="testrail_test",
                        source="testrail",
                        external_id=str(res_id),
                        project_id=project_id,
                        display_key=f"T{res_id}",
                        title=title,
                        status=_as_str(res.get("status_id")),
                        url=_testrail_url(self.client.base_url, "tests", res.get("test_id")),
                        meta=_result_meta(res, run_id, testrail_project_id),
                    )
                    if created:
                        result.results_created += 1
                    else:
                        result.results_updated += 1


async def _load_testrail_settings(db: AsyncSession) -> Optional[IntegrationSetting]:
    res = await db.execute(
        select(IntegrationSetting).where(IntegrationSetting.kind == "testrail")
    )
    return res.scalar_one_or_none()


async def _load_sync_cursor(
    db: AsyncSession,
    source_id: Optional[int],
    project_id: Optional[int],
) -> Optional[int]:
    filters = []
    if source_id is None:
        filters.append(SyncState.source_id.is_(None))
    else:
        filters.append(SyncState.source_id == source_id)
    if project_id is None:
        filters.append(SyncState.project_id.is_(None))
    else:
        filters.append(SyncState.project_id == project_id)

    res = await db.execute(select(SyncState).where(*filters))
    state = res.scalar_one_or_none()
    if state and state.last_cursor:
        return _parse_cursor(state.last_cursor)
    return None


async def _fetch_cases(
    client: TestRailClient,
    testrail_project_id: int,
    *,
    suite_ids: Optional[List[int]],
    updated_after: Optional[int],
) -> List[Dict[str, Any]]:
    if suite_ids is None:
        suites = await client.get_suites(testrail_project_id)
        suite_ids = [_as_int(suite.get("id")) for suite in suites if _as_int(suite.get("id"))]

    cases: List[Dict[str, Any]] = []
    if suite_ids:
        for suite_id in suite_ids:
            cases.extend(
                await client.get_cases(
                    testrail_project_id,
                    suite_id=suite_id,
                    updated_after=updated_after,
                )
            )
    else:
        cases.extend(
            await client.get_cases(testrail_project_id, updated_after=updated_after, suite_id=None)
        )
    return cases


async def _load_case_titles(
    db: AsyncSession,
    *,
    project_id: Optional[int],
    source: str,
) -> Dict[int, str]:
    filters = [Artifact.type == "testrail_case", Artifact.source == source]
    if project_id is None:
        filters.append(Artifact.project_id.is_(None))
    else:
        filters.append(Artifact.project_id == project_id)

    res = await db.execute(select(Artifact.external_id, Artifact.title).where(*filters))
    mapping: Dict[int, str] = {}
    for external_id, title in res.all():
        if external_id and title:
            parsed = _as_int(external_id)
            if parsed is not None:
                mapping[parsed] = title
    return mapping


async def _upsert_artifact(
    db: AsyncSession,
    *,
    artifact_type: str,
    source: str,
    external_id: str,
    project_id: Optional[int],
    display_key: Optional[str],
    title: Optional[str],
    status: Optional[str],
    url: Optional[str],
    meta: Dict[str, Any],
) -> bool:
    sel = select(Artifact).where(
        Artifact.type == artifact_type,
        Artifact.source == source,
        Artifact.external_id == external_id,
    )
    if project_id is None:
        sel = sel.where(Artifact.project_id.is_(None))
    else:
        sel = sel.where(Artifact.project_id == project_id)
    artifact = (await execute_with_lock(db, sel)).scalar_one_or_none()
    created = False
    if artifact is None:
        artifact = Artifact(type=artifact_type, source=source, external_id=external_id)
        db.add(artifact)
        created = True

    if project_id is not None and artifact.project_id != project_id:
        artifact.project_id = project_id
    if display_key is not None:
        artifact.display_key = display_key
    if title is not None:
        artifact.title = title
    if status is not None:
        artifact.status = status
    if url is not None:
        artifact.url = url

    _merge_meta(artifact, meta)
    return created


def _merge_meta(artifact: Artifact, extra: Dict[str, Any]) -> None:
    merged = dict(artifact.meta or {})
    for key, value in extra.items():
        if value is not None:
            merged[key] = value
    artifact.meta = merged


def _case_meta(case: Dict[str, Any], testrail_project_id: int) -> Dict[str, Any]:
    status = "deleted" if case.get("is_deleted") else "active"
    meta: Dict[str, Any] = {
        "testrail_project_id": testrail_project_id,
        "suite_id": case.get("suite_id"),
        "section_id": case.get("section_id"),
        "template_id": case.get("template_id"),
        "type_id": case.get("type_id"),
        "priority_id": case.get("priority_id"),
        "created_on": case.get("created_on"),
        "updated_on": case.get("updated_on"),
        "estimate": case.get("estimate"),
        "estimate_forecast": case.get("estimate_forecast"),
        "refs": case.get("refs"),
        "status": status,
    }
    meta["custom_fields"] = {
        key: value for key, value in case.items() if key.startswith("custom_")
    }
    return meta


def _run_meta(run: Dict[str, Any], testrail_project_id: int) -> Dict[str, Any]:
    status = "completed" if run.get("is_completed") else "active"
    return {
        "testrail_project_id": testrail_project_id,
        "suite_id": run.get("suite_id"),
        "plan_id": run.get("plan_id"),
        "milestone_id": run.get("milestone_id"),
        "created_on": run.get("created_on"),
        "updated_on": run.get("updated_on"),
        "passed_count": run.get("passed_count"),
        "blocked_count": run.get("blocked_count"),
        "untested_count": run.get("untested_count"),
        "retest_count": run.get("retest_count"),
        "failed_count": run.get("failed_count"),
        "custom_status_counts": _custom_status_counts(run),
        "status": status,
    }


def _result_meta(res: Dict[str, Any], run_id: int, testrail_project_id: int) -> Dict[str, Any]:
    status = _as_str(res.get("status_id"))
    meta = {
        "testrail_project_id": testrail_project_id,
        "run_id": run_id,
        "case_id": res.get("case_id"),
        "test_id": res.get("test_id"),
        "status_id": res.get("status_id"),
        "status": status,
        "created_on": res.get("created_on"),
        "created_by": res.get("created_by"),
        "assignedto_id": res.get("assignedto_id"),
        "version": res.get("version"),
        "comment": res.get("comment"),
        "defects": res.get("defects"),
        "elapsed": res.get("elapsed"),
    }
    meta["custom_fields"] = {key: value for key, value in res.items() if key.startswith("custom_")}
    return meta


def _custom_status_counts(run: Dict[str, Any]) -> Dict[str, Any]:
    counts: Dict[str, Any] = {}
    for key, value in run.items():
        if key.startswith("custom_status") and key.endswith("_count"):
            counts[key] = value
    return counts


def _testrail_url(base_url: str, kind: str, entity_id: Optional[int | str]) -> Optional[str]:
    if not base_url or entity_id is None:
        return None
    normalized = base_url.rstrip("/")
    return f"{normalized}/index.php?/{kind}/view/{entity_id}"


def _parse_cursor(raw: str) -> Optional[int]:
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        dt = parse_datetime(raw)
        if dt:
            return int(dt.replace(tzinfo=timezone.utc).timestamp())
    return None


def _extract_timestamp(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    dt = parse_datetime(value)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _update_cursor(result: TestRailSyncResult, ts: Optional[int]) -> None:
    if ts is None:
        return
    if result.cursor_out is None or ts > result.cursor_out:
        result.cursor_out = ts


def _as_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _as_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _extract_suite_ids(settings: Dict[str, Any]) -> Optional[List[int]]:
    raw = settings.get("testrail_suite_ids") or settings.get("suite_ids")
    if raw is None:
        return None
    if isinstance(raw, list):
        values = raw
    else:
        values = [val.strip() for val in str(raw).split(",")]
    ids = [_as_int(val) for val in values]
    return [val for val in ids if val is not None] or None
