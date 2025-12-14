@echo off
echo Starting Celery Worker for Windows...
echo =====================================

REM Activate virtual environment
call .venv\Scripts\activate

REM Set Python path
set PYTHONPATH=%cd%

REM Run Celery worker with solo pool (Windows-compatible)
echo Running with solo pool (single-threaded)...
celery -A app.core.celery_app worker --loglevel=info --pool=solo

REM Alternative: Use threads pool for concurrent execution
REM echo Running with threads pool (multi-threaded)...
REM celery -A app.core.celery_app worker --loglevel=info --pool=threads --concurrency=4

pause