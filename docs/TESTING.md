# Testing Guide

## Unit & Integration Tests
- **Backend**: `cd backend && pytest`
- **Frontend**: `cd frontend && npm test`

### Flaky Quarantine Policy
- Mark unstable tests with explicit metadata:
  - `@pytest.mark.flaky_quarantine(issue="PLAT-123", owner="qa-platform", expires="2026-06-30")`
- Quarantined tests are skipped by default.
- To execute quarantined tests explicitly:
  - `pytest --run-flaky-quarantine`
- Collection fails when metadata is missing/invalid or when `expires` is in the past.

## End-to-End (Playwright)
1. Ensure the app is running (Docker compose or local servers) so the frontend is reachable at `http://localhost:3000` and backend at `http://localhost:8000`.
2. Install dependencies once:
   ```bash
   cd e2e/playwright
   npm install
   npx playwright install
   ```
3. Run the smoke suite:
   ```bash
   npm test
   ```

### Configuration
| Variable | Default | Description |
| --- | --- | --- |
| `E2E_BASE_URL` | `http://localhost:3000` | Frontend base URL used by Playwright |
| `E2E_API_URL` | `http://localhost:8000/health` | Backend health endpoint used for smoke check |

Use `npm run test:headed` for a headed browser or `npm run codegen` to record new flows.

## Operational Runbooks

- Frontend verification (`docker` or auto-bootstrapped local `node/npm`): [docs/runbooks/frontend-verification.md](runbooks/frontend-verification.md)
- Traceability repair artifact-count comparison: [docs/runbooks/traceability-repair-artifact-counts.md](runbooks/traceability-repair-artifact-counts.md)
- Latest frontend quality baseline snapshot: [docs/internal/frontend_quality_baseline_2026-04-17.md](internal/frontend_quality_baseline_2026-04-17.md)
