import asyncio
from app.services.jira_service import jira_service
from app.models.settings import IntegrationSetting
from app.core.crypto import decrypt_str
from app.core.database import AsyncSessionLocal
from sqlalchemy import select

async def test_jira():
    print("Testing Jira API...")

    # Initialize Jira
    if not jira_service.base_url:
        print("Loading Jira settings...")
        async with AsyncSessionLocal() as db:
            res = await db.execute(select(IntegrationSetting).where(IntegrationSetting.kind == 'jira'))
            row = res.scalar_one_or_none()
            if row and row.base_url and row.api_token:
                token = decrypt_str(row.api_token)
                email = row.email if row.email else None
                print(f"Connecting to: {row.base_url}")
                jira_service.connect(row.base_url, email, token)

    if not jira_service.base_url:
        print("ERROR: Jira not configured!")
        return

    print(f"Connected to: {jira_service.base_url}")

    # Test API directly
    print("\nTesting direct API call...")
    import requests

    url = f"{jira_service.base_url}/rest/api/2/search"
    params = {
        'jql': 'project = PRIM',
        'maxResults': 5
    }
    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {jira_service.bearer_token}'
    }

    print(f"Making request to: {url}")
    print(f"JQL: {params['jql']}")

    try:
        response = requests.get(url, params=params, headers=headers, timeout=30)
        print(f"Status code: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print(f"Total issues: {data.get('total', 0)}")
            issues = data.get('issues', [])
            print(f"Retrieved: {len(issues)} issues")
            for issue in issues[:3]:
                key = issue.get('key')
                summary = issue.get('fields', {}).get('summary', 'N/A')
                print(f"  - {key}: {summary}")
        else:
            print(f"Error response: {response.text[:500]}")

    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(test_jira())