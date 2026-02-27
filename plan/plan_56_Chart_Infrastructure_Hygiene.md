---
level: 3
file_id: plan_56
parent: plan_53
status: completed
created: 2026-02-18 10:41
estimated_time: 90 minutes
---

# Task: Consolidate Chart Infrastructure and Fix Text Artifacts

## Task Overview

### Task Description
Consolidate chart registration and plugin configuration to a single consistent approach across the app, and remove text/encoding artifacts in chart tooltips and annotations.

### Task Purpose
Eliminate runtime warnings, avoid inconsistent chart behavior across pages, and ensure UI text renders correctly.

---

## Dependencies

### Prerequisites
- **Prerequisite Tasks**: plan_42
- **Required Resources**: Current chart usage inventory and warning baseline
- **Environment Requirements**: Ability to reproduce chart warnings and verify absence after changes

### Downstream Impact
- **Downstream Tasks**: plan_58, plan_59
- **Provided Output**: Clean chart infrastructure contract and corrected tooltip text

---

## Execution Steps

### Step 1: Inventory Chart Registrations and Plugins
- **Action**: Identify where charts are registered/configured and which plugins are required by each chart.
- **Input**: Current app chart usage.
- **Output**: Plugin and registration inventory.
- **Notes**: Include all `ChartJS.register` call sites across dashboard and all chart components.

### Step 2: Define Single Registration Strategy
- **Action**: Choose and document the single registration strategy used across the app.
- **Input**: Inventory and app initialization flow.
- **Output**: Centralized chart setup contract.
- **Notes**: Avoid per-component registration drift and duplicate plugin registration.

### Step 3: Fix Tooltip/Text Encoding Artifacts
- **Action**: Replace corrupted tooltip characters and standardize annotation strings.
- **Input**: Known artifact strings and UX copy style.
- **Output**: Correctly rendered tooltip/annotation strings.
- **Notes**: Prefer plain text over decorative symbols when stability is uncertain.

### Step 4: Verify No-Warning Baseline
- **Action**: Verify charts render without warnings and the tooltip text is correct.
- **Input**: Manual smoke and test runs.
- **Output**: Verified clean console baseline.
- **Notes**: Include at least one chart for each required plugin feature, including capacity, quality, and testing dashboards.

---

## Visualization Aids

### Step Flowchart
```mermaid
flowchart TD
    A[Inventory registrations/plugins] --> B[Define single strategy]
    B --> C[Fix text artifacts]
    C --> D[Verify no warnings]
```

### Dashboard System Flow (Chart Infra)
```mermaid
flowchart LR
    Setup[Central chart setup] --> Charts[All dashboard charts]
    Charts --> UX[Consistent rendering + tooltips]
```

### Core Metrics Mapping (Infrastructure Hygiene)
| Concern | Symptom | Mitigation | Acceptance Signal |
| --- | --- | --- | --- |
| Missing plugin registration | runtime warnings | central setup contract | no warnings |
| Duplicate registration | inconsistent behavior | single strategy | consistent charts |
| Encoding artifacts | corrupted tooltip text | standardized strings | clean rendering |

### Risk Monitoring Table
| Risk Item | Level | Trigger Signal | Mitigation Strategy | Owner |
| --- | --- | --- | --- | --- |
| Central setup change affects other charts | Medium | regressions on other pages | validate `Dashboard`, `VelocityChart`, `QualityDashboard`, `TestAnalyticsDashboard`, `CFDVisualization` render paths | AI-agent |
| Removing symbols changes UX copy expectations | Low | feedback about visuals | use consistent copy standards | AI-agent |

### File Operations List

#### Files to Create
 - No new files required (current scope)

#### Files to Modify
- `frontend/src/chart.ts`
  - Modification Location: app initialization chart configuration
  - Modification Content: unified registration and plugin set
  - Modification Reason: eliminate drift and warnings
- `frontend/src/components/VelocityChart.tsx`
  - Modification Location: chart tooltip/annotation text
  - Modification Content: replace corrupted artifacts with stable text
  - Modification Reason: encoding correctness
- `frontend/src/components/quality/QualityDashboard.tsx`
  - Modification Location: chart registration line and plugin assumptions
  - Modification Content: remove local `ChartJS.register` and align plugin usage with shared setup
  - Modification Reason: eliminate cross-page duplicate registrations
- `frontend/src/components/testing/TestAnalyticsDashboard.tsx`
  - Modification Location: chart registration line and plugin assumptions
  - Modification Content: remove local `ChartJS.register` and align plugin usage with shared setup
  - Modification Reason: eliminate cross-page duplicate registrations
- `frontend/src/components/capacity/CFDVisualization.tsx`
  - Modification Location: chart registration line and plugin assumptions
  - Modification Content: remove local `ChartJS.register` and align plugin usage with shared setup
  - Modification Reason: eliminate cross-page duplicate registrations
- `frontend/src/pages/Dashboard.tsx`
  - Modification Location: chart registration line and plugin usage
  - Modification Content: remove local duplicate registration and consume shared chart setup
  - Modification Reason: keep registration central for dashboard rendering

#### Files to Read
- `frontend/src/pages/Dashboard.tsx`
  - Read Purpose: confirm which plugins/features are required
  - Usage: avoid breaking other pages
- `frontend/src/components/quality/QualityDashboard.tsx`
  - Read Purpose: confirm plugin requirements for quality charts
  - Usage: keep shared setup minimal and complete
- `frontend/src/components/testing/TestAnalyticsDashboard.tsx`
  - Read Purpose: confirm plugin requirements for testing charts
  - Usage: keep shared setup minimal and complete
- `frontend/src/components/capacity/CFDVisualization.tsx`
  - Read Purpose: confirm plugin requirements for CFD charts
  - Usage: keep shared setup minimal and complete

## Acceptance Criteria

### Functional Acceptance
- Warning `filler plugin` no longer appears in dashboard and shared chart component console output.
- Tooltip text contains plain UTF-8 text for all annotation labels.
- No duplicate `ChartJS.register` calls remain in dashboard or shared chart component files (`Dashboard`, `VelocityChart`, `QualityDashboard`, `TestAnalyticsDashboard`, `CFDVisualization`).

### Technical Acceptance
- `frontend/src/chart.ts` becomes authoritative registration module.
- `frontend/src/pages/Dashboard.tsx` and chart components consume shared chart setup only.
- Plugin list in shared setup aligns with actual feature usage across the updated files.


