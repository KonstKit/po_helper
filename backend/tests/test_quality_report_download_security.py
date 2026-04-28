from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api.api_v1.endpoints.quality.reports import _resolve_report_download_path
from app.api.api_v1.endpoints.quality.common import report_service


def test_resolve_report_download_path_rejects_traversal(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(report_service, "reports_dir", str(tmp_path))

    with pytest.raises(HTTPException) as exc_info:
        _resolve_report_download_path(r"..\escape.json")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid report filename"


def test_resolve_report_download_path_returns_existing_report(monkeypatch, tmp_path: Path):
    report_path = tmp_path / "quality-report.json"
    report_path.write_text('{"status":"ok"}', encoding="utf-8")
    monkeypatch.setattr(report_service, "reports_dir", str(tmp_path))

    resolved = _resolve_report_download_path("quality-report.json")

    assert resolved == report_path.resolve()


@pytest.mark.asyncio
async def test_download_report_rejects_urlencoded_escape(client, monkeypatch, tmp_path: Path):
    report_path = tmp_path / "quality-report.json"
    report_path.write_text('{"status":"ok"}', encoding="utf-8")
    monkeypatch.setattr(report_service, "reports_dir", str(tmp_path))

    response = await client.get("/api/v1/quality/reports/download/..%5Cescape.json")

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid report filename"
