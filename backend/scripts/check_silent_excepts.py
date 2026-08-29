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


_LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}


def _iter_scope(body: list[ast.stmt]):
    """Walk the handler body WITHOUT descending into nested function/
    class/lambda scopes: a handler that merely DEFINES a function which
    logs is still silent at its own level (review D4). Call expressions
    at handler level ARE visited."""
    stack: list[ast.AST] = list(body)
    skipped = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
    while stack:
        node = stack.pop()
        if isinstance(node, skipped):
            # a nested scope's contents do not run at handler level
            continue
        yield node
        for child in ast.iter_child_nodes(node):
            stack.append(child)


def _looks_like_logger_call(call: ast.Call) -> bool:
    func = call.func
    if not isinstance(func, ast.Attribute) or func.attr not in _LOG_METHODS:
        return False
    receiver = func.value
    # logger.<method> / self.logger.<method> / logging.<module-func>
    if isinstance(receiver, ast.Name) and receiver.id in {"logger", "logging"}:
        return True
    if isinstance(receiver, ast.Attribute) and isinstance(receiver.value, ast.Name):
        return receiver.attr in {"logger", "log"} or receiver.value.id == "logging"
    return False


def _is_silent(handler: ast.ExceptHandler) -> bool:
    body = handler.body
    if not body:
        return True
    if len(body) == 1 and isinstance(body[0], ast.Pass):
        return True
    if len(body) == 1 and isinstance(body[0], ast.Return) and body[0].value is None:
        return True
    for node in _iter_scope(body):
        if isinstance(node, ast.Raise):
            return False
        if isinstance(node, ast.Call) and (
            _looks_like_logger_call(node)
            or (isinstance(node.func, ast.Name) and node.func.id == "print")
        ):
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
        BASELINE_FILE.write_text("\n".join(f"{k}:{v}" for k, v in sorted(current.items())) + "\n")
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

    regressions = {
        name: current.get(name, 0) - baseline.get(name, 0)
        for name in set(current) | set(baseline)
        if current.get(name, 0) > baseline.get(name, 0)
    }
    if current_total > baseline_total or regressions:
        print(
            f"SILENT-EXCEPT REGRESSION: total {current_total} vs baseline "
            f"{baseline_total}; per-file regressions: {regressions}"
        )
        return 1

    print(f"Silent-except gate: OK ({current_total} <= baseline {baseline_total})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
