---
level: 2
file_id: plan_06
parent: plan_05
children:
  - plan_07
status: completed
created: 2024-05-26
---

# UI/UX — Matrix, Graph/Flow, Exports

## Goals
- Build RTM matrix UI with server-side pagination, column limiting, filters, drill-down.
- Provide graph/flow exploration and rule builder (React Flow).
- Enable export flows in UI with progress/status and downloads.

## Work Packages
- Matrix UI: selectors (rows/cols/link types), pagination, virtualization, drill-down panels, saved projections.
- Graph/Flow: node-link view, path highlight, filters; integrate derived links and roles.
- Rule builder: visual flow for linking rules; validation messages; preview of derived links.
- Exports UI: trigger async export, show task progress, provide download links.
- Accessibility/perf: loading states, debounce search, responsive layout.

## Visualizations
- RTM matrix wireframe (selectors, grid, drill-down behavior).
- Graph/flow mock (direction, link types).
- Sequence: user triggers export → task status → download.

## Acceptance
- Matrix UI responsive and performant on large datasets; graph/flow usable; exports flow exposed with progress and downloads.
