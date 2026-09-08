# Traceability Matrix Exports (plan_75)

Matrix exports are produced by `app/services/analytics/export_service.py`
(`process_export_task`) and served by the routes in
`app/api/api_v1/endpoints/traceability/matrix.py`:

| Action | Route |
| --- | --- |
| Create | `POST /api/v1/traceability/exports` |
| Status | `GET  /api/v1/traceability/exports/{task_id}` |
| Download | `GET  /api/v1/traceability/exports/{task_id}/download` |
| List | `GET  /api/v1/traceability/exports` |
| Delete | `DELETE /api/v1/traceability/exports/{task_id}` |

> A second, **unregistered** duplicate router (`endpoints/traceability/exports.py`,
> xlsx/csv only, no PDF) was removed in this work — it was never included in the
> traceability router and only caused confusion.

## Formats & renderer dependencies

| Format | Renderer (already in backend requirements) |
| --- | --- |
| `csv` | stdlib `csv` |
| `xlsx` | `openpyxl` |
| `pdf` | `reportlab` (landscape A4) |

No new renderer dependency is added. If `reportlab` is unavailable, PDF export
fails terminally with a readable message (`PDF export requires 'reportlab'…`).

`include_details=True` adds confidence markers to linked cells, e.g. a `tests`
link at confidence 0.9 renders as `tests (90%)`.

## Limits (large-matrix guard)

Defined in `export_service.py`:

| Limit | Value |
| --- | --- |
| `MAX_EXPORT_ROWS` | 5000 |
| `MAX_EXPORT_COLS` | 1000 |
| `MAX_EXPORT_CELLS` | 5,000,000 |

`process_export_task` calls `get_rtm_matrix` with `row_limit`/`col_limit` capped
by these constants, so an oversized matrix cannot exhaust memory — verified by
`test_export_uses_bounded_row_col_limits`.

## Lifecycle & failure modes

- Synchronous path (`CELERY_ENABLED=false`, also the test default): the export
  runs inline and the create call returns `status=completed` (or `failed`).
- Celery path (`CELERY_ENABLED=true`): the create call returns `status=pending`
  and a worker processes it; the UI polls `GET …/{task_id}`.
- Terminal failure: an unsupported format or rendering error sets
  `status=failed` with `error_message`; never a stuck `processing`.
- Download guards: **404** when the task or file is unknown/missing; **400**
  when the export is not yet `completed`.

## Test coverage

`backend/tests/test_traceability_export_content.py` (content-level), and
`backend/tests/test_exports.py` (PDF download). Frontend dialog interaction:
`frontend/src/components/traceability/MatrixExportDialog.test.tsx`
(polling → completed/failed/download).

## Residual / handoff

- Large-matrix performance under a production dataset remains an open
  load-test gate (NOT executed as of 2026-09-08; the docker stack exists,
  so it can now be run there).
- PostgreSQL runtime itself: validated 2026-09-08 on the docker stack —
  see `TRACEABILITY_BACKEND_VALIDATION.md`.
