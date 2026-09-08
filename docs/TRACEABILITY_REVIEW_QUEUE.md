# Traceability Manual-Review Queue (plan_70)

The `queueReviewAction` rule node used to emit transient execution *warnings*
when it flagged an artifact for manual attention. Those warnings disappeared as
soon as the execution log scrolled away. The review queue turns them into
**durable, auditable work items** that operators can find, claim, and resolve.

## Data model

Table `traceability_review_items` (model `app/models/traceability_review.py`,
migration `035_add_traceability_review_items`):

| Column | Notes |
| --- | --- |
| `artifact_id` | The flagged artifact (required). |
| `rule_id`, `rule_execution_id` | Origin rule / run (`SET NULL` on delete). |
| `node_id` | The `queueReviewAction` node that raised the item. |
| `status` | `pending` → `claimed` → `resolved` \| `rejected` (reopen → `pending`). |
| `priority` | `low` \| `normal` \| `high` \| `urgent`. |
| `reason` | Human-readable explanation from node config. |
| `assigned_to_id`, `created_by_id`, `resolved_by_id`, `resolved_at` | Actor/audit context. |
| `metadata` (attr `meta`) | Artifact snapshot + per-transition note history. |

**Deduplication.** A partial unique index
`uq_traceability_review_items_open(project_id, artifact_id, rule_id, node_id)
WHERE status IN ('pending','claimed')` guarantees at most one *open* item per
key. Re-running a rule refreshes the open item (reason, priority, latest
execution id) instead of piling up duplicates. Once an item is resolved or
rejected it leaves the dedup scope, so a later rerun can open a fresh item.

## Lifecycle & RBAC

```
pending ──claim──▶ claimed ──resolve──▶ resolved
   │                  │                    │
   ├──resolve─────────┘                    │
   ├──reject────────────────▶ rejected     │
   └◀──────────── reopen (admin) ──────────┘
```

| Action | Endpoint | Permission |
| --- | --- | --- |
| List / get | `GET /api/v1/traceability/review-items[/{id}]` | `traceability:view` |
| Claim | `POST .../{id}/claim` | `traceability:manage` |
| Resolve | `POST .../{id}/resolve` | `traceability:manage` |
| Reject | `POST .../{id}/reject` | `traceability:manage` |
| Reopen (from terminal) | `POST .../{id}/reopen` | `traceability:manage` **and** administrator/superuser |

Illegal transitions (e.g. resolving an already-resolved item) return **409**.
Every transition writes a `traceability_review_item` audit-log entry
(`review_claim` / `review_resolve` / `review_reject` / `review_reopen`) with the
from/to status, actor, artifact, rule, and optional note.

## Engine integration

`QueueReviewActionExecutor` collects review *candidates* on the execution
context; the engine persists them via
`review_service.persist_review_candidates_sync` **after** the execution record
is flushed. Because candidates are plain dicts (not ORM rows) they survive an
atomic rollback, so a run that fails late still records the review items for the
artifacts that reached the review node. `execute_rule` returns
`review_items_created` / `review_items_updated` counts.

`resolve` is a status transition only — it does **not** create artifact links.
Link creation is the suggestions workflow's job (see suggestions endpoints); the
review queue is for triaging which artifacts need human attention.

## Validation status

- SQLite / offline migration upgrade+downgrade and partial-unique dedup
  validated in-session.
- PostgreSQL upgrade/rollback: VALIDATED on a live PostgreSQL 15 database
  (2026-09-08, docker stack) — see `TRACEABILITY_BACKEND_VALIDATION.md`; the
  035 downgrade path required the revision-id rename
  `034_rewrite_legacy_transform_types` -> `034_rewrite_legacy_types`
  (the old id exceeded the 32-char `alembic_version.version_num`).
- Backend coverage: `backend/tests/test_traceability_review.py` (engine
  persistence + dedup, status-graph, API lifecycle, RBAC, audit).
