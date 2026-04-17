# Frontend Verification Runbook

Use `scripts/verify_frontend.py` as the single entry-point for frontend verification.
It supports:
- `docker` engine (existing `frontend-tooling` container),
- `local` engine (system Node.js),
- `auto` engine (prefers Docker, falls back to local tooling and can bootstrap portable Node.js).

## Prerequisites

- Repository checked out at the project root
- For `--engine docker`: Docker with Compose v2 and a running Docker Engine
- For `--engine local` or fallback `--engine auto`: Python 3 and network access for one-time portable Node bootstrap

## Commands

Run both verification steps:

```powershell
python scripts/verify_frontend.py --mode all
```

Force local execution:

```powershell
python scripts/verify_frontend.py --engine local --mode all
```

Force Docker execution:

```powershell
python scripts/verify_frontend.py --engine docker --mode all
```

Run only typecheck:

```powershell
python scripts/verify_frontend.py --mode typecheck
```

Run only lint:

```powershell
python scripts/verify_frontend.py --mode lint
```

When Docker is available and running, the wrapper uses this container command:

```powershell
docker compose -f docker-compose.dev.yml run --rm frontend-tooling sh -lc "npm ci && npm run typecheck && npx eslint \"src/**/*.{ts,tsx,js,jsx}\" --no-error-on-unmatched-pattern"
```

When Docker is unavailable and local `node/npm` are missing, `--engine auto` (default) can bootstrap a portable Node.js toolchain into:
- Windows: `%LOCALAPPDATA%\po-helper-node`
- Linux/macOS: `~/.cache/po-helper-node`

Disable bootstrap if needed:

```powershell
python scripts/verify_frontend.py --engine local --no-bootstrap-local-node
```

## Notes

- `npm ci` runs before verification in both engines for reproducibility.
- If you need a different compose file, pass `--compose-file docker-compose.yml` or another path.
- If you need a custom frontend directory (monorepo layout), use `--frontend-dir <path>`.
