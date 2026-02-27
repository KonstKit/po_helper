# Dashboard Handover

## Scope
This handover summarizes the stabilization work from `plan_40` dashboard refactor tracks and the operational baseline for future changes.

## Changelog
- Closed dashboard refactor modules (`plan_41`, `plan_45`, `plan_49`, `plan_53`, `plan_57`) after acceptance evidence in code/tests.
- Centralized dashboard runtime warning emission in `frontend/src/pages/dashboard/dashboardSignalEmitter.ts`.
- Bound all guardrail signals to `DASHBOARD_GUARDRAIL_TARGETS` as the single source of signal strings.
- Added request race protection in `frontend/src/pages/Dashboard.tsx`:
  - abort/cancel in-flight metrics requests on project/filter switches
  - stale response guard via request-id latch
- Added versioned persistence contract and migration:
  - `dashboard_contract_version` (`v2`)
  - canonical key migration + invalid-value normalization
- Added task-scope anomaly warning for inconsistent scope metadata.
- Added API boundary normalization for analytics contracts:
  - `normalizeVelocityResponse`
  - `normalizeBurndownResponse`
- Added focused CI gate `dashboard-gate` in `.github/workflows/quality.yml`.

## Known Limits
- Guardrail warnings are diagnostics only; they do not block rendering.
- Perf regression tests use 1k synthetic tasks; they are representative but not a substitute for full production telemetry.
- `dashboard-gate` validates dashboard-critical tests only; full repository checks remain in existing broader gates.

## Runbook: Guardrail Diagnostics

### 1) Refresh Loop Signal
- Signal: `[DashboardGuardrails] refresh_loop_detected`
- Checklist:
  - inspect websocket event frequency and duplicates
  - verify `refreshProjectMetrics` trigger paths
  - confirm latch behavior (single warning per loop burst)

### 2) Filter/Init Budget Signals
- Signals:
  - `[DashboardGuardrails] filter_apply_budget_exceeded`
  - `[DashboardGuardrails] init_budget_exceeded`
- Checklist:
  - review selector/derivation hot paths
  - review project/task scope sizes and pagination bounds
  - confirm no duplicate refresh paths are active

### 3) Runtime Data Warnings
- Signals: `DASHBOARD_GUARDRAIL_TARGETS.runtimeWarnings.*`
- Checklist:
  - inspect API response normalization in `contractNormalization.ts`
  - check for upstream payload drift
  - verify cancellation handling (no stale response overwrite)

### 4) Chart Warning Gate
- Signal: `dashboard_chart_warning_gate`
- Checklist:
  - verify chart registration centralization in `frontend/src/chart.ts`
  - verify plugin availability (`annotation`, `filler`) in shared setup
  - check `Dashboard` chart visibility contract and test-id coverage

## Validation Commands
- `cd frontend && npm run typecheck`
- `cd frontend && npm test -- --run src/pages/__tests__/Dashboard.test.tsx src/utils/__tests__/dashboardPerfGuards.test.ts`
- CI: trigger `dashboard-gate` workflow job and inspect uploaded artifacts.
