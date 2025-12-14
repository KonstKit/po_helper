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
        # Test exactly what the frontend calls
        print("Testing exact frontend calls...")

        # Test project detail endpoint - exact path frontend uses
        response = await client.get(
            "http://localhost:8000/api/v1/projects/3",
            headers=headers
        )
        print(f"GET /api/v1/projects/3")
        print(f"  Status: {response.status_code}")
        print(f"  Response type: {type(response.json()).__name__}")
        print(f"  Response: {response.json()}")

if __name__ == "__main__":
    asyncio.run(test())