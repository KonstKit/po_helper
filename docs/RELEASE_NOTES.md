# Release Notes

## 2025-09-30

### Security & Authentication
- Enforced frontend route guarding with reusable RequireAuth component to prevent anonymous access.
- Added logout cache clearing to wipe project/task/sprint data immediately after sign out.
- Moved backend credential encryption to AES-GCM with legacy Fernet support.
- Introduced scripts/generate_secret_key.py to streamline secure key rotation.

### Stability & Performance
- Fixed Project Detail infinite loading/stack overflow with robust error handling, retry UI, and deterministic GitLab search pagination.
- Added SQL indexes on 	asks.project_id, 	asks.sprint_id, and worklogs.task_id to accelerate common queries.
- Exposed database pool configuration (DB_POOL_SIZE, DB_POOL_MAX_OVERFLOW, etc.) and applied them to the async engine.
- Logged environment name/version at startup and forced DEBUG off when running in production.

### Platform Improvements
- Added ENVIRONMENT setting with validation and helper getters (is_production, etc.).
- Documented deployment workflow including secret generation, migrations, and service startup.
- Centralised environment helpers in the frontend for consistent dev/prod behaviour.
- Refreshed docker-compose stack to consume shared `.env` files, expose ENVIRONMENT/DB pool settings, and run the backend via configurable Uvicorn workers.
- Added Playwright smoke tests (frontend login + backend health) under `e2e/playwright` with documented configuration.
- Optional Sentry instrumentation for FastAPI/Celery with DSN & sampling controls via environment variables.
- Initial GitHub API client and `/git/github/projects/{id}/pulls` endpoint for active PR listings.
- Analytics dashboard now shows live GitHub pull requests when integration is configured.

Refer to previous release documents or commit history for earlier changes.
