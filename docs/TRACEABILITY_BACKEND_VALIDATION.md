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
| Execution `trigger_source` recorded (manual/webhook/post_sync) | new | `test_traceability_automation_triggers.py` |
| Post-sync idempotency (one run per event, no-op gating) | new | `test_traceability_automation_triggers.py` |
| Scheduler due-selection + invalid-cron disable | existing | `test_traceability_rule_builder_contracts.py` |
| Rule lifecycle (list/get/update/enable/disable/duplicate) | new | `test_traceability_rule_lifecycle.py` |
| Rule delete-cascade contract (open→409, terminal preserved, exec cascade) | new | `test_traceability_rule_lifecycle.py` |
| Review reopen RBAC (non-admin manager → 403) | new | `test_traceability_review.py` |
| Export include_details confidence marker; download 404/400; bounded limits | new | `test_traceability_export_content.py` |

Result: focused traceability set all green; the new files add 40+ tests.

### Audit-driven additions (second pass)

A follow-up adversarial audit flagged real in-scope gaps that are now closed:
- **plan_76**: `TraceabilityRuleExecution.trigger_source` column + migration
  `036` (offline-validated) threaded through manual/webhook/scheduled/post_sync;
  surfaced in the execution response + history UI.
- **plan_75**: `include_details`, download 404/400, and bounded-limit tests; the
  unregistered duplicate `endpoints/traceability/exports.py` router was deleted.
- **plan_70**: RBAC negative test for privileged reopen.

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

Latest full run: **494 passed, 0 failed** in ~7.4 min. The two previously
out-of-scope Confluence-sync test failures (the `cannot unpack non-iterable
bool object` mismatch in `test_confluence_tasks.py`) have since been fixed —
see the resolved note under "Residual risks".

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

## Corner-case regression coverage (third audit pass)

A 20-item corner-case audit drove a further round of tests (and one fix). New
files, all green:

| File | Corner cases |
| --- | --- |
| `test_review_concurrency_rbac.py` | #2 re-claim → 409 (row-locked); #4 non-admin releasing another's claim → 403, releasing own claim → 200 |
| `test_review_pagination_cap_bool.py` | #3 pagination tiebreaker (identical `created_at`, no gaps/dupes); #5 `transition_notes` capped at 50; #6 bool/None artifact ids rejected |
| `test_suggestions_bulk_mixed.py` | #10 bulk-approve mixed batch (valid / duplicate / cycle-prevented / not-found) item-level results |
| `test_export_limits_broker.py` | #12 export row/col limits capped by `MAX_EXPORT_ROWS/COLS`; #17 broker-down → **503** + terminal `failed` task (not a raw 500) |
| `test_sync_redelivery_idempotency.py` | #16 redelivered `createLinkAction` run creates **no duplicate link** (existence check); 2nd execution recorded, link count stable |
| `test_migration_035_idempotent.py` | #9 re-running migration 035 with the dedup index dropped re-creates it (idempotent) |

Fix applied for #17: `matrix.py create_export_task` now wraps the Celery
`.delay()` enqueue in try/except — on broker failure it marks the export task
`failed` with a readable message and returns **503** instead of leaking a 500
(a module `logger` was also added).

### Resolved finding — NULL-tenant link dedup

`uq_artifact_link` includes `tenant_id`; under SQL NULL semantics a NULL
`tenant_id` does not collide, so the unique constraint alone does **not** dedupe
single-tenant/local links. Idempotency for the rule path was already guaranteed
by `createLinkAction._create_link`'s explicit existence check (tested in #16).
The gap was the **direct** `LinkService.create_link` path: callers that bypass
the engine got no dedup when `tenant_id` was NULL, so a second identical call
created a duplicate row instead of failing.

**Fix applied (sequential dedup).** `LinkService.create_link` now runs a
tenant-agnostic existence check before inserting — scoped to the full
`uq_artifact_link` tuple (`tenant_id, project_id, from_artifact_id,
to_artifact_id, link_type`) — and raises `ValueError("Link already exists: ...")`
on a match. Raising (rather than returning the existing link) keeps the contract
identical to the pre-existing `IntegrityError` path, so `create_links_batch`'s
"already exists" skip logic keeps working unchanged; because `create_link`
flushes each row, an in-batch duplicate is caught too. `.scalars().first()` (not
`scalar_one_or_none`) is used so a pre-existing duplicate from before this fix
does not itself raise.

**Scope — sequential only, not a concurrency guard.** The check is
read-then-write, so it closes the sequential path (retry / at-least-once
redelivery / a caller invoking twice) for every tenant, but two *concurrent*
transactions can still both pass the SELECT and both INSERT. The `IntegrityError`
backstop catches that race only when `tenant_id` is set (the constraint fires);
for the NULL-tenant case the constraint does not fire, so a concurrent duplicate
remains possible on engines that allow it (Postgres with parallel workers;
SQLite serialises writes, so it is not exposed there). Fully closing it would
need a DB-level unique index treating NULL tenant/project as COALESCE sentinels —
deliberately deferred (no migration in this change).

**Not identical to the engine check.** The rule engine dedupes on
`(from, to, link_type)` only; this service dedupes on the full
`(tenant_id, project_id, from, to, link_type)` tuple. They coincide on
single-tenant data; in a multi-tenant DB the service correctly keeps
same-`(from, to, type)` links distinct across tenants/projects. One deliberate
side change came with it: when `project_id` is omitted the link is now stored
under `project_id or from_artifact.project_id` (was NULL), aligning with the
engine's `source.project_id or target.project_id`.

Guarded by `test_link_service_null_tenant_dedup.py`: NULL-tenant `create_link`
called twice for the same tuple leaves exactly one row (the 2nd raises),
covering the explicit-project, project-resolved-from-source, and pure
NULL-project/NULL-tenant branches; the concurrency limitation above is
intentionally not covered.

## Substance-audit follow-up (fourth pass)

A read-only substance audit (19 agents) confirmed 15/19 targets SUBSTANTIVE and
flagged real issues, now fixed:

- 🔴 **`trigger_source` was half-wired (end-to-end break).** The history UI calls
  `GET /rules/executions` (`get_all_rule_executions`), whose hand-rolled dict
  omitted `trigger_source` — so the UI "Trigger" column always showed `—`. Fixed
  (one line) and guarded by `test_executions_list_endpoint_exposes_trigger_source`
  (the per-rule `/rules/{id}/executions` endpoint is schema-based and never
  caught this). Added `scheduled` trigger coverage too.
- 🟠 **bulk-approve authorization was untested** (the harness user is a superuser,
  so the `except HTTPException: raise` branch never ran). Added
  `test_suggestions_bulk_rbac.py`: a non-admin manager bulk-approving a
  suggestion in an inaccessible project gets a real **403** (not a masked 200),
  and nothing is approved behind it.
- 🟠 **`#16` engine idempotency was proven hollow** (the `commitSource`→
  `createLinkAction` flow has a single input and self-linking is off by default,
  so `_create_link` never ran). Rewrote it to a `manualSource([A,B])`→
  `createLinkAction(allow_self_linking)` flow that genuinely creates one link,
  then proves a redelivered run records a 2nd execution but adds **no** duplicate
  link.
- 🟡 Minor: portable migration-test path (no hardcoded absolute path), `0` is
  positively asserted as a valid int (vs `False`), and `MAX_EXPORT_CELLS` is now
  a live cell-budget guard (clamps `col_limit` so rows×cols cannot exceed it)
  instead of a dead constant.

## Residual risks / handed-off validation

- **PostgreSQL migrations 035/036** upgrade/rollback validated only on
  SQLite/offline in-session; production PostgreSQL validation is handed off.
- **Live Celery/broker** automation (beat schedule, worker dispatch) is handed
  off — see `TRACEABILITY_AUTOMATION_VALIDATION.md`.
- **Confluence-sync tests (resolved):** `test_confluence_tasks.py` previously had
  2 failures from a stale test contract — `_process_page` returns
  `(created, page_row)`, but the tests still treated the result as a bare `bool`
  (one `fake_process_page` returned `True`, so the caller's tuple-unpack raised
  `cannot unpack non-iterable bool object`). The tests were updated to the tuple
  contract; production code was already correct. Separately,
  `ConfluencePage.updated_at` was `NOT NULL` with only `onupdate` (UPDATE-only),
  so API-path inserts hit a `NotNullViolation`; it now carries
  `server_default=func.now()` (and the deployed column got a matching
  `DEFAULT now()`).
- **Frontend green run** requires Node/npm or the Docker tooling container — see
  `TRACEABILITY_FRONTEND_VALIDATION.md`.
