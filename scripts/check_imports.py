#!/usr/bin/env python3
import argparse
import ast
import os
import sys
from typing import Iterable, List, Sequence, Tuple


def iter_py_files(root: str) -> Iterable[str]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {"__pycache__", ".venv", ".mypy_cache"}]
        for filename in filenames:
            if filename.endswith(".py"):
                yield os.path.join(dirpath, filename)


def _normalize_forbids(raw_forbids: Sequence[str]) -> List[str]:
    forbids: List[str] = []
    for item in raw_forbids:
        for token in item.split(","):
            token = token.strip()
            if token:
                forbids.append(token)
    return forbids


def check_file(path: str, forbid_modules: Sequence[str]) -> List[Tuple[int, str]]:
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
            if any(module.startswith(forbid) for forbid in forbid_modules):
                for name in node.names:
                    violations.append((node.lineno, f"from {module} import {name.name}"))
            if module == "app":
                for name in node.names:
                    if name.name == "api":
                        violations.append((node.lineno, "from app import api"))
        elif isinstance(node, ast.Import):
            for name in node.names:
                if any(name.name.startswith(forbid) for forbid in forbid_modules):
                    violations.append((node.lineno, f"import {name.name}"))
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="Check for forbidden imports.")
    parser.add_argument(
        "--root",
        action="append",
        default=["backend/app/services"],
        help="Root to scan (can be passed multiple times).",
    )
    parser.add_argument(
        "--forbid",
        action="append",
        default=["app.api"],
        help="Forbidden module prefix (repeatable or comma-separated).",
    )
    args = parser.parse_args()
    forbid_modules = _normalize_forbids(args.forbid)

    all_violations: List[Tuple[str, int, str]] = []
    for root in args.root:
        abs_root = os.path.abspath(root)
        if not os.path.isdir(abs_root):
            print(f"Root not found: {abs_root}", file=sys.stderr)
            return 2
        for path in iter_py_files(abs_root):
            for lineno, detail in check_file(path, forbid_modules):
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
