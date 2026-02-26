# Dashboard Observability and Guardrails

## Scope
This document describes lightweight runtime guardrails for the dashboard stability module (`plan_57`, `plan_60`).

## Source of Truth
- Guardrail target definitions: `frontend/src/pages/dashboard/dashboardGuardrails.ts`
- Performance budget tracking: `frontend/src/utils/dashboardPerfGuards.ts`

## Guardrail Signals

### Refresh Loop Detection
- Signal: `[DashboardGuardrails] refresh_loop_detected`
- Trigger: `>= 6` dashboard refresh events within `30s` (`windowMs=30000`).
- Purpose: detect accidental refresh loops caused by websocket/event/re-render cascades.
- Response:
  - inspect websocket message frequency
  - inspect `refreshProjectMetrics` call paths
  - verify no cyclical state updates were introduced

### Filter Apply Performance Budget
- Signal: `[DashboardGuardrails] filter_apply_budget_exceeded`
- Metric: `filter_apply_ms` (p95 over rolling window of 20 samples)
- Budget: `300ms`
- Purpose: detect regressions in filter responsiveness.
- Response:
  - inspect expensive selectors/derivations
  - inspect chart model rebuild paths
  - validate task-scope bounds and memoization

### Dashboard Init Performance Budget
- Signal: `[DashboardGuardrails] init_budget_exceeded`
- Metric: `dashboard_init_ms` (p95 over rolling window of 20 samples)
- Budget: `700ms`
- Purpose: detect startup degradation after dashboard refactors.
- Response:
  - inspect startup API fan-out
  - inspect initial render dependencies
  - inspect redundant initializations

### Chart Warning Reappearance Gate
- Signal: `dashboard_chart_warning_gate` (test gate)
- Trigger: warning signatures detected during healthy dashboard chart render path.
- Signature scope:
  - `filler plugin`
  - `annotation plugin`
  - `chart.js.*warning`
  - `failed to register scale`
- Purpose: prevent silent reintroduction of chart plugin/registration regressions.

## Budget Enforcement Rules
- Budget checks run against deterministic rolling p95 from `frontend/src/utils/dashboardPerfGuards.ts`.
- Each budget breach is latched: one warning per metric/budget tuple per page lifecycle.
- Missing/invalid duration samples are sanitized to `0` to avoid flaky behavior.

## Test Coverage
- Unit coverage for the perf guard utility:
  - rolling window trim
  - deterministic p95
  - breach latch behavior
  - invalid duration sanitization
- Dashboard scenario coverage (`Dashboard.test.tsx`) includes:
  - chart-view deterministic toggles
  - date-range behavior with sprint burndown semantics
  - quick-filter deterministic transitions
  - sparse velocity empty-state behavior
  - known chart-warning signature gate

## Verification Runs (2026-02-26)
- Dashboard regression tests in Docker:
  - Command profile: `vitest src/pages/__tests__/Dashboard.test.tsx --run`
  - Artifact: `artifacts/tests/plan_60_dashboard_tests.txt`
  - Result: `1 passed file`, `17 passed tests`
- Repository typecheck gate runs in Docker:
  - Artifacts:
    - `artifacts/typecheck/plan_66_repo_typecheck_run_1.txt`
    - `artifacts/typecheck/plan_66_repo_typecheck_run_2.txt`
  - Result: both runs PASS with zero TypeScript diagnostics.
- Regression lock scan:
  - Artifact: `artifacts/typecheck/plan_66_bypass_scan.txt`
  - Result: empty (`0` matches).
- Note:
  - The test artifact contains expected stderr from negative-path test (`shows WIP error state when endpoint fails`) where failure is intentionally mocked.

## Operational Notes
- Guardrails are intentionally low-noise and do not block UI flow.
- Warnings are diagnostic signals, not user-facing errors.
- Any new dashboard feature should preserve:
  - `filter_apply_ms_p95 <= 300`
  - `dashboard_init_ms_p95 <= 700`
