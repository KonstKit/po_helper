#!/usr/bin/env python
"""
Test script to verify tasks endpoint performance improvements
"""
import time
import requests
import sys

def test_tasks_endpoint(limit=500):
    """Test the tasks endpoint with different limit values"""

    base_url = "http://127.0.0.1:8000"
    endpoint = f"{base_url}/api/v1/tasks"

    # Test with different limit values
    test_cases = [
        {"limit": 100, "description": "Small dataset"},
        {"limit": 250, "description": "Medium dataset"},
        {"limit": 500, "description": "Large dataset (original issue)"},
        {"limit": 1000, "description": "Maximum allowed"}
    ]

    print("Testing Tasks API Performance")
    print("-" * 60)

    for test_case in test_cases:
        limit = test_case["limit"]
        desc = test_case["description"]

        print(f"\nTest: {desc} (limit={limit})")

        params = {"limit": limit}

        try:
            start_time = time.time()
            response = requests.get(endpoint, params=params, timeout=30)
            elapsed_time = time.time() - start_time

            if response.status_code == 200:
                tasks = response.json()
                count = len(tasks)
                print(f"  ✓ Success: Retrieved {count} tasks in {elapsed_time:.3f} seconds")

                if elapsed_time > 5:
                    print("  ⚠ Warning: Response time exceeded 5 seconds")
                elif elapsed_time > 2:
                    print("  ⚠ Notice: Response time exceeded 2 seconds")
                else:
                    print("  ✓ Good: Response time is acceptable")
            else:
                print(f"  ✗ Error: HTTP {response.status_code}")
                print(f"    Response: {response.text[:200]}")

        except requests.exceptions.Timeout:
            print("  ✗ TIMEOUT: Request exceeded 30 seconds")
        except requests.exceptions.ConnectionError:
            print("  ✗ CONNECTION ERROR: Could not connect to backend")
            print("    Make sure the backend is running on port 8000")
            sys.exit(1)
        except Exception as e:
            print(f"  ✗ ERROR: {str(e)}")

    print("\n" + "-" * 60)
    print("Performance test completed")
    print("\nRecommendations:")
    print("1. If any request took > 5 seconds, consider further optimization")
    print("2. Monitor database query performance with logging")
    print("3. Consider implementing pagination on frontend for large datasets")
    print("4. Add caching for frequently accessed data")


if __name__ == "__main__":
    test_tasks_endpoint()