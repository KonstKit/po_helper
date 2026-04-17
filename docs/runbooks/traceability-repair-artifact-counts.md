# Traceability Repair Artifact Count Runbook

This runbook compares `artifact_count` before and after a traceability repair job on a staging snapshot.

## Prerequisites

- A staging database snapshot restored and reachable through `DATABASE_URL`
- Python environment with backend dependencies installed, or an environment where `sqlalchemy` and the DB driver for the snapshot are available
- Authenticated access to the staging repair endpoint if you run the repair through the API

## Export the before snapshot

```powershell
python scripts/traceability_artifact_counts.py export --database-url "$env:STAGING_DATABASE_URL" --output artifacts/staging/artifact_counts.before.json
```

If `DATABASE_URL` is already set in your shell, you can omit `--database-url`.

## Run the repair job

Trigger the repair job for the target project on staging.

```powershell
Invoke-RestMethod -Method Post -Uri "https://staging.example.com/api/v1/traceability/backfill?project_id=123" `
  -Headers @{ Authorization = "Bearer <token>" }
```

If you need to repair multiple projects, run the endpoint once per project and capture the output separately.

## Export the after snapshot

```powershell
python scripts/traceability_artifact_counts.py export --database-url "$env:STAGING_DATABASE_URL" --output artifacts/staging/artifact_counts.after.json
```

## Compare the snapshots

```powershell
python scripts/traceability_artifact_counts.py compare --before artifacts/staging/artifact_counts.before.json --after artifacts/staging/artifact_counts.after.json
```

To make the command fail when any project loses artifacts:

```powershell
python scripts/traceability_artifact_counts.py compare --before artifacts/staging/artifact_counts.before.json --after artifacts/staging/artifact_counts.after.json --fail-on-negative-delta
```

## Expected outcome

- `total_before` and `total_after` are reported at the top.
- Each project row shows `before`, `after`, `delta`, and a status.
- Any negative delta is highlighted so you can decide whether the repair changed the snapshot in a valid way.
- Exported JSON stores a redacted `database_target` value (no credentials).
