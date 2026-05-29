# Backend Regression & Release Evidence (plan_77 / plan_78)

Backend contract and service regression coverage for the traceability
production-completion work (plan_67 → plan_79).

## Commands

```bash
cd backend
# Full suite
python -m pytest -q
# Traceability-focused regression set
python -m pytest -q \
  tests/test_traceability_review.py \
  tests/test_traceability_suggestions_workflow.py \
  tests/test_traceability_export_content.py \
  tests/test_traceability_automation_triggers.py \
  tests/test_traceability_rule_lifecycle.py \
  tests/test_traceability_automation.py \
  tests/test_traceability_transform_contract.py \
  tests/test_traceability_contracts.py \
  tests/test_traceability_rule_builder_contracts.py \
  tests/test_exports.py
```

## Regression matrix

| Risk / workflow | Coverage | File |
| --- | --- | --- |
| Transform contract (unsupported rejected, passthrough, edge cases) | existing | `test_traceability_transform_contract.py` |
| Review queue persistence + dedup (engine) | new | `test_traceability_review.py` |
| Review lifecycle transitions + RBAC + audit | new | `test_traceability_review.py` |
| Suggestion approve → link creation | new | `test_traceability_suggestions_workflow.py` |
| Suggestion duplicate / cycle prevention | new | `test_traceability_suggestions_workflow.py` |
| Suggestion bulk approve (item-level partial results) | new | `test_traceability_suggestions_workflow.py` |
| Suggestion stats + audit | new | `test_traceability_suggestions_workflow.py` |
| Export content CSV / XLSX / PDF | new | `test_traceability_export_content.py` |
| Export empty matrix + unsupported-format terminal failure | new | `test_traceability_export_content.py` |
| Export download returns valid PDF (request path) | existing (now green) | `test_exports.py` |
| Webhook token auth (valid / invalid / disabled rule) | new | `test_traceability_automation_triggers.py` |
| Execution history recording | new | `test_traceability_automation_triggers.py` |
| Post-sync idempotency (one run per event, no-op gating) | new | `test_traceability_automation_triggers.py` |
| Scheduler due-selection + invalid-cron disable | existing | `test_traceability_rule_builder_contracts.py` |
| Rule lifecycle (list/get/update/enable/disable/duplicate) | new | `test_traceability_rule_lifecycle.py` |
| Rule delete-cascade contract (open→409, terminal preserved, exec cascade) | new | `test_traceability_rule_lifecycle.py` |

Result: **70 passed** in the focused traceability set; the new files add 28 tests.

## Test-infrastructure fixes (enable reliable runs)

1. **`tests/_sqlite_schema.py`** — schema reset now uses `drop_all` + `create_all`
   instead of deleting `test.db`. The previous file-deletion approach cascaded
   into `PermissionError` on Windows once WAL-mode handles accumulated, taking
   the full suite from *33 passed / 392 errors* to *422 passed*.
2. **`tests/conftest.py`** — forces `CELERY_ENABLED=false`. The committed `.env`
   enables Celery against a broker (`redis:6381`) that does not exist in test
   environments; without the override, export/sync endpoints 500 on a broker
   `ConnectionError`. One celery-specific guardrail test
   (`test_endpoint_guardrails.py::test_health_alerts_include_backlog_high_signal`)
   was updated to opt back in via `monkeypatch.setattr(settings, "CELERY_ENABLED", True)`,
   since the `queue_backlog_threshold` alert is gated on that flag.

## Full-suite result

Latest full run: **458 passed, 2 failed** in ~4 min. The only failures are the
two out-of-scope, pre-existing Confluence-sync tests below.

## Retention boundary (plan_78 Step 4)

There is **no time-based retention / automatic cleanup** policy for traceability
review items, export tasks, rule executions, or audit log rows. This is recorded
as a **gap, not invented**:

- Export task files can be removed via `DELETE /exports/{task_id}` (manual).
- Rule deletion cascades to its execution rows and detaches terminal review
  items (tested).
- No scheduled purge exists for review items / audit history.

If a retention policy is later required, it should be added explicitly with its
own migration and tests rather than inferred here.

## Residual risks / handed-off validation

- **PostgreSQL migration 035** upgrade/rollback validated only on SQLite/offline
  in-session; production PostgreSQL validation is handed off.
- **Live Celery/broker** automation (beat schedule, worker dispatch) is handed
  off — see `TRACEABILITY_AUTOMATION_VALIDATION.md`.
- **Out-of-scope pre-existing failures:** `test_confluence_tasks.py` (2 tests)
  fail with `cannot unpack non-iterable bool object` in the Confluence sync path
  — unrelated to traceability; pre-existing before this work.
- **Frontend green run** requires Node/npm or the Docker tooling container — see
  `TRACEABILITY_FRONTEND_VALIDATION.md`.
