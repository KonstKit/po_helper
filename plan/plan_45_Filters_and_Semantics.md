---
level: 2
file_id: plan_45
parent: plan_40
status: pending
created: 2026-02-18 10:41
children: [plan_46, plan_47, plan_48]
---

# Module: Filters and Interaction Semantics

## Module Overview

### Module Goal
Make dashboard filters meaningful by defining explicit semantics (what each filter means, which panels it affects, and how it persists) and applying them consistently across KPIs, charts, lists, and widgets.

### Position in Project
This module turns the filter UI from a placeholder into a reliable interaction contract. It also prevents future drift by documenting scope and adding regression expectations.

---

## Dependencies

### Prerequisites
- **Prerequisite Tasks**: plan_41
- **Prerequisite Data**: Current filter UI inventory and expected user workflows
- **Prerequisite Environment**: Minimum 2 projects and 2000 tasks with controlled pagination pages

### Downstream Impact
- **Downstream Tasks**: plan_53, plan_57
- **Output Data**: Stable filter semantics contract and consistent application across dashboard outputs

### External Dependencies
- **Third-Party Services**: External data providers and sync cadence (as configured)
- **Database**: Existing persisted datasets with timestamps and sprint metadata
- **API Interfaces**: Existing endpoints providing project/task/sprint analytics

---

## Subtask Breakdown

- [ ] plan_46 - Define Filter Semantics & Persistence (estimated 90 minutes)
  - Brief: Specify meaning and scope for date range, chart view, and project quick filters.
- [ ] plan_47 - Apply Date Range & Chart View End-to-End (estimated 180 minutes)
  - Brief: Ensure filters affect all computed metrics and visible sections consistently.
- [ ] plan_48 - Implement Project Quick Filters Behavior (estimated 120 minutes)
  - Brief: Make "all/active/recent" behavior real and non-misleading.

## Execution Steps

### Step 0: Fix Task Data Scope Before Filter Semantics
- **Action**: Implement the chosen deterministic task data strategy that avoids default pagination truncation.
- **Input**: dashboard task-derived panel list and existing `listTasks` usage.
- **Output**: project-scoped bounded pagination with explicit partial-mode metadata.
- **Notes**: filter claims are blocked until dashboard task scope is deterministic.
- **Implementation Contract**: add/adjust a bounded fetch loop with `listTasksPaginated` (`skip += limit`) until `meta.has_next === false` or explicit cap (`maxPages` or `maxTotalTasks`) and persist scope metadata (`taskScope.total`, `taskScope.fetched`, `taskScope.isPartial`) by project context.
- **Implementation Contract (guardrail)**: only project-scoped calls may enable full pagination. Calls without `projectId` must remain bounded to the existing lightweight behavior; startup bootstrap (`initializeAppData`) must not trigger full pagination.
- **Implementation Contract (recommended path)**: use project-scoped `taskScopeByProject` and allow `loadAllTasks({ projectId })` cache skip only when cached scope exists and `taskScopeByProject[projectId].isPartial === false`.
- **Implementation Contract (bootstrap safety)**: unscoped bootstrap task loads must not mark project-scoped freshness entries (`lastLoadedAtByProject`) to avoid poisoning dashboard project caches.

---

## Visualization Output

### Module Flowchart
```mermaid
flowchart LR
    A[Define semantics] --> B[Document scope]
    B --> C[Apply to computations]
    C --> D[Apply to rendering]
    D --> E[Validate + add regression expectations]
```

### Dashboard Data Source and Pagination Contract
| Input Surface | Canonical Source | Risk if Misused |
| --- | --- | --- |
| KPI/analytics (velocity, risks, burndown for charts) | `/v1/analytics/...` endpoints with project and sprint context | Incomplete or duplicated summaries |
| Task-derived counts/lists (`upcoming`, `distribution`, risk scoring) | `listTasksPaginated` with deterministic `skip/limit` plan, or backend aggregate endpoint for full-project totals | Filter semantics become non-deterministic when only first 50 tasks are loaded |

Current state: existing dashboard logic reads all tasks from `listTasks` defaults and therefore only receives first page (`skip=0`, `limit=50`). Full deterministic scope is required before enabling any filter behavior claims.

Chosen strategy: fetch all dashboard-relevant tasks via `listTasksPaginated` loops for the active project and expose scope metadata (`total`, `fetched`, `hasNext`, `isPartial`) for explicit partial-mode labeling.

### Dashboard System Flow (Filter-Centric)
```
+------------------+     +--------------------+     +----------------------+
| Filter Controls  | --> | Semantics Contract | --> | Derived Computations |
+------------------+     +--------------------+     +----------+-----------+
                                                               |
                                                               V
                                                     +------------------+
                                                     | Rendered Panels  |
                                                     +------------------+
```

### Core Metrics Mapping (Filter Scope)
| Filter | Scope (Panels) | Primary Effect | Non-Effect (Explicit) | Persistence |
| --- | --- | --- | --- | --- |
| Date range | KPIs, velocity, risks, upcoming | timeseries + list windowing rules | burndown, WIP, project selector defaults | saved |
| Chart view | chart and chart labels | visibility + source selection | KPI/action list content | saved |
| Project quick filter | project context + derived panel source inputs | selected project set and source scope | unrelated panel memory (toasts/notifications) | saved |

### Interface Collaboration Diagram
```mermaid
sequenceDiagram
    participant U as User
    participant F as Filters
    participant C as Semantics Contract
    participant D as Dashboard Sections
    U->>F: Change filter
    F->>C: Update selection
    C-->>D: Provide scoped inputs
    D-->>U: Render updated metrics
```

### Resource Allocation Table
| Resource Type | Owner | Time Window | Key Output | Risk/Notes |
| --- | --- | --- | --- | --- |
| Frontend engineer | AI-agent | one execution pass | semantics + application | avoid partial application |
| Product/QA reviewer | QA engineer | one execution pass | validate semantics with user flows | prevent misleading UX |

---

## Technical Solution

### Architecture Design
Define an explicit filter semantics contract and apply it uniformly to derived computations and rendering. Persistence is handled consistently to avoid surprising behavior across sessions.

### Data Model
Filter selections are first-class inputs to all derived metrics and chart/list subsets. Each dashboard section consumes scoped inputs rather than re-deriving logic independently.
Task scope is explicit and typed in the dashboard contract:
- `TaskScope = { total?: number; fetched: number; hasNext: boolean; isPartial: boolean; capHit?: boolean }`
- `PARTIAL_SCOPE_LABEL = "Showing partial data (first N tasks)"`
- `TEST_IDS.partialScopeBadge = "dashboard-partial-scope"`

### Data Scope Rule
- Dashboard task-derived panels must not use default `listTasks` limits.
- Default implementation uses `listTasksPaginated` loop with fixed bounds: `PAGE_SIZE=500`, `MAX_PAGES=40`, `MAX_TASKS=20000`.
- If full scope cannot be fetched in bounded mode, the dashboard must render explicit partial-scope state and disable completion claims for affected KPIs.
- Canonical semantics for date-range and burndown exclusions are defined in `plan_46` and enforced by `plan_47`; this module must not redefine those rules.

### File Operations List

#### Files to Modify
- `frontend/src/store/dataThunks.ts`
  - Modification Location: dashboard task fetch path and cache metadata
  - Modification Content: add deterministic full-task fetch helper with stop condition and scope counters; cache skip allowed only for complete project scope (`isPartial === false`)
  - Modification Reason: ensure one-time filters operate on complete task scope
- `frontend/src/store/taskSlice.ts`
  - Modification Location: project cache metadata and task scope state
  - Modification Content: add `taskScopeByProject` and avoid setting `lastLoadedAtByProject` from unscoped bootstrap loads
  - Modification Reason: prevent project cache poisoning from first-page/global bootstrap responses
- `frontend/src/pages/dashboard/dashboardContract.ts`
  - Modification Location: filter/task-scope contract exports
  - Modification Content: add `TaskScope`, partial-scope label, and test ids consumed by UI/tests
  - Modification Reason: keep scope semantics DRY and testable
- `frontend/src/pages/__tests__/Dashboard.test.tsx`
  - Modification Location: test fixtures and assertions
  - Modification Content: add assertions that full-task scope or partial-scope badge (`dashboard-partial-scope`) is respected
  - Modification Reason: protect against return to first-page logic

#### Files to Read
- `frontend/src/pages/dashboard/dashboardContract.ts`
  - Read Purpose: expose and consume task-scope mode labels in UI and tests
  - Usage: prevent unaligned behavior after refactors

---

## Acceptance Criteria

### Functional Acceptance
- Each filter has a documented meaning and an explicit scope.
- Changing a filter consistently changes visible outputs as expected.
- "Quick filters" do not misrepresent behavior (selection vs aggregation).
- For task-derived panels, dashboard uses project-scoped `listTasksPaginated` loops with deterministic bounds and explicit scope metadata.
- Dashboard task fetching exports deterministic scope metadata (`total`, `hasNext`, `isPartial`) and never silently consumes only the first page.
- Filter-based behavior claims are incomplete unless task scope is full (`isPartial === false`) or dashboard renders explicit `partial scope` label in affected panels.

- Full pagination is only ever required when dashboard context provides `projectId`; no `initializeAppData` path should request unscoped full-task enumeration.
- `loadAllTasks({ projectId })` skips reload only when cached scope for that project is complete (`isPartial === false`) and cache TTL is valid.
- If bounded pagination hits a cap (`capHit === true`), dashboard shows `dashboard-partial-scope` badge and does not silently present partial totals as complete totals.

### Quality Acceptance
- Regression checks prevent reintroducing "filter UI that does not affect data."
- Source-of-truth and pagination behavior is implemented through `dashboardContract.ts` + tests before gates pass.


