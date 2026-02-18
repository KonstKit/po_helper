---
level: 3
file_id: plan_50
parent: plan_49
status: pending
created: 2026-02-18 10:41
estimated_time: 120 minutes
---

# Task: Unify Sprint Status and Identifier Contract

## Task Overview

### Task Description
Define a canonical sprint identity and status semantics ("active", "closed", etc.) and ensure the dashboard consumes a consistent contract regardless of variations in upstream payload fields.

### Task Purpose
Prevent "active sprint is always null" class failures and ensure sprint-dependent widgets and charts have reliable inputs.

---

## Dependencies

### Prerequisites
- **Prerequisite Tasks**: plan_41
- **Required Resources**: Sprint payload samples from at least one environment
- **Environment Requirements**: Ability to validate sprint status transitions or representative snapshots

### Downstream Impact
- **Downstream Tasks**: plan_51, plan_52, plan_54
- **Provided Output**: Canonical sprint contract and active sprint selection rule

---

## Execution Steps

### Step 1: Collect Contract Samples
- **Action**: Gather representative sprint payload variants and document field differences.
- **Input**: Environment payload samples.
- **Output**: Field mapping table and risk list.
- **Notes**: Include both identifier fields and status/state fields.

### Step 2: Define Canonical Identity and Status Model
- **Action**: Define canonical sprint ID selection and status normalization rules.
- **Input**: Field mapping table.
- **Output**: Canonical model definition and normalization rules.
- **Notes**: Prefer explicit precedence rules over heuristics.

### Step 3: Implement Consistent Selection Rules
- **Action**: Ensure the dashboard always uses the canonical sprint model for "active sprint" selection.
- **Input**: Canonical model definition.
- **Output**: Deterministic active sprint selection behavior.
- **Notes**: Ensure behavior is stable per project context.

### Step 4: Validate With Realistic Scenarios
- **Action**: Validate selection when there is no active sprint, multiple candidates, or partial payload fields.
- **Input**: Sample datasets.
- **Output**: Verified behavior with explicit fallbacks.
- **Notes**: Fallback should prefer clarity over hidden assumptions.

---

## Visualization Aids

### Step Flowchart
```mermaid
flowchart TD
    A[Collect payload samples] --> B[Define canonical model]
    B --> C[Normalize fields]
    C --> D[Select active sprint]
    D --> E[Validate edge cases]
```

### Dashboard System Flow (Sprint Contract)
```mermaid
flowchart LR
    Payload[Raw sprint payload] --> Normalize[Normalization]
    Normalize --> Canon[Canonical sprint model]
    Canon --> Widgets[Sprint-dependent widgets]
```

### Core Metrics Mapping (Sprint Contract Inputs)
| Contract Element | Used By | Must Be Stable | Fallback |
| --- | --- | --- | --- |
| Canonical sprint ID | WIP, burndown, sprint widgets | YES | explicit "unavailable" |
| Normalized status/state | active sprint selection | YES | none -> "no active sprint" |

### Risk Monitoring Table
| Risk Item | Level | Trigger Signal | Mitigation Strategy | Owner |
| --- | --- | --- | --- | --- |
| Environment-specific field names | High | sprint widgets always empty | normalization with precedence + mapping tests | AI-agent |
| Multiple candidates for active sprint | Medium | inconsistent selection | deterministic priority rules in shared helper | AI-agent |

### File Operations List

#### Files to Create
 - No new files required (current scope)

#### Files to Modify
- `frontend/src/utils/sprintNormalization.ts`
  - Modification Location: sprint ingestion/selection
  - Modification Content: canonical identity + status normalization
  - Modification Reason: unify contract consumption
- `frontend/src/pages/ProjectDetail.tsx`
  - Modification Location: active sprint/state checks
  - Modification Content: consume normalization helper instead of page-local assumptions
  - Modification Reason: eliminate contract drift across screens
- `frontend/src/pages/SprintCapacity.tsx`
  - Modification Location: sprint state checks and project context mapping
  - Modification Content: consume normalization helper and canonical active sprint mapping
  - Modification Reason: keep sprint context behavior consistent

#### Files to Read
- `frontend/src/services/api/sprints.ts`
  - Read Purpose: derive field mapping rules
  - Usage: validate normalization

## Acceptance Criteria

### Functional Acceptance
- `id` and `sprint_id` both resolve to a deterministic canonical sprint identifier.
- `state` and `status` are normalized via documented precedence and select the same active sprint as:
  - `s.state === 'active'`
  - fallback to `s.status === 'active'`
  - fallback to date-window match
  - fallback to latest by date when no explicit active marker exists.
- `ProjectDetail.tsx` and `SprintCapacity.tsx` derive active sprint and active-state checks through `sprintNormalization.ts`.

### Technical Acceptance
- `sprintsByProject` grouping is keyed by explicit project context passed to the reducer (or caller payload), not by absent `s.project_id`.
- Shared normalization helper has unit-level tests for:
  - missing fields
  - multiple active markers
  - unknown/null states


