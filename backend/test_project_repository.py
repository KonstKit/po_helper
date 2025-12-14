"""Test script for project-repository binding functionality"""
import asyncio
import aiohttp
import json

API_BASE_URL = "http://localhost:8000/api/v1"

async def test_project_repository_binding():
    """Test binding repository to project"""
    async with aiohttp.ClientSession() as session:
        # Test 1: Get repositories for project 2 (should be empty initially)
        print("\n1. Getting repositories for project 2...")
        async with session.get(f"{API_BASE_URL}/projects/2/repositories") as resp:
            if resp.status == 200:
                data = await resp.json()
                print(f"   Current repositories: {data}")
            else:
                print(f"   Error: {resp.status} - {await resp.text()}")

        # Test 2: Bind a GitLab repository to the project
        print("\n2. Binding GitLab repository to project 2...")
        payload = {
            "project_id": 2,
            "repository_url": "https://gitlab.com/example/wabank-repo",
            "is_primary": True
        }
        async with session.post(
            f"{API_BASE_URL}/projects/2/repositories",
            json=payload
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                print(f"   Repository bound successfully: {json.dumps(data, indent=2)}")
                repo_id = data.get("repository_id")
            else:
                print(f"   Error: {resp.status} - {await resp.text()}")
                return

        # Test 3: Get repositories again to verify binding
        print("\n3. Verifying repository binding...")
        async with session.get(f"{API_BASE_URL}/projects/2/repositories") as resp:
            if resp.status == 200:
                data = await resp.json()
                print(f"   Repositories after binding: {json.dumps(data, indent=2)}")
            else:
                print(f"   Error: {resp.status} - {await resp.text()}")

        # Test 4: Get primary repository
        print("\n4. Getting primary repository for project 2...")
        async with session.get(f"{API_BASE_URL}/projects/2/primary-repository") as resp:
            if resp.status == 200:
                data = await resp.json()
                print(f"   Primary repository: {json.dumps(data, indent=2)}")
            else:
                print(f"   Error: {resp.status} - {await resp.text()}")

        # Test 5: List all repositories
        print("\n5. Listing all repositories...")
        async with session.get(f"{API_BASE_URL}/repositories") as resp:
            if resp.status == 200:
                data = await resp.json()
                print(f"   All repositories: {json.dumps(data, indent=2)}")
            else:
                print(f"   Error: {resp.status} - {await resp.text()}")

        print("\n✓ Test completed successfully!")

if __name__ == "__main__":
    print("Testing Project-Repository Binding Functionality")
    print("=" * 50)
    print("\nIMPORTANT: Make sure:")
    print("1. Backend is running on http://localhost:8000")
    print("2. You have configured GitLab integration in settings")
    print("3. Project with ID 2 exists")
    print("\nPress Enter to continue or Ctrl+C to cancel...")
    input()

    try:
        asyncio.run(test_project_repository_binding())
    except KeyboardInterrupt:
        print("\n\nTest cancelled by user")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")