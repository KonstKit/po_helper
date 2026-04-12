"""Git integration import service.
Fetches commits and pull requests from configured repositories and upserts
traceability artifacts linking them to Jira issues.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core.crypto import decrypt_str
from app.models import IntegrationSetting, Repository
from app.services.integration_config import get_connector_overrides_map
from app.services.traceability.post_sync import run_traceability_post_sync
from app.services.repository_resolver import repository_resolver
from app.services.git.webhook_processor import process_commits, process_pull_request

logger = logging.getLogger(__name__)

COMMITS_PER_SYNC = 50
PRS_PER_SYNC = 50


@dataclass
class ProviderConfig:
    provider: str
    api_base: str
    token: Optional[str]
    extra: Dict[str, Any]

    @property
    def headers(self) -> Dict[str, str]:
        if self.provider == "gitlab":
            return {"PRIVATE-TOKEN": self.token or ""}
        if self.provider == "github":
            headers = {
                "Accept": "application/vnd.github+json",
            }
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            return headers
        return {}


class GitImportService:
    """Service for importing commits and pull requests for project repositories."""

    def __init__(self) -> None:
        self._session: Optional[requests.Session] = None

    def _get_session(self) -> requests.Session:
        """Get or create requests session with proper lifecycle management."""
        if self._session is None:
            self._session = requests.Session()
        return self._session

    def _request_with_retry(
        self, url: str, *, headers: Dict[str, str], params: Dict[str, Any]
    ) -> requests.Response:
        max_retries = settings.INTEGRATION_HTTP_MAX_RETRIES
        backoff_base = settings.INTEGRATION_HTTP_BACKOFF_SECONDS
        backoff_max = settings.INTEGRATION_HTTP_BACKOFF_MAX_SECONDS
        timeout = settings.INTEGRATION_HTTP_TIMEOUT
        attempts = max_retries + 1

        last_exc: Optional[Exception] = None
        for attempt in range(attempts):
            try:
                resp = self._get_session().get(url, headers=headers, params=params, timeout=timeout)
                if resp.status_code >= 500 and attempt < attempts - 1:
                    delay = min(backoff_base * (2**attempt), backoff_max)
                    logger.warning(
                        "Git request failed (%s) retry %d/%d in %.1fs: %s",
                        resp.status_code,
                        attempt + 1,
                        attempts - 1,
                        delay,
                        url,
                    )
                    time.sleep(delay)
                    continue
                return resp
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_exc = exc
                if attempt >= attempts - 1:
                    raise
                delay = min(backoff_base * (2**attempt), backoff_max)
                logger.warning(
                    "Git request error (%s) retry %d/%d in %.1fs: %s",
                    exc.__class__.__name__,
                    attempt + 1,
                    attempts - 1,
                    delay,
                    url,
                )
                time.sleep(delay)

        if last_exc:
            raise last_exc
        raise RuntimeError("Unexpected request retry loop exit")

    async def _session_get(self, url: str, **kwargs) -> requests.Response:
        """Run session.get in a worker thread to avoid blocking the event loop."""
        return await asyncio.to_thread(self._get_session().get, url, **kwargs)

    def close(self) -> None:
        """Close the session and cleanup resources."""
        if self._session:
            self._session.close()
            self._session = None

    def __del__(self) -> None:
        """Ensure session is closed on deletion."""
        self.close()

    async def sync_project(
        self,
        db: AsyncSession,
        project_id: int,
        include_commits: bool = True,
        include_pull_requests: bool = True,
        trigger: str | None = "manual",
    ) -> Dict[str, Any]:
        repositories = await repository_resolver.get_all_repositories(project_id, db)
        results: List[Dict[str, Any]] = []

        if not repositories:
            logger.info("No repositories linked to project %s", project_id)
            return {"project_id": project_id, "repositories": []}

        # OPTIMIZED: Pre-fetch provider configs to avoid N+1 queries
        unique_providers = {(repo.provider or "").lower() for repo in repositories}
        valid_providers = unique_providers & {"github", "gitlab"}
        provider_configs = await self._get_all_provider_configs(db, project_id, valid_providers)

        for repo in repositories:
            provider = (repo.provider or "").lower()
            if provider not in {"github", "gitlab"}:
                logger.warning(
                    "Skipping repository %s with unsupported provider %s",
                    repo.repo_slug,
                    provider,
                )
                continue

            config = provider_configs.get(provider)
            if not config or not config.token:
                logger.warning(
                    "Provider %s is not fully configured; skipping repository",
                    provider,
                )
                continue

            default_branch = await self._ensure_default_branch(db, repo, config)
            repo_stats: Dict[str, Any] = {
                "repository_id": repo.id,
                "provider": provider,
                "repo_slug": repo.repo_slug,
                "default_branch": default_branch,
            }

            if include_commits:
                commit_stats = await self._sync_commits(
                    db, repo, config, default_branch, trigger=trigger
                )
                repo_stats["commits"] = commit_stats

            if include_pull_requests:
                pr_stats = await self._sync_pull_requests(db, repo, config, trigger=trigger)
                repo_stats["pull_requests"] = pr_stats

            results.append(repo_stats)

        artifact_delta = 0
        for repo_result in results:
            commits = repo_result.get("commits") or {}
            pull_requests = repo_result.get("pull_requests") or {}
            artifact_delta += int(commits.get("created", 0) or 0)
            artifact_delta += int(commits.get("updated", 0) or 0)
            artifact_delta += int(pull_requests.get("processed", 0) or 0)

        if artifact_delta > 0:
            await run_traceability_post_sync(
                project_id,
                artifact_delta=artifact_delta,
                source="git_import",
                trigger=trigger,
            )

        return {"project_id": project_id, "repositories": results}

    async def _get_provider_config(
        self,
        db: AsyncSession,
        provider: str,
    ) -> Optional[ProviderConfig]:
        res = await db.execute(
            select(IntegrationSetting).where(IntegrationSetting.kind == provider)
        )
        row = res.scalar_one_or_none()
        if not row or not row.api_token:
            return None

        decrypted = decrypt_str(row.api_token)
        token: Optional[str] = None
        extra: Dict[str, Any] = {}

        if decrypted:
            try:
                bundle = json.loads(decrypted)
                token = bundle.get("api_token") or bundle.get("token")
                extra.update(bundle)
            except (json.JSONDecodeError, TypeError):
                token = decrypted

        base_url = (row.base_url or "").strip()

        if provider == "github":
            api_base = base_url or "https://api.github.com"
            api_base = api_base.rstrip("/")
            return ProviderConfig(provider="github", api_base=api_base, token=token, extra=extra)

        if provider == "gitlab":
            api_base = base_url or "https://gitlab.com"
            api_base = api_base.rstrip("/") + "/api/v4"
            logger.info(f"GitLab API base URL: {api_base}")
            return ProviderConfig(provider="gitlab", api_base=api_base, token=token, extra=extra)

        return None

    async def _get_all_provider_configs(
        self,
        db: AsyncSession,
        project_id: int,
        providers: set,
    ) -> Dict[str, ProviderConfig]:
        """Batch fetch all provider configs in a single query (N+1 optimization)."""
        if not providers:
            return {}

        connector_overrides = await get_connector_overrides_map(db, project_id, providers)
        res = await db.execute(
            select(IntegrationSetting).where(IntegrationSetting.kind.in_(list(providers)))
        )
        rows = res.scalars().all()

        configs: Dict[str, ProviderConfig] = {}
        for row in rows:
            override = connector_overrides.get(row.kind)
            if override and not override.enabled:
                continue

            override_settings = override.settings if override else {}

            if not row.api_token and not (
                override_settings.get("api_token") or override_settings.get("token")
            ):
                continue

            provider = row.kind
            decrypted = decrypt_str(row.api_token)
            token: Optional[str] = None
            extra: Dict[str, Any] = {}

            if decrypted:
                try:
                    bundle = json.loads(decrypted)
                    token = bundle.get("api_token") or bundle.get("token")
                    extra.update(bundle)
                except (json.JSONDecodeError, TypeError):
                    token = decrypted

            if override_settings.get("api_token") or override_settings.get("token"):
                token = str(override_settings.get("api_token") or override_settings.get("token"))
            base_url = str(override_settings.get("base_url") or row.base_url or "").strip()

            if provider == "github":
                api_base = base_url or "https://api.github.com"
                api_base = api_base.rstrip("/")
                configs[provider] = ProviderConfig(
                    provider="github", api_base=api_base, token=token, extra=extra
                )
            elif provider == "gitlab":
                api_base = base_url or "https://gitlab.com"
                api_base = api_base.rstrip("/") + "/api/v4"
                configs[provider] = ProviderConfig(
                    provider="gitlab", api_base=api_base, token=token, extra=extra
                )

        return configs

    async def _ensure_default_branch(
        self,
        db: AsyncSession,
        repo: Repository,
        config: ProviderConfig,
    ) -> Optional[str]:
        if repo.default_branch:
            return repo.default_branch

        # Validate repo_slug format to prevent path traversal
        if config.provider == "github":
            if not re.match(r"^[a-zA-Z0-9\-_\.]+/[a-zA-Z0-9\-_\.]+$", repo.repo_slug):
                logger.error("Invalid GitHub repo_slug format: %s", repo.repo_slug)
                return None
        else:
            if not re.match(r"^[a-zA-Z0-9\-_.]+(?:/[a-zA-Z0-9\-_.]+)+$", repo.repo_slug):
                logger.error("Invalid GitLab repo_slug format: %s", repo.repo_slug)
                return None

        branch = None
        try:
            if config.provider == "github":
                url = f"{config.api_base}/repos/{repo.repo_slug}"
                resp = await self._session_get(
                    url,
                    headers=config.headers,
                    timeout=settings.INTEGRATION_HTTP_TIMEOUT,
                )
                if resp.status_code < 400:
                    branch = resp.json().get("default_branch")
            elif config.provider == "gitlab":
                project_path = quote(repo.repo_slug, safe="")
                url = f"{config.api_base}/projects/{project_path}"
                resp = await self._session_get(
                    url,
                    headers=config.headers,
                    timeout=settings.INTEGRATION_HTTP_TIMEOUT,
                )
                if resp.status_code < 400:
                    branch = resp.json().get("default_branch")
        except Exception as exc:
            logger.warning("Failed to fetch default branch for %s: %s", repo.repo_slug, exc)

        if branch and branch != repo.default_branch:
            repo.default_branch = branch
            try:
                await db.commit()
            except Exception as e:
                # Roll back transaction on failure
                await db.rollback()
                logger.exception("Failed to persist default branch: %s", str(e))

        return repo.default_branch or branch

    async def _sync_commits(
        self,
        db: AsyncSession,
        repo: Repository,
        config: ProviderConfig,
        branch: Optional[str],
        trigger: str | None = "manual",
    ) -> Dict[str, Any]:
        commits: List[Dict[str, Any]] = []
        try:
            if config.provider == "github":
                commits = await asyncio.to_thread(
                    self._fetch_github_commits, config, repo.repo_slug
                )
            elif config.provider == "gitlab":
                commits = await asyncio.to_thread(
                    self._fetch_gitlab_commits, config, repo.repo_slug, branch
                )
        except Exception as exc:
            logger.error("Git import: failed to fetch commits for %s: %s", repo.repo_slug, exc)
            return {"error": str(exc)}

        if not commits:
            return {"created": 0, "updated": 0, "links_created": 0, "suggestions": []}

        try:
            return await process_commits(
                db,
                provider=config.provider,
                repo_slug=repo.repo_slug,
                commits=commits,
                branch=branch,
                trigger=trigger,
            )
        except Exception as exc:
            logger.error("Git import: process_commits failed for %s: %s", repo.repo_slug, exc)
            return {"error": str(exc)}

    async def _sync_pull_requests(
        self,
        db: AsyncSession,
        repo: Repository,
        config: ProviderConfig,
        trigger: str | None = "manual",
    ) -> Dict[str, Any]:
        prs: List[Dict[str, Any]] = []
        try:
            if config.provider == "github":
                prs = await asyncio.to_thread(
                    self._fetch_github_pull_requests, config, repo.repo_slug
                )
            elif config.provider == "gitlab":
                prs = await asyncio.to_thread(
                    self._fetch_gitlab_merge_requests, config, repo.repo_slug
                )
        except Exception as exc:
            logger.error(
                "Git import: failed to fetch pull requests for %s: %s", repo.repo_slug, exc
            )
            return {"error": str(exc)}

        suggestions: List[Dict[str, Any]] = []
        links_created = 0
        processed = 0

        for pr in prs:
            try:
                result = await process_pull_request(
                    db=db,
                    provider=config.provider,
                    repo_slug=repo.repo_slug,
                    pr_data=pr,
                    action="synchronize",
                    trigger=trigger,
                )
                processed += 1
                links_created += result.get("links_created", 0)
                suggestions.extend(result.get("suggestions", []))
            except Exception as exc:
                logger.error(
                    "Git import: failed to process pull request %s/%s: %s",
                    repo.repo_slug,
                    pr.get("number"),
                    exc,
                )

        return {
            "processed": processed,
            "links_created": links_created,
            "suggestions": suggestions,
        }

    def _fetch_github_commits(self, config: ProviderConfig, repo_slug: str) -> List[Dict[str, Any]]:
        # Validate repo_slug format
        if not re.match(r"^[a-zA-Z0-9\-_\.]+/[a-zA-Z0-9\-_\.]+$", repo_slug):
            raise ValueError(f"Invalid repo_slug format: {repo_slug}")

        params: Dict[str, str | int | float | bool | None] = {"per_page": COMMITS_PER_SYNC}
        url = f"{config.api_base}/repos/{repo_slug}/commits"
        resp = self._request_with_retry(url, headers=config.headers, params=params)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"GitHub commits request failed ({resp.status_code}): {resp.text[:200]}"
            )

        data = resp.json() or []
        commits: List[Dict[str, Any]] = []
        for item in data:
            commit = item.get("commit", {})
            author = commit.get("author") or {}
            commits.append(
                {
                    "id": item.get("sha") or item.get("id"),
                    "sha": item.get("sha"),
                    "message": commit.get("message"),
                    "author": {
                        "email": author.get("email") or (item.get("author") or {}).get("email"),
                        "name": author.get("name") or (item.get("author") or {}).get("login"),
                    },
                    "url": item.get("html_url"),
                }
            )
        return commits

    def _fetch_github_pull_requests(
        self, config: ProviderConfig, repo_slug: str
    ) -> List[Dict[str, Any]]:
        if not re.match(r"^[a-zA-Z0-9\-_\.]+/[a-zA-Z0-9\-_\.]+$", repo_slug):
            raise ValueError(f"Invalid repo_slug format: {repo_slug}")

        params: Dict[str, str | int | float | bool | None] = {
            "per_page": PRS_PER_SYNC,
            "state": "all",
        }
        url = f"{config.api_base}/repos/{repo_slug}/pulls"
        resp = self._request_with_retry(url, headers=config.headers, params=params)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"GitHub pull requests request failed ({resp.status_code}): {resp.text[:200]}"
            )

        data = resp.json() or []
        prs: List[Dict[str, Any]] = []
        for item in data:
            user = item.get("user") or {}
            head = item.get("head") or {}
            prs.append(
                {
                    "number": item.get("number"),
                    "title": item.get("title"),
                    "body": item.get("body"),
                    "state": item.get("state"),
                    "user": {"login": user.get("login")},
                    "head": {"sha": head.get("sha"), "ref": head.get("ref")},
                    "created_at": item.get("created_at"),
                    "merged_at": item.get("merged_at"),
                    "closed_at": item.get("closed_at"),
                    "additions": item.get("additions"),
                    "deletions": item.get("deletions"),
                    "changed_files": item.get("changed_files"),
                    "html_url": item.get("html_url"),
                }
            )

        return prs

    def _fetch_gitlab_commits(
        self,
        config: ProviderConfig,
        repo_slug: str,
        branch: Optional[str],
    ) -> List[Dict[str, Any]]:
        """Fetch all commits for a GitLab project (handles pagination)."""
        project_path = quote(repo_slug, safe="")
        page = 1
        commits: List[Dict[str, Any]] = []

        logger.info(f"Starting GitLab commit fetch for {repo_slug}, branch={branch}")

        while True:
            params: Dict[str, Any] = {"per_page": COMMITS_PER_SYNC, "page": page}
            if branch:
                params["ref_name"] = branch

            url = f"{config.api_base}/projects/{project_path}/repository/commits"
            resp = self._request_with_retry(url, headers=config.headers, params=params)
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"GitLab commits request failed ({resp.status_code}): {resp.text[:200]}"
                )

            data = resp.json() or []
            page_count = len(data)

            logger.info(
                f"GitLab commits page {page}: fetched {page_count} items, "
                f"total so far: {len(commits) + page_count}, "
                f"X-Total-Pages: {resp.headers.get('X-Total-Pages')}, "
                f"X-Next-Page: {resp.headers.get('X-Next-Page')}"
            )

            if not data:
                logger.info(f"No more commits found on page {page}, stopping pagination")
                break

            for item in data:
                commits.append(
                    {
                        "id": item.get("id"),
                        "sha": item.get("id"),
                        "message": item.get("message"),
                        "author": {
                            "email": item.get("author_email"),
                            "name": item.get("author_name"),
                        },
                        "url": item.get("web_url") or item.get("url"),
                    }
                )

            # Check if there are more pages
            next_page_str = resp.headers.get("X-Next-Page")

            # Continue if we got a full page of results
            if page_count == COMMITS_PER_SYNC:
                page += 1
                logger.info(f"Full page received, continuing to page {page}")
                continue

            # If we got less than per_page, we're done
            if page_count < COMMITS_PER_SYNC:
                logger.info(
                    f"Partial page received ({page_count} < {COMMITS_PER_SYNC}), this is the last page"
                )
                break

            # Fallback: check X-Next-Page header
            if not next_page_str:
                logger.info("No X-Next-Page header, stopping pagination")
                break

            try:
                page = int(next_page_str)
            except (TypeError, ValueError):
                logger.warning(f"Invalid X-Next-Page value: {next_page_str}, stopping pagination")
                break

        logger.info(f"GitLab commit fetch complete for {repo_slug}: {len(commits)} total commits")
        return commits

    def _fetch_gitlab_merge_requests(
        self, config: ProviderConfig, repo_slug: str
    ) -> List[Dict[str, Any]]:
        """Fetch all merge requests for a GitLab project (handles pagination)."""
        project_path = quote(repo_slug, safe="")
        page = 1
        prs: List[Dict[str, Any]] = []

        logger.info(f"Starting GitLab merge request fetch for {repo_slug}")

        while True:
            params: Dict[str, str | int | float | bool | None] = {
                "per_page": PRS_PER_SYNC,
                "state": "all",
                "order_by": "updated_at",
                "sort": "desc",
                "page": page,
            }
            url = f"{config.api_base}/projects/{project_path}/merge_requests"
            resp = self._request_with_retry(url, headers=config.headers, params=params)
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"GitLab MR request failed ({resp.status_code}): {resp.text[:200]}"
                )

            data = resp.json() or []
            page_count = len(data)

            logger.info(
                f"GitLab MRs page {page}: fetched {page_count} items, "
                f"total so far: {len(prs) + page_count}, "
                f"X-Total-Pages: {resp.headers.get('X-Total-Pages')}, "
                f"X-Next-Page: {resp.headers.get('X-Next-Page')}"
            )

            if not data:
                logger.info(f"No more merge requests found on page {page}, stopping pagination")
                break

            for item in data:
                prs.append(
                    {
                        "number": item.get("iid"),
                        "title": item.get("title"),
                        "state": item.get("state"),
                        "body": item.get("description"),
                        "html_url": item.get("web_url"),
                        "created_at": item.get("created_at"),
                        "merged_at": item.get("merged_at"),
                        "closed_at": item.get("closed_at"),
                        "user": {"login": (item.get("author") or {}).get("username")},
                        "head": {"ref": item.get("source_branch")},
                        "changed_files": item.get("changes_count"),
                    }
                )

            # Continue if we got a full page of results
            if page_count == PRS_PER_SYNC:
                page += 1
                logger.info(f"Full page received, continuing to page {page}")
                continue

            # If we got less than per_page, we're done
            if page_count < PRS_PER_SYNC:
                logger.info(
                    f"Partial page received ({page_count} < {PRS_PER_SYNC}), this is the last page"
                )
                break

            # Fallback: check X-Next-Page header
            next_page_str = resp.headers.get("X-Next-Page")
            if not next_page_str:
                logger.info("No X-Next-Page header, stopping pagination")
                break

            try:
                page = int(next_page_str)
            except (TypeError, ValueError):
                logger.warning(f"Invalid X-Next-Page value: {next_page_str}, stopping pagination")
                break

        logger.info(f"GitLab MR fetch complete for {repo_slug}: {len(prs)} total merge requests")
        return prs


git_import_service = GitImportService()
