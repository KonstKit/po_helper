# Testing Guide

## Unit & Integration Tests
- **Backend**: `cd backend && pytest`
- **Frontend**: `cd frontend && npm test`

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
