# Frontend Regression & Validation (plan_79)

Frontend panel and interaction coverage for the traceability production-completion
work, plus the new operator surfaces (rules management, review queue).

## Runner availability (plan_79 Step 1A)

The frontend test runner is **Vitest** (`frontend/package.json` → `npm test`).
At authoring time the host had **no Node/npm**, and the **Docker daemon was not
running**, so a green run could not be produced in-session. Per the plan_79
constraint this is recorded as an **infrastructure handoff, not a failure**.

Run the suite in any environment with Node 18+ (or the documented Docker tooling
container):

```bash
cd frontend
npm install
npm run typecheck   # tsc --noEmit
npm test -- --run   # vitest
```

Docker-only path (no local Node):

```bash
docker compose -f docker-compose.pohelper.deploy.yml --profile tools up -d frontend-tooling
docker compose -f docker-compose.pohelper.deploy.yml --profile tools exec frontend-tooling npm run typecheck
docker compose -f docker-compose.pohelper.deploy.yml --profile tools exec frontend-tooling npm test -- --run
```

## New code (this work)

| Area | File |
| --- | --- |
| Review queue API client (list/get/claim/resolve/reject/reopen) | `src/services/api/traceability.ts` + types in `types.ts` |
| Rules management page | `src/pages/RulesManagement.tsx` |
| Review queue page | `src/pages/ReviewQueue.tsx` |
| Routes + nav entries | `src/App.tsx`, `src/components/Layout.tsx` |

## New tests (this work)

| Test | Covers | States |
| --- | --- | --- |
| `pages/__tests__/RulesManagement.test.tsx` | rule list, enable/disable, duplicate, delete confirm + 409 cascade error, builder routing | loading, empty, error+retry, success, actions |
| `pages/__tests__/ReviewQueue.test.tsx` | review list, claim/resolve/reject, refetch | loading, empty, error+retry, success, actions |
| `services/api/__tests__/reviewQueueApi.test.ts` | review client URL/param/body mapping (contract) | n/a |

These assert **user-visible outcomes** (rendered rows, empty/error states,
action dispatch) and keep mock payloads aligned with the backend contract
(`ReviewItem`, `TraceabilityRule`). Mocks are the source-of-truth shapes returned
by the backend endpoints validated in `TRACEABILITY_BACKEND_VALIDATION.md`.

## Pre-existing coverage (relevant)

`pages/__tests__/Traceability.test.tsx`, `TraceabilityFlowBuilder.test.tsx`
(validation/template/properties panels as mocked children), `Dashboard.test.tsx`,
`utils/__tests__/ruleValidation.test.ts`, `services/api/__tests__/contractNormalization.test.ts`.

## Residual UI risk register (handed off)

- **Green run**: not executed in-session (no Node/npm, Docker daemon down). Must
  be run by CI or a developer environment before release.
- **Suggestions panel & Matrix export dialog**: backend workflows are covered by
  service/API tests; dedicated component interaction tests were not added here
  and remain a recommended follow-up.
- **D3 visualization (`TraceabilityGraph`)**: semantic-state assertions (node /
  edge counts, empty / error states) are recommended but not added — D3 render
  tests are best authored against a live runner to avoid brittle mocks.
- **Browser smoke** (graph/matrix not blank, responsive layout) remains a
  separate manual/visual release gate.
