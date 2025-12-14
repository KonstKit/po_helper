import asyncio
import httpx
from app.core.security import create_access_token

async def test():
    # Generate a token for demo user
    token = create_access_token({"sub": "demo@example.com"})

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }

    async with httpx.AsyncClient() as client:
        # Test project list with trailing slash
        response = await client.get("http://localhost:8000/api/v1/projects/", headers=headers)
        print(f"Projects list (with /) status: {response.status_code}")
        print(f"Projects list (with /) response: {response.text[:500]}")

        # Test project detail
        response = await client.get("http://localhost:8000/api/v1/projects/3", headers=headers)
        print(f"\nProject 3 detail status: {response.status_code}")
        print(f"Project 3 detail response: {response.text[:500]}")

if __name__ == "__main__":
    asyncio.run(test())