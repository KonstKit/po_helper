# Confluence Authentication Fix Summary

## Problem Identified

The Confluence API authentication was failing with 302 redirects to login page even when PAT tokens were configured. The root cause was a misunderstanding of how Confluence Cloud vs Data Center/Server handle authentication.

## Key Differences

### Confluence Cloud
- **URL Pattern**: Usually contains `.atlassian.net`
- **Authentication**: Uses API tokens with Basic authentication
- **Format**: `Authorization: Basic base64(email:api_token)`
- **Requirements**: Both email AND API token are required

### Confluence Data Center/Server (On-Premise)
- **URL Pattern**: Custom domain (e.g., `confluence.company.com`)
- **Authentication**: Uses Personal Access Tokens (PATs) with Bearer authentication
- **Format**: `Authorization: Bearer {pat_token}`
- **Requirements**: Only PAT token needed, no email required

## The Issue

The original code incorrectly assumed:
- If email is provided → use Basic auth
- If no email → assume it's a PAT and use Bearer auth

This caused failures because:
1. Confluence Cloud ALWAYS requires email + API token with Basic auth
2. The code was trying to use Bearer auth for Cloud when no email was provided
3. This resulted in 302 redirects to the login page

## The Fix

### 1. Added Instance Type Tracking
- Added `is_cloud` parameter to track whether instance is Cloud or Data Center
- Default is `None` for auto-detection

### 2. Auto-Detection Logic
- Detects Cloud instances by URL pattern (`.atlassian.net` or `atlassian.com`)
- Falls back to testing auth methods to determine instance type
- Tests Bearer auth first (Data Center), then Basic auth (Cloud)

### 3. Improved Authentication Logic
```python
if email:
    # Use Basic auth (works for both Cloud and Data Center)
    use_basic_auth(email, api_token)
elif not is_cloud:
    # Data Center with PAT - use Bearer auth
    use_bearer_auth(api_token)
else:
    # Cloud without email - this is an error
    raise_error("Cloud requires email + API token")
```

### 4. Enhanced Error Handling
- Better detection of 302 redirects with specific error messages
- Detailed logging of authentication attempts
- Clear error messages indicating whether it's a credential or instance type issue

## API Changes

### `/api/v1/confluence/connect` Endpoint

**New Parameter:**
- `is_cloud` (Optional[bool]):
  - `True`: Force Cloud mode (Basic auth)
  - `False`: Force Data Center mode (Bearer auth)
  - `None` (default): Auto-detect based on URL and auth probing

**Example Requests:**

```bash
# Confluence Cloud (auto-detect)
curl -X POST http://localhost:8000/api/v1/confluence/connect \
  -H "Content-Type: application/json" \
  -d '{
    "base_url": "https://example.atlassian.net/wiki",
    "email": "user@example.com",
    "api_token": "your-api-token"
  }'

# Confluence Data Center (explicit)
curl -X POST http://localhost:8000/api/v1/confluence/connect \
  -H "Content-Type: application/json" \
  -d '{
    "base_url": "https://confluence.company.com",
    "api_token": "your-pat-token",
    "is_cloud": false
  }'
```

## Status Response

The `/api/v1/confluence/status` endpoint now returns:
```json
{
  "configured": true,
  "base_url": "https://...",
  "auth_mode": "Basic (Email + Token)" | "Bearer (Data Center PAT)",
  "instance_type": "Cloud" | "Data Center/Server"
}
```

## Testing

A test script has been created at `backend/test_confluence_auth.py` to verify both authentication methods work correctly.

## Migration Notes

For existing users:
1. If using Confluence Cloud: Ensure both email and API token are provided
2. If using Data Center: Set `is_cloud=false` when connecting
3. The system will auto-detect in most cases, but explicit setting is more reliable

## Security Considerations

- Never log or expose actual tokens in error messages
- Use encrypted storage for saved credentials
- API tokens and PATs should have minimal required permissions

## Restart Instructions

After applying this fix:
1. Restart the backend:
   ```powershell
   PS C:\Users\Use\IdeaProjects\po_helper\backend> .\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```
2. Test the connection with your Confluence instance
3. Check the logs for detailed authentication information if issues persist