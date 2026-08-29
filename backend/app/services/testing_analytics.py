"""Test analytics computations (wave D1.3).

Pure aggregation extracted from the testing router: grouping test
results into per-test statistics, flakiness classification, and
coverage aggregation by component path. No HTTP or DB concerns.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable


def group_test_results(results: Iterable[Any]) -> Dict[tuple, Dict[str, Any]]:
    """Group raw test results into per-test statistics."""
    test_stats: Dict[tuple, Dict[str, Any]] = {}
    for r in results:
        key = (r.suite or "", r.classname or "", r.name or "")
        if key not in test_stats:
            test_stats[key] = {
                "suite": r.suite,
                "classname": r.classname,
                "test_name": r.name,
                "total_runs": 0,
                "failures": 0,
                "passes": 0,
                "commits_with_both": set(),
                "failure_messages": [],
                "affected_commits": set(),
            }
        stats = test_stats[key]
        stats["total_runs"] += 1

        status = (r.status or "").lower()
        if status in ("failed", "error"):
            stats["failures"] += 1
            stats["affected_commits"].add(r.commit_sha)
            if r.message:
                stats["failure_messages"].append(r.message[:200])
        elif status == "passed":
            stats["passes"] += 1
    return test_stats


def is_flaky_stats(stats: Dict[str, Any], flakiness_threshold: float) -> bool:
    """Flaky = both passes and failures, rate within [threshold, 99%)."""
    failure_rate = stats["failures"] / stats["total_runs"]
    return (
        stats["failures"] > 0 and stats["passes"] > 0 and flakiness_threshold <= failure_rate < 0.99
    )


def aggregate_file_coverage_by_component(
    files: Iterable[Any], depth: int
) -> Dict[str, Dict[str, Any]]:
    """Aggregate per-file coverage into directory components.

    depth=2 groups "src/services/auth.py" under "src/services".
    """
    components: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "total_lines": 0,
            "covered_lines": 0,
            "total_files": 0,
            "covered_files": 0,
            "file_coverages": [],
        }
    )

    for f in files:
        parts = f.file_path.split("/")
        component_path = "/".join(parts[:depth]) if len(parts) > depth else parts[0]

        comp = components[component_path]
        comp["total_files"] += 1
        comp["total_lines"] += f.lines_total or 0
        comp["covered_lines"] += f.lines_covered or 0
        comp["file_coverages"].append(f.line_coverage or 0)

        if (f.line_coverage or 0) > 0:
            comp["covered_files"] += 1

    return dict(components)
