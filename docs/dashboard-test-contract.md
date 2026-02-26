# Dashboard Test Contract

## Purpose
This document locks the stable dashboard test contract for `plan_58` and the regression scenarios in `plan_59`.

## Stable Identifiers
The source of truth is `frontend/src/pages/dashboard/dashboardContract.ts` (`DASHBOARD_TEST_IDS`).

Key surfaces:
- Page and layout: `page`, `sectionCharts`, `sectionInsights`, `sectionStats`
- Filters: `filterProject`, `filterDateRange`, `filterChartView`
- Charts: `chartVelocity`, `chartBurndown`, `chartDistribution`
- Insights: `riskPanel`, `riskItem`, `upcomingPanel`, `upcomingItem`
- Stats: `cardTotal`, `cardCompleted`, `cardInProgress`, `cardBlockers`, `cardBudget`, `cardRoi`, `cardWip`
- Other: `partialScopeBadge`, `drilldownItem`

## Selector Migration Map
| Legacy Selector Pattern | Behavior Intent | Current Contract |
| --- | --- | --- |
| `[data-testid^="dashboard-risk-item-"]` | risk row exists and opens drilldown | `DASHBOARD_TEST_IDS.riskItem` + dialog/drilldown assertions |
| `[data-testid="dashboard-upcoming-item"]` via direct DOM query | upcoming list reacts to filters | `findAllByTestId(DASHBOARD_TEST_IDS.upcomingItem)` |
| inline literals (`dashboard-chart-*`, `dashboard-filter-*`, `card-wip`) | chart/filter/WIP behavior checks | `DASHBOARD_TEST_IDS.*` |

## Usage Rules
- Import `DASHBOARD_TEST_IDS` in dashboard tests and components instead of hardcoded test-id strings.
- Prefer behavior assertions (visible state transitions, scoped outcomes) over layout shape assertions.
- For list-like dashboard surfaces, use stable repeated IDs (`riskItem`, `upcomingItem`) instead of index-suffixed IDs.
- Warning gates must use scoped dashboard warning signatures, not generic global warning suppression.
