# Traceability Operator Workflows (plan_71 / plan_72)

Operational runbook for the three standalone traceability workflows. Companion
docs: `TRACEABILITY_REVIEW_QUEUE.md` (review lifecycle), `TRACEABILITY_EXPORTS.md`,
`TRACEABILITY_AUTOMATION_VALIDATION.md`.

## 1. Suggestion review (plan_72)

Suggested links are TF-IDF/heuristic candidates awaiting a human decision.

**Lifecycle:** `pending → approved | rejected` (terminal). Re-acting on a
non-pending suggestion returns **400**.

| Step | API | Notes |
| --- | --- | --- |
| Generate | `POST /traceability/suggested-links/generate` | requires `project_id` (or admin); manager only |
| List | `GET /traceability/suggested-links` | filter by status, min score; paginated |
| Approve | `POST /traceability/suggested-links/{id}/approve` | creates the real `ArtifactLink`; **duplicate** → reuses existing link, no second row; **cycle** → 409 and the suggestion is auto-rejected |
| Reject | `POST /traceability/suggested-links/{id}/reject` | terminal |
| Bulk approve | `POST /traceability/suggested-links/bulk-approve` | best-effort, **item-level** results `{approved, already_processed, cycle_prevented, errors[]}`; max 100/batch |
| Stats | `GET /traceability/suggested-links/stats` | counts by status/method/type |

**Audit:** approve / reject / bulk-approve each write a `suggested_link` audit
entry (`suggestion_approve` / `suggestion_reject` / `suggestion_bulk_approve`).

**UI:** `SuggestedLinksPanel` (filters, score control, approve/reject, bulk).
Approved/rejected items leave the pending queue and stats refresh.

**Acceptance evidence:** `backend/tests/test_traceability_suggestions_workflow.py`
(approve→link, duplicate, cycle→409, bulk partial-failure, stats, audit);
`frontend/src/components/SuggestedLinksPanel.test.tsx`.

## 2. Rules management (plan_71 / plan_73)

List-first operational control over rules, without the visual builder.

**Checklist of supported actions** (page: `RulesManagement.tsx`, route
`/traceability/rules`, discoverable from the Traceability nav):

- [x] List + search by name, filter by enabled/disabled
- [x] Open / edit → routes into the visual builder (`?ruleId=`)
- [x] Enable / disable (PUT `enabled`)
- [x] Duplicate (creates a disabled copy named `"<name> (copy)"`)
- [x] Execute (manual run; disabled rules can't execute)
- [x] Delete with confirmation, honoring the **delete-cascade contract**:
  - unresolved (open) review items → **409** (must resolve/reject first)
  - terminal review items → preserved, `rule_id` cleared + rule snapshot kept
  - execution rows → removed via ORM cascade
  - artifact/suggested links → **not** deleted

**Acceptance evidence:** `backend/tests/test_traceability_rule_lifecycle.py`;
`frontend/src/pages/__tests__/RulesManagement.test.tsx`.

## 3. Review queue (plan_70)

See `TRACEABILITY_REVIEW_QUEUE.md`. Summary: `pending → claimed → resolved |
rejected`, privileged reopen, RBAC (view/manage/admin), full audit. Page:
`ReviewQueue.tsx`, route `/traceability/review`.

## Execution history & triggers (plan_76)

`/traceability/history` shows each run's status, links created, errors/warnings,
and **trigger source** (`manual` / `webhook` / `scheduled` / `post_sync`) so
operators can tell what initiated a run.
