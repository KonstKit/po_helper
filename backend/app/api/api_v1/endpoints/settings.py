from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
import logging
import json
import requests
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models import IntegrationSetting, Permissions, User
from app.schemas.settings import IntegrationSettings, IntegrationSettingsBase
from app.services.jira_service import jira_service
from app.services.confluence_service import confluence_service
from app.core.crypto import encrypt_str, decrypt_str
from app.api.deps import require_permission, get_current_user
from app.utils import transactional_session, handle_api_error

router = APIRouter()
logger = logging.getLogger(__name__)


async def _get_integration(db: AsyncSession, kind: str) -> IntegrationSetting | None:
    result = await db.execute(select(IntegrationSetting).where(IntegrationSetting.kind == kind))
    return result.scalar_one_or_none()


@router.get("/jira", response_model=IntegrationSettings)
async def get_jira_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.SETTINGS_VIEW))
):
    row = await _get_integration(db, "jira")
    if row:
        # Do not expose token
        return {"kind": "jira", "base_url": row.base_url, "email": row.email, "api_token": None, "has_token": bool(row.api_token)}
    # Default from env (without exposing secrets if not set)
    return {"kind": "jira", "base_url": None, "email": None, "api_token": None, "has_token": False}


@router.put("/jira", response_model=IntegrationSettings)
async def put_jira_settings(
    payload: IntegrationSettingsBase,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.SETTINGS_UPDATE))
):
    row = await _get_integration(db, "jira")
    if not row:
        row = IntegrationSetting(kind="jira")
        db.add(row)
    async with transactional_session(db):
        use_pat = payload.use_pat if payload.use_pat is not None else not bool(payload.email)
        # normalize blanks to None and persist according to mode
        row.base_url = (payload.base_url or None) or None
        row.email = None if use_pat else ((payload.email or None) or None)
        if payload.api_token is not None and payload.api_token != "":
            row.api_token = encrypt_str(payload.api_token)
    await db.refresh(row)
    # Update in-memory Jira client without blocking the event loop
    try:
        if row.base_url:
            token_plain: Optional[str] = None
            if payload.api_token:
                token_plain = payload.api_token
            elif row.api_token:
                try:
                    token_plain = decrypt_str(row.api_token)
                except Exception:
                    token_plain = None
            if token_plain:
                import asyncio
                from functools import partial
                loop = asyncio.get_event_loop()
                connect_email = None if use_pat else row.email
                try:
                    await asyncio.wait_for(
                        loop.run_in_executor(
                            None,
                            partial(
                                jira_service.connect,
                                row.base_url,
                                connect_email,
                                token_plain,
                                use_pat,
                            ),
                        ),
                        timeout=10.0,
                    )
                    mode_label = "PAT" if use_pat else "Basic"
                    logger.info(
                        "Jira settings saved. Mode=%s base_url=%s email=%s token_len=%s",
                        mode_label,
                        (row.base_url or "").rstrip('/'),
                        connect_email or "<none>",
                        len(token_plain),
                    )
                except asyncio.TimeoutError:
                    logger.warning("Jira connection timed out, but settings were saved")
    except Exception:
        pass
    # Do not expose token even encrypted
    return {"kind": "jira", "base_url": row.base_url, "email": row.email, "api_token": None, "has_token": bool(row.api_token)}


@router.get("/confluence", response_model=IntegrationSettings)
async def get_confluence_settings(db: AsyncSession = Depends(get_db)):
    row = await _get_integration(db, "confluence")
    if row:
        return {"kind": "confluence", "base_url": row.base_url, "email": row.email, "api_token": None, "has_token": bool(row.api_token)}
    return {"kind": "confluence", "base_url": None, "email": None, "api_token": None, "has_token": False}


@router.put("/confluence", response_model=IntegrationSettings)
async def put_confluence_settings(payload: IntegrationSettingsBase, db: AsyncSession = Depends(get_db)):
    row = await _get_integration(db, "confluence")
    if not row:
        row = IntegrationSetting(kind="confluence")
        db.add(row)
    async with transactional_session(db):
        row.base_url = (payload.base_url or None) or None
        row.email = (payload.email or None) or None
        row.api_token = encrypt_str(payload.api_token) if (payload.api_token is not None and payload.api_token != "") else row.api_token
    await db.refresh(row)

    # Update in-memory Confluence client (similar to Jira)
    try:
        if payload.base_url and payload.api_token:
            # Run connect in background to avoid blocking the response
            import asyncio
            loop = asyncio.get_event_loop()
            # Use run_in_executor with timeout to avoid blocking
            try:
                # Pass None for email if it's empty to trigger PAT auth for Data Center
                email_for_auth = payload.email if payload.email else None
                await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        confluence_service.connect,
                        payload.base_url,
                        email_for_auth,
                        payload.api_token
                    ),
                    timeout=10.0  # 10 second timeout for connection
                )
                logger.info("Confluence settings saved and connected. base_url=%s email=%s token_len=%s mode=%s",
                            (payload.base_url or "").rstrip('/'),
                            payload.email or "<none>",
                            len(payload.api_token) if payload.api_token else 0,
                            "PAT/Bearer" if not email_for_auth else "Basic")
            except asyncio.TimeoutError:
                logger.warning("Confluence connection timed out, but settings were saved")
    except Exception as e:
        logger.warning("Failed to initialize Confluence service: %s", e)
        # Continue anyway - settings are saved

    return {"kind": "confluence", "base_url": row.base_url, "email": row.email, "api_token": None, "has_token": bool(row.api_token)}


@router.post("/confluence/reload")
async def reload_confluence_settings(db: AsyncSession = Depends(get_db)):
    """Reload Confluence settings from database and reconnect"""
    row = await _get_integration(db, "confluence")
    if not row or not row.base_url or not row.api_token:
        raise HTTPException(status_code=400, detail="Confluence settings not found or incomplete")

    with handle_api_error(operation="reload_confluence_settings"):
        token = decrypt_str(row.api_token)
        # Run connect with timeout
        import asyncio
        loop = asyncio.get_event_loop()
        # Pass None for email if it's empty to trigger PAT auth for Data Center
        email_for_auth = row.email if row.email else None
        await asyncio.wait_for(
            loop.run_in_executor(
                None,
                confluence_service.connect,
                row.base_url,
                email_for_auth,
                token
            ),
            timeout=10.0
        )
        logger.info("Confluence reconnected from stored settings (base_url=%s, mode=%s)",
                    row.base_url, "PAT/Bearer" if not email_for_auth else "Basic")


# ---- GitHub settings ----
@router.get("/github", response_model=IntegrationSettings)
async def get_github_settings(db: AsyncSession = Depends(get_db)):
    row = await _get_integration(db, "github")
    if row:
        # If token stored as encrypted JSON bundle, we still mask it
        return {"kind": "github", "base_url": row.base_url, "email": None, "api_token": None, "has_token": bool(row.api_token), "has_webhook_secret": bool(row.api_token)}
    return {"kind": "github", "base_url": None, "email": None, "api_token": None, "has_token": False, "has_webhook_secret": False}


@router.put("/github", response_model=IntegrationSettings)
async def put_github_settings(payload: IntegrationSettingsBase, db: AsyncSession = Depends(get_db)):
    row = await _get_integration(db, "github")
    if not row:
        row = IntegrationSetting(kind="github")
        db.add(row)
    async with transactional_session(db):
        row.base_url = (payload.base_url or None) or None
        row.email = None
        # pack token + webhook_secret into encrypted JSON string for flexibility
        try:
            token_bundle = None
            if payload.api_token or payload.webhook_secret:
                import json
                token_bundle = json.dumps({"api_token": payload.api_token, "webhook_secret": payload.webhook_secret})
            row.api_token = encrypt_str(token_bundle) if (token_bundle is not None and token_bundle != "") else row.api_token
        except Exception:
            pass
    await db.refresh(row)
    return {"kind": "github", "base_url": row.base_url, "email": None, "api_token": None, "has_token": bool(row.api_token), "has_webhook_secret": bool(row.api_token)}


@router.post("/github/test")
async def test_github_connection(payload: IntegrationSettingsBase, db: AsyncSession = Depends(get_db)):
    row = await _get_integration(db, "github")
    base_url = payload.base_url or (row.base_url if row and row.base_url else None)
    if base_url:
        base_url = base_url.strip()
    stored_bundle = None
    if row and row.api_token:
        try:
            decrypted = decrypt_str(row.api_token)
            if decrypted:
                try:
                    stored_bundle = json.loads(decrypted)
                except Exception:
                    stored_bundle = {"api_token": decrypted}
        except Exception:
            stored_bundle = None
    stored_secret = None
    if stored_bundle:
        stored_secret = (stored_bundle or {}).get("webhook_secret")
    token = payload.api_token or ((stored_bundle or {}).get("api_token") if stored_bundle else None)
    api_base = (base_url or "https://api.github.com").rstrip("/")
    if not api_base:
        raise HTTPException(status_code=400, detail="GitHub base URL is required")

    webhook_secret = payload.webhook_secret or stored_secret
    if not token:
        if webhook_secret:
            return {
                "status": "configured",
                "base_url": api_base,
                "login": None,
                "name": None,
                "plan": None,
                "scopes": None,
                "rate_limit_remaining": None,
                "rate_limit_reset": None,
                "message": "Webhook secret is configured. Provide an API token to verify REST API access.",
            }
        raise HTTPException(status_code=400, detail="GitHub token not configured")

    used_base = api_base
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "po-helper",
        "Authorization": f"Bearer {token}",
    }

    def _github_request(base: str) -> requests.Response:
        test_url = f"{base}/user"
        try:
            return requests.get(test_url, headers=headers, timeout=10)
        except requests.Timeout:
            raise HTTPException(status_code=504, detail="GitHub request timed out")
        except requests.RequestException as exc:
            raise HTTPException(status_code=400, detail=f"GitHub request failed: {exc}")

    def _is_json_response(response: requests.Response) -> bool:
        content_type = (response.headers.get("Content-Type") or "").lower()
        if "json" in content_type:
            return True
        try:
            response.json()
            return True
        except ValueError:
            return False

    resp = _github_request(api_base)

    def _maybe_switch_to_rest_api(response: requests.Response) -> requests.Response:
        nonlocal used_base
        normalized = api_base.lower()
        should_try_alt = False
        if "/api/" not in normalized:
            if response.status_code == 404:
                should_try_alt = True
            elif response.status_code == 403 and not _is_json_response(response):
                should_try_alt = True
        if not should_try_alt:
            return response

        alt_base = api_base.rstrip("/") + "/api/v3"
        alt_resp = _github_request(alt_base)
        if alt_resp.status_code < 400:
            used_base = alt_base
            return alt_resp

        snippet = alt_resp.text[:200] if alt_resp.text else ""
        raise HTTPException(
            status_code=response.status_code,
            detail=(
                f"GitHub returned {response.status_code}. If you use GitHub Enterprise, set the base URL to the REST API "
                f"(e.g. https://api.github.com or https://your-host/api/v3). Attempted {alt_base}/user -> {snippet!r}"
            ),
        )

    resp = _maybe_switch_to_rest_api(resp)

    if resp.status_code == 404:
        snippet = resp.text[:200] if resp.text else ""
        raise HTTPException(
            status_code=404,
            detail=(
                "GitHub returned 404. Ensure the base URL points to the REST API (e.g. https://api.github.com or https://your-host/api/v3). "
                f"Response snippet: {snippet!r}"
            ),
        )

    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail="GitHub authentication failed (401)")
    if resp.status_code == 403:
        detail = ""
        try:
            detail = resp.json().get("message", "")
        except Exception:
            detail = resp.text[:200]
        raise HTTPException(status_code=403, detail=f"GitHub access forbidden: {detail or 'forbidden'}")
    if resp.status_code >= 400:
        detail = ""
        try:
            detail = resp.json().get("message", "")
        except Exception:
            detail = resp.text[:200]
        raise HTTPException(status_code=resp.status_code, detail=f"GitHub error {resp.status_code}: {detail or 'unknown'}")
    try:
        data = resp.json()
    except ValueError:
        data = {}
    result = {
        "status": "connected",
        "base_url": used_base,
        "login": data.get("login"),
        "name": data.get("name"),
        "plan": (data.get("plan") or {}).get("name") if isinstance(data.get("plan"), dict) else None,
        "scopes": resp.headers.get("X-OAuth-Scopes"),
        "rate_limit_remaining": resp.headers.get("X-RateLimit-Remaining"),
        "rate_limit_reset": resp.headers.get("X-RateLimit-Reset"),
    }
    return result

# ---- GitLab settings ----
@router.get("/gitlab", response_model=IntegrationSettings)
async def get_gitlab_settings(db: AsyncSession = Depends(get_db)):
    row = await _get_integration(db, "gitlab")
    if row:
        return {"kind": "gitlab", "base_url": row.base_url, "email": None, "api_token": None, "has_token": bool(row.api_token), "has_webhook_secret": bool(row.api_token)}
    return {"kind": "gitlab", "base_url": None, "email": None, "api_token": None, "has_token": False, "has_webhook_secret": False}


@router.put("/gitlab", response_model=IntegrationSettings)
async def put_gitlab_settings(payload: IntegrationSettingsBase, db: AsyncSession = Depends(get_db)):
    row = await _get_integration(db, "gitlab")
    if not row:
        row = IntegrationSetting(kind="gitlab")
        db.add(row)
    async with transactional_session(db):
        row.base_url = (payload.base_url or None) or None
        row.email = None
        try:
            token_bundle = None
            if payload.api_token or payload.webhook_secret:
                import json
                token_bundle = json.dumps({"api_token": payload.api_token, "webhook_secret": payload.webhook_secret})
            row.api_token = encrypt_str(token_bundle) if (token_bundle is not None and token_bundle != "") else row.api_token
        except Exception:
            pass
    await db.refresh(row)
    return {"kind": "gitlab", "base_url": row.base_url, "email": None, "api_token": None, "has_token": bool(row.api_token), "has_webhook_secret": bool(row.api_token)}


@router.post("/gitlab/test")
async def test_gitlab_connection(payload: IntegrationSettingsBase, db: AsyncSession = Depends(get_db)):
    row = await _get_integration(db, "gitlab")
    base_url = payload.base_url or (row.base_url if row and row.base_url else None)
    if not base_url:
        raise HTTPException(status_code=400, detail="GitLab base URL is required")
    base_url = base_url.strip().rstrip('/')

    stored_bundle = None
    if row and row.api_token:
        try:
            decrypted = decrypt_str(row.api_token)
            if decrypted:
                try:
                    stored_bundle = json.loads(decrypted)
                except Exception:
                    stored_bundle = {"api_token": decrypted}
        except Exception:
            stored_bundle = None

    stored_token = (stored_bundle or {}).get("api_token") if stored_bundle else None
    stored_secret = (stored_bundle or {}).get("webhook_secret") if stored_bundle else None

    token = payload.api_token or stored_token
    webhook_secret = payload.webhook_secret or stored_secret

    if not token:
        raise HTTPException(status_code=400, detail="GitLab API token not configured")

    api_base = f"{base_url}/api/v4"
    headers = {
        "Private-Token": token,
        "Accept": "application/json",
        "User-Agent": "po-helper",
    }

    try:
        resp = requests.get(f"{api_base}/user", headers=headers, timeout=10)
    except requests.Timeout:
        raise HTTPException(status_code=504, detail="GitLab request timed out")
    except requests.RequestException as exc:
        raise HTTPException(status_code=400, detail=f"GitLab request failed: {exc}")

    def _resp_message(response: requests.Response) -> str:
        try:
            data = response.json()
            if isinstance(data, dict):
                return data.get("message") or data.get("error") or ""
        except Exception:
            pass
        return (response.text or "")[:200]

    if resp.status_code == 401:
        detail = _resp_message(resp)
        raise HTTPException(status_code=401, detail=f"GitLab authentication failed (401){': ' + detail if detail else ''}")
    if resp.status_code == 403:
        detail = _resp_message(resp)
        raise HTTPException(status_code=403, detail=f"GitLab access forbidden{': ' + detail if detail else ''}")
    if resp.status_code >= 400:
        detail = _resp_message(resp)
        raise HTTPException(status_code=resp.status_code, detail=f"GitLab error {resp.status_code}: {detail or 'unknown'}")

    try:
        data = resp.json()
    except ValueError:
        data = {}

    return {
        "status": "connected",
        "base_url": base_url,
        "api_base": api_base,
        "username": data.get("username"),
        "name": data.get("name"),
        "email": data.get("email"),
        "webhook_secret_configured": bool(webhook_secret),
    }


# ---- TestRail settings ----
@router.get("/testrail", response_model=IntegrationSettings)
async def get_testrail_settings(db: AsyncSession = Depends(get_db)):
    row = await _get_integration(db, "testrail")
    if row:
        return {"kind": "testrail", "base_url": row.base_url, "email": row.email, "api_token": None, "has_token": bool(row.api_token)}
    return {"kind": "testrail", "base_url": None, "email": None, "api_token": None, "has_token": False}


@router.put("/testrail", response_model=IntegrationSettings)
async def put_testrail_settings(payload: IntegrationSettingsBase, db: AsyncSession = Depends(get_db)):
    row = await _get_integration(db, "testrail")
    if not row:
        row = IntegrationSetting(kind="testrail")
        db.add(row)
    async with transactional_session(db):
        row.base_url = (payload.base_url or None) or None
        row.email = (payload.email or None) or None
        row.api_token = encrypt_str(payload.api_token) if (payload.api_token is not None and payload.api_token != "") else row.api_token
    await db.refresh(row)
    return {"kind": "testrail", "base_url": row.base_url, "email": row.email, "api_token": None, "has_token": bool(row.api_token)}
@router.post("/testrail/test")
async def test_testrail_connection(payload: IntegrationSettingsBase, db: AsyncSession = Depends(get_db)):
    row = await _get_integration(db, "testrail")
    base_url = payload.base_url or (row.base_url if row and row.base_url else None)
    email = payload.email or (row.email if row and row.email else None)
    if not base_url:
        raise HTTPException(status_code=400, detail="TestRail base URL is required")
    if not email:
        raise HTTPException(status_code=400, detail="TestRail user email is required")
    token = payload.api_token
    if not token and row and row.api_token:
        try:
            token = decrypt_str(row.api_token)
        except Exception:
            token = None
    if not token:
        raise HTTPException(status_code=400, detail="TestRail API key not configured")

    base_url = base_url.strip().rstrip('/')
    endpoint = f"{base_url}/index.php?/api/v2/get_statuses"

    try:
        resp = requests.get(endpoint, auth=(email, token), timeout=10)
    except requests.Timeout:
        raise HTTPException(status_code=504, detail="TestRail request timed out")
    except requests.RequestException as exc:
        raise HTTPException(status_code=400, detail=f"TestRail request failed: {exc}")

    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail="TestRail authentication failed (401)")
    if resp.status_code == 403:
        raise HTTPException(status_code=403, detail="TestRail access forbidden")
    if resp.status_code >= 400:
        snippet = (resp.text or "")[:200]
        raise HTTPException(status_code=resp.status_code, detail=f"TestRail error {resp.status_code}: {snippet or 'unknown'}")

    statuses = []
    try:
        body = resp.json()
        if isinstance(body, list):
            statuses = body
    except ValueError:
        statuses = []

    return {
        "status": "connected",
        "base_url": base_url,
        "user": email,
        "status_count": len(statuses),
    }
