# Dashboard UI Contract

## Scope
This document defines the stabilized dashboard surface after refactors:
- `plan_41` (UI consolidation)
- `plan_45` (filters and interaction semantics)

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

## Filter Contract
- `Date Range`:
  - Affects KPI summary, velocity trend, risk alerts, and upcoming list.
  - Uses task `resolved_date` as primary activity timestamp with fallback to `updated_date`.
  - Does not affect sprint-scoped burndown and WIP widgets.
- `Chart View`:
  - `velocity` -> velocity only.
  - `burndown` -> burndown only.
  - `both` -> velocity + burndown.
  - `distribution` -> task distribution only.
- `Quick Filters` (selection shortcuts, no aggregation):
  - `all` keeps dashboard in single-project mode with full project list available.
  - `active` picks active projects (`status === active` or `state === active`) deterministically.
  - `recent` uses persisted LRU project ids, then deterministic fallback.

## Persistence Contract
- Storage keys:
  - `dashboard_date_range`
  - `dashboard_chart_view`
  - `dashboard_quick_filter`
  - `dashboard_recent_project_ids`
  - `dashboard_last_project_id`
- Defaults:
  - `dateRange = 30d`
  - `chartView = both`
  - `quickFilter = recent`

## Velocity Mapping Contract
Date range maps to backend `sprints_count`:
- `7d -> 2`
- `14d -> 3`
- `30d -> 5`
- `90d -> 8`
- `180d -> 12`
- `365d -> 16`
- `all -> 20`

## Task Scope Contract
- Project-scoped task loading uses bounded pagination.
- Scope metadata is tracked per project (`taskScopeByProject`):
  - `total`
  - `fetched`
  - `hasNext`
  - `isPartial`
  - `capHit`
- Partial scope must be explicit in UI and never silently treated as full coverage.

## Sprint/WIP Contract
- Active sprint resolution is normalized through `frontend/src/utils/sprintNormalization.ts`.
- Canonical sprint identifier precedence:
  - `sprint_id`
  - fallback `id`
- Active sprint precedence:
  - `state === active`
  - fallback `status === active`
  - fallback date-window match (`start_date <= now <= end_date`)
  - fallback latest sprint by timeline
- Sprint loading is project-scoped only (`loadAllSprints` requires `projectId`).
- WIP widget states are explicit:
  - `no_sprint`: show `--` + `No active sprint`
  - `loading`: show `N/A` + loading message
  - `ready`: show numeric active WIP + limit
  - `not_available`: show `N/A` + unavailable message
  - `error`: show `N/A` + endpoint failure message

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
- Scope:
  - `dashboard-partial-scope`

## State Contract
- No project:
  - Explicit empty state via `EmptyState` component.
- Loading:
  - Full-page `DashboardSkeleton` only when no project context exists yet.
  - Section-level loading placeholders when project context exists.
- Error:
  - Non-blocking alert with retry action.
  - Drilldown and unaffected sections remain available.
