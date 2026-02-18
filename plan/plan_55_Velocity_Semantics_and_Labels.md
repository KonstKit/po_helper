---
level: 3
file_id: plan_55
parent: plan_53
status: pending
created: 2026-02-18 10:41
estimated_time: 120 minutes
---

# Task: Standardize Velocity Computation and Labels

## Task Overview

### Task Description
Standardize velocity computation so bucket labeling, time boundaries, and "completed work" semantics are consistent and stable across environments and datasets.

### Task Purpose
Ensure velocity trends are interpretable and prevent label drift or timezone-related bucket errors.

---

## Dependencies

### Prerequisites
- **Prerequisite Tasks**: plan_46
- **Required Resources**: Velocity semantics definition (what counts as completed work)
- **Environment Requirements**: Dataset spanning multiple time buckets

### Downstream Impact
- **Downstream Tasks**: plan_59
- **Provided Output**: Stable velocity series definition and labeling rules

---

## Execution Steps

### Step 1: Define Velocity Semantics
- **Action**: Define whether velocity is sprint-based or time-window-based and which completion signal is used.
- **Input**: Stakeholder expectations and data availability.
- **Output**: Velocity semantics statement.
- **Notes**: Include how estimates vs counts are handled.

### Step 2: Define Bucket and Label Rules
- **Action**: Choose bucket granularity and define stable label formatting rules.
- **Input**: Semantics statement.
- **Output**: Bucket and labeling spec.
- **Notes**: Consider locale and timezone stability.

### Step 3: Implement Series Model and Trend Interpretation
- **Action**: Implement the series model and define trend interpretation rules (up/down/flat).
- **Input**: Bucket spec and dataset.
- **Output**: Velocity series model used consistently in the dashboard.
- **Notes**: Ensure the trend line/annotation logic cannot mislead when data is sparse.

### Step 4: Validate With Sparse and Noisy Data
- **Action**: Validate behavior for: sparse completion data, missing estimates, and timezone boundary cases.
- **Input**: Scenario datasets.
- **Output**: Verified stable behavior and explicit empty states.
- **Notes**: Avoid silently showing all zeros without explanation.

---

## Visualization Aids

### Step Flowchart
```mermaid
flowchart TD
    A[Define semantics] --> B[Define buckets + labels]
    B --> C[Implement series + trend rules]
    C --> D[Validate edge cases]
```

### Dashboard System Flow (Velocity)
```mermaid
flowchart LR
    Tasks[Task completion signals] --> Bucket[Bucketization]
    Bucket --> Series[Velocity series]
    Series --> Chart[Velocity chart]
```

### Core Metrics Mapping (Velocity)
| Velocity Mode | Input Signal | Output Unit | Label Example | Empty-State Rule |
| --- | --- | --- | --- | --- |
| Time-window velocity | completion timestamps | hours or points | `Week 1`, `Week 2` | "not enough data" |
| Sprint velocity (optional) | sprint completion summary | hours or points | `Sprint N` | "no sprint data" |

### Risk Monitoring Table
| Risk Item | Level | Trigger Signal | Mitigation Strategy | Owner |
| --- | --- | --- | --- | --- |
| Buckets shift due to timezone/locale | Medium | inconsistent labels across sessions | stable labeling rules | AI-agent |
| Sparse data misleads trend | Medium | trend shows false signal | require minimum points | AI-agent |

### File Operations List

#### Files to Create
 - No new files required (current scope)

#### Files to Modify
- `frontend/src/components/VelocityChart.tsx`
- `frontend/src/services/api/analytics.ts`
  - Modification Location: velocity computation and labels
  - Modification Content: stable bucket rules + empty-state behavior
  - Modification Reason: improve interpretability

#### Files to Read
- `frontend/src/pages/dashboard/dashboardSemanticsContract.md`
  - Read Purpose: align computation to agreed meaning
  - Usage: validate bucket scope

## Acceptance Criteria

### Functional Acceptance
- Velocity labels remain stable under locale/timezone changes.
- Missing or sparse values produce explicit empty-state signals, not deceptive flat lines.
- Trend interpretation (up/down/flat) is consistent with documented bucket semantics.

### Technical Acceptance
- One calculation path is authoritative for velocity across dashboard and related components.
- Label format appears in dashboard snapshots and tests as deterministic strings.


