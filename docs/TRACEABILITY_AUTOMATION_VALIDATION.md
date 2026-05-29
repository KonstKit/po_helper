# Traceability Automation Validation (plan_76)

Covers scheduled, webhook, post-sync, and manual rule execution. Per the
plan_76 AI-executor constraint, **in-session** acceptance is limited to unit and
mocked trigger coverage; live worker/broker/scheduler validation is handed off.

## Policies (read from current repository behavior)

- **Webhook authorization.** Token-in-path: `POST /api/v1/traceability/webhook/{token}`
  matches a rule with `webhook_token == token` **and** `trigger_on_webhook == True`.
  Unknown/disabled tokens → 404; a matched-but-disabled rule → 400. HMAC request
  signing is **not** added (it would require explicit approval per the gate);
  the existing token model is the validated policy.
- **Post-sync idempotency.** One execution per eligible rule per sync event.
  `run_traceability_post_sync` short-circuits when `project_id is None` or
  `artifact_delta <= 0`. Each sync event triggers one execution per rule with
  `execute_on_sync_complete=True`.
- **Cron timezone.** Cron schedules are interpreted as **UTC** (`croniter` with a
  UTC `now`). No per-rule timezone field is introduced.
- **Invalid schedule.** An unparseable `schedule_cron` disables the schedule
  (`schedule_enabled=False`, `next_scheduled_run=None`) to avoid an error loop.

## Validated in-session (automated)

| Scenario | Test |
| --- | --- |
| Scheduler selects due rules, recomputes next run | `test_traceability_rule_builder_contracts.py::test_scheduler_uses_schedule_fields_and_recomputes_next_run` |
| Invalid cron disables schedule (no loop) | `…::test_scheduler_disables_invalid_cron_to_avoid_error_loop` |
| Webhook enable → execute → disable → 404 | `test_traceability_automation.py::test_rule_webhook_and_schedule_flow` |
| Webhook invalid token → 404 | `test_traceability_automation_triggers.py::test_webhook_invalid_token_returns_404` |
| Webhook valid token executes + records history | `…::test_webhook_executes_with_valid_token_and_records_history` |
| Webhook on disabled rule → 400 | `…::test_webhook_on_disabled_rule_returns_400` |
| Post-sync runs each rule once per event | `…::test_sync_complete_rule_runs_once_per_event` |
| Post-sync no-op when no artifact delta / no project | `…::test_post_sync_noop_when_no_artifact_delta` |

## Handed off (live runtime — outside AI session)

Requires a running Celery worker, a Redis broker/result backend, and Celery
beat. With `CELERY_ENABLED=true`:

1. **Beat schedule.** Confirm `scheduled_rule_execution_task` is registered on a
   beat interval and that a rule with a near-future `schedule_cron` fires once,
   updates `next_scheduled_run`, and records an execution.
2. **Worker dispatch.** Confirm `execute_rule_task.delay(rule_id)` runs on the
   worker (not inline) and produces a terminal execution record.
3. **Webhook under load.** Confirm webhook execution dispatched to the worker
   does not block the request thread.
4. **Post-sync via broker.** Confirm a real Jira/Confluence sync completion
   dispatches `execute_sync_complete_rules_task` exactly once per sync event.
5. **Failure isolation.** Confirm a failing rule does not poison the queue and is
   visible in execution history with an error message.

> The test suite forces `CELERY_ENABLED=false` so these paths run inline; the
> broker-backed behavior above cannot be asserted without a live broker.
