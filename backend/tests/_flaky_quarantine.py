from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping


REQUIRED_FLAKY_QUARANTINE_FIELDS = ("issue", "owner", "expires")


@dataclass(frozen=True)
class FlakyQuarantineMetadata:
    issue: str
    owner: str
    expires: date


def validate_flaky_quarantine_metadata(
    raw_metadata: Mapping[str, object], *, today: date | None = None
) -> FlakyQuarantineMetadata:
    missing = [field for field in REQUIRED_FLAKY_QUARANTINE_FIELDS if field not in raw_metadata]
    if missing:
        raise ValueError(
            "flaky_quarantine marker requires metadata fields: "
            "issue=<ticket>, owner=<team-or-user>, expires=YYYY-MM-DD"
        )

    issue_raw = raw_metadata["issue"]
    owner_raw = raw_metadata["owner"]
    expires_raw = raw_metadata["expires"]

    if not isinstance(issue_raw, str) or not issue_raw.strip():
        raise ValueError("flaky_quarantine issue must be a non-empty string")
    if not isinstance(owner_raw, str) or not owner_raw.strip():
        raise ValueError("flaky_quarantine owner must be a non-empty string")
    if not isinstance(expires_raw, str) or not expires_raw.strip():
        raise ValueError("flaky_quarantine expires must be a non-empty ISO date string")

    issue = issue_raw.strip()
    owner = owner_raw.strip()
    expires_text = expires_raw.strip()

    try:
        expires = date.fromisoformat(expires_text)
    except ValueError as exc:
        raise ValueError("flaky_quarantine expires must be an ISO date (YYYY-MM-DD)") from exc

    reference_day = today or date.today()
    if expires < reference_day:
        raise ValueError(
            f"flaky_quarantine expired on {expires.isoformat()} " f"(issue={issue}, owner={owner})"
        )

    return FlakyQuarantineMetadata(issue=issue, owner=owner, expires=expires)


def build_flaky_quarantine_skip_reason(metadata: FlakyQuarantineMetadata) -> str:
    return (
        f"flaky_quarantine(issue={metadata.issue}, owner={metadata.owner}, "
        f"expires={metadata.expires.isoformat()}); use --run-flaky-quarantine to execute"
    )
