from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.traceability import Artifact, ArtifactLink
from app.services.git import parse_jira_keys_from_text
from app.services.integration_config import get_connector_overrides
from app.utils import execute_with_lock, transactional_session

COMMIT_RE = re.compile(r"\b[a-f0-9]{7,40}\b", re.IGNORECASE)


@dataclass
class TestRailLinkResult:
    cases_scanned: int = 0
    cases_linked: int = 0
    case_links_created: int = 0
    results_scanned: int = 0
    results_linked: int = 0
    result_links_created: int = 0
    errors: List[Tuple[str, str]] = field(default_factory=list)


class TestRailLinker:
    """Link TestRail artifacts to Jira issues and commits."""

    def __init__(self, settings: Optional[Dict[str, Any]] = None) -> None:
        self.settings = settings or {}
        self.jira_fields = _extract_field_names(
            self.settings,
            single_key="testrail_jira_key_field",
            list_key="testrail_jira_key_fields",
            default=["refs"],
        )
        self.commit_fields = _extract_field_names(
            self.settings,
            single_key="testrail_commit_field",
            list_key="testrail_commit_fields",
            default=["refs", "comment", "defects", "version", "run.refs", "run.name"],
        )

    @classmethod
    async def from_settings(
        cls,
        db: AsyncSession,
        project_id: Optional[int],
    ) -> "TestRailLinker":
        overrides = await get_connector_overrides(db, project_id, "testrail")
        if overrides and not overrides.enabled:
            raise ValueError("TestRail connector is disabled for this project")
        return cls(settings=(overrides.settings if overrides else {}))

    async def link_project(
        self,
        db: AsyncSession,
        *,
        project_id: Optional[int],
    ) -> TestRailLinkResult:
        result = TestRailLinkResult()
        await self._link_cases_to_jira(db, project_id=project_id, result=result)
        await self._link_results_to_commits(db, project_id=project_id, result=result)
        return result

    async def _link_cases_to_jira(
        self,
        db: AsyncSession,
        *,
        project_id: Optional[int],
        result: TestRailLinkResult,
    ) -> None:
        cases = await _load_testrail_artifacts(db, "testrail_case", project_id)
        if not cases:
            return

        case_keys: Dict[int, List[str]] = {}
        all_keys: List[str] = []

        for case in cases:
            result.cases_scanned += 1
            keys = _extract_jira_keys_from_case(case, self.jira_fields)
            if not keys:
                continue
            case_keys[case.id] = keys
            all_keys.extend(keys)

        unique_keys = sorted(set(all_keys))
        if not unique_keys:
            return

        issues = await _load_jira_issues(db, unique_keys, project_id)
        if not issues:
            return

        issue_map = {issue.external_id: issue for issue in issues if issue.external_id}

        async with transactional_session(db):
            for case in cases:
                keys = case_keys.get(case.id)
                if not keys:
                    continue
                linked_any = False
                for key in keys:
                    issue = issue_map.get(key)
                    if issue is None:
                        continue
                    created = await _ensure_link(
                        db,
                        source=case,
                        target=issue,
                        link_type="tests",
                        confidence=0.9,
                        factors={"source": "testrail", "field": ",".join(self.jira_fields)},
                        created_via="sync",
                        source_system="testrail",
                        source_reference_id=key,
                    )
                    if created:
                        result.case_links_created += 1
                    linked_any = linked_any or created
                if linked_any:
                    result.cases_linked += 1

    async def _link_results_to_commits(
        self,
        db: AsyncSession,
        *,
        project_id: Optional[int],
        result: TestRailLinkResult,
    ) -> None:
        tests = await _load_testrail_artifacts(db, "testrail_test", project_id)
        if not tests:
            return

        runs = await _load_testrail_runs(db, project_id)
        run_map = {run.external_id: run for run in runs if run.external_id}

        test_commits: Dict[int, List[str]] = {}
        all_shas: List[str] = []

        for test in tests:
            result.results_scanned += 1
            run_id = _as_str((test.meta or {}).get("run_id"))
            run = run_map.get(run_id)
            commits = _extract_commits_from_test(
                test,
                run,
                self.commit_fields,
            )
            if not commits:
                continue
            test_commits[test.id] = commits
            all_shas.extend(commits)

        unique_shas = sorted(set(all_shas))
        if not unique_shas:
            return

        commit_map = await _load_commits(db, unique_shas, project_id)
        if not commit_map:
            return

        async with transactional_session(db):
            for test in tests:
                shas = test_commits.get(test.id)
                if not shas:
                    continue
                linked_any = False
                for sha in shas:
                    commits = commit_map.get(sha) or []
                    for commit in commits:
                        created = await _ensure_link(
                            db,
                            source=test,
                            target=commit,
                            link_type="tests",
                            confidence=0.85,
                            factors={"source": "testrail", "field": ",".join(self.commit_fields)},
                            created_via="sync",
                            source_system="testrail",
                            source_reference_id=sha,
                        )
                        if created:
                            result.result_links_created += 1
                        linked_any = linked_any or created
                if linked_any:
                    result.results_linked += 1


async def _load_testrail_artifacts(
    db: AsyncSession,
    artifact_type: str,
    project_id: Optional[int],
) -> List[Artifact]:
    stmt = select(Artifact).where(
        Artifact.type == artifact_type,
        Artifact.source == "testrail",
    )
    if project_id is not None:
        stmt = stmt.where(Artifact.project_id == project_id)
    return (await db.execute(stmt)).scalars().all()


async def _load_testrail_runs(
    db: AsyncSession,
    project_id: Optional[int],
) -> List[Artifact]:
    return await _load_testrail_artifacts(db, "testrail_run", project_id)


async def _load_jira_issues(
    db: AsyncSession,
    keys: Sequence[str],
    project_id: Optional[int],
) -> List[Artifact]:
    if not keys:
        return []
    stmt = select(Artifact).where(
        Artifact.type == "jira_issue",
        Artifact.external_id.in_(list(keys)),
    )
    if project_id is not None:
        stmt = stmt.where(Artifact.project_id == project_id)
    return (await db.execute(stmt)).scalars().all()


async def _load_commits(
    db: AsyncSession,
    shas: Sequence[str],
    project_id: Optional[int],
) -> Dict[str, List[Artifact]]:
    if not shas:
        return {}
    stmt = select(Artifact).where(
        Artifact.type == "commit",
        Artifact.external_id.in_(list(shas)),
    )
    if project_id is not None:
        stmt = stmt.where(Artifact.project_id == project_id)
    commits = (await db.execute(stmt)).scalars().all()
    commit_map: Dict[str, List[Artifact]] = {}
    for commit in commits:
        if not commit.external_id:
            continue
        commit_map.setdefault(commit.external_id, []).append(commit)
    return commit_map


async def _ensure_link(
    db: AsyncSession,
    *,
    source: Artifact,
    target: Artifact,
    link_type: str,
    confidence: float,
    factors: Dict[str, Any],
    created_via: Optional[str],
    source_system: Optional[str],
    source_reference_id: Optional[str],
) -> bool:
    if target.project_id and source.project_id is None:
        source.project_id = target.project_id
    if target.tenant_id and source.tenant_id is None:
        source.tenant_id = target.tenant_id

    sel = select(ArtifactLink).where(
        ArtifactLink.from_artifact_id == source.id,
        ArtifactLink.to_artifact_id == target.id,
        ArtifactLink.link_type == link_type,
    )
    existing = (await execute_with_lock(db, sel)).scalar_one_or_none()
    if existing:
        return False

    link = ArtifactLink(
        from_artifact_id=source.id,
        to_artifact_id=target.id,
        link_type=link_type,
        confidence=confidence,
        confidence_factors=factors,
        created_via=created_via,
        source_system=source_system,
        source_reference_id=source_reference_id,
        project_id=target.project_id,
        tenant_id=target.tenant_id,
    )
    db.add(link)
    return True


def _extract_jira_keys_from_case(case: Artifact, fields: Sequence[str]) -> List[str]:
    meta = case.meta or {}
    texts = _collect_field_texts(meta, fields)
    combined = " ".join(texts)
    return parse_jira_keys_from_text(combined)


def _extract_commits_from_test(
    test: Artifact,
    run: Optional[Artifact],
    fields: Sequence[str],
) -> List[str]:
    meta = test.meta or {}
    run_meta = run.meta if run else {}
    run_title = run.title if run else None
    texts = _collect_commit_texts(meta, run_meta, run_title, fields)
    combined = " ".join(texts)
    return sorted(set(match.lower() for match in COMMIT_RE.findall(combined)))


def _collect_commit_texts(
    meta: Dict[str, Any],
    run_meta: Optional[Dict[str, Any]],
    run_title: Optional[str],
    fields: Sequence[str],
) -> List[str]:
    values: List[str] = []
    for field_name in fields:
        if field_name.startswith("run."):
            run_field = field_name.split(".", 1)[1]
            if run_field in {"title", "name"} and run_title:
                values.append(run_title)
                continue
            value = _extract_field_value(run_meta or {}, run_field)
        else:
            value = _extract_field_value(meta, field_name)
        if value is not None:
            values.append(_normalize_text(value))
    return values


def _collect_field_texts(meta: Dict[str, Any], fields: Sequence[str]) -> List[str]:
    values: List[str] = []
    for field_name in fields:
        value = _extract_field_value(meta, field_name)
        if value is not None:
            values.append(_normalize_text(value))
    return values


def _extract_field_value(meta: Dict[str, Any], field: str) -> Any:
    if field in meta:
        return meta.get(field)
    custom_fields = meta.get("custom_fields") or {}
    if field in custom_fields:
        return custom_fields.get(field)
    if field.startswith("custom."):
        key = field.split(".", 1)[1]
        return custom_fields.get(key)
    if field.startswith("custom_"):
        return custom_fields.get(field)
    return None


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return " ".join(_normalize_text(item) for item in value if item is not None)
    if isinstance(value, dict):
        return " ".join(_normalize_text(item) for item in value.values() if item is not None)
    return str(value)


def _extract_field_names(
    settings: Dict[str, Any],
    *,
    single_key: str,
    list_key: str,
    default: Sequence[str],
) -> List[str]:
    raw = settings.get(list_key)
    if raw is None:
        raw = settings.get(single_key)
    if raw is None:
        return list(default)
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    return [item.strip() for item in str(raw).split(",") if item.strip()]


def _as_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value)
