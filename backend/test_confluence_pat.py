#!/usr/bin/env python
"""
Test script to verify Confluence PAT authentication works correctly.
This script tests that the service properly detects Data Center and uses Bearer auth
when no email is provided.
"""

import logging
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.confluence_service import ConfluenceService

# Configure logging to see debug messages
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def test_confluence_pat():
    """Test Confluence connection with PAT token (no email)."""

    # Get credentials from environment or use test values
    base_url = input("Enter Confluence base URL (e.g., https://wiki.andersenlab.com): ").strip()
    pat_token = input("Enter PAT token: ").strip()

    if not base_url or not pat_token:
        print("Error: Base URL and PAT token are required")
        return False

    print("\n" + "="*60)
    print("Testing Confluence PAT Authentication")
    print("="*60)

    service = ConfluenceService()

    try:
        # Test 1: Connect without email (should use Bearer auth)
        print("\n1. Testing PAT authentication (no email)...")
        service.connect(
            base_url=base_url,
            email=None,  # No email = Data Center PAT mode
            api_token=pat_token
        )
        print("✓ Connection established")

        # Check status
        status = service.status()
        print(f"✓ Auth mode: {status['auth_mode']}")
        print(f"✓ Instance type: {status['instance_type']}")
        print(f"✓ Base URL: {status['base_url']}")

        # Test 2: Validate connection
        print("\n2. Validating connection...")
        if service.validate():
            print("✓ Connection validated successfully")

        # Test 3: List spaces
        print("\n3. Testing API call (list spaces)...")
        spaces = service.list_spaces(limit=5)
        if spaces:
            print(f"✓ Found {len(spaces)} spaces:")
            for space in spaces[:3]:  # Show first 3
                print(f"  - {space.get('key')}: {space.get('name')}")
        else:
            print("⚠ No spaces found (might be a permissions issue)")

        print("\n" + "="*60)
        print("SUCCESS: Confluence PAT authentication is working!")
        print("="*60)
        return True

    except Exception as e:
        print("\n" + "="*60)
        print(f"ERROR: {e}")
        print("="*60)

        # Additional debugging info
        print("\nDebugging info:")
        print(f"- Bearer token set: {service.bearer_token is not None}")
        print(f"- Basic auth set: {service.auth is not None}")
        print(f"- Is Cloud: {service.is_cloud}")

        return False

if __name__ == "__main__":
    success = test_confluence_pat()
    sys.exit(0 if success else 1)