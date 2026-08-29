"""Non-regression gate: silent exception handlers must not grow.

Runs the same counter as scripts/check_silent_excepts.py against the
committed baseline; adding a new swallow-without-log fails this test.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_silent_excepts.py"


def test_silent_except_count_does_not_grow():
    spec = importlib.util.spec_from_file_location("check_silent_excepts", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    current = module.count_silent_excepts(module.APP_ROOT)
    current_total = sum(current.values())

    baseline: dict[str, int] = {}
    for line in module.BASELINE_FILE.read_text().splitlines():
        if ":" in line:
            name, _, count = line.rpartition(":")
            baseline[name] = int(count)
    baseline_total = sum(baseline.values())

    regressions = {
        name: current.get(name, 0) - baseline.get(name, 0)
        for name in set(current) | set(baseline)
        if current.get(name, 0) > baseline.get(name, 0)
    }
    assert current_total <= baseline_total and not regressions, (
        f"silent except handlers grew: total {current_total} vs {baseline_total}, "
        f"per-file regressions {regressions}; log the exception or justify "
        "a baseline bump"
    )
