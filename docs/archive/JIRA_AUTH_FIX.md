# Jira Authentication Fix Documentation

## Problem Analysis

### Root Cause
The application was attempting to authenticate with Jira Server/DC (jira.andersenlab.com) using:
1. **Wrong API version**: API v3 (Cloud-only) instead of v2/latest
2. **Wrong authentication method**: Basic Auth (email + token) instead of Bearer token with PAT

### Error Symptoms
- API v3 endpoints returning 200 OK with HTML (login page redirect)
- API v2/latest endpoints returning 401 Unauthorized with JSON
- Authentication failing despite correct credentials

## Solution Implemented

### Code Changes
1. **Auto-detection of Jira Server/DC vs Cloud**
   - Added `_is_jira_server_instance()` method to detect server type based on URL
   - Cloud instances use `*.atlassian.net` domains
   - All other domains are treated as Server/DC

2. **Dynamic API Version Selection**
   - Server/DC: Only uses API v2 and latest (skips v3)
   - Cloud: Tries v3, then falls back to v2 and latest

3. **Improved Authentication Logic**
   - Server/DC: Always uses Bearer token with PAT
   - Cloud: Uses Basic Auth with email + API token
   - Respects `JIRA_FORCE_PAT` setting for override

## Configuration Instructions

### For Jira Server/Data Center (like jira.andersenlab.com)

1. **Generate a Personal Access Token (PAT) in Jira:**
   - Log into your Jira instance
   - Go to Profile → Manage your account → Security → Personal Access Tokens
   - Click "Create token"
   - Give it a name (e.g., "PO Helper Integration")
   - **Important**: Ensure "REST API" scope is enabled
   - Copy the generated token immediately (it won't be shown again)

2. **Configure the application (.env file):**
   ```env
   # Jira Server/DC Configuration
   JIRA_BASE_URL=https://jira.andersenlab.com
   # Do NOT set JIRA_EMAIL for Server/DC
   # JIRA_EMAIL=  # Leave empty or commented out
   JIRA_API_TOKEN=your-personal-access-token-here

   # Force PAT mode (recommended for Server/DC)
   JIRA_FORCE_PAT=true
   ```

3. **Alternative: Pass credentials via API:**
   ```python
   # When connecting via API, omit email for Server/DC
   POST /api/v1/settings/jira
   {
       "base_url": "https://jira.andersenlab.com",
       "api_token": "your-pat-token"
       # No "email" field for Server/DC
   }
   ```

### For Jira Cloud (*.atlassian.net)

1. **Generate an API Token:**
   - Go to https://id.atlassian.com/manage-profile/security/api-tokens
   - Click "Create API token"
   - Give it a label
   - Copy the token

2. **Configure the application (.env file):**
   ```env
   # Jira Cloud Configuration
   JIRA_BASE_URL=https://yourcompany.atlassian.net
   JIRA_EMAIL=your-email@company.com
   JIRA_API_TOKEN=your-api-token-here

   # Don't force PAT for Cloud
   JIRA_FORCE_PAT=false
   ```

## Testing the Fix

### 1. Restart the backend:
```powershell
PS C:\Users\Use\IdeaProjects\po_helper\backend> .\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 2. Test the connection:
```powershell
# Test via curl
curl -X POST http://localhost:8000/api/v1/settings/jira/test \
  -H "Content-Type: application/json" \
  -d '{
    "base_url": "https://jira.andersenlab.com",
    "api_token": "your-pat-token"
  }'
```

### 3. Expected successful response:
```json
{
  "success": true,
  "message": "Connected successfully",
  "server_type": "Server/DC",
  "api_version": "2"
}
```

## Troubleshooting

### If authentication still fails:

1. **Verify PAT permissions in Jira:**
   - Go to Profile → Personal Access Tokens
   - Check that your token has "REST API" scope enabled
   - If not, revoke and create a new token with correct permissions

2. **Check for SSO/Proxy interference:**
   - Some corporate environments require API bypass rules
   - Contact your Jira administrator to whitelist API access
   - The PAT should bypass SSO authentication

3. **Verify the base URL:**
   - Ensure no trailing slash in JIRA_BASE_URL
   - Try with and without `/jira` context path
   - The application will auto-discover the correct path

4. **Enable debug logging:**
   ```env
   DEBUG=true
   ```
   Then check logs for detailed error messages

### Common Issues and Solutions:

| Issue | Solution |
|-------|----------|
| Still getting HTML responses | Ensure PAT is used (not email/password) |
| 401 on all endpoints | Regenerate PAT with REST API scope |
| 403 Forbidden | Check user permissions in Jira projects |
| Connection timeouts | Increase `JIRA_HTTP_TIMEOUT` in settings |
| Circuit breaker activated | Set `JIRA_CB_ENABLED=false` temporarily |

## Security Best Practices

1. **Never commit tokens to version control**
   - Use `.env` file (already in .gitignore)
   - Or use environment variables

2. **Rotate tokens regularly**
   - Set expiration dates on PATs in Jira
   - Update tokens quarterly

3. **Use minimal permissions**
   - Only grant necessary project access
   - Use read-only tokens where possible

4. **Encrypt tokens at rest**
   - The application encrypts stored tokens
   - Ensure `ENCRYPTION_SECRET` is set in production

## Summary of Changes

The fix ensures:
- ✅ Correct API version for Server/DC (v2/latest only)
- ✅ Proper Bearer authentication with PAT
- ✅ Automatic detection of Jira type
- ✅ Backward compatibility with Cloud instances
- ✅ Clear error messages for debugging
- ✅ Resilient fallback mechanisms

After applying these changes and configuring the correct authentication, the Jira connection should work properly with jira.andersenlab.com and other Jira Server/DC instances.