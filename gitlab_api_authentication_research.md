# GitLab API Authentication with Personal Access Tokens - Research Report

## Executive Summary

This research provides comprehensive guidance on authenticating with GitLab API v4 using Personal Access Tokens (PAT), with special focus on enterprise/self-hosted instances and resolving common "404 Project Not Found" errors.

## 1. Correct API Endpoint Formats for GitLab Enterprise

### Base URL Structure
- **Format**: `https://{gitlab-instance}/api/v4/{endpoint}`
- **Examples**:
  - Self-hosted: `https://gitlab.company.com/api/v4/projects`
  - GitLab.com: `https://gitlab.com/api/v4/projects`

### Project Access Methods

#### Using Numeric Project ID (Recommended)
```bash
# Format
https://gitlab.example.com/api/v4/projects/{numeric_id}

# Example with ID 10252
https://gitlab.example.com/api/v4/projects/10252
https://gitlab.example.com/api/v4/projects/10252/issues
https://gitlab.example.com/api/v4/projects/10252/repository/branches
https://gitlab.example.com/api/v4/projects/10252/merge_requests
```

#### Using Namespace/Project Path (Requires URL Encoding)
```bash
# Format - MUST be URL-encoded
https://gitlab.example.com/api/v4/projects/{namespace}%2F{project_name}

# Example
https://gitlab.example.com/api/v4/projects/mygroup%2Fmyproject
```

**Important**: When using namespace/project format, the forward slash (/) must be encoded as `%2F`. Double-check that reverse proxies don't double-encode to `%252F`.

## 2. Proper Authentication Headers for PAT Tokens

### Authentication Methods

#### Method 1: PRIVATE-TOKEN Header (Recommended)
```bash
curl --request GET \
  --header "PRIVATE-TOKEN: <your_access_token>" \
  --url "https://gitlab.example.com/api/v4/projects/10252"
```

#### Method 2: Authorization Bearer Header
```bash
curl --request GET \
  --header "Authorization: Bearer <your_access_token>" \
  --url "https://gitlab.example.com/api/v4/projects/10252"
```

#### Method 3: Query Parameter (Less Secure)
```bash
curl --request GET \
  --url "https://gitlab.example.com/api/v4/projects/10252?private_token=<your_access_token>"
```

### Testing Authentication
```bash
# Test token validity with user endpoint
curl --header "PRIVATE-TOKEN: <your_token>" \
  "https://gitlab.example.com/api/v4/user"

# Test token scopes and permissions
curl --header "PRIVATE-TOKEN: <your_token>" \
  "https://gitlab.example.com/api/v4/personal_access_tokens/self"
```

## 3. Project ID vs Path Access in GitLab API v4

### Key Differences

| Access Method | Format | Example | Pros | Cons |
|--------------|--------|---------|------|------|
| Numeric ID | `/projects/{id}` | `/projects/10252` | Direct, no encoding needed | Need to know ID |
| Namespace Path | `/projects/{encoded_path}` | `/projects/group%2Fproject` | Human-readable | Requires URL encoding |

### Finding Project IDs

1. **Via Web Interface**:
   - Navigate to project → Settings → General
   - Project ID is displayed at the top
   - Alternative: Visit `https://gitlab.example.com/projects/{id}` redirects to project

2. **Via API**:
```bash
# List all accessible projects
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects"

# Search by name
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects?search=project_name"
```

## 4. Common Issues with 404 "Project Not Found" Errors

### Root Causes and Solutions

#### 1. Permission Issues
**Cause**: Token lacks necessary permissions
**Solution**:
- Ensure user has at least Developer access to the project
- For private projects, user must be a project member
- Check token hasn't expired

#### 2. Wrong Token Type
**Cause**: Using inappropriate token for the operation
**Solutions**:
- Use Personal Access Token for general API access
- Use Project Access Token for project-specific operations
- Use Pipeline Trigger Token for triggering pipelines
- Avoid CI_JOB_TOKEN for cross-project access unless configured

#### 3. Token Scope Limitations
**Required Scopes**:
- `api` - Full API access (includes repository access)
- `read_api` - Read-only API access
- `read_repository` - Repository read access only
- `write_repository` - Repository write access

#### 4. Cross-Project Access Issues
**For CI/CD Jobs**:
1. Navigate to Project → Settings → CI/CD → Token Access
2. Add allowed projects to the list
3. Enable "Allow access to this project with a CI_JOB_TOKEN"

#### 5. Reverse Proxy Configuration
**Apache Configuration Fix**:
```apache
# Add 'nocanon' to prevent double-encoding
ProxyPass /gitlab http://gitlab-server:80/gitlab nocanon
ProxyPassReverse /gitlab http://gitlab-server:80/gitlab
```

#### 6. Empty or Malformed Headers
**Common Mistakes**:
- Missing quotes around token
- Extra spaces in header
- Using wrong header name (Private-Token vs PRIVATE-TOKEN)

## 5. Differences Between Token Types

### Personal Access Token (PAT)
- **Scope**: User-level, inherits user permissions
- **Use Cases**: General API access, automation scripts
- **Creation**: User Settings → Access Tokens
- **Permissions**: Based on user's role across all projects

### Project Access Token
- **Scope**: Specific project only
- **Use Cases**: Project-specific CI/CD, limited automation
- **Creation**: Project → Settings → Access Tokens
- **Permissions**: Limited to assigned role in that project
- **Note**: Cannot be used to create other project tokens via API

### Group Access Token
- **Scope**: All projects within a group
- **Use Cases**: Group-wide operations
- **Creation**: Group → Settings → Access Tokens
- **Permissions**: Applies to all group projects

### CI_JOB_TOKEN
- **Scope**: Current pipeline execution
- **Use Cases**: CI/CD jobs, limited cross-project access
- **Duration**: Valid only during job execution
- **Permissions**: Inherits from user triggering pipeline

## 6. Alternative Methods for Repository Access

### 1. OAuth2 Tokens
```bash
# Obtain token via OAuth flow
curl --request POST \
  --data "grant_type=password&username=<username>&password=<password>" \
  "https://gitlab.example.com/oauth/token"
```

### 2. Deploy Tokens
- Read-only or read-write repository access
- Ideal for deployment scenarios
- No API access, only Git operations

### 3. Deploy Keys
- SSH key-based access
- Repository-level or project-level
- No API access

### 4. Git Credential Helpers
```bash
# Clone using PAT
git clone https://oauth2:<token>@gitlab.example.com/group/project.git

# Or with username
git clone https://<username>:<token>@gitlab.example.com/group/project.git
```

## 7. Debugging and Testing

### Diagnostic Commands

```bash
# 1. Verify token validity
curl -I --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/user"

# 2. Check accessible projects
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects?membership=true"

# 3. Test specific project access
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/10252"

# 4. Verify token scopes
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/personal_access_tokens/self"
```

### Common Response Codes
- **200 OK**: Successful request
- **401 Unauthorized**: Invalid or missing token
- **403 Forbidden**: Valid token but insufficient permissions
- **404 Not Found**: Can be misleading - often means permission issue
- **422 Unprocessable Entity**: Invalid parameters

## 8. Best Practices

### Security
1. Never commit tokens to version control
2. Use environment variables for tokens
3. Rotate tokens regularly
4. Use minimal required scopes
5. Prefer header authentication over query parameters

### Performance
1. Use numeric project IDs when possible
2. Cache project IDs for frequently accessed projects
3. Batch API requests when possible
4. Implement proper error handling and retries

### Error Handling
```python
# Python example with proper error handling
import requests

def get_project(gitlab_url, project_id, token):
    headers = {'PRIVATE-TOKEN': token}
    url = f"{gitlab_url}/api/v4/projects/{project_id}"

    try:
        response = requests.get(url, headers=headers)

        if response.status_code == 404:
            # Check if it's really not found or permission issue
            user_check = requests.get(
                f"{gitlab_url}/api/v4/user",
                headers=headers
            )
            if user_check.status_code != 200:
                return "Authentication failed"
            return "Project not found or no access"

        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return f"Error: {e}"
```

## 9. Quick Reference

### Essential cURL Commands
```bash
# Get project details
curl -H "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/10252"

# List project branches
curl -H "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/10252/repository/branches"

# Get file content
curl -H "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/10252/repository/files/README.md/raw?ref=main"

# Trigger pipeline
curl -X POST -H "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/10252/pipeline?ref=main"
```

## Summary

Successfully authenticating with GitLab API requires:
1. Using correct endpoint formats (prefer numeric IDs)
2. Proper token type for your use case
3. Adequate permissions and scopes
4. Correct authentication headers
5. Understanding that 404 errors often indicate permission issues

When troubleshooting:
- Start with simple API calls to verify authentication
- Check token scopes and project permissions
- Verify project ID and API endpoint format
- Review any proxy or infrastructure configurations
- Use verbose output to debug header transmission