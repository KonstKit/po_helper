#!/usr/bin/env python3
import argparse
import ast
import os
import sys
from typing import Iterable, List, Tuple


def iter_py_files(root: str) -> Iterable[str]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {"__pycache__", ".venv", ".mypy_cache"}]
        for filename in filenames:
            if filename.endswith(".py"):
                yield os.path.join(dirpath, filename)


def check_file(path: str, forbid_module: str) -> List[Tuple[int, str]]:
    with open(path, "r", encoding="utf-8") as handle:
        source = handle.read()
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return [(exc.lineno or 1, f"SyntaxError: {exc.msg}")]

    violations: List[Tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith(forbid_module):
                for name in node.names:
                    violations.append((node.lineno, f"from {module} import {name.name}"))
            if module == "app":
                for name in node.names:
                    if name.name == "api":
                        violations.append((node.lineno, "from app import api"))
        elif isinstance(node, ast.Import):
            for name in node.names:
                if name.name.startswith(forbid_module):
                    violations.append((node.lineno, f"import {name.name}"))
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="Check for forbidden imports.")
    parser.add_argument("--root", default="backend/app/services", help="Root to scan.")
    parser.add_argument(
        "--forbid",
        default="app.api",
        help="Forbidden module prefix (default: app.api).",
    )
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f"Root not found: {root}", file=sys.stderr)
        return 2

    all_violations: List[Tuple[str, int, str]] = []
    for path in iter_py_files(root):
        for lineno, detail in check_file(path, args.forbid):
            rel_path = os.path.relpath(path, os.getcwd())
            all_violations.append((rel_path, lineno, detail))

    if all_violations:
        print("Forbidden imports detected:", file=sys.stderr)
        for rel_path, lineno, detail in sorted(all_violations):
            print(f"{rel_path}:{lineno} {detail}", file=sys.stderr)
        return 1

    print("Import layering check: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
