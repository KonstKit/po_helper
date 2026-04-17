#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit


ARTIFACT_COUNT_SQL = """
    SELECT
        a.project_id AS project_id,
        COALESCE(p.name, '__unassigned__') AS project_name,
        COALESCE(p.jira_key, '__unassigned__') AS jira_key,
        COUNT(*) AS artifact_count
    FROM artifacts AS a
    LEFT JOIN projects AS p ON p.id = a.project_id
    GROUP BY a.project_id, p.name, p.jira_key
    ORDER BY a.project_id
"""


@dataclass(frozen=True)
class ArtifactCountRow:
    project_id: int | None
    project_name: str
    jira_key: str
    artifact_count: int


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export and compare artifact_count snapshots for traceability repairs."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser(
        "export",
        help="Export artifact counts from a database snapshot to JSON.",
    )
    export_parser.add_argument(
        "--database-url",
        default=None,
        help="Database URL to query. Defaults to DATABASE_URL from the environment.",
    )
    export_parser.add_argument(
        "--output",
        required=True,
        help="Path to write the exported JSON snapshot.",
    )

    compare_parser = subparsers.add_parser(
        "compare",
        help="Compare two exported artifact-count JSON snapshots.",
    )
    compare_parser.add_argument("--before", required=True, help="Path to the before snapshot.")
    compare_parser.add_argument("--after", required=True, help="Path to the after snapshot.")
    compare_parser.add_argument(
        "--fail-on-negative-delta",
        action="store_true",
        help="Return a non-zero exit code if any project loses artifacts.",
    )

    return parser.parse_args()


def _resolve_database_url(value: str | None) -> str:
    database_url = value or os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL was not provided.")
    return database_url


async def _fetch_counts(database_url: str) -> list[ArtifactCountRow]:
    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine
    except ImportError as exc:  # pragma: no cover - import error only happens in thin envs
        raise RuntimeError(
            "SQLAlchemy is required for the export command. Install backend dependencies first."
        ) from exc

    engine = create_async_engine(database_url, future=True)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text(ARTIFACT_COUNT_SQL))
            rows = result.mappings().all()
    finally:
        await engine.dispose()

    return [
        ArtifactCountRow(
            project_id=row["project_id"],
            project_name=row["project_name"],
            jira_key=row["jira_key"],
            artifact_count=int(row["artifact_count"]),
        )
        for row in rows
    ]


def _snapshot_payload(database_url: str, rows: Iterable[ArtifactCountRow]) -> dict[str, Any]:
    row_list = list(rows)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database_target": _redact_database_url(database_url),
        "total_artifacts": sum(row.artifact_count for row in row_list),
        "rows": [asdict(row) for row in row_list],
    }


def _redact_database_url(database_url: str) -> str:
    parts = urlsplit(database_url)
    if not parts.scheme:
        return "redacted"
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    path = parts.path or ""
    redacted_netloc = f"{host}{port}" if host else "redacted"
    return urlunsplit((parts.scheme, redacted_netloc, path, "", ""))


def _load_snapshot(path: Path) -> list[ArtifactCountRow]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    raw_rows = data["rows"] if isinstance(data, dict) and "rows" in data else data

    rows: list[ArtifactCountRow] = []
    for item in raw_rows:
        rows.append(
            ArtifactCountRow(
                project_id=item.get("project_id"),
                project_name=item.get("project_name") or "__unassigned__",
                jira_key=item.get("jira_key") or "__unassigned__",
                artifact_count=int(item.get("artifact_count", 0)),
            )
        )
    return rows


def _row_key(row: ArtifactCountRow) -> str:
    return "__unassigned__" if row.project_id is None else str(row.project_id)


def _format_delta(delta: int) -> str:
    return f"+{delta}" if delta > 0 else str(delta)


def _print_comparison(before_rows: list[ArtifactCountRow], after_rows: list[ArtifactCountRow]) -> int:
    before_map = {_row_key(row): row for row in before_rows}
    after_map = {_row_key(row): row for row in after_rows}
    all_keys = sorted(
        set(before_map) | set(after_map),
        key=lambda key: (
            key == "__unassigned__",
            1 if not key.isdigit() else 0,
            int(key) if key.isdigit() else key,
        ),
    )

    total_before = sum(row.artifact_count for row in before_rows)
    total_after = sum(row.artifact_count for row in after_rows)
    total_delta = total_after - total_before

    print(f"total_before: {total_before}")
    print(f"total_after : {total_after}")
    print(f"delta       : {_format_delta(total_delta)}")
    print()
    print("project_id | project_name | jira_key | before | after | delta | status")
    print("-----------|--------------|----------|--------|-------|-------|--------")

    negative_delta_found = False
    for key in all_keys:
        before = before_map.get(key)
        after = after_map.get(key)
        before_count = before.artifact_count if before else 0
        after_count = after.artifact_count if after else 0
        delta = after_count - before_count
        if delta < 0:
            negative_delta_found = True
        status = (
            "new"
            if before is None
            else "removed"
            if after is None
            else "changed"
            if delta != 0
            else "unchanged"
        )
        row = after or before
        print(
            f"{key} | {row.project_name} | {row.jira_key} | "
            f"{before_count} | {after_count} | {_format_delta(delta)} | {status}"
        )

    return 1 if negative_delta_found else 0


async def _run_export(database_url: str, output: Path) -> int:
    rows = await _fetch_counts(database_url)
    payload = _snapshot_payload(database_url, rows)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {output} ({payload['total_artifacts']} artifacts, {len(rows)} project rows)")
    return 0


def main() -> int:
    args = _parse_args()

    if args.command == "export":
        try:
            database_url = _resolve_database_url(args.database_url)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        output = Path(args.output).expanduser().resolve()
        return asyncio.run(_run_export(database_url, output))

    before_path = Path(args.before).expanduser().resolve()
    after_path = Path(args.after).expanduser().resolve()
    if not before_path.exists():
        print(f"Before snapshot not found: {before_path}", file=sys.stderr)
        return 2
    if not after_path.exists():
        print(f"After snapshot not found: {after_path}", file=sys.stderr)
        return 2

    before_rows = _load_snapshot(before_path)
    after_rows = _load_snapshot(after_path)
    exit_code = _print_comparison(before_rows, after_rows)
    if exit_code and not args.fail_on_negative_delta:
        print()
        print(
            "Negative deltas were detected. Re-run with --fail-on-negative-delta "
            "if you want the script to fail on project count drops."
        )
        return 0
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
