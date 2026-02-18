---
level: 3
file_id: plan_60
parent: plan_57
status: pending
created: 2026-02-18 10:41
estimated_time: 120 minutes
---

# Task: Add Observability and Performance Guardrails

## Task Overview

### Task Description
Add lightweight observability and performance guardrails for the dashboard to detect refresh loops, slow renders, and reintroduction of noisy warnings or broken data flows.

### Task Purpose
Reduce time-to-diagnosis and prevent gradual degradation of dashboard quality over time.

---

## Dependencies

### Prerequisites
- **Prerequisite Tasks**: plan_59
- **Required Resources**: Current logging/telemetry conventions and performance baseline
- **Environment Requirements**: Ability to measure typical dashboard load and interaction durations

### Downstream Impact
- **Downstream Tasks**: Release readiness checks
- **Provided Output**: Guardrails and signals that detect regressions early

---

## Execution Steps

### Step 1: Define Guardrail Targets
- **Action**: Define which signals matter: repeated refresh loops, slow filter application, and chart warning reappearance.
- **Input**: Known risk list and performance baseline.
- **Output**: Guardrail target list.
- **Notes**: Keep targets minimal and actionable.

### Step 2: Add Observable Signals
- **Action**: Add lightweight signals consistent with existing conventions (logs/metrics/events).
- **Input**: Guardrail target list.
- **Output**: Observable dashboard behavior signals.
- **Notes**: Avoid excessive logging.

### Step 3: Add Performance Budgets
- **Action**: Define and enforce basic performance budgets for key interactions (initial load, filter changes).
- **Input**: Baseline measurements.
- **Output**: Budget thresholds and enforcement approach.
- **Notes**: Use a deterministic, bounded aggregator (rolling window of durations) so tests can deterministically verify threshold behavior independent of wall-clock jitter.

### Step 4: Verification and Documentation
- **Action**: Validate signals appear as expected and document how to use them in diagnosis.
- **Input**: Guardrail implementation.
- **Output**: Verified guardrails and usage notes.
- **Notes**: Coordinate with QA and release readiness.

---

## Visualization Aids

### Step Flowchart
```mermaid
flowchart TD
    A[Define guardrail targets] --> B[Add observable signals]
    B --> C[Add performance budgets]
    C --> D[Verify + document]
```

### Dashboard System Flow (Observability)
```mermaid
flowchart LR
    Events[Dashboard Events] --> Signals[Logs/Metrics]
    Signals --> Diagnose[Diagnosis Workflow]
    Diagnose --> Fix[Actionable Remediation]
```

### Core Metrics Mapping (Guardrails)
| Guardrail | Signal | Trigger | Response |
| --- | --- | --- | --- |
| Refresh loop | repeated refresh events | frequency threshold | investigate realtime + refresh rules |
| Slow filter apply | duration metric | exceeds 300ms p95 on 1k-task dataset | optimize derived computations |
| Chart warnings | warning gate | warning detected | fix plugin/registration drift |
| Init regression | dashboard init duration | exceeds 700ms p95 over last 20 samples | investigate startup path and network fan-out |

### Risk Monitoring Table
| Risk Item | Level | Trigger Signal | Mitigation Strategy | Owner |
| --- | --- | --- | --- | --- |
| Too much telemetry noise | Low | logs become noisy | keep signals minimal | AI-agent |
| Budgets create flaky gates | Medium | inconsistent timing | use trend-based validation | AI-agent |

### File Operations List

#### Files to Create
- `docs/dashboard-observability.md`
  - Type: documentation
  - Purpose: guide diagnosis using dashboard signals
  - Content: signal definitions and troubleshooting steps
  - Provisioning Note: create `docs/` directory first if it does not exist in the target workspace
- `frontend/src/utils/dashboardPerfGuards.ts`
  - Type: utility module
  - Purpose: deterministic p95 budget tracking with fixed sample window
  - Content: rolling buffer + helper functions for `recordDuration` and `isAboveBudget`
- `frontend/src/utils/__tests__/dashboardPerfGuards.test.ts`
  - Type: unit tests
  - Purpose: validate p95 math and budget enforcement behavior
  - Usage: guarantee guardrail checks without flaky timing in CI

#### Files to Modify
- `frontend/src/pages/Dashboard.tsx`
  - Modification Location: load/refresh/filter pathways
  - Modification Content: emit minimal signals + duration tracking via `dashboardPerfGuards`; wire warning signals to existing toast/log helpers
  - Modification Reason: early regression detection

#### Files to Read
- `frontend/src/pages/ProjectDetail.tsx`
  - Read Purpose: align instrumentation with app standards
  - Usage: avoid creating a parallel telemetry style

## Acceptance Criteria

### Functional Acceptance
- Dashboard exposes consistent signal/trace points for:
  - refresh frequency
  - filter application duration
  - chart render warnings
- Guardrails never break normal interaction flow when events are absent.

### Technical Acceptance
- No new high-volume logs are introduced for every render tick.
- Performance thresholds are measurable, deterministic, and test-enforced: `filter_apply_ms_p95 <= 300`, `dashboard_init_ms_p95 <= 700` via `dashboardPerfGuards`.
- Regression tests include a synthetic p95-budget test that marks a violation when synthetic durations exceed thresholds.

- `docs/dashboard-observability.md` is added under existing docs structure and includes all new metrics and thresholds.

