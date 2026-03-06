def test_sessionlocal_alias_matches_sync():
    from app.core.database import SessionLocal, SyncSessionLocal

    assert SessionLocal is SyncSessionLocal


def test_traceability_scheduler_registered_in_beat():
    from app.core.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule or {}
    assert "traceability-rule-scheduler-every-minute" in schedule
    entry = schedule["traceability-rule-scheduler-every-minute"]
    assert entry.get("task") == "traceability.scheduled_rule_execution"
    assert "recover-stale-sync-tasks-every-5-min" in schedule
    recovery_entry = schedule["recover-stale-sync-tasks-every-5-min"]
    assert recovery_entry.get("task") == "maintenance.recover_stale_sync_tasks"


def test_celery_worker_defaults_are_bounded():
    from app.core.celery_app import celery_app
    from app.core.config import settings

    assert celery_app.conf.worker_concurrency == settings.CELERY_WORKER_CONCURRENCY == 4
    assert (
        celery_app.conf.worker_prefetch_multiplier
        == settings.CELERY_WORKER_PREFETCH_MULTIPLIER
        == 1
    )
