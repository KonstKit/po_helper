from __future__ import annotations

from datetime import date

import pytest

from tests._flaky_quarantine import (
    build_flaky_quarantine_skip_reason,
    validate_flaky_quarantine_metadata,
)


def test_validate_flaky_quarantine_metadata_accepts_valid_marker():
    metadata = validate_flaky_quarantine_metadata(
        {
            "issue": "PLAT-123",
            "owner": "qa-platform",
            "expires": "2099-01-31",
        },
        today=date(2026, 4, 17),
    )

    assert metadata.issue == "PLAT-123"
    assert metadata.owner == "qa-platform"
    assert metadata.expires == date(2099, 1, 31)


@pytest.mark.parametrize(
    "payload",
    [
        {"owner": "qa", "expires": "2099-01-31"},
        {"issue": "PLAT-123", "expires": "2099-01-31"},
        {"issue": "PLAT-123", "owner": "qa"},
    ],
)
def test_validate_flaky_quarantine_metadata_requires_all_fields(payload):
    with pytest.raises(ValueError, match="requires metadata fields"):
        validate_flaky_quarantine_metadata(payload, today=date(2026, 4, 17))


def test_validate_flaky_quarantine_metadata_requires_iso_expiry():
    with pytest.raises(ValueError, match="ISO date"):
        validate_flaky_quarantine_metadata(
            {
                "issue": "PLAT-123",
                "owner": "qa-platform",
                "expires": "31-01-2099",
            },
            today=date(2026, 4, 17),
        )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {"issue": None, "owner": "qa-platform", "expires": "2099-01-31"},
            "issue must be a non-empty string",
        ),
        (
            {"issue": "PLAT-123", "owner": 123, "expires": "2099-01-31"},
            "owner must be a non-empty string",
        ),
    ],
)
def test_validate_flaky_quarantine_metadata_rejects_non_string_identity_fields(
    payload, message
):
    with pytest.raises(ValueError, match=message):
        validate_flaky_quarantine_metadata(payload, today=date(2026, 4, 17))


def test_validate_flaky_quarantine_metadata_rejects_expired_marker():
    with pytest.raises(ValueError, match="expired on 2026-04-16"):
        validate_flaky_quarantine_metadata(
            {
                "issue": "PLAT-123",
                "owner": "qa-platform",
                "expires": "2026-04-16",
            },
            today=date(2026, 4, 17),
        )


def test_build_skip_reason_contains_operational_metadata():
    metadata = validate_flaky_quarantine_metadata(
        {
            "issue": "PLAT-123",
            "owner": "qa-platform",
            "expires": "2099-01-31",
        },
        today=date(2026, 4, 17),
    )

    reason = build_flaky_quarantine_skip_reason(metadata)
    assert "PLAT-123" in reason
    assert "qa-platform" in reason
    assert "2099-01-31" in reason
    assert "--run-flaky-quarantine" in reason
