# Frontend Regression & Validation (plan_79)

Frontend panel and interaction coverage for the traceability production-completion
work, plus the new operator surfaces (rules management, review queue).

## Runner availability (plan_79 Step 1A)

The frontend test runner is **Vitest** (`frontend/package.json` → `npm test`).
A Node 20 runtime is available on this host
(`AppData/Local/po-helper-node/node-v20.19.0-win-x64`), so the suite **was run
here — it is NOT a handoff.**

```bash
cd frontend
node ./node_modules/vitest/vitest.mjs run                      # full suite
node ./node_modules/vitest/vitest.mjs run --no-file-parallelism # deterministic (see flake note)
```

**Result: 172 passed / 0 failed across 28 test files** (serial run).

### Parallel-run flake (pre-existing, infra)

Under default file-parallelism on a busy host, a couple of **pre-existing** page
tests (`Traceability.test.tsx`, `TraceabilityFlowBuilder.test.tsx`) intermittently
time out during the heavy (~150s) collect phase — the failing set changes between
runs and each passes in isolation. Run with `--no-file-parallelism` (or raise
`testTimeout`) on resource-constrained machines / CI. This is a test-runner
timing issue, not a correctness regression, and predates this work.

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
| `components/SuggestedLinksPanel.test.tsx` | suggestions list, approve/reject (dialog), generate, status filter re-query | loading, empty, error, success, actions (plan_72 FE) |
| `components/traceability/MatrixExportDialog.test.tsx` | export start → progress poll → completed download / failed | form, processing, completed, failed, download (plan_75 FE) |
| `components/traceability/TraceabilityGraph.test.tsx` | D3 graph: node labels, `g.node` count, `N nodes`/`N links` stat chips, onNodeClick datum | loading, empty (0/0), error, success, refresh, direction filter, node click |
| `components/traceability/ImpactAnalysisPanel.test.tsx` | forward/backward impact, risk score/level, recommendations | initial, empty, error, success, run, artifact click |
| `components/traceability/OrphanedArtifactsPanel.test.tsx` | orphan list, by_type/by_source, create-link, type filter | loading, empty, error, success, refresh, filter |
| `components/traceability/SyncHealthDashboard.test.tsx` | health score/status, summary, source cards, project rows, detail expand | loading, empty, error+retry, success, row click |
| `components/traceability/DataConsistencyPanel.test.tsx` | health score, issue counts, section labels, dry-run fix | initial, healthy, error, success, options, preview |
| `components/traceability/ValidationPanel.test.tsx` | errors/warnings/valid states (prop-driven) | error, warning, valid/empty |
| `services/__tests__/analyticsLifecycle.test.ts` | analytics transport queue: #18 bounded backlog + event retention under repeated 404; #19 queue dropped on owner-key change (logout) | 404 window, cap, logout drop |

These assert **user-visible outcomes** (rendered rows, empty/error states,
action dispatch, semantic graph state — node/edge counts and labels, not pixels)
and keep mock payloads aligned with the backend contracts in `types.ts`.
Minimal a11y fix applied to support testability: `SuggestedLinksPanel` Status
`Select` now has a linked `labelId`.

## Pre-existing coverage (relevant)

`pages/__tests__/Traceability.test.tsx`, `TraceabilityFlowBuilder.test.tsx`
(validation/template/properties panels as mocked children), `Dashboard.test.tsx`,
`utils/__tests__/ruleValidation.test.ts`, `services/api/__tests__/contractNormalization.test.ts`.

## Residual UI risk register

Previously-listed gaps are now **closed** (suggestions panel, matrix export
dialog, and D3 visualization all have semantic component tests above). Remaining:

- **Parallel-run flake**: see the note above — run `--no-file-parallelism` on
  busy hosts. Pre-existing, not a correctness issue.
- **Browser smoke** (graph/matrix visually not blank, responsive layout at
  mobile/desktop widths) remains a separate manual/visual release gate — jsdom
  asserts semantic state, not real layout/paint.
- **TraceabilityVisualization page** integration (tabs wiring the panels) is
  covered indirectly via the per-panel tests, not a full page-level test.
