# Deployment Guide

This guide describes how to promote PO Helper from a local workstation to staging or production environments.

## 1. Prerequisites
- Python 3.11+
- Node.js 18+ and npm
- PostgreSQL 14+ (production/staging); SQLite is only supported for local development
- Redis 6+ (for Celery broker/result backend)
- Recommended: Nginx or another reverse proxy, systemd service units, and TLS termination

## 2. Repository Preparation
`ash
# Clone repository and install submodules if any
$ git clone <repo-url>
$ cd po_helper
`

Create and activate the Python virtual environment:
`ash
$ python -m venv .venv
$ .\.venv\Scripts\activate  # Windows PowerShell
$ pip install -r backend/requirements.txt
`

Install frontend dependencies:
`ash
$ cd frontend
$ npm install
$ cd ..
`

## 3. Environment Configuration
Copy the example environment files and populate production values:
`ash
$ copy .env.example .env
$ copy backend\.env.example backend\.env
`

Key settings to review:

| Variable | Description |
| --- | --- |
| ENVIRONMENT | production, staging, or development |
| SECRET_KEY | JWT signing key (generate below) |
| ENCRYPTION_SECRET | Optional key for stored credentials (defaults to SECRET_KEY) |
| DB_POOL_SIZE, DB_POOL_MAX_OVERFLOW, DB_POOL_TIMEOUT, DB_POOL_RECYCLE, DB_POOL_PRE_PING | Tune SQLAlchemy connection pool |
| DATABASE_URL | PostgreSQL connection string |
| REDIS_URL | Redis instance URL |
| CELERY_ENABLED and broker/result settings | Required for background sync |
| Integration secrets | Jira/Confluence/TestRail/GitHub/GitLab tokens |

### Generate Secure Keys
Use the helper script to create strong keys:
`ash
$ python backend/scripts/generate_secret_key.py --write
`
Re-run with --force when rotating secrets.

## 4. Database Setup
1. Create the PostgreSQL database and user referenced by DATABASE_URL.
2. Apply Alembic migrations:
`ash
$ cd backend
$ alembic upgrade head
$ cd ..
`

## 5. Static Assets
Build the production frontend bundle:
`ash
$ cd frontend
$ npm run build
$ cd ..
`
The output in rontend/dist/ can be served via your reverse proxy or copied to object storage/CDN.

## 6. Docker Compose
```bash
$ docker compose --env-file .env up --build
```
This command builds the backend/frontend images, runs PostgreSQL/Redis dependencies, and starts the backend, frontend, and Celery services with the environment variables from `.env` and `backend/.env`.

Use `docker compose down` to stop all services. For production, map secrets via an external secrets manager or override the `.env` files passed to Compose.

## 7. Running the Services
### FastAPI (Uvicorn / Gunicorn)
Example using uvicorn directly:
`ash
$ cd backend
$ .\.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
`
For production, prefer gunicorn with uvicorn.workers.UvicornWorker behind a process manager (systemd, Supervisor).

### Celery Worker
If CELERY_ENABLED=true:
`ash
$ cd backend
$ celery -A app.core.celery_app worker --loglevel=info
`

### Frontend (Optional Dev Server)
For staging without a separate static host:
`ash
$ cd frontend
$ npm run preview -- --host 0.0.0.0 --port 4173
`

## 8. Health Checks and Monitoring
- Backend health endpoint: GET /health
- Configure logging via LOG_LEVEL and centralize logs (e.g., to CloudWatch, ELK).
- Consider enabling Sentry or equivalent; .env.example contains placeholders.

## 9. Post-Deployment Tasks
- Seed initial admin user if needed (see API docs or admin CLI).
- Verify Jira/Confluence integrations by running manual sync from the UI.
- Monitor database connection usage to validate pool sizing.

## 10. Upgrade Checklist
When applying updates:
1. Pull latest code and install dependencies.
2. Review release notes (see docs/RELEASE_NOTES.md).
3. Regenerate secrets if instructed.
4. Run lembic upgrade head.
5. Rebuild frontend assets.
6. Restart backend, worker, and proxy services.

Follow this checklist for each environment (development → staging → production) and maintain backups before major migrations.
