#!/usr/bin/env python
"""
Celery Worker Runner for Windows
This script helps run Celery workers on Windows with the correct pool configuration.
"""

import os
import sys
import platform
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def run_worker():
    """Run Celery worker with appropriate settings for Windows."""

    # Set environment variables if needed
    os.environ.setdefault('PYTHONPATH', str(project_root))

    # Import Celery app
    from app.core.celery_app import celery_app

    # Determine pool type based on platform
    pool_type = 'solo' if platform.system() == 'Windows' else 'prefork'

    # Worker configuration
    worker_args = [
        'worker',
        '--loglevel=info',
        f'--pool={pool_type}',
        '--hostname=worker@%h',
    ]

    # For Windows, you might also want to add:
    if platform.system() == 'Windows':
        # Use solo pool (single-threaded) for simplicity
        # Or uncomment the next line to use threads pool instead
        # worker_args.append('--pool=threads')
        pass

    print(f"Starting Celery worker on {platform.system()} with pool: {pool_type}")
    print(f"Command: celery -A app.core.celery_app {' '.join(worker_args)}")

    # Start the worker
    celery_app.worker_main(argv=worker_args)

if __name__ == '__main__':
    run_worker()