"""Unit tests for the silent-except counter (review D4).

Pins the two bypasses Codex found: logging only inside a NESTED function
definition must still count as silent, and arbitrary objects with a
`.debug()` method must not be mistaken for loggers.
"""

from __future__ import annotations

import ast
from pathlib import Path

import importlib.util

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_silent_excepts.py"
spec = importlib.util.spec_from_file_location("cse", SCRIPT)
cse = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cse)


def _first_handler(code: str) -> ast.ExceptHandler:
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            return node
    raise AssertionError("no handler found")


def test_nested_function_logging_is_still_silent():
    code = """
try:
    x = 1
except Exception:
    def _helper():
        logger.error("this never runs at handler level")
    pass
"""
    assert cse._is_silent(_first_handler(code)) is True


def test_fake_debug_object_is_not_a_logger():
    code = """
try:
    x = 1
except Exception:
    widget.debug("not a logger")
"""
    assert cse._is_silent(_first_handler(code)) is True


def test_direct_logger_and_raise_are_not_silent():
    code = """
try:
    x = 1
except Exception:
    logger.warning("logged")
"""
    assert cse._is_silent(_first_handler(code)) is False

    code = """
try:
    x = 1
except Exception:
    raise
"""
    assert cse._is_silent(_first_handler(code)) is False
