#!/usr/bin/env python
"""
Test script for Confluence authentication fix.
This script tests both Cloud and Data Center authentication scenarios.
"""

import asyncio
import logging
import sys
from app.services.confluence_service import confluence_service

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_cloud_auth():
    """Test Confluence Cloud authentication (requires email + API token)"""
    print("\n=== Testing Confluence Cloud Authentication ===")

    # Example values - replace with actual test credentials
    base_url = "https://example.atlassian.net/wiki"
    email = "user@example.com"
    api_token = "your-api-token-here"

    try:
        # Should auto-detect as Cloud from URL
        confluence_service.connect(base_url, email, api_token)
        confluence_service.validate()
        status = confluence_service.status()
        print(f"✓ Cloud authentication successful!")
        print(f"  Instance type: {status['instance_type']}")
        print(f"  Auth mode: {status['auth_mode']}")
        return True
    except Exception as e:
        print(f"✗ Cloud authentication failed: {e}")
        return False


def test_datacenter_auth():
    """Test Confluence Data Center authentication (PAT without email)"""
    print("\n=== Testing Confluence Data Center Authentication ===")

    # Example values - replace with actual test credentials
    base_url = "https://confluence.company.com"
    pat_token = "your-personal-access-token-here"

    try:
        # Explicitly set as Data Center (no email needed for PAT)
        confluence_service.connect(base_url, None, pat_token, is_cloud=False)
        confluence_service.validate()
        status = confluence_service.status()
        print(f"✓ Data Center authentication successful!")
        print(f"  Instance type: {status['instance_type']}")
        print(f"  Auth mode: {status['auth_mode']}")
        return True
    except Exception as e:
        print(f"✗ Data Center authentication failed: {e}")
        return False


def test_auto_detect():
    """Test auto-detection of instance type"""
    print("\n=== Testing Auto-Detection ===")

    # Test with Cloud URL pattern
    cloud_url = "https://example.atlassian.net/wiki"
    confluence_service.base_url = cloud_url

    # This should detect Cloud from URL
    is_cloud = '.atlassian.net' in cloud_url or 'atlassian.com' in cloud_url
    print(f"URL: {cloud_url}")
    print(f"Auto-detected as: {'Cloud' if is_cloud else 'Data Center'}")

    # Test with Data Center URL pattern
    dc_url = "https://confluence.internal.company.com"
    confluence_service.base_url = dc_url

    is_cloud = '.atlassian.net' in dc_url or 'atlassian.com' in dc_url
    print(f"URL: {dc_url}")
    print(f"Auto-detected as: {'Cloud' if is_cloud else 'Data Center'}")


if __name__ == "__main__":
    print("Confluence Authentication Test Script")
    print("=====================================")

    # Uncomment and modify these lines to test with real credentials
    # WARNING: Do not commit real credentials to version control!

    # Test 1: Cloud with email + API token
    # test_cloud_auth()

    # Test 2: Data Center with PAT
    # test_datacenter_auth()

    # Test 3: Auto-detection
    test_auto_detect()

    print("\n" + "="*50)
    print("Test complete. Remember to never commit real credentials!")
    print("For actual testing, modify the credential values in this script.")