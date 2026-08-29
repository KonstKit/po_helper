"""Non-regression gate for silent exception handlers.

Counts `except ...: pass` / `except ...: return None` blocks that swallow
errors without logging. The baseline file pins the current count; the gate
fails when the count GROWS, so new code must log (or justify a baseline
bump via a documented regression).

Usage: python scripts/check_silent_excepts.py [--update-baseline]
(The gate also runs as a pytest test: tests/test_silent_except_gate.py)
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
BASELINE_FILE = Path(__file__).resolve().parent / "silent_except_baseline.txt"


def _is_silent(handler: ast.ExceptHandler) -> bool:
    body = handler.body
    if not body:
        return True
    # single `pass`
    if len(body) == 1 and isinstance(body[0], ast.Pass):
        return True
    # single bare `return None` with no logging calls anywhere
    if len(body) == 1 and isinstance(body[0], ast.Return) and body[0].value is None:
        return True
    # any logging call (logger.*, logging.*) anywhere -> not silent
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in {
                "debug",
                "info",
                "warning",
                "error",
                "exception",
                "critical",
            }:
                return False
            if isinstance(func, ast.Name) and func.id in {"print"}:
                return False
    # body without logging and without raising: treat multi-statement no-ops
    # like assignments as silent only if nothing re-raises
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(node, ast.Raise):
            return False
    return True


def count_silent_excepts(root: Path) -> dict[str, int]:
    per_file: dict[str, int] = {}
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        count = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and _is_silent(node):
                count += 1
        if count:
            per_file[str(path.relative_to(root.parents[1]))] = count
    return per_file


def main() -> int:
    current = count_silent_excepts(APP_ROOT)
    current_total = sum(current.values())

    if "--update-baseline" in sys.argv:
        BASELINE_FILE.write_text(
            "\n".join(f"{k}:{v}" for k, v in sorted(current.items())) + "\n"
        )
        print(f"Baseline updated: {current_total} silent excepts")
        return 0

    if not BASELINE_FILE.exists():
        print(f"Baseline missing at {BASELINE_FILE}; run with --update-baseline")
        return 1

    baseline: dict[str, int] = {}
    for line in BASELINE_FILE.read_text().splitlines():
        if ":" in line:
            name, _, count = line.rpartition(":")
            baseline[name] = int(count)
    baseline_total = sum(baseline.values())

    if current_total > baseline_total:
        print(
            f"SILENT-EXCEPT REGRESSION: {current_total} > baseline {baseline_total}"
        )
        for name, count in sorted(current.items()):
            delta = count - baseline.get(name, 0)
            if delta > 0:
                print(f"  +{delta} {name}")
        return 1

    print(f"Silent-except gate: OK ({current_total} <= baseline {baseline_total})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
