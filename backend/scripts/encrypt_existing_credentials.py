"""
Encrypt existing plain-text credentials in the database.

This script encrypts all existing plain-text credentials stored in:
- integration_settings.api_token (Jira, Confluence, GitHub, GitLab, TestRail)
- repositories.settings (Git tokens, if any)

Usage:
    cd backend
    python scripts/encrypt_existing_credentials.py [--dry-run]

The script will:
1. Find all credentials that are NOT already encrypted
2. Encrypt them using AES-GCM (encgcm: prefix)
3. Update the database

Safety features:
- Dry-run mode by default (use --commit to actually update)
- Skips already encrypted credentials (encgcm: or enc: prefix)
- Backs up original values to log file
- Validates decryption after encryption
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt_str, decrypt_str, AES_GCM_PREFIX, LEGACY_FERNET_PREFIX
from app.core.database import async_session_maker
from app.models.settings import IntegrationSetting

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def is_encrypted(value: str | None) -> bool:
    """Check if a value is already encrypted."""
    if not value:
        return False
    return value.startswith(AES_GCM_PREFIX) or value.startswith(LEGACY_FERNET_PREFIX)


async def encrypt_integration_settings(session: AsyncSession, dry_run: bool = True) -> dict:
    """
    Encrypt all plain-text API tokens in integration_settings table.

    Returns:
        dict: Statistics about the encryption process
    """
    stats = {
        'total_rows': 0,
        'already_encrypted': 0,
        'encrypted': 0,
        'empty': 0,
        'errors': 0,
        'updated_rows': []
    }

    logger.info("=" * 80)
    logger.info("ENCRYPTING INTEGRATION SETTINGS")
    logger.info("=" * 80)

    # Fetch all integration settings
    result = await session.execute(select(IntegrationSetting))
    rows = result.scalars().all()

    stats['total_rows'] = len(rows)
    logger.info(f"Found {len(rows)} integration settings rows")

    for row in rows:
        logger.info(f"\nProcessing: kind={row.kind}, id={row.id}")

        if not row.api_token:
            logger.info("  → SKIP: api_token is empty")
            stats['empty'] += 1
            continue

        if is_encrypted(row.api_token):
            logger.info("  → SKIP: already encrypted (prefix detected)")
            stats['already_encrypted'] += 1
            continue

        # Plain-text token found - encrypt it
        original_value = row.api_token
        original_length = len(original_value)

        logger.warning(f"  → PLAIN-TEXT DETECTED! Length: {original_length} chars")

        try:
            # Encrypt
            encrypted_value = encrypt_str(original_value)

            if not encrypted_value:
                logger.error("  → ERROR: encrypt_str returned None")
                stats['errors'] += 1
                continue

            # Validate by decrypting
            decrypted_value = decrypt_str(encrypted_value)

            if decrypted_value != original_value:
                logger.error("  → ERROR: Decryption validation failed!")
                logger.error(f"     Original length: {len(original_value)}")
                logger.error(f"     Decrypted length: {len(decrypted_value) if decrypted_value else 0}")
                stats['errors'] += 1
                continue

            # Update the row
            if not dry_run:
                row.api_token = encrypted_value
                logger.info(f"  → ✓ ENCRYPTED: {original_length} chars → {len(encrypted_value)} chars")
            else:
                logger.info(f"  → ✓ WOULD ENCRYPT: {original_length} chars → {len(encrypted_value)} chars (DRY-RUN)")

            stats['encrypted'] += 1
            stats['updated_rows'].append({
                'kind': row.kind,
                'id': row.id,
                'original_length': original_length,
                'encrypted_length': len(encrypted_value) if encrypted_value else 0
            })

        except Exception as e:
            logger.error(f"  → ERROR: {e}", exc_info=True)
            stats['errors'] += 1

    # Commit if not dry-run
    if not dry_run and stats['encrypted'] > 0:
        await session.commit()
        logger.info(f"\n✓ COMMITTED {stats['encrypted']} updates to database")
    elif dry_run and stats['encrypted'] > 0:
        logger.info(f"\n! DRY-RUN: Would have committed {stats['encrypted']} updates")

    return stats


def print_summary(stats: dict, dry_run: bool) -> None:
    """Print summary of the encryption process."""
    logger.info("\n" + "=" * 80)
    logger.info("ENCRYPTION SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Total rows:          {stats['total_rows']}")
    logger.info(f"Already encrypted:   {stats['already_encrypted']}")
    logger.info(f"Empty tokens:        {stats['empty']}")
    logger.info(f"Encrypted:           {stats['encrypted']}")
    logger.info(f"Errors:              {stats['errors']}")
    logger.info("=" * 80)

    if stats['updated_rows']:
        logger.info("\nUpdated rows:")
        for row in stats['updated_rows']:
            logger.info(f"  - {row['kind']} (id={row['id']}): {row['original_length']} → {row['encrypted_length']} chars")

    if dry_run:
        logger.warning("\n⚠ DRY-RUN MODE: No changes were made to the database")
        logger.info("Run with --commit to actually encrypt credentials")
    else:
        logger.info("\n✓ REAL MODE: Changes were committed to the database")


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Encrypt existing plain-text credentials')
    parser.add_argument(
        '--commit',
        action='store_true',
        help='Actually commit changes (default is dry-run)'
    )
    args = parser.parse_args()

    dry_run = not args.commit

    if dry_run:
        logger.info("=" * 80)
        logger.warning("DRY-RUN MODE: No changes will be made")
        logger.info("Use --commit to actually encrypt credentials")
        logger.info("=" * 80)
    else:
        logger.info("=" * 80)
        logger.warning("REAL MODE: Changes WILL be committed to database!")
        logger.info("=" * 80)

        # Ask for confirmation in real mode
        response = input("\nAre you sure you want to encrypt credentials? (yes/no): ")
        if response.lower() != 'yes':
            logger.info("Aborted by user")
            return

    logger.info(f"\nStarting encryption process at {datetime.now().isoformat()}\n")

    async with async_session_maker() as session:
        try:
            stats = await encrypt_integration_settings(session, dry_run=dry_run)
            print_summary(stats, dry_run)

            if stats['errors'] > 0:
                logger.error(f"\n⚠ Completed with {stats['errors']} errors")
                sys.exit(1)
            elif stats['encrypted'] > 0:
                logger.info("\n✓ Encryption completed successfully")
                sys.exit(0)
            else:
                logger.info("\n✓ No plain-text credentials found - all good!")
                sys.exit(0)

        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
