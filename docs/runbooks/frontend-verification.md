# Frontend Verification Runbook

Use the repository's existing `frontend-tooling` container when local `node/npm` is not available.

## Prerequisites

- Docker with Compose v2
- Repository checked out at the project root

## Commands

Run both verification steps:

```powershell
python scripts/verify_frontend.py --mode all
```

Run only typecheck:

```powershell
python scripts/verify_frontend.py --mode typecheck
```

Run only lint:

```powershell
python scripts/verify_frontend.py --mode lint
```

The wrapper uses this container command under the hood:

```powershell
docker compose -f docker-compose.dev.yml run --rm frontend-tooling sh -lc "npm ci && npm run typecheck && npx eslint \"src/**/*.{ts,tsx,js,jsx}\" --no-error-on-unmatched-pattern"
```

## Notes

- The container has `node/npm` preinstalled.
- `npm ci` runs inside the container so the verification is reproducible across developer machines.
- If you need a different compose file, pass `--compose-file docker-compose.yml` or another path.
