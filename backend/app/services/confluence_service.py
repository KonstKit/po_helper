import logging
import time
from typing import Optional, Dict, Any, List
import re
from dataclasses import dataclass
import requests
from requests.auth import HTTPBasicAuth
from app.core.config import settings
from app.core.redaction import redact_headers

logger = logging.getLogger(__name__)


class ConfluenceService:
    def __init__(self):
        self.base_url: Optional[str] = None
        self.auth: Optional[HTTPBasicAuth] = None
        self.bearer_token: Optional[str] = None
        self.is_cloud: bool = True  # Track if this is a Cloud or Data Center instance
        if settings.CONFLUENCE_BASE_URL:
            # lazy init: rely on /settings connect to set creds
            self.base_url = settings.CONFLUENCE_BASE_URL.rstrip("/")

    def _headers(self) -> Dict[str, str]:
        h = {"Accept": "application/json"}
        if self.bearer_token:
            h["Authorization"] = f"Bearer {self.bearer_token}"
        return h

    def _request_with_retry(
        self,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        auth: Optional[HTTPBasicAuth] = None,
        timeout: Optional[int] = None,
        allow_redirects: bool = True,
        max_retries: Optional[int] = None,
    ) -> requests.Response:
        retry_count = (
            settings.INTEGRATION_HTTP_MAX_RETRIES if max_retries is None else max(0, max_retries)
        )
        backoff_base = settings.INTEGRATION_HTTP_BACKOFF_SECONDS
        backoff_max = settings.INTEGRATION_HTTP_BACKOFF_MAX_SECONDS
        timeout_val = settings.INTEGRATION_HTTP_TIMEOUT if timeout is None else int(timeout)
        attempts = retry_count + 1

        last_exc: Optional[Exception] = None
        for attempt in range(attempts):
            try:
                resp = requests.get(
                    url,
                    params=params,
                    headers=headers,
                    auth=auth,
                    timeout=timeout_val,
                    allow_redirects=allow_redirects,
                )
                if resp.status_code >= 500 and attempt < attempts - 1:
                    delay = min(backoff_base * (2**attempt), backoff_max)
                    logger.warning(
                        "Confluence request failed (%s) retry %d/%d in %.1fs: %s",
                        resp.status_code,
                        attempt + 1,
                        attempts - 1,
                        delay,
                        url,
                    )
                    time.sleep(delay)
                    continue
                return resp
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                last_exc = exc
                if attempt >= attempts - 1:
                    raise
                delay = min(backoff_base * (2**attempt), backoff_max)
                logger.warning(
                    "Confluence request error (%s) retry %d/%d in %.1fs: %s",
                    exc.__class__.__name__,
                    attempt + 1,
                    attempts - 1,
                    delay,
                    url,
                )
                time.sleep(delay)

        if last_exc:
            raise last_exc
        raise RuntimeError("Unexpected Confluence request retry loop exit")

    def connect(
        self, base_url: str, email: Optional[str], api_token: str, is_cloud: Optional[bool] = None
    ):
        """Connect to Confluence instance.

        Args:
            base_url: Base URL of Confluence instance
            email: Email for authentication (required for Cloud, optional for Data Center)
            api_token: API token for Cloud or PAT for Data Center
            is_cloud: True for Cloud, False for Data Center, None for auto-detect
        """
        raw = (base_url or "").rstrip("/")
        # normalize wiki base
        if not raw.endswith("/wiki"):
            raw = raw  # we will auto-discover
        self.base_url = raw
        # Always start from a clean auth state to avoid leaking previous creds
        self.auth = None
        self.bearer_token = None

        # If no email is provided, it's definitely Data Center with PAT
        if not email:
            is_cloud = False
            logger.info("No email provided - using Data Center mode with PAT authentication")
        elif is_cloud is None:
            # Auto-detect Cloud vs Data Center if not specified
            # Common Cloud patterns
            if ".atlassian.net" in raw or "atlassian.com" in raw:
                is_cloud = True
                logger.info("Auto-detected Confluence Cloud from URL pattern")
            else:
                # Try to detect based on API response
                is_cloud = self._detect_instance_type(raw, email, api_token)

        self.is_cloud = is_cloud

        # Determine authentication method
        if email:
            # Email provided - use Basic auth (works for both Cloud with API token and Data Center with password/PAT)
            self.auth = HTTPBasicAuth(email, api_token)
            self.bearer_token = None
            auth_mode = "Basic"
        elif not is_cloud:
            # No email and Data Center mode - use Bearer auth with PAT
            self.auth = None
            self.bearer_token = api_token
            auth_mode = "PAT (Bearer)"
        else:
            # Cloud mode without email - this is likely an error
            logger.error("Confluence Cloud requires email for API token authentication.")
            # Ensure we do not leave half-initialized auth state
            self.auth = None
            self.bearer_token = None
            raise ValueError(
                "Confluence Cloud requires both email and API token. For Data Center with PAT, set is_cloud=False"
            )

        # try discovery
        self._discover_base_url()
        logger.info(
            "Confluence configured base_url=%s mode=%s is_cloud=%s",
            self.base_url,
            auth_mode,
            is_cloud,
        )

    def _detect_instance_type(self, base_url: str, email: Optional[str], api_token: str) -> bool:
        """Auto-detect if this is a Cloud or Data Center instance.

        Returns:
            True if Cloud, False if Data Center/Server
        """
        candidates = [base_url]
        if not base_url.endswith("/wiki"):
            candidates.append(base_url + "/wiki")

        # First, try with Bearer auth (Data Center PAT)
        for base in candidates:
            url = f"{base}/rest/api/latest/space"
            try:
                headers = {"Accept": "application/json", "Authorization": f"Bearer {api_token}"}
                r = requests.get(url, headers=headers, timeout=3, allow_redirects=False)
                if r.status_code == 200:
                    logger.info("Detected Data Center/Server instance (Bearer auth successful)")
                    return False  # Data Center
                elif r.status_code == 302:
                    # Redirect to login usually means auth failed on Data Center
                    location = r.headers.get("Location", "")
                    if "/login" in location:
                        logger.debug(
                            "Bearer auth got login redirect - likely Data Center needing proper auth"
                        )
                        # Continue to try Basic auth if email provided
                elif r.status_code in (401, 403):
                    # Bearer auth failed, might be Cloud
                    pass
            except Exception as e:
                logger.debug("Bearer auth test failed: %s", e)

        # If email provided, try Basic auth (Cloud with API token or Data Center with email+PAT)
        if email:
            for base in candidates:
                url = f"{base}/rest/api/latest/space"
                try:
                    auth = HTTPBasicAuth(email, api_token)
                    r = requests.get(url, auth=auth, timeout=3, allow_redirects=False)
                    if r.status_code == 200:
                        logger.info(
                            "Detected Cloud instance or Data Center with email auth (Basic auth successful)"
                        )
                        return True  # Assume Cloud when Basic auth with email works
                    elif r.status_code == 302:
                        # Redirect to login means auth failed
                        location = r.headers.get("Location", "")
                        if "/login" in location:
                            logger.debug("Basic auth got login redirect - authentication failed")
                except Exception as e:
                    logger.debug("Basic auth test failed: %s", e)

        # Default to Data Center if we couldn't detect (safer for PAT usage)
        logger.warning("Could not auto-detect instance type, defaulting to Data Center")
        return False

    def _discover_base_url(self):
        if not self.base_url:
            return
        candidates = [self.base_url]
        if not self.base_url.endswith("/wiki"):
            candidates.append(self.base_url + "/wiki")
        for base in candidates:
            for ver in ("latest", "2"):
                url = f"{base}/rest/api/{ver}/space"
                try:
                    # Reduced timeout to 3 seconds for discovery
                    r = requests.get(url, headers=self._headers(), auth=self.auth, timeout=3)
                    if r.status_code == 200:
                        self.base_url = base
                        logger.info("Confluence base URL discovered: %s", base)
                        return
                except requests.exceptions.Timeout:
                    logger.warning("Confluence discovery timeout for %s", url)
                    continue
                except Exception as e:
                    logger.debug("Confluence discovery failed for %s: %s", url, e)
                    continue
        # If discovery fails, keep the original base_url
        logger.warning("Confluence discovery failed for all candidates, keeping: %s", self.base_url)

    def status(self) -> Dict[str, Any]:
        if self.bearer_token:
            auth_mode = "Bearer (Data Center PAT)"
        elif self.auth:
            auth_mode = "Basic (Email + Token)"
        else:
            auth_mode = "none"

        return {
            "configured": self.base_url is not None
            and (self.bearer_token is not None or self.auth is not None),
            "base_url": self.base_url,
            "auth_mode": auth_mode,
            "instance_type": "Cloud" if self.is_cloud else "Data Center/Server",
        }

    def validate(self) -> bool:
        if not self.base_url or (self.bearer_token is None and self.auth is None):
            raise Exception("Confluence not configured")

        last_error = None
        for ver in ("latest", "2"):
            url = f"{self.base_url}/rest/api/{ver}/space"
            try:
                # Reduced timeout to 5 seconds for validation
                r = requests.get(
                    url, headers=self._headers(), auth=self.auth, timeout=5, allow_redirects=False
                )

                # Log detailed response info for debugging
                logger.debug(
                    "Validation response: status=%s, headers=%s",
                    r.status_code,
                    redact_headers(dict(r.headers)),
                )

                if r.status_code == 200:
                    return True
                elif r.status_code == 302:
                    # Redirect to login - authentication not working
                    location = r.headers.get("Location", "")
                    if "/login" in location:
                        last_error = "Authentication failed - redirected to login. Check credentials and instance type (Cloud vs Data Center)"
                        logger.error(last_error)
                    else:
                        last_error = f"Unexpected redirect to: {location}"
                        logger.warning(last_error)
                elif r.status_code == 401:
                    last_error = f"Authentication failed (401). {'Using Bearer auth' if self.bearer_token else 'Using Basic auth'}"
                    logger.error(last_error)
                elif r.status_code == 403:
                    last_error = "Access forbidden (403). User may lack permissions"
                    logger.error(last_error)
                else:
                    last_error = f"Unexpected status code: {r.status_code}"
                    logger.warning(last_error)

            except requests.exceptions.Timeout:
                last_error = f"Connection timeout for {url}"
                logger.warning(last_error)
                continue
            except Exception as e:
                last_error = f"Validation failed for {url}: {str(e)}"
                logger.warning(last_error)
                continue

        # Provide helpful error message
        if last_error:
            raise Exception(f"Confluence validation failed: {last_error}")
        else:
            raise Exception(f"Confluence validate failed at {self.base_url}")

    def search_content(
        self, cql: str, limit: int = 50, expand: str = "version,history,metadata.labels"
    ) -> List[Dict[str, Any]]:
        if not self.base_url:
            return []
        for ver in ("latest", "2"):
            url = f"{self.base_url}/rest/api/{ver}/search"
            try:
                params: Dict[str, str | int | float | bool | None] = {
                    "cql": cql,
                    "limit": int(limit),
                    "expand": expand,
                }
                r = self._request_with_retry(
                    url, params=params, headers=self._headers(), auth=self.auth, timeout=30
                )
                r.raise_for_status()
                data = r.json()
                results = data.get("results", [])
                return results
            except Exception as e:
                logger.warning("Confluence search failed ver=%s: %s", ver, e)
        return []

    def get_page_by_id(
        self, page_id: str, expand: str = "body.storage,version,history,metadata.labels"
    ) -> Dict[str, Any]:
        if not self.base_url:
            raise Exception("Confluence not configured")
        for ver in ("latest", "2"):
            url = f"{self.base_url}/rest/api/{ver}/content/{page_id}"
            try:
                params: Dict[str, str | int | float | bool | None] = {"expand": expand}
                r = self._request_with_retry(
                    url, params=params, headers=self._headers(), auth=self.auth, timeout=30
                )
                r.raise_for_status()
                return r.json()
            except Exception as e:
                logger.warning("get_page_by_id failed ver=%s: %s", ver, e)
        raise Exception("Page not found")

    # --- Autolink helpers ---

    @dataclass
    class JiraKeyContext:
        key: str
        context: str
        in_header: bool
        in_link: bool

    def extract_jira_keys_from_page(
        self, page_content: str
    ) -> List["ConfluenceService.JiraKeyContext"]:
        """Extract Jira keys with simple context signals from raw HTML (storage format).
        Heuristics: regex on text, capture +/- 60 chars context; flags: in header, in anchor.
        """
        if not page_content:
            return []
        try:
            from bs4 import BeautifulSoup
        except Exception:
            # fallback: regex only
            keys = []
            for m in re.finditer(r"\b[A-Z][A-Z0-9]+-\d+\b", page_content):
                start = max(0, m.start() - 60)
                end = min(len(page_content), m.end() + 60)
                ctx = page_content[start:end]
                keys.append(ConfluenceService.JiraKeyContext(m.group(0), ctx, False, False))
            return keys

        soup = BeautifulSoup(page_content, "html.parser")
        text = soup.get_text(" ", strip=False)

        results: List[ConfluenceService.JiraKeyContext] = []

        # Anchor-based detection
        for a in soup.find_all("a"):
            txt = (a.get_text() or "").strip()
            for m in re.finditer(r"\b[A-Z][A-Z0-9]+-\d+\b", txt):
                key = m.group(0)
                ctx = txt
                # header containment
                in_header = False
                p = a
                for _ in range(3):
                    p = p.parent
                    if p is None:
                        break
                    name = getattr(p, "name", "").lower()
                    if name in ("h1", "h2", "h3", "h4"):
                        in_header = True
                        break
                results.append(ConfluenceService.JiraKeyContext(key, ctx, in_header, True))

        # Text-based detection (including tables)
        for m in re.finditer(r"\b[A-Z][A-Z0-9]+-\d+\b", text):
            key = m.group(0)
            start = max(0, m.start() - 80)
            end = min(len(text), m.end() + 80)
            ctx = text[start:end]
            # Check if already captured from anchors
            if not any(r.key == key and r.context == ctx for r in results):
                results.append(ConfluenceService.JiraKeyContext(key, ctx, False, False))
        return results

    def list_spaces(self, q: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        if not self.base_url:
            return []
        params: Dict[str, str | int | float | bool | None] = {"limit": int(limit)}
        if q:
            # Confluence REST supports 'q' search on /space for name/key
            params["q"] = str(q)
        for ver in ("latest", "2"):
            url = f"{self.base_url}/rest/api/{ver}/space"
            try:
                logger.info(
                    "Requesting spaces: url=%s, headers=%s, auth=%s",
                    url,
                    redact_headers(self._headers()),
                    "Basic" if self.auth else "Bearer",
                )
                r = self._request_with_retry(
                    url,
                    params=params,
                    headers=self._headers(),
                    auth=self.auth,
                    timeout=30,
                    allow_redirects=False,
                )
                logger.info(
                    "Response status=%s, location=%s",
                    r.status_code,
                    r.headers.get("Location", "none"),
                )

                # Handle redirects
                if r.status_code == 302:
                    location = r.headers.get("Location", "")
                    if "/login" in location:
                        logger.error("Got redirect to login page - authentication failed")
                        logger.error("Headers sent: %s", redact_headers(self._headers()))
                        logger.error("Auth mode: %s", "Basic" if self.auth else "Bearer")
                    else:
                        logger.error("Got redirect to: %s", location)
                    continue

                if r.status_code == 401 or r.status_code == 403:
                    logger.error("Authentication failed: %s", r.text[:200])
                r.raise_for_status()
                # Log first 500 chars of response to debug HTML vs JSON
                logger.info("Response content preview: %s", r.text[:500] if r.text else "empty")
                data = r.json()
                items = data.get("results") or data.get("spaces") or []
                logger.info("Found %d spaces in response", len(items))
                spaces: List[Dict[str, Any]] = []
                for s in items:
                    links = s.get("_links", {})
                    spaces.append(
                        {
                            "id": s.get("id") or s.get("spaceId"),
                            "key": s.get("key"),
                            "name": s.get("name"),
                            "type": s.get("type"),
                            "status": s.get("status"),
                            "url": f"{self.base_url}{links.get('webui', '')}"
                            if self.base_url
                            else links.get("webui"),
                        }
                    )
                return spaces
            except Exception as e:
                logger.warning("list_spaces failed ver=%s: %s", ver, e)
                if hasattr(e, "response") and e.response is not None:
                    logger.warning(
                        "Response text: %s", e.response.text[:500] if e.response.text else "empty"
                    )
        return []

    def list_pages(
        self,
        space: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = 50,
        expand: str = "version,history,metadata.labels",
        start: int = 0,
    ) -> List[Dict[str, Any]]:
        if not self.base_url:
            return []
        # If query text provided, prefer CQL for flexible search
        if q:
            cql_parts = ["type = page"]
            if space:
                cql_parts.append(f'space = "{space}"')

            # Build robust search for terms with hyphens/dashes by combining phrase and token ANDs
            def _cql_escape(s: str) -> str:
                return s.replace("\\", "\\\\").replace('"', '\\"')

            safe_q = _cql_escape(q)
            # split on common separators: whitespace, hyphen '-', en/em dash, non-breaking hyphen, slash and underscore
            import re as _re

            tokens = [t for t in _re.split(r"[\s\-/\u2011\u2012\u2013\u2014\u2212_]+", q) if t]
            # For each token, search token as-is and with trailing wildcard for better recall
            token_terms_all: list[str] = []
            for t in tokens:
                te = _cql_escape(t)
                base = f'(title ~ "{te}" OR text ~ "{te}")'
                wc = f'(title ~ "{te}*" OR text ~ "{te}*")'
                # Always include wildcard variant to match morphological/compound cases
                token_terms_all.append(f"({base} OR {wc})")
            token_clause = " AND ".join(token_terms_all) if token_terms_all else None
            # Any-token clause on title (broad catch) to improve recall when AND is too strict
            any_title_clause = None
            if tokens:
                any_title_clause = " OR ".join([f'title ~ "{_cql_escape(t)}*"' for t in tokens])
            phrase_clause = f'(title ~ "{safe_q}" OR text ~ "{safe_q}")'
            combined = [phrase_clause]
            if token_clause:
                combined.append(f"({token_clause})")
            if any_title_clause:
                combined.append(f"({any_title_clause})")
            cql_parts.append(" OR ".join(combined))
            cql = " AND ".join(cql_parts) + " ORDER BY lastmodified DESC"
            # For /search we can also support pagination via 'start'
            results = []
            if not self.base_url:
                return []
            for ver in ("latest", "2"):
                for ep in ("search", "content/search"):
                    url = f"{self.base_url}/rest/api/{ver}/{ep}"
                    try:
                        cql_params: Dict[str, str | int | float | bool | None] = {
                            "cql": cql,
                            "limit": int(limit),
                            "start": int(start),
                            "expand": expand,
                        }
                        logger.debug("Confluence CQL %s v%s: %s", ep, ver, cql)
                        r = self._request_with_retry(
                            url,
                            params=cql_params,
                            headers=self._headers(),
                            auth=self.auth,
                            timeout=30,
                        )
                        r.raise_for_status()
                        data = r.json()
                        results = data.get("results", [])
                        if results:
                            break
                    except Exception as e:
                        logger.warning("Confluence %s (v%s) failed: %s", ep, ver, e)
                if results:
                    break
            pages: List[Dict[str, Any]] = []
            for it in results:
                # Different schemas: directly with id/title or nested under 'content'
                content = it.get("content") if isinstance(it, dict) else None
                cid = (it.get("id") if isinstance(it, dict) else None) or (content or {}).get("id")
                title = it.get("title") or (content or {}).get("title")
                it_type = it.get("type") or (content or {}).get("type")
                space_key = None
                s_obj = it.get("space") or (content or {}).get("space")
                if isinstance(s_obj, dict):
                    space_key = s_obj.get("key")
                links = it.get("_links", {}) or (content or {}).get("_links", {})
                version_obj = it.get("version") or (content or {}).get("version") or {}
                history_obj = it.get("history") or (content or {}).get("history") or {}
                last_updated = version_obj.get("when") or (
                    history_obj.get("lastUpdated") or {}
                ).get("when")
                pages.append(
                    {
                        "id": str(cid) if cid is not None else None,
                        "title": title,
                        "type": it_type,
                        "space": space_key,
                        "url": f"{self.base_url}{links.get('webui', '')}"
                        if self.base_url
                        else links.get("webui"),
                        "version": version_obj.get("number"),
                        "last_updated": last_updated,
                    }
                )
            # Filter out items without IDs to avoid downstream errors
            return [p for p in pages if p.get("id")]
        # Otherwise list content by space (or all) via /content
        for ver in ("latest", "2"):
            url = f"{self.base_url}/rest/api/{ver}/content"
            try:
                content_params: Dict[str, str | int | float | bool | None] = {
                    "type": "page",
                    "limit": int(limit),
                    "start": int(start),
                    "expand": expand,
                }
                if space:
                    content_params["spaceKey"] = space
                r = self._request_with_retry(
                    url,
                    params=content_params,
                    headers=self._headers(),
                    auth=self.auth,
                    timeout=30,
                )
                r.raise_for_status()
                data = r.json()
                results = data.get("results", [])
                pages = []
                for r_ in results:
                    links = r_.get("_links", {})
                    pages.append(
                        {
                            "id": r_.get("id"),
                            "title": r_.get("title"),
                            "type": r_.get("type"),
                            "space": ((r_.get("space") or {}).get("key"))
                            if isinstance(r_.get("space"), dict)
                            else None,
                            "url": f"{self.base_url}{links.get('webui', '')}"
                            if self.base_url
                            else links.get("webui"),
                            "version": (r_.get("version") or {}).get("number"),
                            "last_updated": (r_.get("version") or {}).get("when")
                            or (r_.get("history") or {}).get("lastUpdated", {}).get("when"),
                        }
                    )
                return pages
            except Exception as e:
                logger.warning("list_pages failed ver=%s: %s", ver, e)
        return []

    def list_space_tree(
        self, space: str, page_limit: int = 100, max_pages: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Return hierarchical page tree for a space using expand=ancestors to infer parent-child.
        If max_pages is None, fetch all pages via pagination.
        """
        if not self.base_url:
            return []
        nodes: Dict[str, Dict[str, Any]] = {}
        parent_map: Dict[str, Optional[str]] = {}
        fetched = 0
        start = 0
        while True:
            batch = []
            for ver in ("latest", "2"):
                url = f"{self.base_url}/rest/api/{ver}/content"
                try:
                    params: Dict[str, str | int | float | bool | None] = {
                        "type": "page",
                        "spaceKey": space,
                        "limit": int(page_limit),
                        "start": int(start),
                        "expand": "ancestors",
                    }
                    r = self._request_with_retry(
                        url,
                        params=params,
                        headers=self._headers(),
                        auth=self.auth,
                        timeout=30,
                    )
                    r.raise_for_status()
                    data = r.json()
                    batch = data.get("results", [])
                    break
                except Exception:
                    continue
            if not batch:
                break
            for it in batch:
                cid = str(it.get("id")) if it.get("id") is not None else None
                if not cid:
                    continue
                title = it.get("title")
                ancestors = it.get("ancestors") or []
                parent_id = str(ancestors[-1]["id"]) if ancestors else None
                nodes.setdefault(cid, {"id": cid, "title": title, "children": []})
                nodes[cid]["title"] = title
                parent_map[cid] = parent_id
            fetched += len(batch)
            start += len(batch)
            if len(batch) < page_limit:
                break
            if max_pages is not None and fetched >= max_pages:
                break
        # Build hierarchy: attach children when parent is present in current set
        for cid, parent_id in parent_map.items():
            if parent_id and parent_id in nodes and cid in nodes:
                nodes[parent_id]["children"].append(nodes[cid])
        # Roots: no parent, or parent not fetched (treat as top-level to keep visible)
        roots = []
        for cid, node in nodes.items():
            pid = parent_map.get(cid)
            if not pid or pid not in nodes:
                roots.append(node)

        # Sort children by title for consistency
        def sort_tree(n: Dict[str, Any]):
            n["children"].sort(key=lambda x: (x.get("title") or "").lower())
            for ch in n["children"]:
                sort_tree(ch)

        for node in roots:
            if isinstance(node, dict):
                sort_tree(node)
        return roots

    def list_children(self, page_id: str, limit: int = 50, start: int = 0) -> List[Dict[str, Any]]:
        if not self.base_url:
            return []
        for ver in ("latest", "2"):
            url = f"{self.base_url}/rest/api/{ver}/content/{page_id}/child/page"
            try:
                params: Dict[str, str | int | float | bool | None] = {
                    "limit": int(limit),
                    "start": int(start),
                    "expand": "version,space",
                }
                r = self._request_with_retry(
                    url, params=params, headers=self._headers(), auth=self.auth, timeout=30
                )
                r.raise_for_status()
                data = r.json()
                results = data.get("results", [])
                out: List[Dict[str, Any]] = []
                for it in results:
                    out.append(
                        {
                            "id": str(it.get("id")) if it.get("id") is not None else None,
                            "title": it.get("title"),
                        }
                    )
                return [i for i in out if i.get("id")]
            except Exception:
                continue
        return []

    def iter_subtree(self, root_id: str, limit: int = 50) -> List[str]:
        """Return list of page IDs in subtree rooted at root_id (including root)."""
        result: List[str] = []
        stack = [root_id]
        while stack:
            pid = stack.pop()
            result.append(pid)
            start = 0
            while True:
                kids = self.list_children(pid, limit=limit, start=start)
                if not kids:
                    break
                stack.extend([k["id"] for k in kids if k.get("id")])
                if len(kids) < limit:
                    break
                start += len(kids)
        return result


confluence_service = ConfluenceService()
