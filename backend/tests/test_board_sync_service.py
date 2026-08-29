from __future__ import annotations

import pytest

from app.services.sync.board_sync_service import BoardSyncService


class _DummyJiraService:
    def list_boards_for_project(self, _project_key: str):
        return [
            {"id": 1, "name": "Primary Scrum"},
            {"id": 2, "name": "Duplicate Scrum"},
        ]

    def list_sprints(self, board_id: int):
        if board_id == 1:
            return [
                {"id": 101, "name": "Sprint 101"},
                {"id": 102, "name": "Sprint 102"},
            ]
        return [
            {"id": 102, "name": "Sprint 102"},
            {"id": 103, "name": "Sprint 103"},
        ]

    def list_issues_in_sprint(self, _sprint_id: int):
        return []


@pytest.mark.asyncio
async def test_sync_boards_deduplicates_sprints_across_multiple_boards(
    monkeypatch: pytest.MonkeyPatch,
):
    service = BoardSyncService(_DummyJiraService())  # type: ignore[arg-type]
    processed_sprint_ids: list[int] = []
    heartbeat_payloads: list[dict[str, int]] = []

    async def _fake_sync_sprint(self, sprint, project_id, db):  # type: ignore[no-untyped-def]
        del project_id, db
        processed_sprint_ids.append(int(sprint["id"]))
        return 1

    async def _heartbeat(item_counts: dict[str, int]) -> None:
        heartbeat_payloads.append(dict(item_counts))

    monkeypatch.setattr(BoardSyncService, "_sync_sprint", _fake_sync_sprint)

    result = await service.sync_boards(
        "WAB",
        1,
        db=None,  # type: ignore[arg-type]
        heartbeat_callback=_heartbeat,
    )

    assert processed_sprint_ids == [101, 102, 103]
    assert result.total_boards_processed == 2
    assert result.total_sprints_synced == 3
    assert result.total_tasks_linked == 3
    assert heartbeat_payloads[-1] == {
        "boards_processed": 2,
        "sprints_synced": 3,
        "tasks_linked": 3,
    }
