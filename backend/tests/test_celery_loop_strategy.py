from __future__ import annotations

from pathlib import Path


TASKS_DIR = Path(__file__).resolve().parents[1] / "app" / "tasks"


def test_celery_tasks_do_not_use_per_task_event_loops() -> None:
    forbidden_tokens = (
        "asyncio.run(",
        "asyncio.new_event_loop(",
        ".run_until_complete(",
    )
    task_files = sorted(TASKS_DIR.glob("*.py"))
    assert task_files, "No Celery task files found"

    violations: list[str] = []
    for path in task_files:
        content = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            if token in content:
                violations.append(f"{path.name}: {token}")

    assert violations == [], "Per-task event loop usage found:\n" + "\n".join(violations)
