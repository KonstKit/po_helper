# Dashboard UI Contract

## Scope
This document defines the stabilized dashboard surface after refactor `plan_41` (UI consolidation).

## Layout Contract
- The dashboard renders exactly one composition path.
- The page is composed from three section containers:
  - `dashboard-section-charts`
  - `dashboard-section-insights`
  - `dashboard-section-stats`

Legacy sections are intentionally removed and must not reappear:
- `Risk Assessment`
- `Upcoming Focus`
- `Team Velocity` (legacy duplicate panel title)

## Stable Test Identifiers
- Root:
  - `dashboard-page`
  - `dashboard-header`
  - `dashboard-filters`
- Charts:
  - `dashboard-chart-velocity`
  - `dashboard-chart-burndown`
  - `dashboard-chart-distribution`
- Insights:
  - `dashboard-risk-panel`
  - `dashboard-risk-item-{index}`
  - `dashboard-upcoming-panel`
  - `dashboard-upcoming-item`
- Stats cards:
  - `card-total`
  - `card-completed`
  - `card-in-progress`
  - `card-blockers`
  - `card-budget`
  - `card-roi`
  - `card-wip`
- Drilldown:
  - `dashboard-drilldown-item`

## State Contract
- No project:
  - Explicit empty state via `EmptyState` component.
- Loading:
  - Full-page `DashboardSkeleton` only when no project context exists yet.
  - Section-level loading placeholders when project context exists.
- Error:
  - Non-blocking alert with retry action.
  - Drilldown and unaffected sections remain available.
